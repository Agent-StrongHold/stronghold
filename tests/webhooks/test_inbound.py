"""Tests for inbound webhook processing — external events trigger agent actions."""

from __future__ import annotations

import hashlib
import hmac
import time

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from stronghold.webhooks.inbound import (
    InMemoryWebhookStore,
    WebhookConfig,
    WebhookExecution,
    render_template,
)


# ── Unit tests: WebhookConfig + InMemoryWebhookStore ───────────────────


class TestWebhookConfig:
    """WebhookConfig dataclass construction."""

    def test_defaults(self) -> None:
        cfg = WebhookConfig()
        assert cfg.id == ""
        assert cfg.name == ""
        assert cfg.org_id == ""
        assert cfg.secret == ""
        assert cfg.source == ""
        assert cfg.agent == ""
        assert cfg.prompt_template == ""
        assert cfg.enabled is True
        assert cfg.created_at == 0.0
        assert cfg.call_count == 0

    def test_custom_values(self) -> None:
        cfg = WebhookConfig(
            id="wh-1",
            name="GitHub PR",
            org_id="org-42",
            secret="s3cret",
            source="github",
            agent="artificer",
            prompt_template="PR merged: {{title}}",
            enabled=False,
        )
        assert cfg.id == "wh-1"
        assert cfg.name == "GitHub PR"
        assert cfg.agent == "artificer"
        assert cfg.enabled is False


class TestInMemoryWebhookStore:
    """InMemoryWebhookStore CRUD operations."""

    async def test_register_generates_id_and_secret(self) -> None:
        store = InMemoryWebhookStore()
        cfg = WebhookConfig(name="test", org_id="org-1")
        result = await store.register(cfg)
        assert result.id != ""
        assert result.secret != ""
        assert len(result.secret) > 20  # token_urlsafe(32) is ~43 chars

    async def test_register_preserves_explicit_id(self) -> None:
        store = InMemoryWebhookStore()
        cfg = WebhookConfig(id="my-id", name="test", org_id="org-1", secret="my-secret")
        result = await store.register(cfg)
        assert result.id == "my-id"
        assert result.secret == "my-secret"

    async def test_get_returns_webhook_for_matching_org(self) -> None:
        store = InMemoryWebhookStore()
        cfg = WebhookConfig(name="test", org_id="org-1")
        registered = await store.register(cfg)
        fetched = await store.get(registered.id, org_id="org-1")
        assert fetched is not None
        assert fetched.id == registered.id

    async def test_get_returns_none_for_wrong_org(self) -> None:
        store = InMemoryWebhookStore()
        cfg = WebhookConfig(name="test", org_id="org-1")
        registered = await store.register(cfg)
        fetched = await store.get(registered.id, org_id="org-OTHER")
        assert fetched is None

    async def test_get_returns_none_for_nonexistent(self) -> None:
        store = InMemoryWebhookStore()
        fetched = await store.get("no-such-id", org_id="org-1")
        assert fetched is None

    async def test_list_all_scoped_by_org(self) -> None:
        store = InMemoryWebhookStore()
        await store.register(WebhookConfig(name="a", org_id="org-1"))
        await store.register(WebhookConfig(name="b", org_id="org-1"))
        await store.register(WebhookConfig(name="c", org_id="org-2"))

        org1 = await store.list_all(org_id="org-1")
        org2 = await store.list_all(org_id="org-2")
        assert len(org1) == 2
        assert len(org2) == 1

    async def test_delete_removes_webhook(self) -> None:
        store = InMemoryWebhookStore()
        cfg = WebhookConfig(name="test", org_id="org-1")
        registered = await store.register(cfg)
        deleted = await store.delete(registered.id, org_id="org-1")
        assert deleted is True
        assert await store.get(registered.id, org_id="org-1") is None

    async def test_delete_wrong_org_returns_false(self) -> None:
        store = InMemoryWebhookStore()
        cfg = WebhookConfig(name="test", org_id="org-1")
        registered = await store.register(cfg)
        deleted = await store.delete(registered.id, org_id="org-OTHER")
        assert deleted is False
        # Still exists for original org
        assert await store.get(registered.id, org_id="org-1") is not None

    async def test_delete_nonexistent_returns_false(self) -> None:
        store = InMemoryWebhookStore()
        deleted = await store.delete("no-such-id", org_id="org-1")
        assert deleted is False

    async def test_record_execution(self) -> None:
        store = InMemoryWebhookStore()
        cfg = await store.register(WebhookConfig(name="test", org_id="org-1"))
        execution = WebhookExecution(
            id="exec-1",
            webhook_id=cfg.id,
            timestamp=time.time(),
            status="success",
            detail="rendered prompt",
        )
        await store.record_execution(cfg.id, execution)
        execs = await store.get_executions(cfg.id)
        assert len(execs) == 1
        assert execs[0].id == "exec-1"
        assert execs[0].status == "success"

    async def test_get_by_id_unsafe_ignores_org(self) -> None:
        store = InMemoryWebhookStore()
        cfg = await store.register(WebhookConfig(name="test", org_id="org-1"))
        # get_by_id_unsafe doesn't check org
        fetched = await store.get_by_id_unsafe(cfg.id)
        assert fetched is not None
        assert fetched.id == cfg.id

    async def test_get_by_id_unsafe_returns_none_for_missing(self) -> None:
        store = InMemoryWebhookStore()
        assert await store.get_by_id_unsafe("nope") is None


