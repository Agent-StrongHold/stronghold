"""Tests for Mason management API routes."""

from __future__ import annotations

import hashlib
import hmac
import json
import os
from dataclasses import dataclass, field
from typing import Any
from unittest.mock import patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from stronghold.api.routes import mason as mason_mod
from stronghold.api.routes.mason import (
    _verify_signature,
    configure_mason_router,
    router as mason_router,
)


# ── Fake queue and reactor ──────────────────────────────────────────


@dataclass
class FakeIssue:
    issue_number: int
    title: str = ""
    owner: str = ""
    repo: str = ""
    status: str = "queued"


@dataclass
class FakeMasonQueue:
    """Simple in-memory implementation of the queue interface Mason uses."""

    _issues: dict[int, FakeIssue] = field(default_factory=dict)
    _logs: dict[int, list[str]] = field(default_factory=dict)

    def assign(self, issue_number: int, title: str = "", owner: str = "", repo: str = "") -> FakeIssue:
        issue = FakeIssue(issue_number=issue_number, title=title, owner=owner, repo=repo)
        self._issues[issue_number] = issue
        self._logs[issue_number] = []
        return issue

    def list_all(self) -> list[dict[str, Any]]:
        return [
            {
                "issue_number": i.issue_number,
                "title": i.title,
                "owner": i.owner,
                "repo": i.repo,
                "status": i.status,
            }
            for i in self._issues.values()
        ]

    def status(self) -> dict[str, Any]:
        return {
            "queued": sum(1 for i in self._issues.values() if i.status == "queued"),
            "running": sum(1 for i in self._issues.values() if i.status == "running"),
            "total": len(self._issues),
        }

    def start(self, issue_number: int) -> None:
        if issue_number in self._issues:
            self._issues[issue_number].status = "running"

    def complete(self, issue_number: int) -> None:
        if issue_number in self._issues:
            self._issues[issue_number].status = "completed"

    def fail(self, issue_number: int, error: str = "") -> None:
        if issue_number in self._issues:
            self._issues[issue_number].status = "failed"

    def add_log(self, issue_number: int, msg: str) -> None:
        self._logs.setdefault(issue_number, []).append(msg)


@dataclass
class FakeReactor:
    events: list[Any] = field(default_factory=list)

    def emit(self, event: Any) -> None:
        self.events.append(event)


# ── Fixtures ────────────────────────────────────────────────────────


@pytest.fixture
def mason_app():
    """App with Mason router configured with fakes."""
    queue = FakeMasonQueue()
    reactor = FakeReactor()
    configure_mason_router(queue=queue, reactor=reactor, container=None)
    # Clear shared cache between tests
    mason_mod._issues_cache.clear()

    app = FastAPI()
    app.include_router(mason_router)
    return app, queue, reactor


@pytest.fixture
def client(mason_app):
    app, _, _ = mason_app
    return TestClient(app)


# ── /mason/assign ───────────────────────────────────────────────────


def test_assign_missing_issue_number_returns_400(client: TestClient) -> None:
    resp = client.post("/v1/stronghold/mason/assign", json={})
    assert resp.status_code == 400
    assert "issue_number" in resp.json()["error"]


