"""Coverage gap filler for litellm.py, rss_fetcher.py, reactor.py, quota.py, chat body limit.

Spec: Test uncovered paths in:
- LiteLLMProvider: complete (429, 5xx retry, non-success), embed, quota_window,
  close, empty virtual_key/base_url, _extract_text edge cases
- RSSFetcher: on_tick, _poll, _to_backlog
- RealReactor: validation, drift recording, get_status, spawn
- FreeTierQuotaTracker: window, pressure_for edge cases, select_best_provider
- Chat: body size limit (413)

Acceptance criteria:
- LiteLLMProvider raises RateLimited on 429
- LiteLLMProvider retries once on 5xx, raises ProviderUnavailable on retry failure
- LiteLLMProvider raises ProviderUnavailable on non-success (non-429, non-5xx)
- LiteLLMProvider embed returns float list
- LiteLLMProvider embed raises on non-success
- LiteLLMProvider raises ValueError on empty virtual_key or base_url
- _extract_text handles empty choices, missing content, non-string content
- RSSFetcher polls on cadence, skips if not yet time
- RealReactor rejects tick_rate_hz<=0 and executor_workers<=0
- RealReactor records drift and get_status returns ReactorStatus
- RealReactor spawn returns Future
- FreeTierQuotaTracker returns None window for unknown pool
- FreeTierQuotaTracker pressure_for returns 0.0 for no window or no headroom
- FreeTierQuotaTracker select_best_provider picks highest-scoring provider
- Chat POST with body > 1MiB returns 413
"""

from __future__ import annotations

import json
import socket
import time
import urllib.error
import urllib.request
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from typing import Any

import httpx
import pytest

from turing.motivation import Motivation
from turing.reactor import FakeReactor
from turing.runtime.chat import MAX_REQUEST_BODY_BYTES, ChatBridge, start_chat_server
from turing.runtime.providers.base import FreeTierWindow, ProviderUnavailable, RateLimited
from turing.runtime.providers.litellm import LiteLLMProvider, _extract_text
from turing.runtime.quota import FreeTierQuotaTracker
from turing.runtime.rss_fetcher import RSSFetcher
from turing.runtime.reactor import RealReactor
from turing.runtime.pools import PoolConfig
from turing.self_identity import bootstrap_self_id
from turing.repo import Repo
from turing.runtime.tools.rss import FeedItem, RSSReader


def _free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def _pool_config(**overrides) -> PoolConfig:
    defaults = dict(
        pool_name="test-pool",
        model="test-model",
        window_kind="rpm",
        window_duration_seconds=60,
        tokens_allowed=10000,
        quality_weight=1.0,
        role="chat",
    )
    defaults.update(overrides)
    return PoolConfig(**defaults)


class TestLiteLLMProviderValidation:
    def test_empty_virtual_key_raises(self) -> None:
        with pytest.raises(ValueError, match="virtual_key"):
            LiteLLMProvider(
                pool_config=_pool_config(),
                base_url="http://localhost:4000",
                virtual_key="",
            )

    def test_empty_base_url_raises(self) -> None:
        with pytest.raises(ValueError, match="base_url"):
            LiteLLMProvider(
                pool_config=_pool_config(),
                base_url="",
                virtual_key="sk-test",
            )


class TestLiteLLMProviderComplete:
    def _make_provider(self, *, responses: list[httpx.Response]) -> LiteLLMProvider:
        transport = httpx.MockTransport(lambda req: responses.pop(0))
        client = httpx.Client(transport=transport, base_url="http://localhost:4000")
        return LiteLLMProvider(
            pool_config=_pool_config(),
            base_url="http://localhost:4000",
            virtual_key="sk-test",
            client=client,
        )

    def _ok_response(self, text: str = "hello") -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "choices": [{"message": {"content": text}}],
                "usage": {"total_tokens": 10},
            },
        )

    def test_429_raises_rate_limited(self) -> None:
        provider = self._make_provider(responses=[httpx.Response(429)])
        with pytest.raises(RateLimited):
            provider.complete("test")

    def test_5xx_retry_success(self) -> None:
        provider = self._make_provider(
            responses=[
                httpx.Response(500),
                self._ok_response("retry ok"),
            ]
        )
        result = provider.complete("test")
        assert result == "retry ok"

    def test_5xx_retry_also_fails(self) -> None:
        provider = self._make_provider(
            responses=[
                httpx.Response(500),
                httpx.Response(503),
            ]
        )
        with pytest.raises(ProviderUnavailable, match="sanitized"):
            provider.complete("test")

    def test_non_success_non_5xx(self) -> None:
        provider = self._make_provider(responses=[httpx.Response(403)])
        with pytest.raises(ProviderUnavailable, match="sanitized"):
            provider.complete("test")

    def test_success_returns_text(self) -> None:
        provider = self._make_provider(responses=[self._ok_response("world")])
        assert provider.complete("test") == "world"

    def test_request_error_raises_provider_unavailable(self) -> None:
        def _fail(req):
            raise httpx.ConnectError("connection refused")

        transport = httpx.MockTransport(_fail)
        client = httpx.Client(transport=transport, base_url="http://localhost:4000")
        provider = LiteLLMProvider(
            pool_config=_pool_config(),
            base_url="http://localhost:4000",
            virtual_key="sk-test",
            client=client,
        )
        with pytest.raises(ProviderUnavailable, match="request error"):
            provider.complete("test")

    def test_close_closes_client(self) -> None:
        provider = self._make_provider(responses=[self._ok_response()])
        provider.close()

    def test_quota_window_returns_window(self) -> None:
        provider = self._make_provider(responses=[self._ok_response()])
        window = provider.quota_window()
        assert window is not None
        assert window.provider == "test-pool"
        assert window.tokens_allowed == 10000


