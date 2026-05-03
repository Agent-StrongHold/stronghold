"""Emissary: the MCP gateway dispatcher.

Implements the ``MCPGateway`` protocol. Two bindings sit on top of this
core: an HTTP listener (OAuth 2.1 + RFC 8707 + RFC 9728 — see
``stronghold/mcp/http_binding.py``) and an in-process binding called
directly by Stronghold's own agents. The protocol shape is identical so
authorisation semantics never differ between bindings.

Per ``ToolCallRequest``, Emissary:

  1. Validates session ownership and freshness (if a session is provided).
  2. Returns a cached idempotent result when the caller's idempotency_key
     hits an unexpired cache entry.
  3. Looks up the principal's catalog entry for the requested fingerprint.
     A miss is ``UnauthorizedToolError``.
  4. Routes by ``TargetKind``:
       - COMPOSITE   → delegated to ``Composer``, which calls back through
                       Emissary for every atomic step.
       - LOCAL_HOST / REMOTE_PROXY / FIRST_PARTY → invoker function.
  5. Mints a Keyward token (audience-bound, scoped) for the call. Refusal
     here propagates to the caller verbatim.
  6. Invokes the backend with the token.
  7. Scans the result through Warden. A "block" verdict turns the call
     into an error result; a ``revoke`` directive triggers Keyward.
  8. Caches the result under the idempotency key, if any.

Backends are registered via ``register_backend``; backend invocation is
delegated to a ``BackendInvoker`` callable injected at construction so
the Emissary itself stays out of the LOCAL_HOST / REMOTE_PROXY transport
business. Production wires those invokers to ``MCPDeployer`` (HTTP to a
deployed pod) and to the outbound MCP client respectively.
"""

from __future__ import annotations

import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field, replace
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING, Any

from stronghold.types.security import (
    Session,
    SessionId,
    TargetKind,
    TokenRequest,
    ToolCallResult,
    ToolDescriptor,
    WardenVerdict,
)

if TYPE_CHECKING:
    from stronghold.protocols.security import (
        Composer,
        CredentialIssuer,
        ToolCatalog,
    )
    from stronghold.security.warden.detector import Warden
    from stronghold.types.auth import AuthContext
    from stronghold.types.security import (
        IssuedToken,
        ToolCallRequest,
        ToolFingerprint,
    )


BackendInvoker = Callable[
    ["BackendRegistration", "ToolCallRequest", "IssuedToken", str | None],
    Awaitable[Any],
]


@dataclass(frozen=True)
class BackendRegistration:
    """Maps a registered fingerprint to its TargetKind and routing metadata."""

    fingerprint: ToolFingerprint
    target_kind: TargetKind
    audiences: frozenset[str]
    session_affinity: bool = False
    metadata: dict[str, str] = field(default_factory=dict)


class UnauthorizedToolError(Exception):
    """Caller lacks an approval for the requested tool fingerprint."""


class SessionOwnershipError(Exception):
    """A session is being used by a principal other than its owner."""


class SessionUnknownError(Exception):
    """The supplied SessionId is not active."""


class SessionExpiredError(Exception):
    """The session passed idle or hard timeout and has been ended."""


class BackendUnavailableError(Exception):
    """A registered backend raised an exception during invocation."""


class MissingBackendError(Exception):
    """Fingerprint approved in catalog but not registered with Emissary."""


class IdempotencyConflictError(Exception):
    """Same idempotency_key reused with different args within the cache TTL."""


@dataclass
class _IdempotencyRecord:
    args_hash: int
    result: ToolCallResult
    expires_at: datetime


