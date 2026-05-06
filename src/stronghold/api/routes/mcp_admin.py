"""API routes: admin endpoints for the MCP tool catalog.

Provides the operational surface for managing approved tools at runtime
without restarting the process. Complements the YAML loader
(``mcp_tools_file``) which seeds the catalog at startup; these endpoints
let an operator add, remove, and inspect entries while the gateway runs.

Auth model: every endpoint requires the ``admin`` role. CSRF protection
is consistent with the rest of admin.py (bearer-token requests skip it,
cookie-authenticated mutations require ``X-Stronghold-Request``).

Scope semantics:

- A platform-scope approval is visible to every principal.
- An org/team/user-scope approval requires the requesting admin to have
  the corresponding ids set; the catalog enforces visibility on read.

The endpoints intentionally couple catalog approval and Emissary backend
registration so the two stay in sync — same invariant the YAML loader
maintains.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime
from typing import Any

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import JSONResponse

from stronghold.api.routes.admin import _require_admin
from stronghold.mcp.emissary import BackendRegistration
from stronghold.security import tool_fingerprint as fingerprinter
from stronghold.types.security import (
    CatalogEntry,
    Provenance,
    Scope,
    TargetKind,
    TrustTier,
)

logger = logging.getLogger("stronghold.api.mcp_admin")

router = APIRouter()


def _require_emissary_plane(request: Request) -> tuple[Any, Any]:
    """Return (catalog, emissary) or 503 if the plane is not wired."""
    container = request.app.state.container
    catalog = container.mcp_tool_catalog
    emissary = container.emissary
    if catalog is None or emissary is None:
        raise HTTPException(
            status_code=503,
            detail="Emissary MCP gateway plane not wired in this deployment",
        )
    return catalog, emissary


def _entry_to_dict(entry: CatalogEntry) -> dict[str, Any]:
    return {
        "fingerprint": entry.fingerprint.value,
        "name": entry.fingerprint.name,
        "schema_hash": entry.fingerprint.schema_hash,
        "trust_tier": entry.trust_tier.value,
        "provenance": entry.provenance.value,
        "approved_at_scope": entry.approved_at_scope.value,
        "org_id": entry.org_id,
        "team_id": entry.team_id,
        "user_id": entry.user_id,
        "allowed_audiences": sorted(entry.allowed_audiences),
        "declared_caps": sorted(entry.declared_caps),
        "approved_at": entry.approved_at.isoformat(),
        "approved_by": entry.approved_by,
        "expires_at": entry.expires_at.isoformat() if entry.expires_at else None,
    }


@router.get("/v1/stronghold/admin/mcp/tools")
async def list_mcp_tools(request: Request) -> JSONResponse:
    """List approved tools visible to the requesting admin.

    Visibility follows the catalog's scope-walk semantics: a platform admin
    sees every entry; an org admin sees their org plus platform; a team
    admin sees their team plus parents; a user-scope admin (rare) sees
    only their own.
    """
    auth = await _require_admin(request)
    catalog, _ = _require_emissary_plane(request)

    fingerprints = catalog.approvals_for(auth)
    out: list[dict[str, Any]] = []
    for fingerprint in fingerprints:
        entry = catalog.lookup(fingerprint, auth)
        if entry is not None:
            out.append(_entry_to_dict(entry))
    return JSONResponse(content={"tools": out})


@router.get("/v1/stronghold/admin/mcp/tools/{fingerprint_value}")
async def get_mcp_tool(request: Request, fingerprint_value: str) -> JSONResponse:
    """Get one approved tool's full catalog entry by fingerprint."""
    auth = await _require_admin(request)
    catalog, _ = _require_emissary_plane(request)

    fingerprint_match = next(
        (fp for fp in catalog.approvals_for(auth) if fp.value == fingerprint_value),
        None,
    )
    if fingerprint_match is None:
        raise HTTPException(status_code=404, detail="fingerprint not found in your scope")

    entry = catalog.lookup(fingerprint_match, auth)
    if entry is None:
        raise HTTPException(status_code=404, detail="entry no longer present")
    return JSONResponse(content=_entry_to_dict(entry))


