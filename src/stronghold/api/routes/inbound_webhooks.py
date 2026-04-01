"""API routes for inbound webhooks — external events trigger agent actions.

Management endpoints (register/list/delete) require authentication.
The inbound endpoint uses HMAC signature verification instead of auth.
"""

from __future__ import annotations

import hashlib
import hmac
import logging
import time
from typing import Any
from uuid import uuid4

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import JSONResponse

from stronghold.webhooks.inbound import (
    WebhookConfig,
    WebhookExecution,
    render_template,
)

logger = logging.getLogger("stronghold.api.inbound_webhooks")

_MAX_TIMESTAMP_AGE_SECONDS = 300  # 5 minutes


def _verify_hmac(secret: str, timestamp: str, body: bytes, signature: str) -> bool:
    """Verify HMAC-SHA256 signature: HMAC(secret, "timestamp." + body)."""
    message = f"{timestamp}.".encode() + body
    expected = hmac.new(secret.encode(), message, hashlib.sha256).hexdigest()
    return hmac.compare_digest(expected, signature)


async def _require_auth(request: Request) -> Any:
    """Authenticate the caller and return AuthContext."""
    container = request.app.state.container
    auth_header = request.headers.get("authorization")
    try:
        auth: Any = await container.auth_provider.authenticate(
            auth_header, headers=dict(request.headers)
        )
    except ValueError as e:
        raise HTTPException(status_code=401, detail=str(e)) from e
    return auth


async def _require_admin(request: Request) -> Any:
    """Authenticate and require admin role."""
    auth = await _require_auth(request)
    if not auth.has_role("admin"):
        raise HTTPException(status_code=403, detail="Admin role required")
    return auth


def build_inbound_webhook_router() -> APIRouter:
    """Build and return the inbound webhook router."""
    router = APIRouter(prefix="/v1/stronghold/webhooks")

    @router.post("", status_code=201)
    async def register_webhook(request: Request) -> JSONResponse:
        """Register a new inbound webhook (admin only)."""
        auth = await _require_admin(request)
        container = request.app.state.container
        body: dict[str, Any] = await request.json()

        config = WebhookConfig(
            name=body.get("name", ""),
            org_id=auth.org_id,
            source=body.get("source", ""),
            agent=body.get("agent", ""),
            prompt_template=body.get("prompt_template", ""),
            enabled=body.get("enabled", True),
            created_at=time.time(),
        )

        registered = await container.webhook_store.register(config)
        return JSONResponse(
            status_code=201,
            content={
                "id": registered.id,
                "name": registered.name,
                "secret": registered.secret,
                "source": registered.source,
                "agent": registered.agent,
                "enabled": registered.enabled,
            },
        )

    @router.get("")
    async def list_webhooks(request: Request) -> JSONResponse:
        """List all webhooks for the authenticated user's org."""
        auth = await _require_auth(request)
        container = request.app.state.container
        webhooks = await container.webhook_store.list_all(org_id=auth.org_id)
        return JSONResponse(
            content={
                "webhooks": [
                    {
                        "id": wh.id,
                        "name": wh.name,
                        "source": wh.source,
                        "agent": wh.agent,
                        "enabled": wh.enabled,
                        "call_count": wh.call_count,
                    }
                    for wh in webhooks
                ]
            }
        )

    @router.delete("/{webhook_id}")
    async def delete_webhook(request: Request, webhook_id: str) -> JSONResponse:
        """Delete a webhook (admin only)."""
        auth = await _require_admin(request)
        container = request.app.state.container
        deleted = await container.webhook_store.delete(webhook_id, org_id=auth.org_id)
        if not deleted:
            raise HTTPException(status_code=404, detail="Webhook not found")
        return JSONResponse(content={"deleted": True})

    @router.post("/inbound/{webhook_id}")
    async def receive_inbound(request: Request, webhook_id: str) -> JSONResponse:
        """Receive an external event via inbound webhook.

        No auth required — uses HMAC signature verification.
        Headers:
            X-Stronghold-Signature: HMAC-SHA256 hex digest
            X-Stronghold-Timestamp: Unix epoch seconds
        Body: any JSON payload
        """
        container = request.app.state.container

        # 1. Look up webhook config by ID
        webhook = await container.webhook_store.get_by_id_unsafe(webhook_id)
        if webhook is None:
            raise HTTPException(status_code=404, detail="Webhook not found")

        # 2. Check if webhook is enabled
        if not webhook.enabled:
            raise HTTPException(status_code=403, detail="Webhook is disabled")

        # 3. Validate timestamp
        ts_header = request.headers.get("X-Stronghold-Timestamp", "")
        if not ts_header:
            raise HTTPException(status_code=401, detail="Missing X-Stronghold-Timestamp header")

        try:
            ts = float(ts_header)
        except (ValueError, TypeError):
            raise HTTPException(
                status_code=401,
                detail="X-Stronghold-Timestamp must be a numeric epoch",
            ) from None

        age = abs(time.time() - ts)
        if age > _MAX_TIMESTAMP_AGE_SECONDS:
            raise HTTPException(
                status_code=401,
                detail=(f"Webhook timestamp too old ({int(age)}s > {_MAX_TIMESTAMP_AGE_SECONDS}s)"),
            )

        # 4. Verify HMAC signature
        signature = request.headers.get("X-Stronghold-Signature", "")
        if not signature:
            raise HTTPException(status_code=401, detail="Missing X-Stronghold-Signature header")

        body_bytes = await request.body()
        if not _verify_hmac(webhook.secret, ts_header, body_bytes, signature):
            raise HTTPException(status_code=401, detail="Invalid HMAC signature")

        # 5. Rate limit: max 60 calls/minute per webhook
        now = time.time()
        if not container.webhook_store.check_rate_limit(webhook_id, now):
            raise HTTPException(status_code=429, detail="Rate limit exceeded")
        container.webhook_store.record_call(webhook_id, now)

        # 6. Parse payload and render template
        import json  # noqa: PLC0415

        try:
            payload: dict[str, Any] = json.loads(body_bytes)
        except (json.JSONDecodeError, ValueError):
            raise HTTPException(status_code=400, detail="Invalid JSON payload") from None

        rendered = render_template(webhook.prompt_template, payload)

        # 7. Record execution
        execution = WebhookExecution(
            id=str(uuid4()),
            webhook_id=webhook_id,
            timestamp=now,
            status="success",
            detail=rendered,
        )
        await container.webhook_store.record_execution(webhook_id, execution)

        # Increment call count
        webhook.call_count += 1

        # 8. Return result (actual Conduit dispatch is a follow-up)
        return JSONResponse(
            content={
                "status": "success",
                "webhook_id": webhook_id,
                "rendered_prompt": rendered,
                "agent": webhook.agent,
                "execution_id": execution.id,
            }
        )

    return router
