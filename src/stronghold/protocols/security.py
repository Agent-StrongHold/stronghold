"""Protocols for the Emissary (MCP gateway) plane.

ToolCatalog       — scope-aware approved-tool lookup with subscribe-on-change
CredentialIssuer  — Keyward; mints short-lived audience-bound tokens per call
Composer          — orchestrates composite tools as deterministic step graphs
CompositeRuntime  — callback shape the Composer uses to invoke atomic steps
                    (production wire: routes back through Emissary so each
                    step gets full Sentinel/Keyward/Warden coverage)
MCPGateway        — Emissary's external surface; serves an MCP-spec-compliant
                    listener and an in-process binding from one shape
TokenValidator    — used by the HTTP binding to convert raw bearer tokens
                    into AuthContexts after audience validation

SecurityLedger does not appear here on purpose: existing
``stronghold.protocols.memory.AuditLog`` plus the Sentinel audit pipeline
already provide that surface, and the Emissary plane writes through them.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Protocol, runtime_checkable

if TYPE_CHECKING:
    from collections.abc import Callable

    from stronghold.types.auth import AuthContext
    from stronghold.types.security import (
        CatalogEntry,
        CompositeDefinition,
        Session,
        SessionId,
        TokenRequest,
        TokenResult,
        TokenStatus,
        ToolCallRequest,
        ToolCallResult,
        ToolDescriptor,
        ToolFingerprint,
    )
    from stronghold.types.security import (
        RevocationCriteria as _RevocationCriteria,
    )


@runtime_checkable
class ToolCatalog(Protocol):
    """Scope-aware approved-tool lookup.

    Implementations may be in-memory (tests, single-node dev), Postgres, or
    Cosmos-backed. The scope walk is the protocol's responsibility — a caller
    passes an ``AuthContext`` and gets the union across all scopes the
    principal sits at.
    """

    def lookup(
        self,
        fingerprint: ToolFingerprint,
        auth: AuthContext,
    ) -> CatalogEntry | None:
        """Return the narrowest matching approval, or ``None`` if unapproved."""
        ...

    def approvals_for(self, auth: AuthContext) -> frozenset[ToolFingerprint]:
        """Return all fingerprints visible to the principal across scope chain."""
        ...

    def subscribe_changes(
        self,
        callback: Callable[[], None],
    ) -> Callable[[], None]:
        """Register a callback invoked after every approve/revoke. Returns
        an unsubscribe handle.
        """
        ...


@runtime_checkable
class CredentialIssuer(Protocol):
    """Keyward — mints audience-bound short-lived tokens per call.

    Master credentials never leave the issuer's process memory; the issued
    token is the only artefact the calling tool ever sees.
    """

    async def issue(self, request: TokenRequest) -> TokenResult: ...

    async def revoke(self, criteria: _RevocationCriteria) -> None: ...

    async def introspect(self, token_id: str) -> TokenStatus | None: ...


@runtime_checkable
class CompositeRuntime(Protocol):
    """Callback the Composer uses to invoke atomic steps.

    In production this resolves to ``MCPGateway.call_tool`` so every step
    routes through the same Sentinel/Keyward/Warden pipeline as a top-level
    agent call. Composites are not back doors.
    """

    async def call(self, request: ToolCallRequest) -> ToolCallResult: ...


@runtime_checkable
class Composer(Protocol):
    """Composite tool orchestrator.

    The composer is deterministic code (no LLM in the orchestration path).
    Steps may abort, skip, or rollback per ``CompositeStep.on_error``.
    """

    def register(self, definition: CompositeDefinition) -> None: ...

    async def execute(
        self,
        request: ToolCallRequest,
        runtime: CompositeRuntime,
    ) -> ToolCallResult: ...


@runtime_checkable
class MCPGateway(Protocol):
    """Emissary's external surface.

    Two bindings implement this: an MCP-over-HTTP listener (OAuth 2.1 +
    PKCE + RFC 8707 + RFC 9728) and an in-process binding called directly by
    Stronghold's own agents. The protocol shape is identical so authorisation
    semantics never differ between bindings.
    """

    async def list_tools(
        self,
        auth: AuthContext,
        session: SessionId | None,
    ) -> list[ToolDescriptor]: ...

    async def call_tool(self, request: ToolCallRequest) -> ToolCallResult: ...

    async def start_session(
        self,
        auth: AuthContext,
        client_info: dict[str, object],
    ) -> Session: ...

    async def end_session(self, session: SessionId) -> None: ...

    def describe_server(self) -> dict[str, object]:
        """Return the data needed for the MCP capability/PRM advertisement."""
        ...


@runtime_checkable
class TokenValidator(Protocol):
    """Validates raw bearer tokens at the HTTP binding edge.

    On success returns an ``AuthContext``. On failure raises a domain-typed
    error (audience mismatch, expired, etc.) so the binding can map it to
    the correct 401/403 + WWW-Authenticate response.
    """

    async def validate(
        self,
        raw_token: str,
        expected_audience: str,
    ) -> AuthContext: ...
