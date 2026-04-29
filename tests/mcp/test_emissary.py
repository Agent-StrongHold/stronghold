"""Emissary in-process binding contract tests."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

import pytest

from stronghold.mcp.composer import Composer
from stronghold.mcp.emissary import (
    BackendRegistration,
    BackendUnavailableError,
    Emissary,
    IdempotencyConflictError,
    MissingBackendError,
    SessionExpiredError,
    SessionOwnershipError,
    UnauthorizedToolError,
)
from stronghold.security.keyward import Keyward, KeywardConfig
from stronghold.security.tool_catalog import InMemoryToolCatalog
from stronghold.types.auth import AuthContext, IdentityKind
from stronghold.types.security import (
    CatalogEntry,
    CompositeDefinition,
    CompositeStep,
    Provenance,
    RevocationCriteria,
    Scope,
    TargetKind,
    ToolCallRequest,
    ToolFingerprint,
    TrustTier,
    WardenVerdict,
)

_SIGNING_KEY = "emissary-test-signing-key-32-bytes-or-more!!"


# --- helpers ----------------------------------------------------------------


def _alice() -> AuthContext:
    return AuthContext(
        user_id="alice",
        username="alice",
        org_id="acme",
        team_id="platform",
        kind=IdentityKind.USER,
        auth_method="jwt",
    )


def _bob() -> AuthContext:
    return AuthContext(
        user_id="bob",
        username="bob",
        org_id="acme",
        team_id="platform",
        kind=IdentityKind.USER,
        auth_method="jwt",
    )


def _fp(name: str) -> ToolFingerprint:
    return ToolFingerprint(value=f"fp-{name}", name=name, schema_hash=f"sh-{name}")


def _approve(
    catalog: InMemoryToolCatalog,
    fingerprint: ToolFingerprint,
    *,
    audiences: frozenset[str] = frozenset({"https://api.example/"}),
    caps: frozenset[str] = frozenset({"read"}),
) -> None:
    catalog.approve(
        fingerprint,
        CatalogEntry(
            fingerprint=fingerprint,
            trust_tier=TrustTier.T1,
            provenance=Provenance.ADMIN,
            approved_at_scope=Scope.ORG,
            org_id="acme",
            allowed_audiences=audiences,
            declared_caps=caps,
            approved_at=datetime.now(UTC),
            approved_by="admin",
        ),
    )


class _FakeWarden:
    """Minimal Warden surface — clean-by-default with test hooks."""

    def __init__(self) -> None:
        self._next_block: bool = False
        self._next_revoke: RevocationCriteria | None = None
        self._next_sanitize: str | None = None
        self.scans: list[tuple[str, str]] = []

    def block_next(self, *, with_revoke: RevocationCriteria | None = None) -> None:
        self._next_block = True
        self._next_revoke = with_revoke

    def sanitize_next(self, payload: str) -> None:
        self._next_sanitize = payload

    async def scan(self, content: str, boundary: str) -> WardenVerdict:
        self.scans.append((content, boundary))
        if self._next_block:
            self._next_block = False
            revoke, self._next_revoke = self._next_revoke, None
            return WardenVerdict(
                clean=False,
                blocked=True,
                flags=("test_block",),
                revoke=revoke,
            )
        if self._next_sanitize is not None:
            sanitised, self._next_sanitize = self._next_sanitize, None
            return WardenVerdict(
                clean=False,
                blocked=False,
                sanitized_content=sanitised,
                flags=("test_sanitised",),
            )
        return WardenVerdict(clean=True)


class _Invokers:
    """Collects per-target invoker callables and records calls for assertions."""

    def __init__(
        self,
        local_response: dict[str, Any] | None = None,
        local_exception: Exception | None = None,
    ) -> None:
        self.local_calls: list[Any] = []
        self.remote_calls: list[Any] = []
        self.first_party_calls: list[Any] = []
        self._local_response = local_response or {"ok": True, "data": "result"}
        self._local_exception = local_exception

    async def local(
        self,
        registration,
        request,
        token,
        instance,
    ) -> dict[str, Any]:
        self.local_calls.append((registration, request, token, instance))
        if self._local_exception is not None:
            raise self._local_exception
        return dict(self._local_response)

    async def remote(self, registration, request, token, instance) -> dict[str, Any]:
        self.remote_calls.append((registration, request, token, instance))
        return {"ok": True, "remote": registration.metadata.get("server_uri", "?")}

    async def first_party(self, registration, request, token, instance) -> dict[str, Any]:
        self.first_party_calls.append((registration, request, token, instance))
        return {"ok": True, "fp_native": request.fingerprint.name}

    def as_dict(self) -> dict:
        return {
            TargetKind.LOCAL_HOST: self.local,
            TargetKind.REMOTE_PROXY: self.remote,
            TargetKind.FIRST_PARTY: self.first_party,
        }


def _make_emissary(
    *,
    invokers: _Invokers | None = None,
    warden: _FakeWarden | None = None,
    clock: Any | None = None,
) -> tuple[Emissary, InMemoryToolCatalog, Keyward, _FakeWarden, _Invokers]:
    catalog = InMemoryToolCatalog()
    keyward = Keyward(catalog=catalog, config=KeywardConfig(signing_key=_SIGNING_KEY))
    warden = warden or _FakeWarden()
    invokers = invokers or _Invokers()
    composer = Composer()
    emissary = Emissary(
        catalog=catalog,
        keyward=keyward,
        warden=warden,
        composer=composer,
        invokers=invokers.as_dict(),
        clock=clock or (lambda: datetime.now(UTC)),
    )
    return emissary, catalog, keyward, warden, invokers


def _register(
    emissary: Emissary,
    fingerprint: ToolFingerprint,
    *,
    target_kind: TargetKind = TargetKind.LOCAL_HOST,
    audiences: frozenset[str] = frozenset({"https://api.example/"}),
    session_affinity: bool = False,
    metadata: dict[str, str] | None = None,
) -> None:
    emissary.register_backend(
        BackendRegistration(
            fingerprint=fingerprint,
            target_kind=target_kind,
            audiences=audiences,
            session_affinity=session_affinity,
            metadata=metadata or {},
        ),
    )


# --- authorization ----------------------------------------------------------


@pytest.mark.asyncio
async def test_unknown_tool_raises_unauthorized() -> None:
    emissary, _, _, _, _ = _make_emissary()
    with pytest.raises(UnauthorizedToolError):
        await emissary.call_tool(
            ToolCallRequest(
                fingerprint=_fp("nope"),
                args={},
                auth=_alice(),
                call_id="c1",
            ),
        )


@pytest.mark.asyncio
async def test_approved_tool_with_no_backend_raises_missing_backend() -> None:
    emissary, catalog, _, _, _ = _make_emissary()
    fingerprint = _fp("github_search")
    _approve(catalog, fingerprint)
    with pytest.raises(MissingBackendError):
        await emissary.call_tool(
            ToolCallRequest(
                fingerprint=fingerprint,
                args={},
                auth=_alice(),
                call_id="c1",
            ),
        )


# --- routing ---------------------------------------------------------------


@pytest.mark.asyncio
async def test_local_host_dispatch_invokes_local_invoker() -> None:
    emissary, catalog, _, _, invokers = _make_emissary()
    fingerprint = _fp("github_search")
    _approve(catalog, fingerprint)
    _register(emissary, fingerprint, target_kind=TargetKind.LOCAL_HOST)

    result = await emissary.call_tool(
        ToolCallRequest(
            fingerprint=fingerprint,
            args={"q": "x"},
            auth=_alice(),
            call_id="c1",
        ),
    )
    assert result.is_error is False
    assert len(invokers.local_calls) == 1
    assert len(invokers.remote_calls) == 0


@pytest.mark.asyncio
async def test_remote_proxy_dispatch_invokes_remote_invoker() -> None:
    emissary, catalog, _, _, invokers = _make_emissary()
    fingerprint = _fp("remote_search")
    _approve(
        catalog,
        fingerprint,
        audiences=frozenset({"https://remote-mcp.example/mcp"}),
    )
    _register(
        emissary,
        fingerprint,
        target_kind=TargetKind.REMOTE_PROXY,
        audiences=frozenset({"https://remote-mcp.example/mcp"}),
        metadata={"server_uri": "https://remote-mcp.example/mcp"},
    )
    result = await emissary.call_tool(
        ToolCallRequest(
            fingerprint=fingerprint,
            args={},
            auth=_alice(),
            call_id="c1",
        ),
    )
    assert result.is_error is False
    assert len(invokers.remote_calls) == 1
    assert len(invokers.local_calls) == 0


@pytest.mark.asyncio
async def test_first_party_dispatch_invokes_first_party_invoker() -> None:
    emissary, catalog, _, _, invokers = _make_emissary()
    fingerprint = _fp("native_summary")
    _approve(catalog, fingerprint, audiences=frozenset({"internal:summary"}))
    _register(
        emissary,
        fingerprint,
        target_kind=TargetKind.FIRST_PARTY,
        audiences=frozenset({"internal:summary"}),
    )
    result = await emissary.call_tool(
        ToolCallRequest(
            fingerprint=fingerprint,
            args={},
            auth=_alice(),
            call_id="c1",
        ),
    )
    assert result.is_error is False
    assert len(invokers.first_party_calls) == 1


# --- Keyward integration ----------------------------------------------------


@pytest.mark.asyncio
async def test_call_records_keyward_token_id_on_result() -> None:
    emissary, catalog, _, _, _ = _make_emissary()
    fingerprint = _fp("github_search")
    _approve(catalog, fingerprint)
    _register(emissary, fingerprint)
    result = await emissary.call_tool(
        ToolCallRequest(
            fingerprint=fingerprint,
            args={},
            auth=_alice(),
            call_id="c1",
        ),
    )
    assert result.token_id is not None


@pytest.mark.asyncio
async def test_keyward_audience_denied_propagates_as_unauthorized() -> None:
    emissary, catalog, _, _, _ = _make_emissary()
    fingerprint = _fp("github_search")
    _approve(catalog, fingerprint, audiences=frozenset({"https://only-here/"}))
    _register(
        emissary,
        fingerprint,
        audiences=frozenset({"https://different/"}),  # not in catalog
    )
    with pytest.raises(UnauthorizedToolError):
        await emissary.call_tool(
            ToolCallRequest(
                fingerprint=fingerprint,
                args={},
                auth=_alice(),
                call_id="c1",
            ),
        )


# --- Warden integration -----------------------------------------------------


@pytest.mark.asyncio
async def test_warden_block_returns_error_result_not_raw_content() -> None:
    emissary, catalog, _, warden, _ = _make_emissary()
    fingerprint = _fp("github_search")
    _approve(catalog, fingerprint)
    _register(emissary, fingerprint)
    warden.block_next()

    result = await emissary.call_tool(
        ToolCallRequest(
            fingerprint=fingerprint,
            args={},
            auth=_alice(),
            call_id="c1",
        ),
    )
    assert result.is_error is True
    assert "blocked_by_warden" in str(result.content)


@pytest.mark.asyncio
async def test_warden_revoke_directive_calls_keyward_revoke() -> None:
    emissary, catalog, keyward, warden, _ = _make_emissary()
    fingerprint = _fp("github_search")
    _approve(catalog, fingerprint)
    _register(emissary, fingerprint)
    warden.block_next(with_revoke=RevocationCriteria(reason="test"))

    pre_revocations = len([t for t in keyward._issued.values() if True])  # baseline
    await emissary.call_tool(
        ToolCallRequest(
            fingerprint=fingerprint,
            args={},
            auth=_alice(),
            call_id="c1",
        ),
    )
    # Confirm revocation occurred — at least one token marked revoked.
    issued = list(keyward._issued.keys())
    assert pre_revocations >= 0
    statuses = [await keyward.introspect(token_id) for token_id in issued]
    assert any(status is not None and status.revoked for status in statuses)


@pytest.mark.asyncio
async def test_warden_sanitize_returns_sanitised_wrapper() -> None:
    emissary, catalog, _, warden, _ = _make_emissary()
    fingerprint = _fp("github_search")
    _approve(catalog, fingerprint)
    _register(emissary, fingerprint)
    warden.sanitize_next("clean version")

    result = await emissary.call_tool(
        ToolCallRequest(
            fingerprint=fingerprint,
            args={},
            auth=_alice(),
            call_id="c1",
        ),
    )
    assert result.is_error is False
    assert isinstance(result.content, dict)
    assert result.content.get("sanitized") == "clean version"


# --- sessions ---------------------------------------------------------------


@pytest.mark.asyncio
async def test_session_lookup_by_wrong_principal_refused() -> None:
    emissary, catalog, _, _, _ = _make_emissary()
    fingerprint = _fp("github_search")
    _approve(catalog, fingerprint)
    _register(emissary, fingerprint)

    session = await emissary.start_session(_alice(), {})
    with pytest.raises(SessionOwnershipError):
        await emissary.call_tool(
            ToolCallRequest(
                fingerprint=fingerprint,
                args={},
                auth=_bob(),
                session=session.id,
                call_id="c1",
            ),
        )


@pytest.mark.asyncio
async def test_session_idle_timeout_expires_session() -> None:
    now = [datetime.now(UTC)]
    emissary, catalog, _, _, _ = _make_emissary(clock=lambda: now[0])
    fingerprint = _fp("github_search")
    _approve(catalog, fingerprint)
    _register(emissary, fingerprint)
    session = await emissary.start_session(_alice(), {})

    now[0] = now[0] + timedelta(minutes=31)
    with pytest.raises(SessionExpiredError):
        await emissary.call_tool(
            ToolCallRequest(
                fingerprint=fingerprint,
                args={},
                auth=_alice(),
                session=session.id,
                call_id="c1",
            ),
        )


@pytest.mark.asyncio
async def test_session_affinity_routes_to_same_instance() -> None:
    emissary, catalog, _, _, invokers = _make_emissary()
    fingerprint = _fp("github_search")
    _approve(catalog, fingerprint)
    _register(emissary, fingerprint, session_affinity=True)
    session = await emissary.start_session(_alice(), {})

    for i in range(2):
        await emissary.call_tool(
            ToolCallRequest(
                fingerprint=fingerprint,
                args={},
                auth=_alice(),
                session=session.id,
                call_id=f"c{i}",
            ),
        )

    assert len(invokers.local_calls) == 2
    instance_a = invokers.local_calls[0][3]
    instance_b = invokers.local_calls[1][3]
    assert instance_a == instance_b


# --- idempotency ------------------------------------------------------------


@pytest.mark.asyncio
async def test_idempotency_key_same_args_returns_cached() -> None:
    emissary, catalog, _, _, invokers = _make_emissary()
    fingerprint = _fp("github_search")
    _approve(catalog, fingerprint)
    _register(emissary, fingerprint)

    request = ToolCallRequest(
        fingerprint=fingerprint,
        args={"q": "x"},
        auth=_alice(),
        call_id="c1",
        idempotency_key="key-1",
    )
    r1 = await emissary.call_tool(request)
    r2 = await emissary.call_tool(request)
    assert r1.token_id == r2.token_id
    assert len(invokers.local_calls) == 1


@pytest.mark.asyncio
async def test_idempotency_key_different_args_raises_conflict() -> None:
    emissary, catalog, _, _, _ = _make_emissary()
    fingerprint = _fp("github_search")
    _approve(catalog, fingerprint)
    _register(emissary, fingerprint)

    await emissary.call_tool(
        ToolCallRequest(
            fingerprint=fingerprint,
            args={"q": "x"},
            auth=_alice(),
            call_id="c1",
            idempotency_key="key-1",
        ),
    )
    with pytest.raises(IdempotencyConflictError):
        await emissary.call_tool(
            ToolCallRequest(
                fingerprint=fingerprint,
                args={"q": "y"},
                auth=_alice(),
                call_id="c2",
                idempotency_key="key-1",
            ),
        )


# --- failure modes ----------------------------------------------------------


@pytest.mark.asyncio
async def test_backend_exception_raises_backend_unavailable() -> None:
    invokers = _Invokers(local_exception=RuntimeError("backend down"))
    emissary, catalog, _, _, _ = _make_emissary(invokers=invokers)
    fingerprint = _fp("github_search")
    _approve(catalog, fingerprint)
    _register(emissary, fingerprint)

    with pytest.raises(BackendUnavailableError):
        await emissary.call_tool(
            ToolCallRequest(
                fingerprint=fingerprint,
                args={},
                auth=_alice(),
                call_id="c1",
            ),
        )


# --- list_tools -------------------------------------------------------------


@pytest.mark.asyncio
async def test_list_tools_returns_only_authorized() -> None:
    emissary, catalog, _, _, _ = _make_emissary()
    visible = _fp("visible")
    invisible = _fp("invisible")
    _approve(catalog, visible)
    # invisible is not approved at all.
    _register(emissary, visible)
    _register(emissary, invisible)

    descriptors = await emissary.list_tools(_alice(), session=None)
    names = {d.name for d in descriptors}
    assert "visible" in names
    assert "invisible" not in names


# --- composites -------------------------------------------------------------


@pytest.mark.asyncio
async def test_composite_dispatch_routes_through_composer_and_back_to_atomic_steps() -> None:
    emissary, catalog, _, _, invokers = _make_emissary()
    atomic = _fp("github_search")
    composite_fp = _fp("triage")
    _approve(catalog, atomic)
    _approve(catalog, composite_fp, audiences=frozenset({"internal:composite"}))
    _register(emissary, atomic)
    _register(
        emissary,
        composite_fp,
        target_kind=TargetKind.COMPOSITE,
        audiences=frozenset({"internal:composite"}),
    )
    emissary._composer.register(
        CompositeDefinition(
            fingerprint=composite_fp,
            name="triage",
            description="",
            input_schema={},
            output_schema={},
            steps=(
                CompositeStep(
                    id="s1",
                    tool=atomic,
                    args_template={"q": "$args.q"},
                ),
            ),
            trust_tier=TrustTier.T1,
        ),
    )

    result = await emissary.call_tool(
        ToolCallRequest(
            fingerprint=composite_fp,
            args={"q": "bug"},
            auth=_alice(),
            call_id="c1",
        ),
    )
    # Composite returned successfully — the atomic step was dispatched and
    # therefore the local invoker was called once.
    assert result.is_error is False
    assert result.partial is False
    assert len(invokers.local_calls) == 1
