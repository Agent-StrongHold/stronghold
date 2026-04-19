"""Prometheus-format metrics endpoint.

Stdlib-only http.server. The running reactor registers a MetricsCollector
with the app; the server renders its snapshot per scrape.
"""

from __future__ import annotations

import logging
import threading
from collections.abc import Callable
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer


logger = logging.getLogger("turing.runtime.metrics")


Snapshot = dict[str, object]


class MetricsCollector:
    """Mutable store of current metric values.

    The reactor's per-tick handlers update these; the HTTP server reads them
    under a lock. All metrics are single-scalar or labeled-scalar — enough
    for a research box, not enough for complex aggregation.
    """

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._snapshot: Snapshot = {
            "turing_tick_count": 0,
            "turing_drift_ms_p99": 0.0,
            "turing_durable_memories_total": {},          # tier -> count
            "turing_pressure": {},                         # pool -> pressure
            "turing_quota_headroom": {},                   # pool -> headroom
            "turing_daydream_sessions_total": {},          # pool -> count
            "turing_dispatch_total": {},                   # (kind, pool) -> count
        }

    def update(self, **kwargs: object) -> None:
        with self._lock:
            for key, value in kwargs.items():
                self._snapshot[key] = value

    def set_labeled(self, name: str, labels: tuple, value: float | int) -> None:
        with self._lock:
            bucket = self._snapshot.setdefault(name, {})
            assert isinstance(bucket, dict)
            bucket[labels] = value

    def inc_labeled(self, name: str, labels: tuple, delta: int = 1) -> None:
        with self._lock:
            bucket = self._snapshot.setdefault(name, {})
            assert isinstance(bucket, dict)
            bucket[labels] = int(bucket.get(labels, 0)) + delta

    def render(self) -> str:
        with self._lock:
            lines: list[str] = []
            for name, value in self._snapshot.items():
                if isinstance(value, dict):
                    for labels, v in value.items():
                        labelstr = ",".join(
                            f'{k}="{lbl}"'
                            for k, lbl in zip(_label_keys_for(name), labels)
                        )
                        lines.append(f"{name}{{{labelstr}}} {v}")
                else:
                    lines.append(f"{name} {value}")
            return "\n".join(lines) + "\n"


_LABEL_KEYS: dict[str, tuple[str, ...]] = {
    "turing_durable_memories_total": ("tier",),
    "turing_pressure": ("pool",),
    "turing_quota_headroom": ("pool",),
    "turing_daydream_sessions_total": ("pool",),
    "turing_dispatch_total": ("kind", "pool"),
}


def _label_keys_for(name: str) -> tuple[str, ...]:
    return _LABEL_KEYS.get(name, ())


class _Handler(BaseHTTPRequestHandler):
    collector: MetricsCollector

    def do_GET(self) -> None:                                   # noqa: N802
        if self.path.rstrip("/") != "/metrics":
            self.send_response(404)
            self.end_headers()
            return
        body = self.collector.render().encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "text/plain; version=0.0.4")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, format: str, *args: object) -> None:   # noqa: A002
        # silence default stderr logging
        logger.debug("metrics request: " + format, *args)


def start_metrics_server(
    collector: MetricsCollector,
    *,
    port: int,
    host: str = "0.0.0.0",
) -> Callable[[], None]:
    """Launch an HTTP server in a background thread. Returns a stop callable."""

    class BoundHandler(_Handler):
        pass

    BoundHandler.collector = collector

    server = ThreadingHTTPServer((host, port), BoundHandler)
    thread = threading.Thread(
        target=server.serve_forever, name="turing-metrics", daemon=True
    )
    thread.start()
    logger.info("metrics endpoint serving on http://%s:%d/metrics", host, port)

    def _stop() -> None:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2.0)

    return _stop