class Emissary:
    """In-process MCP gateway dispatcher (also re-used by the HTTP binding)."""

    def __init__(
        self,
        *,
        catalog: ToolCatalog,
        keyward: CredentialIssuer,
        warden: Warden,
        composer: Composer,
        invokers: dict[TargetKind, BackendInvoker],
        idempotency_ttl: timedelta = timedelta(hours=1),
        session_idle_timeout: timedelta = timedelta(minutes=30),
        session_hard_timeout: timedelta = timedelta(hours=12),
        clock: Callable[[], datetime] = lambda: datetime.now(UTC),
    ) -> None:
        self._catalog = catalog
        self._keyward = keyward
        self._warden = warden
        self._composer = composer
        self._invokers = dict(invokers)
        self._idempotency_ttl = idempotency_ttl
        self._idle_timeout = session_idle_timeout
        self._hard_timeout = session_hard_timeout
        self._now = clock

        self._registrations: dict[str, BackendRegistration] = {}
        self._sessions: dict[str, Session] = {}
        self._session_client_info: dict[str, dict[str, object]] = {}
        self._affinity: dict[tuple[str, str], str] = {}
        self._idempotency: dict[tuple[str | None, str], _IdempotencyRecord] = {}

    # --- registration ----------------------------------------------------

    def register_backend(self, registration: BackendRegistration) -> None:
        self._registrations[registration.fingerprint.value] = registration

    def describe_server(self) -> dict[str, object]:
        # Surface advertised metadata for HTTP-binding PRM. The HTTP binding
        # supplies the canonical URI / authorization servers; the in-process
        # binding doesn't need PRM at all.
        return {
            "registrations": [
                {
                    "fingerprint": fp_value,
                    "target_kind": str(reg.target_kind),
                    "audiences": sorted(reg.audiences),
                }
                for fp_value, reg in self._registrations.items()
            ],
        }

    # --- sessions --------------------------------------------------------

    async def start_session(
        self,
        auth: AuthContext,
        client_info: dict[str, object],
    ) -> Session:
        now = self._now()
        sid = SessionId(value=f"sess-{auth.user_id}-{int(time.time_ns())}")
        session = Session(
            id=sid,
            auth=auth,
            started_at=now,
            last_activity=now,
        )
        self._sessions[sid.value] = session
        # client_info is recorded for audit correlation; the session itself
        # is principal-scoped, but operators investigating an incident need
        # to know which MCP client opened it.
        if client_info:
            self._session_client_info[sid.value] = dict(client_info)
        return session

    async def end_session(self, session: SessionId) -> None:
        self._sessions.pop(session.value, None)
        self._session_client_info.pop(session.value, None)
        for key in list(self._affinity):
            if key[0] == session.value:
                self._affinity.pop(key, None)

    # --- list_tools ------------------------------------------------------

    async def list_tools(
        self,
        auth: AuthContext,
        session: SessionId | None,
    ) -> list[ToolDescriptor]:
        approved = self._catalog.approvals_for(auth)
        out: list[ToolDescriptor] = []
        for fingerprint in approved:
            entry = self._catalog.lookup(fingerprint, auth)
            if entry is None:
                continue
            registration = self._registrations.get(fingerprint.value)
            target_kind = registration.target_kind if registration else TargetKind.LOCAL_HOST
            out.append(
                ToolDescriptor(
                    fingerprint=fingerprint,
                    name=fingerprint.name,
                    description="",
                    input_schema={},
                    target_kind=target_kind,
                    trust_tier=entry.trust_tier,
                    scope=entry.approved_at_scope,
                ),
            )
        return out

    # --- call_tool -------------------------------------------------------

    async def call_tool(self, request: ToolCallRequest) -> ToolCallResult:
        now = self._now()

        if request.session is not None:
            self._validate_session(request, now)

        if request.idempotency_key is not None:
            cached = self._idempotency_lookup(request, now)
            if cached is not None:
                return cached

        entry = self._catalog.lookup(request.fingerprint, request.auth)
        if entry is None:
            raise UnauthorizedToolError(request.fingerprint.name)

        registration = self._registrations.get(request.fingerprint.value)
        if registration is None:
            raise MissingBackendError(request.fingerprint.name)
        if not registration.audiences:
            raise MissingBackendError(
                f"{request.fingerprint.name} has no audiences",
            )

        if registration.target_kind is TargetKind.COMPOSITE:
            result = await self._composer.execute(
                request,
                _SelfRoutingRuntime(self),
            )
            self._maybe_cache(request, result, now)
            return result

        audience = next(iter(registration.audiences))
        token_result = await self._keyward.issue(
            TokenRequest(
                tool=request.fingerprint,
                auth=request.auth,
                audience=audience,
                requested_scopes=entry.declared_caps,
                call_id=request.call_id,
            ),
        )
        if token_result.token is None:
            raise UnauthorizedToolError(
                f"keyward refused {request.fingerprint.name}: {token_result.error_kind}",
            )
        token = token_result.token

        instance = None
        if registration.session_affinity and request.session is not None:
            instance = self._resolve_affinity(request.session, request.fingerprint)

        invoker = self._invokers.get(registration.target_kind)
        if invoker is None:
            raise MissingBackendError(
                f"no invoker for {registration.target_kind}",
            )

        try:
            raw = await invoker(registration, request, token, instance)
        except Exception as exc:
            raise BackendUnavailableError(request.fingerprint.name) from exc

        verdict = await self._warden.scan(_to_text(raw), "tool_result")
        if verdict.revoke is not None:
            # Warden doesn't see the issuing token; pin to this call's token
            # unless the verdict already specified one.
            criteria = (
                verdict.revoke
                if verdict.revoke.token_id is not None
                else replace(verdict.revoke, token_id=token.id)
            )
            await self._keyward.revoke(criteria)

        if verdict.blocked:
            result = ToolCallResult(
                content={"error": "blocked_by_warden", "flags": list(verdict.flags)},
                is_error=True,
                warden_verdict=verdict,
                token_id=token.id,
            )
        elif not verdict.clean:
            content = (
                {"sanitized": verdict.sanitized_content, "flags": list(verdict.flags)}
                if verdict.sanitized_content is not None
                else {"flagged": raw, "flags": list(verdict.flags)}
            )
            result = ToolCallResult(
                content=content,
                is_error=False,
                warden_verdict=verdict,
                token_id=token.id,
            )
        else:
            result = ToolCallResult(
                content=raw,
                is_error=False,
                warden_verdict=verdict,
                token_id=token.id,
            )

        self._maybe_cache(request, result, now)
        return result

    # --- helpers ---------------------------------------------------------

    def _validate_session(self, request: ToolCallRequest, now: datetime) -> None:
        if request.session is None:
            return
        session = self._sessions.get(request.session.value)
        if session is None:
            raise SessionUnknownError(request.session.value)
        if session.auth.user_id != request.auth.user_id:
            raise SessionOwnershipError(request.session.value)
        if now - session.last_activity > self._idle_timeout:
            self._sessions.pop(request.session.value, None)
            raise SessionExpiredError(request.session.value)
        if now - session.started_at > self._hard_timeout:
            self._sessions.pop(request.session.value, None)
            raise SessionExpiredError(request.session.value)
        self._sessions[request.session.value] = replace(session, last_activity=now)

    def _idempotency_lookup(
        self,
        request: ToolCallRequest,
        now: datetime,
    ) -> ToolCallResult | None:
        if request.idempotency_key is None:
            return None
        session_key = request.session.value if request.session else None
        cache_key = (session_key, request.idempotency_key)
        record = self._idempotency.get(cache_key)
        if record is None or record.expires_at <= now:
            return None
        if record.args_hash != _hash_args(request.args):
            raise IdempotencyConflictError(request.idempotency_key)
        return record.result

    def _maybe_cache(
        self,
        request: ToolCallRequest,
        result: ToolCallResult,
        now: datetime,
    ) -> None:
        if request.idempotency_key is None:
            return
        session_key = request.session.value if request.session else None
        self._idempotency[(session_key, request.idempotency_key)] = _IdempotencyRecord(
            args_hash=_hash_args(request.args),
            result=result,
            expires_at=now + self._idempotency_ttl,
        )

    def _resolve_affinity(
        self,
        session: SessionId,
        fingerprint: ToolFingerprint,
    ) -> str:
        key = (session.value, fingerprint.value)
        instance = self._affinity.get(key)
        if instance is None:
            instance = f"inst-{fingerprint.value[:8]}-{session.value[-8:]}"
            self._affinity[key] = instance
        return instance


def _hash_args(args: dict[str, Any]) -> int:
    """Stable hash for idempotency comparisons."""
    import json

    return hash(json.dumps(args, sort_keys=True, separators=(",", ":")))


def _to_text(payload: Any) -> str:
    if isinstance(payload, str):
        return payload
    try:
        import json

        return json.dumps(payload, sort_keys=True, default=str)
    except (TypeError, ValueError):
        return repr(payload)


# CompositeRuntime that loops back into Emissary so atomic steps go
# through full Sentinel/Keyward/Warden routing again.
class _SelfRoutingRuntime:
    def __init__(self, emissary: Emissary) -> None:
        self._emissary = emissary

    async def call(self, request: ToolCallRequest) -> ToolCallResult:
        return await self._emissary.call_tool(request)


__all__ = [
    "BackendInvoker",
    "BackendRegistration",
    "BackendUnavailableError",
    "Emissary",
    "IdempotencyConflictError",
    "MissingBackendError",
    "SessionExpiredError",
    "SessionOwnershipError",
    "SessionUnknownError",
    "UnauthorizedToolError",
]


# Re-export WardenVerdict for callers that build sanitised results.
_ = WardenVerdict
