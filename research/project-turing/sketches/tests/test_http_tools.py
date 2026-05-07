"""Tests for SearxSearch, MediaWikiWriter, WordPressWriter.

These tools make HTTP calls, so we inject a mock httpx.Client with
a custom transport that returns canned responses.

Acceptance criteria:
- AC-S1: SearxSearch.invoke returns SearchResult list from JSON
- AC-S2: SearxSearch.invoke respects max_results
- AC-S3: SearxSearch raises on empty base_url
- AC-S4: MediaWikiWriter.invoke logs in + fetches CSRF + edits page
- AC-S5: MediaWikiWriter raises on missing credentials
- AC-S6: WordPressWriter.invoke creates a draft post
- AC-W1: WordPressWriter raises on missing credentials
- AC-W2: WordPressWriter passes optional fields (categories, tags, excerpt)
"""

from __future__ import annotations

import json
from typing import Any

import httpx
import pytest

from turing.runtime.tools.search import SearxSearch, SearchResult
from turing.runtime.tools.wiki import MediaWikiWriter
from turing.runtime.tools.wordpress import WordPressWriter


class _CannedTransport(httpx.BaseTransport):
    def __init__(self, responses: list[tuple[int, dict[str, Any]]]) -> None:
        self._responses = list(responses)
        self.requests: list[httpx.Request] = []

    def handle_request(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        if not self._responses:
            return httpx.Response(500, request=request)
        status, body = self._responses.pop(0)
        return httpx.Response(status, json=body, request=request)


class TestSearxSearch:
    def test_acs1_returns_results(self) -> None:
        transport = _CannedTransport(
            [
                (
                    200,
                    {
                        "results": [
                            {
                                "title": "Python",
                                "url": "https://python.org",
                                "content": "The language",
                            },
                            {"title": "PyPI", "url": "https://pypi.org", "content": "Packages"},
                        ]
                    },
                ),
            ]
        )
        client = httpx.Client(transport=transport)
        searcher = SearxSearch(base_url="http://localhost:8888", client=client)
        results = searcher.invoke(query="python")
        assert len(results) == 2
        assert isinstance(results[0], SearchResult)
        assert results[0].title == "Python"
        assert results[0].url == "https://python.org"
        assert results[0].snippet == "The language"

    def test_acs2_max_results(self) -> None:
        transport = _CannedTransport(
            [
                (
                    200,
                    {
                        "results": [
                            {"title": f"R{i}", "url": f"http://x/{i}", "content": f"C{i}"}
                            for i in range(20)
                        ]
                    },
                ),
            ]
        )
        client = httpx.Client(transport=transport)
        searcher = SearxSearch(base_url="http://localhost:8888", client=client)
        results = searcher.invoke(query="test", max_results=3)
        assert len(results) == 3

    def test_acs3_empty_url_raises(self) -> None:
        with pytest.raises(ValueError):
            SearxSearch(base_url="")

    def test_http_error_raises(self) -> None:
        transport = _CannedTransport([(500, {})])
        client = httpx.Client(transport=transport)
        searcher = SearxSearch(base_url="http://localhost:8888", client=client)
        with pytest.raises(httpx.HTTPStatusError):
            searcher.invoke(query="fail")

    def test_empty_results(self) -> None:
        transport = _CannedTransport([(200, {"results": []})])
        client = httpx.Client(transport=transport)
        searcher = SearxSearch(base_url="http://localhost:8888", client=client)
        assert searcher.invoke(query="nothing") == []


class TestMediaWikiWriter:
    def test_acs5_missing_credentials_raises(self) -> None:
        with pytest.raises(ValueError):
            MediaWikiWriter(api_url="", bot_username="u", bot_password="p")

    def test_acs4_login_edit_flow(self) -> None:
        transport = _CannedTransport(
            [
                (200, {"query": {"tokens": {"logintoken": "LT+/"}}}),
                (200, {"login": {"result": "Success"}}),
                (200, {"query": {"tokens": {"csrftoken": "CSRF+/"}}}),
                (200, {"edit": {"result": "Success", "pageid": 1}}),
            ]
        )
        client = httpx.Client(transport=transport)
        writer = MediaWikiWriter(
            api_url="http://wiki/api.php",
            bot_username="bot",
            bot_password="pass",
            client=client,
        )
        result = writer.invoke(title="TestPage", content="Hello wiki")
        assert result["result"] == "Success"
        assert len(transport.requests) == 4

    def test_wiki_edit_error_raises(self) -> None:
        transport = _CannedTransport(
            [
                (200, {"query": {"tokens": {"logintoken": "LT+/"}}}),
                (200, {"login": {"result": "Success"}}),
                (200, {"query": {"tokens": {"csrftoken": "CSRF+/"}}}),
                (200, {"error": {"code": "permissiondenied", "info": "nope"}}),
            ]
        )
        client = httpx.Client(transport=transport)
        writer = MediaWikiWriter(
            api_url="http://wiki/api.php",
            bot_username="bot",
            bot_password="pass",
            client=client,
        )
        with pytest.raises(RuntimeError, match="wiki edit error"):
            writer.invoke(title="X", content="Y")

    def test_page_prefix_applied(self) -> None:
        transport = _CannedTransport(
            [
                (200, {"query": {"tokens": {"logintoken": "LT+/"}}}),
                (200, {"login": {"result": "Success"}}),
                (200, {"query": {"tokens": {"csrftoken": "CSRF+/"}}}),
                (200, {"edit": {"result": "Success"}}),
            ]
        )
        client = httpx.Client(transport=transport)
        writer = MediaWikiWriter(
            api_url="http://wiki/api.php",
            bot_username="bot",
            bot_password="pass",
            page_prefix="Custom/",
            client=client,
        )
        writer.invoke(title="Page", content="C")
        edit_req = transport.requests[3]
        body = edit_req.content.decode()
        assert "Custom%2FPage" in body

    def test_section_param_passed(self) -> None:
        transport = _CannedTransport(
            [
                (200, {"query": {"tokens": {"logintoken": "LT+/"}}}),
                (200, {"login": {"result": "Success"}}),
                (200, {"query": {"tokens": {"csrftoken": "CSRF+/"}}}),
                (200, {"edit": {"result": "Success"}}),
            ]
        )
        client = httpx.Client(transport=transport)
        writer = MediaWikiWriter(
            api_url="http://wiki/api.php",
            bot_username="bot",
            bot_password="pass",
            client=client,
        )
        writer.invoke(title="P", content="C", section="0")
        edit_body = transport.requests[3].content.decode()
        assert "section=0" in edit_body or b"section" in transport.requests[3].content


class TestWordPressWriter:
    def test_acw1_missing_credentials_raises(self) -> None:
        with pytest.raises(ValueError):
            WordPressWriter(site_url="", username="u", application_password="p")

    def test_acw6_creates_draft(self) -> None:
        transport = _CannedTransport(
            [
                (200, {"id": 42, "status": "draft", "title": {"rendered": "Test"}}),
            ]
        )
        client = httpx.Client(transport=transport)
        writer = WordPressWriter(
            site_url="http://blog.example.com",
            username="admin",
            application_password="ap",
            client=client,
        )
        result = writer.invoke(title="Test", content="Body")
        assert result["status"] == "draft"
        req = transport.requests[0]
        body = json.loads(req.content)
        assert body["title"] == "Test"
        assert body["status"] == "draft"

    def test_acw2_optional_fields(self) -> None:
        transport = _CannedTransport(
            [
                (200, {"id": 43, "status": "publish"}),
            ]
        )
        client = httpx.Client(transport=transport)
        writer = WordPressWriter(
            site_url="http://blog.example.com",
            username="admin",
            application_password="ap",
            default_status="publish",
            client=client,
        )
        result = writer.invoke(
            title="T",
            content="C",
            status="publish",
            categories=[1, 2],
            tags=[10],
            excerpt="Short",
        )
        body = json.loads(transport.requests[0].content)
        assert body["categories"] == [1, 2]
        assert body["tags"] == [10]
        assert body["excerpt"] == "Short"

    def test_custom_status_overrides_default(self) -> None:
        transport = _CannedTransport(
            [
                (200, {"id": 44, "status": "publish"}),
            ]
        )
        client = httpx.Client(transport=transport)
        writer = WordPressWriter(
            site_url="http://blog.example.com",
            username="admin",
            application_password="ap",
            client=client,
        )
        writer.invoke(title="T", content="C", status="publish")
        body = json.loads(transport.requests[0].content)
        assert body["status"] == "publish"