class TestLiteLLMProviderEmbed:
    def _make_provider(self, *, responses: list[httpx.Response]) -> LiteLLMProvider:
        transport = httpx.MockTransport(lambda req: responses.pop(0))
        client = httpx.Client(transport=transport, base_url="http://localhost:4000")
        return LiteLLMProvider(
            pool_config=_pool_config(),
            base_url="http://localhost:4000",
            virtual_key="sk-test",
            client=client,
        )

    def test_embed_success(self) -> None:
        provider = self._make_provider(
            responses=[
                httpx.Response(
                    200,
                    json={
                        "data": [{"embedding": [0.1, 0.2, 0.3]}],
                        "usage": {"total_tokens": 5},
                    },
                )
            ]
        )
        result = provider.embed("hello")
        assert result == [0.1, 0.2, 0.3]

    def test_embed_429_raises_rate_limited(self) -> None:
        provider = self._make_provider(responses=[httpx.Response(429)])
        with pytest.raises(RateLimited):
            provider.embed("hello")

    def test_embed_non_success_raises(self) -> None:
        provider = self._make_provider(responses=[httpx.Response(403)])
        with pytest.raises(ProviderUnavailable, match="sanitized"):
            provider.embed("hello")

    def test_embed_request_error_raises(self) -> None:
        def _fail(req):
            raise httpx.ConnectError("connection refused")

        transport = httpx.MockTransport(_fail)
        client = httpx.Client(transport=transport, base_url="http://localhost:4000")
        provider = LiteLLMProvider(
            pool_config=_pool_config(),
            base_url="http://localhost:4000",
            virtual_key="sk-test",
            client=client,
        )
        with pytest.raises(ProviderUnavailable, match="embed error"):
            provider.embed("hello")

    def test_embed_no_embedding_data_raises(self) -> None:
        provider = self._make_provider(
            responses=[
                httpx.Response(
                    200,
                    json={"data": [], "usage": {}},
                )
            ]
        )
        with pytest.raises(ProviderUnavailable, match="no embedding"):
            provider.embed("hello")

    def test_embed_missing_embedding_key_raises(self) -> None:
        provider = self._make_provider(
            responses=[
                httpx.Response(
                    200,
                    json={"data": [{"other": 1}], "usage": {}},
                )
            ]
        )
        with pytest.raises(ProviderUnavailable, match="no embedding"):
            provider.embed("hello")


class TestExtractText:
    def test_empty_choices(self) -> None:
        assert _extract_text({"choices": []}) == ""

    def test_no_choices_key(self) -> None:
        assert _extract_text({}) == ""

    def test_content_is_not_string(self) -> None:
        assert _extract_text({"choices": [{"message": {"content": 42}}]}) == ""

    def test_extracts_string(self) -> None:
        assert _extract_text({"choices": [{"message": {"content": "hi"}}]}) == "hi"