# ── Unit tests: render_template ────────────────────────────────────────


class TestRenderTemplate:
    """Template rendering with {{field}} placeholders."""

    def test_simple_substitution(self) -> None:
        result = render_template("Hello {{name}}", {"name": "World"})
        assert result == "Hello World"

    def test_multiple_fields(self) -> None:
        tpl = "PR {{action}} by {{author}} on {{repo}}"
        payload = {"action": "merged", "author": "alice", "repo": "stronghold"}
        result = render_template(tpl, payload)
        assert result == "PR merged by alice on stronghold"

    def test_missing_field_leaves_placeholder(self) -> None:
        result = render_template("Hello {{name}}, welcome to {{place}}", {"name": "Bob"})
        assert result == "Hello Bob, welcome to {{place}}"

    def test_empty_template(self) -> None:
        result = render_template("", {"name": "test"})
        assert result == ""

    def test_no_placeholders(self) -> None:
        result = render_template("Just plain text", {"key": "val"})
        assert result == "Just plain text"

    def test_numeric_value_converted_to_string(self) -> None:
        result = render_template("Count: {{n}}", {"n": 42})
        assert result == "Count: 42"


# ── Integration tests: API routes ──────────────────────────────────────


def _build_test_app(
    webhook_store: InMemoryWebhookStore,
    *,
    auth_org_id: str = "org-test",
) -> FastAPI:
    """Build a minimal FastAPI app with inbound webhook routes for testing."""
    from unittest.mock import AsyncMock

    from stronghold.api.routes.inbound_webhooks import build_inbound_webhook_router
    from stronghold.types.auth import AuthContext, IdentityKind

    app = FastAPI()

    # Fake container with what the routes need
    class FakeContainer:
        webhook_store = None  # set below
        auth_provider = None  # set below

    fake_auth = AsyncMock()
    fake_auth.authenticate = AsyncMock(
        return_value=AuthContext(
            user_id="admin-user",
            username="admin",
            org_id=auth_org_id,
            roles=frozenset({"admin", "user"}),
            kind=IdentityKind.USER,
            auth_method="api_key",
        )
    )

    container = FakeContainer()
    container.webhook_store = webhook_store
    container.auth_provider = fake_auth
    app.state.container = container  # type: ignore[attr-defined]

    router = build_inbound_webhook_router()
    app.include_router(router)
    return app


def _sign_payload(secret: str, timestamp: str, body: bytes) -> str:
    """Compute HMAC-SHA256 signature for a webhook payload."""
    message = f"{timestamp}.".encode() + body
    return hmac.new(secret.encode(), message, hashlib.sha256).hexdigest()


@pytest.fixture
async def webhook_store() -> InMemoryWebhookStore:
    """Fresh webhook store for each test."""
    return InMemoryWebhookStore()


@pytest.fixture
async def registered_webhook(webhook_store: InMemoryWebhookStore) -> WebhookConfig:
    """A pre-registered webhook for inbound tests."""
    return await webhook_store.register(
        WebhookConfig(
            name="Test Webhook",
            org_id="org-test",
            source="github",
            agent="artificer",
            prompt_template="Event: {{action}} on {{repo}}",
        )
    )