@router.post("/v1/stronghold/admin/mcp/tools")
async def approve_mcp_tool(request: Request) -> JSONResponse:
    """Approve a tool and register its Emissary backend.

    Body shape mirrors the YAML loader entry (see registration_loader.py):

    .. code-block:: json

        {
          "name": "github_search",
          "description": "Search GitHub",
          "input_schema": {"type": "object", "properties": {"q": {"type": "string"}}},
          "target_kind": "remote_proxy",
          "audiences": ["https://api.github.com/"],
          "declared_caps": ["read:issues"],
          "trust_tier": "t1",
          "provenance": "admin",
          "approved_at_scope": "platform",
          "metadata": {"server_uri": "https://api.github.com/mcp"}
        }
    """
    auth = await _require_admin(request)
    catalog, emissary = _require_emissary_plane(request)

    try:
        body = await request.json()
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=f"malformed JSON: {exc}") from exc
    if not isinstance(body, dict):
        raise HTTPException(status_code=400, detail="body must be a JSON object")

    try:
        declaration = {
            "name": _required_str(body, "name"),
            "description": str(body.get("description", "")),
            "input_schema": dict(body.get("input_schema") or {}),
        }
        fingerprint = fingerprinter.compute(declaration)

        target_kind = TargetKind(_required_str(body, "target_kind"))
        scope = Scope(_required_str(body, "approved_at_scope"))
        trust_tier = TrustTier(body.get("trust_tier", TrustTier.T3.value))
        provenance = Provenance(body.get("provenance", Provenance.ADMIN.value))
        audiences = frozenset(str(a) for a in body.get("audiences") or [])
        if not audiences:
            raise ValueError("audiences must be non-empty")
        declared_caps = frozenset(str(c) for c in body.get("declared_caps") or [])

        metadata_in = body.get("metadata") or {}
        if not isinstance(metadata_in, dict):
            raise ValueError("metadata must be a mapping")
    except (KeyError, ValueError, TypeError) as exc:
        raise HTTPException(status_code=400, detail=f"invalid entry: {exc}") from exc

    catalog.approve(
        fingerprint,
        CatalogEntry(
            fingerprint=fingerprint,
            trust_tier=trust_tier,
            provenance=provenance,
            approved_at_scope=scope,
            org_id=str(
                body.get("org_id", "") or auth.org_id if scope is not Scope.PLATFORM else ""
            ),
            team_id=str(body.get("team_id", "")),
            user_id=str(body.get("user_id", "")),
            allowed_audiences=audiences,
            declared_caps=declared_caps,
            approved_at=datetime.now(UTC),
            approved_by=auth.user_id or "admin",
        ),
    )
    emissary.register_backend(
        BackendRegistration(
            fingerprint=fingerprint,
            target_kind=target_kind,
            audiences=audiences,
            session_affinity=bool(body.get("session_affinity", False)),
            metadata={str(k): str(v) for k, v in metadata_in.items()},
        ),
    )

    logger.info(
        "MCP tool approved by %s: %s @ %s (fingerprint=%s)",
        auth.user_id,
        fingerprint.name,
        scope.value,
        fingerprint.value,
    )
    return JSONResponse(
        status_code=201,
        content={"fingerprint": fingerprint.value, "name": fingerprint.name},
    )


@router.delete("/v1/stronghold/admin/mcp/tools/{fingerprint_value}")
async def revoke_mcp_tool(request: Request, fingerprint_value: str) -> JSONResponse:
    """Revoke a tool's approval at every scope.

    The catalog drops the entry; the Emissary backend registration becomes
    unreachable (call_tool will UnauthorizedToolError on the next call).
    """
    auth = await _require_admin(request)
    catalog, _ = _require_emissary_plane(request)

    fingerprint = next(
        (fp for fp in catalog.approvals_for(auth) if fp.value == fingerprint_value),
        None,
    )
    if fingerprint is None:
        raise HTTPException(status_code=404, detail="fingerprint not found in your scope")

    catalog.revoke(fingerprint)
    logger.info("MCP tool revoked by %s: %s", auth.user_id, fingerprint.name)
    return JSONResponse(content={"revoked": fingerprint.value})


def _required_str(body: dict[str, Any], key: str) -> str:
    value = body.get(key)
    if not isinstance(value, str) or not value:
        raise ValueError(f"required string field '{key}' missing or empty")
    return value
