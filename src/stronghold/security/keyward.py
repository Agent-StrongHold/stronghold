"""Keyward: short-lived audience-bound credential issuer.

Master credentials never leave Keyward's process memory; the only artefact
a calling tool ever sees is a Keyward-minted bearer token.

The token format is a JWT with the following claims:

- ``sub``  user_id of the principal
- ``org``  org_id of the principal
- ``aud``  canonical URI of the target downstream (RFC 8707 alignment)
- ``scope``  space-separated scope list, ⊆ the tool's ``declared_caps``
- ``tool_fp``  the fingerprint value the call is for
- ``call_id``  caller's correlation id
- ``jti``  unique token id; used for emergency revocation
- ``iat``, ``exp``  issued/expiry per ``KeywardConfig``

Refusal modes (`TokenResult.error_kind`):

- ``unauthorized``      — tool not in principal's approved catalog
- ``audience_denied``   — audience not in catalog's allowed_audiences
- ``scope_escalation``  — requested_scopes ⊄ tool.declared_caps
- ``unavailable``       — vault/signing key unavailable
"""

from __future__ import annotations

import secrets
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING

import jwt

from stronghold.types.security import (
    IssuedToken,
    RevocationCriteria,
    TokenResult,
    TokenStatus,
)

if TYPE_CHECKING:
    from stronghold.protocols.security import ToolCatalog
    from stronghold.types.security import TokenRequest


@dataclass(frozen=True)
class KeywardConfig:
    """Configuration for the Keyward issuer.

    ``signing_key`` is a symmetric secret for HS256 in tests/dev;
    production wires an asymmetric key pair via the vault.
    """

    default_ttl_seconds: int = 900  # 15 min
    per_audience_ttl_seconds: dict[str, int] = field(default_factory=dict)
    issuer: str = "stronghold-keyward"
    algorithm: str = "HS256"
    signing_key: str = ""  # set at startup; no default for safety


class Keyward:
    """Credential issuer for the Emissary MCP-gateway plane."""

    def __init__(self, *, catalog: ToolCatalog, config: KeywardConfig) -> None:
        if not config.signing_key:
            raise ValueError("Keyward refuses to start without a signing_key")
        self._catalog = catalog
        self._config = config
        # In-memory token registry. Persistent revocation belongs in
        # the audit ledger; this is local introspection state.
        self._issued: dict[str, IssuedToken] = {}
        self._revoked: set[str] = set()

    # --- issuance --------------------------------------------------------

    async def issue(self, request: TokenRequest) -> TokenResult:
        entry = self._catalog.lookup(request.tool, request.auth)
        if entry is None:
            return TokenResult(
                token=None,
                error=f"tool '{request.tool.name}' not approved for principal",
                error_kind="unauthorized",
            )

        if request.audience not in entry.allowed_audiences:
            return TokenResult(
                token=None,
                error=f"audience '{request.audience}' not in tool's allowed audiences",
                error_kind="audience_denied",
            )

        if not request.requested_scopes.issubset(entry.declared_caps):
            return TokenResult(
                token=None,
                error=(
                    f"requested {set(request.requested_scopes)} ⊄ "
                    f"declared {set(entry.declared_caps)}"
                ),
                error_kind="scope_escalation",
            )

        ttl = self._config.per_audience_ttl_seconds.get(
            request.audience,
            self._config.default_ttl_seconds,
        )
        now = datetime.now(UTC)
        token_id = secrets.token_urlsafe(16)
        claims: dict[str, object] = {
            "iss": self._config.issuer,
            "sub": request.auth.user_id,
            "org": request.auth.org_id,
            "aud": request.audience,
            "scope": " ".join(sorted(request.requested_scopes)),
            "tool_fp": request.tool.value,
            "call_id": request.call_id,
            "jti": token_id,
            "iat": int(now.timestamp()),
            "exp": int((now + timedelta(seconds=ttl)).timestamp()),
        }
        encoded = jwt.encode(
            claims,
            self._config.signing_key,
            algorithm=self._config.algorithm,
        )

        token = IssuedToken(
            id=token_id,
            tool=request.tool,
            principal_user_id=request.auth.user_id,
            principal_org_id=request.auth.org_id,
            audience=request.audience,
            scopes=request.requested_scopes,
            issued_at=now,
            ttl_seconds=ttl,
            serialized=encoded,
        )
        self._issued[token_id] = token
        return TokenResult(token=token)

    # --- revocation ------------------------------------------------------

    async def revoke(self, criteria: RevocationCriteria) -> None:
        targets: set[str] = set()

        if criteria.token_id is not None:
            targets.add(criteria.token_id)

        for token_id, token in self._issued.items():
            if criteria.tool is not None and token.tool.value == criteria.tool.value:
                targets.add(token_id)
            if criteria.user_id is not None and token.principal_user_id == criteria.user_id:
                targets.add(token_id)
            if criteria.audience is not None and token.audience == criteria.audience:
                targets.add(token_id)

        self._revoked.update(targets)

    # --- introspection ---------------------------------------------------

    async def introspect(self, token_id: str) -> TokenStatus | None:
        token = self._issued.get(token_id)
        if token is None:
            return None
        return TokenStatus(
            token_id=token_id,
            revoked=token_id in self._revoked,
            expires_at=token.issued_at + timedelta(seconds=token.ttl_seconds),
        )