class TestInboundWebhookAPI:
    """Integration tests for inbound webhook HTTP endpoints."""

    async def test_register_webhook(self, webhook_store: InMemoryWebhookStore) -> None:
        app = _build_test_app(webhook_store)
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            resp = await client.post(
                "/v1/stronghold/webhooks",
                json={
                    "name": "CI Webhook",
                    "source": "github",
                    "agent": "artificer",
                    "prompt_template": "Build: {{status}}",
                },
                headers={"Authorization": "Bearer sk-test"},
            )
        assert resp.status_code == 201
        data = resp.json()
        assert data["id"] != ""
        assert data["secret"] != ""
        assert data["name"] == "CI Webhook"

    async def test_list_webhooks_scoped_by_org(
        self,
        webhook_store: InMemoryWebhookStore,
        registered_webhook: WebhookConfig,
    ) -> None:
        # Also register one for a different org
        await webhook_store.register(WebhookConfig(name="other", org_id="org-other"))
        app = _build_test_app(webhook_store, auth_org_id="org-test")
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            resp = await client.get(
                "/v1/stronghold/webhooks",
                headers={"Authorization": "Bearer sk-test"},
            )
        assert resp.status_code == 200
        data = resp.json()
        assert len(data["webhooks"]) == 1
        assert data["webhooks"][0]["name"] == "Test Webhook"

    async def test_delete_webhook(
        self,
        webhook_store: InMemoryWebhookStore,
        registered_webhook: WebhookConfig,
    ) -> None:
        app = _build_test_app(webhook_store)
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            resp = await client.delete(
                f"/v1/stronghold/webhooks/{registered_webhook.id}",
                headers={"Authorization": "Bearer sk-test"},
            )
        assert resp.status_code == 200
        assert await webhook_store.get(registered_webhook.id, org_id="org-test") is None

    async def test_delete_nonexistent_webhook(
        self,
        webhook_store: InMemoryWebhookStore,
    ) -> None:
        app = _build_test_app(webhook_store)
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            resp = await client.delete(
                "/v1/stronghold/webhooks/no-such-id",
                headers={"Authorization": "Bearer sk-test"},
            )
        assert resp.status_code == 404

    async def test_inbound_valid_hmac_succeeds(
        self,
        webhook_store: InMemoryWebhookStore,
        registered_webhook: WebhookConfig,
    ) -> None:
        app = _build_test_app(webhook_store)
        body = b'{"action":"push","repo":"stronghold"}'
        ts = str(int(time.time()))
        sig = _sign_payload(registered_webhook.secret, ts, body)
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            resp = await client.post(
                f"/v1/stronghold/webhooks/inbound/{registered_webhook.id}",
                content=body,
                headers={
                    "Content-Type": "application/json",
                    "X-Stronghold-Signature": sig,
                    "X-Stronghold-Timestamp": ts,
                },
            )
        assert resp.status_code == 200
        data = resp.json()
        assert data["rendered_prompt"] == "Event: push on stronghold"
        assert data["status"] == "success"

    async def test_inbound_invalid_hmac_rejected(
        self,
        webhook_store: InMemoryWebhookStore,
        registered_webhook: WebhookConfig,
    ) -> None:
        app = _build_test_app(webhook_store)
        body = b'{"action":"push"}'
        ts = str(int(time.time()))
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            resp = await client.post(
                f"/v1/stronghold/webhooks/inbound/{registered_webhook.id}",
                content=body,
                headers={
                    "Content-Type": "application/json",
                    "X-Stronghold-Signature": "bad-signature",
                    "X-Stronghold-Timestamp": ts,
                },
            )
        assert resp.status_code == 401
        assert "HMAC" in resp.json()["detail"] or "signature" in resp.json()["detail"].lower()

    async def test_inbound_expired_timestamp_rejected(
        self,
        webhook_store: InMemoryWebhookStore,
        registered_webhook: WebhookConfig,
    ) -> None:
        app = _build_test_app(webhook_store)
        body = b'{"action":"push"}'
        old_ts = str(int(time.time()) - 600)  # 10 minutes ago
        sig = _sign_payload(registered_webhook.secret, old_ts, body)
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            resp = await client.post(
                f"/v1/stronghold/webhooks/inbound/{registered_webhook.id}",
                content=body,
                headers={
                    "Content-Type": "application/json",
                    "X-Stronghold-Signature": sig,
                    "X-Stronghold-Timestamp": old_ts,
                },
            )
        assert resp.status_code == 401
        assert "timestamp" in resp.json()["detail"].lower()

    async def test_inbound_nonexistent_webhook_returns_404(
        self,
        webhook_store: InMemoryWebhookStore,
    ) -> None:
        app = _build_test_app(webhook_store)
        body = b'{"action":"push"}'
        ts = str(int(time.time()))
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            resp = await client.post(
                "/v1/stronghold/webhooks/inbound/nonexistent-id",
                content=body,
                headers={
                    "Content-Type": "application/json",
                    "X-Stronghold-Signature": "anything",
                    "X-Stronghold-Timestamp": ts,
                },
            )
        assert resp.status_code == 404

    async def test_inbound_missing_signature_header_rejected(
        self,
        webhook_store: InMemoryWebhookStore,
        registered_webhook: WebhookConfig,
    ) -> None:
        app = _build_test_app(webhook_store)
        body = b'{"action":"push"}'
        ts = str(int(time.time()))
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            resp = await client.post(
                f"/v1/stronghold/webhooks/inbound/{registered_webhook.id}",
                content=body,
                headers={
                    "Content-Type": "application/json",
                    "X-Stronghold-Timestamp": ts,
                },
            )
        assert resp.status_code == 401

    async def test_inbound_missing_timestamp_header_rejected(
        self,
        webhook_store: InMemoryWebhookStore,
        registered_webhook: WebhookConfig,
    ) -> None:
        app = _build_test_app(webhook_store)
        body = b'{"action":"push"}'
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            resp = await client.post(
                f"/v1/stronghold/webhooks/inbound/{registered_webhook.id}",
                content=body,
                headers={
                    "Content-Type": "application/json",
                    "X-Stronghold-Signature": "anything",
                },
            )
        assert resp.status_code == 401

    async def test_execution_recorded_after_inbound(
        self,
        webhook_store: InMemoryWebhookStore,
        registered_webhook: WebhookConfig,
    ) -> None:
        app = _build_test_app(webhook_store)
        body = b'{"action":"push","repo":"stronghold"}'
        ts = str(int(time.time()))
        sig = _sign_payload(registered_webhook.secret, ts, body)
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            await client.post(
                f"/v1/stronghold/webhooks/inbound/{registered_webhook.id}",
                content=body,
                headers={
                    "Content-Type": "application/json",
                    "X-Stronghold-Signature": sig,
                    "X-Stronghold-Timestamp": ts,
                },
            )
        execs = await webhook_store.get_executions(registered_webhook.id)
        assert len(execs) == 1
        assert execs[0].status == "success"
        assert execs[0].webhook_id == registered_webhook.id

    async def test_inbound_disabled_webhook_rejected(
        self,
        webhook_store: InMemoryWebhookStore,
    ) -> None:
        cfg = await webhook_store.register(
            WebhookConfig(
                name="Disabled",
                org_id="org-test",
                enabled=False,
            )
        )
        app = _build_test_app(webhook_store)
        body = b'{"action":"push"}'
        ts = str(int(time.time()))
        sig = _sign_payload(cfg.secret, ts, body)
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            resp = await client.post(
                f"/v1/stronghold/webhooks/inbound/{cfg.id}",
                content=body,
                headers={
                    "Content-Type": "application/json",
                    "X-Stronghold-Signature": sig,
                    "X-Stronghold-Timestamp": ts,
                },
            )
        assert resp.status_code == 403
        assert "disabled" in resp.json()["detail"].lower()

    async def test_inbound_rate_limit_exceeded(
        self,
        webhook_store: InMemoryWebhookStore,
    ) -> None:
        """Webhook with 60 recent calls should be rate limited."""
        cfg = await webhook_store.register(
            WebhookConfig(
                name="Busy",
                org_id="org-test",
                prompt_template="{{action}}",
            )
        )
        # Simulate 60 recent calls by recording timestamps in the store
        now = time.time()
        for i in range(60):
            webhook_store.record_call(cfg.id, now - i)

        app = _build_test_app(webhook_store)
        body = b'{"action":"push"}'
        ts = str(int(time.time()))
        sig = _sign_payload(cfg.secret, ts, body)
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            resp = await client.post(
                f"/v1/stronghold/webhooks/inbound/{cfg.id}",
                content=body,
                headers={
                    "Content-Type": "application/json",
                    "X-Stronghold-Signature": sig,
                    "X-Stronghold-Timestamp": ts,
                },
            )
        assert resp.status_code == 429
