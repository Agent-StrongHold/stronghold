"""Entry point. `python -m turing.runtime.main [flags]`.

Wires Repo + self_id + Motivation + Scheduler + DaydreamProducers +
ContradictionDetector + CoefficientTuner + Providers into a long-running
RealReactor tick loop.
"""

from __future__ import annotations

import argparse
import logging
import signal
import sys
from typing import Any

from ..daydream import DaydreamProducer
from ..detectors.contradiction import ContradictionDetector
from ..motivation import Motivation
from ..repo import Repo
from ..scheduler import Scheduler
from ..self_identity import bootstrap_self_id
from ..tuning import CoefficientTuner
from .config import RuntimeConfig, load_config_from_env
from .instrumentation import setup_logging
from .providers.base import Provider
from .providers.fake import FakeProvider
from .reactor import RealReactor


logger = logging.getLogger("turing.runtime.main")


def _build_providers(cfg: RuntimeConfig) -> dict[str, Provider]:
    providers: dict[str, Provider] = {}
    for name in cfg.provider_choice:
        if name == "fake":
            providers[name] = FakeProvider(name="fake")
        elif name == "gemini":
            # Chunk 2 wires the real client; chunk 1 stubs as FakeProvider so
            # the structural path is exercised.
            providers[name] = FakeProvider(name="gemini")
        elif name == "openrouter":
            providers[name] = FakeProvider(name="openrouter")
        elif name == "zai":
            providers[name] = FakeProvider(name="zai")
        else:
            raise ValueError(f"unknown provider: {name}")
    return providers


def _make_imagine_for_provider(provider: Provider) -> Any:
    """Return an `imagine` callable that uses the given provider."""
    from ..daydream import default_imagine
    from ..types import EpisodicMemory

    def imagine(
        seed: EpisodicMemory,
        retrieved: list[EpisodicMemory],
        pool_name: str,
    ) -> list[tuple[str, str, str]]:
        prompt = (
            f"Seed memory: {seed.content!r}\n"
            f"Related ({len(retrieved)}): "
            + "; ".join(m.content for m in retrieved[:3])
            + "\nProduce one HYPOTHESIS that explores an alternative future."
        )
        try:
            reply = provider.complete(prompt, max_tokens=256)
        except Exception:
            logger.exception("provider %s failed during imagine", provider.name)
            return default_imagine(seed, retrieved, pool_name)
        return [
            (
                "hypothesis",
                reply.strip() or f"no reply from {provider.name}",
                seed.intent_at_time or "generic-intent",
            )
        ]

    return imagine


def build_and_run(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="turing-runtime")
    parser.add_argument("--tick-rate", type=int)
    parser.add_argument("--db", type=str)
    parser.add_argument("--log-level", type=str, choices=["DEBUG", "INFO", "WARNING", "ERROR"])
    parser.add_argument("--log-format", type=str, choices=["plain", "json"])
    parser.add_argument("--providers", type=str, help="comma-separated: fake,gemini,openrouter,zai")
    parser.add_argument("--scenario", type=str)
    parser.add_argument("--duration", type=int, help="seconds to run before auto-stop (default: forever)")
    args = parser.parse_args(argv)

    overrides: dict[str, Any] = {}
    if args.tick_rate is not None:
        overrides["tick_rate_hz"] = args.tick_rate
    if args.db is not None:
        overrides["db_path"] = args.db
    if args.log_level is not None:
        overrides["log_level"] = args.log_level
    if args.log_format is not None:
        overrides["log_format"] = args.log_format
    if args.providers is not None:
        overrides["provider_choice"] = tuple(
            p.strip() for p in args.providers.split(",") if p.strip()
        )
    if args.scenario is not None:
        overrides["scenario"] = args.scenario

    cfg = load_config_from_env(overrides=overrides)
    setup_logging(level=cfg.log_level, fmt=cfg.log_format)

    logger.info(
        "starting runtime tick_rate=%d db=%s providers=%s",
        cfg.tick_rate_hz,
        cfg.db_path,
        ",".join(cfg.provider_choice),
    )

    repo = Repo(cfg.db_path if cfg.db_path != ":memory:" else None)
    self_id = bootstrap_self_id(repo.conn)
    logger.info("self_id=%s", self_id)

    reactor = RealReactor(
        tick_rate_hz=cfg.tick_rate_hz,
        executor_workers=cfg.executor_workers,
    )
    motivation = Motivation(reactor)
    scheduler = Scheduler(reactor, motivation)

    providers = _build_providers(cfg)
    for pool_name, provider in providers.items():
        DaydreamProducer(
            pool_name=pool_name,
            self_id=self_id,
            motivation=motivation,
            reactor=reactor,
            repo=repo,
            imagine=_make_imagine_for_provider(provider),
        )
        # Seed some pressure so the producer actually emits candidates during
        # the smoke run. Chunk 2 replaces this with real quota tracking.
        motivation.set_pressure(pool_name, 500.0)

    ContradictionDetector(
        repo=repo,
        motivation=motivation,
        reactor=reactor,
        self_id=self_id,
    )
    CoefficientTuner(
        motivation=motivation,
        reactor=reactor,
        repo=repo,
        self_id=self_id,
    )

    def _handle_signal(signum: int, _frame: Any) -> None:
        logger.info("signal %d received; stopping reactor", signum)
        reactor.stop()

    signal.signal(signal.SIGINT, _handle_signal)
    signal.signal(signal.SIGTERM, _handle_signal)

    if args.duration is not None:
        import threading

        threading.Timer(args.duration, reactor.stop).start()

    reactor.run_forever()
    status = reactor.get_status()
    logger.info(
        "reactor stopped tick_count=%d drift_p99_ms=%.2f",
        status.tick_count,
        status.drift_ms_p99,
    )
    repo.close()
    return 0


if __name__ == "__main__":
    sys.exit(build_and_run())