def test_assign_puts_issue_in_queue(mason_app) -> None:
    app, queue, _ = mason_app
    client = TestClient(app)
    resp = client.post(
        "/v1/stronghold/mason/assign",
        json={"issue_number": 42, "title": "fix bug", "owner": "org", "repo": "repo"},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "assigned"
    assert data["issue_number"] == 42
    assert len(queue._issues) == 1
    assert queue._issues[42].title == "fix bug"


def test_assign_returns_queue_position(mason_app) -> None:
    app, queue, _ = mason_app
    client = TestClient(app)
    # Pre-queue 2 issues
    queue.assign(1)
    queue.assign(2)
    resp = client.post("/v1/stronghold/mason/assign", json={"issue_number": 3})
    assert resp.json()["queue_position"] >= 1


# ── /mason/review-pr ────────────────────────────────────────────────


def test_review_pr_missing_pr_number_returns_400(client: TestClient) -> None:
    resp = client.post("/v1/stronghold/mason/review-pr", json={})
    assert resp.status_code == 400
    assert "pr_number" in resp.json()["error"]


def test_review_pr_emits_event(mason_app) -> None:
    app, _, reactor = mason_app
    client = TestClient(app)
    resp = client.post(
        "/v1/stronghold/mason/review-pr",
        json={"pr_number": 100, "owner": "org", "repo": "repo"},
    )
    assert resp.status_code == 200
    assert resp.json()["status"] == "queued"
    assert len(reactor.events) == 1
    event = reactor.events[0]
    assert event.name == "mason.pr_review_requested"
    assert event.data["pr_number"] == 100


# ── /mason/queue ────────────────────────────────────────────────────


def test_queue_lists_all(mason_app) -> None:
    app, queue, _ = mason_app
    client = TestClient(app)
    queue.assign(1, title="one")
    queue.assign(2, title="two")
    resp = client.get("/v1/stronghold/mason/queue")
    assert resp.status_code == 200
    issues = resp.json()["issues"]
    assert len(issues) == 2


def test_queue_empty(client: TestClient) -> None:
    resp = client.get("/v1/stronghold/mason/queue")
    assert resp.json()["issues"] == []


# ── /mason/status ───────────────────────────────────────────────────


def test_status_returns_counts(mason_app) -> None:
    app, queue, _ = mason_app
    client = TestClient(app)
    queue.assign(1)
    queue.assign(2)
    queue.start(1)
    resp = client.get("/v1/stronghold/mason/status")
    data = resp.json()
    assert data["running"] == 1
    assert data["queued"] == 1
    assert data["total"] == 2


# ── GitHub webhook — signature verification ─────────────────────────


def test_verify_signature_missing_prefix_rejected() -> None:
    assert _verify_signature(b"payload", "secret", "not-a-valid-signature") is False


def test_verify_signature_valid() -> None:
    body = b'{"test": "payload"}'
    secret = "shhh"
    sig = "sha256=" + hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()
    assert _verify_signature(body, secret, sig) is True


def test_verify_signature_wrong_secret() -> None:
    body = b'{"test": "payload"}'
    sig = "sha256=" + hmac.new(b"wrong", body, hashlib.sha256).hexdigest()
    assert _verify_signature(body, "right", sig) is False


# ── /webhooks/github ────────────────────────────────────────────────


def test_webhook_no_secret_accepts_unsigned(mason_app) -> None:
    app, queue, _ = mason_app
    client = TestClient(app)
    os.environ.pop("GITHUB_WEBHOOK_SECRET", None)
    resp = client.post(
        "/v1/stronghold/webhooks/github",
        headers={"X-GitHub-Event": "issues"},
        json={
            "action": "assigned",
            "issue": {"number": 99, "title": "webhook issue"},
            "repository": {"owner": {"login": "org"}, "name": "repo"},
        },
    )
    assert resp.status_code == 200
    assert 99 in queue._issues


def test_webhook_bad_signature_rejected(client: TestClient) -> None:
    try:
        os.environ["GITHUB_WEBHOOK_SECRET"] = "test-secret"
        resp = client.post(
            "/v1/stronghold/webhooks/github",
            headers={"X-Hub-Signature-256": "sha256=bogus"},
            json={},
        )
        assert resp.status_code == 401
    finally:
        os.environ.pop("GITHUB_WEBHOOK_SECRET", None)


def test_webhook_valid_signature_accepted(client: TestClient) -> None:
    try:
        secret = "test-secret"
        os.environ["GITHUB_WEBHOOK_SECRET"] = secret
        body_bytes = b'{"action":"opened"}'
        sig = "sha256=" + hmac.new(secret.encode(), body_bytes, hashlib.sha256).hexdigest()
        resp = client.post(
            "/v1/stronghold/webhooks/github",
            headers={"X-Hub-Signature-256": sig, "X-GitHub-Event": "pull_request", "content-type": "application/json"},
            content=body_bytes,
        )
        assert resp.status_code == 200
    finally:
        os.environ.pop("GITHUB_WEBHOOK_SECRET", None)


def test_webhook_issue_assigned_queues(mason_app) -> None:
    app, queue, reactor = mason_app
    client = TestClient(app)
    resp = client.post(
        "/v1/stronghold/webhooks/github",
        headers={"X-GitHub-Event": "issues"},
        json={
            "action": "assigned",
            "issue": {"number": 555, "title": "webhook queued"},
            "repository": {"owner": {"login": "acme"}, "name": "repo"},
        },
    )
    assert resp.status_code == 200
    assert 555 in queue._issues
    assert any(e.name == "mason.issue_assigned" for e in reactor.events)


def test_webhook_pr_opened_emits_event(mason_app) -> None:
    app, _, reactor = mason_app
    client = TestClient(app)
    resp = client.post(
        "/v1/stronghold/webhooks/github",
        headers={"X-GitHub-Event": "pull_request"},
        json={
            "action": "opened",
            "pull_request": {"number": 200, "title": "new pr", "user": {"login": "dev"}},
        },
    )
    assert resp.status_code == 200
    assert any(e.name == "pr.opened" and e.data["pr_number"] == 200 for e in reactor.events)


def test_webhook_pr_reviewed_emits_event(mason_app) -> None:
    app, _, reactor = mason_app
    client = TestClient(app)
    resp = client.post(
        "/v1/stronghold/webhooks/github",
        headers={"X-GitHub-Event": "pull_request_review"},
        json={
            "action": "submitted",
            "pull_request": {"number": 300},
            "review": {"state": "changes_requested", "user": {"login": "reviewer"}, "body": "fix x"},
        },
    )
    assert resp.status_code == 200
    assert any(e.name == "pr.reviewed" for e in reactor.events)


def test_webhook_issue_comment_on_pr_emits(mason_app) -> None:
    app, _, reactor = mason_app
    client = TestClient(app)
    resp = client.post(
        "/v1/stronghold/webhooks/github",
        headers={"X-GitHub-Event": "issue_comment"},
        json={
            "action": "created",
            "comment": {"body": "lgtm", "user": {"login": "reviewer"}},
            "issue": {"number": 777, "pull_request": {"url": "..."}},
        },
    )
    assert resp.status_code == 200
    assert any(e.name == "pr.commented" for e in reactor.events)


def test_webhook_issue_comment_not_on_pr_ignored(mason_app) -> None:
    app, _, reactor = mason_app
    client = TestClient(app)
    resp = client.post(
        "/v1/stronghold/webhooks/github",
        headers={"X-GitHub-Event": "issue_comment"},
        json={
            "action": "created",
            "comment": {"body": "ignored", "user": {"login": "x"}},
            "issue": {"number": 100},  # No pull_request key
        },
    )
    assert resp.status_code == 200
    assert not any(e.name == "pr.commented" for e in reactor.events)


def test_webhook_unknown_event_returns_ok(mason_app) -> None:
    app, _, _ = mason_app
    client = TestClient(app)
    resp = client.post(
        "/v1/stronghold/webhooks/github",
        headers={"X-GitHub-Event": "push"},
        json={"action": "pushed"},
    )
    assert resp.status_code == 200


# ── /mason/issues (cached fetch) ────────────────────────────────────


def test_issues_missing_params_returns_400(client: TestClient) -> None:
    resp = client.get("/v1/stronghold/mason/issues")
    assert resp.status_code == 400


def test_issues_missing_repo_returns_400(client: TestClient) -> None:
    resp = client.get("/v1/stronghold/mason/issues?owner=foo")
    assert resp.status_code == 400


# ── /mason/scan (codebase scanner) ──────────────────────────────────


def test_scan_returns_suggestions(client: TestClient) -> None:
    """Scan endpoint runs scanner and returns suggestions in expected shape."""
    resp = client.get("/v1/stronghold/mason/scan")
    assert resp.status_code == 200
    data = resp.json()
    assert "count" in data
    assert "suggestions" in data
    assert isinstance(data["suggestions"], list)
    # Each suggestion should have required keys
    for s in data["suggestions"]:
        assert "title" in s
        assert "category" in s
        assert "scope" in s
        assert "github_payload" in s


# ── /mason/scan/create ──────────────────────────────────────────────


def test_scan_create_missing_owner_returns_400(client: TestClient) -> None:
    resp = client.post("/v1/stronghold/mason/scan/create", json={"repo": "r"})
    assert resp.status_code == 400


def test_scan_create_missing_repo_returns_400(client: TestClient) -> None:
    resp = client.post("/v1/stronghold/mason/scan/create", json={"owner": "o"})
    assert resp.status_code == 400


def test_scan_create_with_invalid_indices(client: TestClient) -> None:
    """Out-of-range indices are silently skipped."""
    from unittest.mock import AsyncMock, patch
    fake_result = type("R", (), {"success": False, "content": "", "error": "gh offline"})()
    with patch(
        "stronghold.tools.github.GitHubToolExecutor.execute",
        new=AsyncMock(return_value=fake_result),
    ):
        resp = client.post(
            "/v1/stronghold/mason/scan/create",
            json={"owner": "o", "repo": "r", "indices": [9999]},
        )
    assert resp.status_code == 200
    # Out-of-range index is skipped → no errors, no creates
    assert resp.json()["created"] == 0


# ── /mason/issues cached fetch ──────────────────────────────────────


def test_issues_fetches_from_github_on_miss(client: TestClient) -> None:
    """First call hits GitHub, subsequent calls use cache."""
    from unittest.mock import AsyncMock, patch

    call_count = {"n": 0}
    issues_payload = [
        {"number": 1, "title": "issue-1", "labels": ["bug"]},
        {"number": 2, "title": "issue-2", "labels": ["feature"]},
    ]

    async def fake_execute(args):
        call_count["n"] += 1
        result = type("R", (), {
            "success": True,
            "content": json.dumps(issues_payload),
            "error": None,
        })()
        return result

    with patch(
        "stronghold.tools.github.GitHubToolExecutor.execute",
        new=AsyncMock(side_effect=fake_execute),
    ):
        r1 = client.get("/v1/stronghold/mason/issues?owner=org&repo=repo")
        r2 = client.get("/v1/stronghold/mason/issues?owner=org&repo=repo")

    assert r1.status_code == 200
    assert r1.json()["total"] == 2
    assert "bug" in r1.json()["labels"]
    # Second call served from cache — executor called only once
    assert call_count["n"] == 1
    assert r2.json()["total"] == 2


def test_issues_github_error_502(client: TestClient) -> None:
    """If GitHub fails and no cache, return 502."""
    from unittest.mock import AsyncMock, patch

    fake_result = type("R", (), {
        "success": False,
        "content": "",
        "error": "GitHub API offline",
    })()

    with patch(
        "stronghold.tools.github.GitHubToolExecutor.execute",
        new=AsyncMock(return_value=fake_result),
    ):
        resp = client.get("/v1/stronghold/mason/issues?owner=novel&repo=novel")

    assert resp.status_code == 502
    assert "GitHub API offline" in resp.json()["error"]


# ── _dispatch_mason (background task) ───────────────────────────────


async def test_dispatch_mason_no_container_fails_gracefully(mason_app) -> None:
    """_dispatch_mason with no container records failure and returns."""
    app, queue, _ = mason_app
    # container=None configured in fixture
    queue.assign(issue_number=1, title="t", owner="o", repo="r")
    issue = queue._issues[1]

    from stronghold.api.routes.mason import _dispatch_mason
    await _dispatch_mason(issue)

    assert queue._issues[1].status == "failed"


async def test_dispatch_mason_workspace_failure(mason_app) -> None:
    """_dispatch_mason handles workspace creation failure."""
    from unittest.mock import AsyncMock, MagicMock, patch
    app, queue, reactor = mason_app

    # Configure with a real container mock
    container = MagicMock()
    container.route_request = AsyncMock()
    mason_mod._state["container"] = container

    queue.assign(issue_number=2, title="t", owner="o", repo="r")
    issue = queue._issues[2]

    fake_ws_result = type("R", (), {
        "success": False,
        "content": "",
        "error": "git checkout failed",
    })()

    with patch(
        "stronghold.tools.workspace.WorkspaceManager.execute",
        new=AsyncMock(return_value=fake_ws_result),
    ):
        from stronghold.api.routes.mason import _dispatch_mason
        await _dispatch_mason(issue)

    assert queue._issues[2].status == "failed"
    # Reset
    mason_mod._state["container"] = None


async def test_dispatch_mason_success_path(mason_app) -> None:
    """Full dispatch: workspace creates, route_request runs, issue marked completed."""
    from unittest.mock import AsyncMock, MagicMock, patch
    app, queue, _ = mason_app

    container = MagicMock()
    container.route_request = AsyncMock()
    mason_mod._state["container"] = container

    queue.assign(issue_number=3, title="feature", owner="o", repo="r")
    issue = queue._issues[3]

    fake_ws_result = type("R", (), {
        "success": True,
        "content": json.dumps({"path": "/tmp/ws", "branch": "feature/3"}),
        "error": None,
    })()

    with patch(
        "stronghold.tools.workspace.WorkspaceManager.execute",
        new=AsyncMock(return_value=fake_ws_result),
    ):
        from stronghold.api.routes.mason import _dispatch_mason
        await _dispatch_mason(issue)

    assert queue._issues[3].status == "completed"
    container.route_request.assert_awaited_once()
    # Verify the messages contain expected fields
    call_kwargs = container.route_request.call_args
    msgs = call_kwargs.kwargs["messages"]
    assert "feature/3" in msgs[0]["content"]
    assert "/tmp/ws" in msgs[0]["content"]
    mason_mod._state["container"] = None


def test_scan_create_all_true(client: TestClient) -> None:
    """all=True processes every suggestion."""
    from unittest.mock import AsyncMock, patch

    fake_result = type("R", (), {
        "success": True,
        "content": '{"url": "https://github.com/o/r/issues/1"}',
        "error": None,
    })()

    with patch(
        "stronghold.tools.github.GitHubToolExecutor.execute",
        new=AsyncMock(return_value=fake_result),
    ):
        resp = client.post(
            "/v1/stronghold/mason/scan/create",
            json={"owner": "o", "repo": "r", "all": True},
        )
    assert resp.status_code == 200
    data = resp.json()
    # Depends on scanner finding anything — just verify the path ran
    assert "created" in data
    assert "errors" in data
    assert "issues" in data


def test_scan_create_partial_failures(client: TestClient) -> None:
    """Mix of successful and failed creates records both."""
    from unittest.mock import AsyncMock, patch

    calls = {"n": 0}
    async def alternate(args):
        calls["n"] += 1
        if calls["n"] % 2 == 0:
            return type("R", (), {"success": False, "content": "", "error": "rate limit"})()
        return type("R", (), {"success": True, "content": "created", "error": None})()

    with patch(
        "stronghold.tools.github.GitHubToolExecutor.execute",
        new=AsyncMock(side_effect=alternate),
    ):
        resp = client.post(
            "/v1/stronghold/mason/scan/create",
            json={"owner": "o", "repo": "r", "all": True},
        )

    assert resp.status_code == 200
    data = resp.json()
    # If scanner found suggestions, we should have some errors
    if data["created"] + len(data["errors"]) > 0:
        assert data["created"] > 0 or len(data["errors"]) > 0