class TestRSSFetcher:
    def test_skips_if_not_yet_time(self) -> None:
        reactor = FakeReactor()
        motivation = Motivation(reactor)
        reader = RSSReader(feeds=("https://example.com/feed.xml",))
        fetcher = RSSFetcher(
            reader=reader,
            motivation=motivation,
            reactor=reactor,
            poll_ticks=100,
        )
        initial = len(motivation.backlog)
        fetcher.on_tick(1)
        assert len(motivation.backlog) == initial

    def test_polls_when_cadence_reached(self) -> None:
        reactor = FakeReactor()
        motivation = Motivation(reactor)
        item = FeedItem(
            item_id="i1",
            title="t1",
            link="https://example.com/1",
            summary="s1",
            published_at=None,
            feed_url="https://example.com/feed.xml",
        )
        reader = RSSReader(feeds=("https://example.com/feed.xml",))
        original_invoke = reader.invoke

        def _mock_invoke(**kwargs):
            return [item]

        reader.invoke = _mock_invoke
        fetcher = RSSFetcher(
            reader=reader,
            motivation=motivation,
            reactor=reactor,
            poll_ticks=10,
        )
        fetcher.on_tick(10)
        assert any(bi.kind == "rss_item" for bi in motivation.backlog)
        reader = RSSReader(feeds=("https://example.com/feed.xml",))
        reader._cache = [item]
        reader._last_etag = {"https://example.com/feed.xml": True}
        fetcher = RSSFetcher(
            reader=reader,
            motivation=motivation,
            reactor=reactor,
            poll_ticks=10,
        )
        fetcher.on_tick(10)
        assert any(item.kind == "rss_item" for item in motivation.backlog)

    def test_poll_exception_is_caught(self) -> None:
        reactor = FakeReactor()
        motivation = Motivation(reactor)
        reader = RSSReader(feeds=("https://example.com/feed.xml",))

        def _boom():
            raise RuntimeError("network down")

        reader.invoke = _boom
        fetcher = RSSFetcher(
            reader=reader,
            motivation=motivation,
            reactor=reactor,
            poll_ticks=10,
        )
        fetcher.on_tick(10)

    def test_to_backlog_structure(self) -> None:
        reactor = FakeReactor()
        motivation = Motivation(reactor)
        reader = RSSReader(feeds=("https://example.com/feed.xml",))
        fetcher = RSSFetcher(
            reader=reader,
            motivation=motivation,
            reactor=reactor,
        )
        item = FeedItem(
            item_id="x1",
            title="x",
            link="https://example.com/x",
            summary="x",
            published_at=None,
            feed_url="https://example.com/f",
        )
        backlog_item = fetcher._to_backlog(item)
        assert backlog_item.kind == "rss_item"
        assert backlog_item.class_ == 7
        assert backlog_item.payload["feed_item"] is item


class TestRealReactorCoverage:
    def test_tick_rate_hz_zero_raises(self) -> None:
        with pytest.raises(ValueError, match="tick_rate_hz"):
            RealReactor(tick_rate_hz=0)

    def test_tick_rate_hz_negative_raises(self) -> None:
        with pytest.raises(ValueError, match="tick_rate_hz"):
            RealReactor(tick_rate_hz=-1)

    def test_executor_workers_zero_raises(self) -> None:
        with pytest.raises(ValueError, match="executor_workers"):
            RealReactor(executor_workers=0)

    def test_get_status_initial(self) -> None:
        reactor = RealReactor(tick_rate_hz=100)
        status = reactor.get_status()
        assert status.tick_count == 0
        assert status.running is False
        assert status.drift_ms_p99 == 0.0
        reactor.stop()
        reactor._executor.shutdown(wait=False)

    def test_spawn_returns_future(self) -> None:
        reactor = RealReactor(tick_rate_hz=100)
        future = reactor.spawn(lambda: 42)
        assert future.result(timeout=2.0) == 42
        reactor.stop()
        reactor._executor.shutdown(wait=True)


class TestQuotaTrackerEdgeCases:
    def test_window_unknown_pool_returns_none(self) -> None:
        tracker = FreeTierQuotaTracker()
        assert tracker.window("nonexistent") is None

    def test_pressure_for_unknown_pool_returns_zero(self) -> None:
        tracker = FreeTierQuotaTracker()
        assert tracker.pressure_for("nonexistent") == 0.0

    def test_providers_returns_registered(self) -> None:
        from turing.runtime.providers.fake import FakeProvider

        tracker = FreeTierQuotaTracker()
        provider = FakeProvider(name="test")
        tracker.register(provider, quality_weight=0.5)
        assert "test" in tracker.providers()

    def test_select_best_provider_none_when_no_headroom(self) -> None:
        from turing.runtime.providers.fake import FakeProvider

        tracker = FreeTierQuotaTracker()
        provider = FakeProvider(name="exhausted", quota_allowed=100, quota_used=200)
        tracker.register(provider)
        best = tracker.select_best_provider()
        assert best is None


class TestChatBodySizeLimit:
    def test_oversized_body_returns_413(self) -> None:
        repo = Repo(None)
        self_id = bootstrap_self_id(repo.conn)
        reactor = FakeReactor()
        motivation = Motivation(reactor)
        bridge = ChatBridge()
        port = _free_port()
        stop = start_chat_server(
            motivation=motivation,
            repo=repo,
            self_id=self_id,
            bridge=bridge,
            port=port,
            host="127.0.0.1",
            response_timeout_s=1.0,
        )
        time.sleep(0.1)
        try:
            import http.client

            conn = http.client.HTTPConnection("127.0.0.1", port, timeout=2.0)
            body = b'{"message":"x"}'
            conn.request(
                "POST",
                "/chat",
                body=body,
                headers={
                    "Content-Type": "application/json",
                    "Content-Length": str(MAX_REQUEST_BODY_BYTES + 1),
                },
            )
            resp = conn.getresponse()
            assert resp.status == 413
            conn.close()
        finally:
            stop()
            repo.close()
