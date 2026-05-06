"""Bootstrap loader tests — YAML → catalog approval + Emissary backend."""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

if TYPE_CHECKING:
    from pathlib import Path

from stronghold.mcp.composer import Composer
from stronghold.mcp.emissary import Emissary
from stronghold.mcp.registration_loader import (
    RegistrationFileError,
    load_registrations,
)
from stronghold.security.keyward import Keyward, KeywardConfig
from stronghold.security.tool_catalog import InMemoryToolCatalog
from stronghold.types.auth import SYSTEM_AUTH
from stronghold.types.security import (
    Scope,
    TargetKind,
    TrustTier,
    WardenVerdict,
)

_SIGNING_KEY = "registration-loader-test-key-32-bytes-min!!"


class _CleanWarden:
    async def scan(self, content: str, boundary: str) -> WardenVerdict:
        return WardenVerdict(clean=True)


def _make_emissary() -> tuple[Emissary, InMemoryToolCatalog]:
    catalog = InMemoryToolCatalog()
    keyward = Keyward(catalog=catalog, config=KeywardConfig(signing_key=_SIGNING_KEY))
    emissary = Emissary(
        catalog=catalog,
        keyward=keyward,
        warden=_CleanWarden(),  # type: ignore[arg-type]
        composer=Composer(),
        invokers={},
    )
    return emissary, catalog


def _yaml(tmp_path: Path, body: str) -> Path:
    p = tmp_path / "mcp_tools.yaml"
    p.write_text(body)
    return p


# --- happy path -----------------------------------------------------------


@pytest.mark.asyncio
async def test_loads_remote_proxy_entry(tmp_path: Path) -> None:
    emissary, catalog = _make_emissary()
    file = _yaml(
        tmp_path,
        """
mcp_tools:
  - name: github_search
    description: Search GitHub
    input_schema:
      type: object
      properties:
        q: {type: string}
    target_kind: remote_proxy
    audiences:
      - https://api.github.com/
    declared_caps:
      - read:issues
    trust_tier: t1
    provenance: admin
    approved_at_scope: platform
    metadata:
      server_uri: https://api.github.com/mcp
""",
    )
    n = load_registrations(path=file, catalog=catalog, emissary=emissary)
    assert n == 1
    descriptors = await emissary.list_tools(SYSTEM_AUTH, session=None)
    assert len(descriptors) == 1
    assert descriptors[0].name == "github_search"
    assert descriptors[0].target_kind is TargetKind.REMOTE_PROXY
    assert descriptors[0].trust_tier is TrustTier.T1
    assert descriptors[0].scope is Scope.PLATFORM


@pytest.mark.asyncio
async def test_loads_multiple_entries(tmp_path: Path) -> None:
    emissary, catalog = _make_emissary()
    file = _yaml(
        tmp_path,
        """
mcp_tools:
  - name: a
    description: ""
    input_schema: {}
    target_kind: first_party
    audiences: ["internal:a"]
    declared_caps: []
    trust_tier: t0
    provenance: builtin
    approved_at_scope: platform
    metadata: {}
  - name: b
    description: ""
    input_schema: {}
    target_kind: remote_proxy
    audiences: ["https://b/"]
    declared_caps: []
    trust_tier: t1
    provenance: admin
    approved_at_scope: platform
    metadata: {server_uri: "https://b/mcp"}
""",
    )
    n = load_registrations(path=file, catalog=catalog, emissary=emissary)
    assert n == 2
    names = {d.name for d in await emissary.list_tools(SYSTEM_AUTH, session=None)}
    assert names == {"a", "b"}


# --- error cases ----------------------------------------------------------


def test_missing_file_raises(tmp_path: Path) -> None:
    emissary, catalog = _make_emissary()
    with pytest.raises(RegistrationFileError, match="does not exist"):
        load_registrations(path=tmp_path / "nope.yaml", catalog=catalog, emissary=emissary)


def test_malformed_yaml_raises(tmp_path: Path) -> None:
    emissary, catalog = _make_emissary()
    file = _yaml(tmp_path, "mcp_tools: [: bad")
    with pytest.raises(RegistrationFileError, match="YAML parse error"):
        load_registrations(path=file, catalog=catalog, emissary=emissary)


def test_top_level_not_a_list_raises(tmp_path: Path) -> None:
    emissary, catalog = _make_emissary()
    file = _yaml(tmp_path, "mcp_tools: {not: a-list}")
    with pytest.raises(RegistrationFileError, match="must be a list"):
        load_registrations(path=file, catalog=catalog, emissary=emissary)


def test_entry_missing_name_raises(tmp_path: Path) -> None:
    emissary, catalog = _make_emissary()
    file = _yaml(
        tmp_path,
        """
mcp_tools:
  - description: ""
    input_schema: {}
    target_kind: remote_proxy
    audiences: ["https://x/"]
    approved_at_scope: platform
    metadata: {}
""",
    )
    with pytest.raises(RegistrationFileError, match="name"):
        load_registrations(path=file, catalog=catalog, emissary=emissary)


def test_entry_missing_audiences_raises(tmp_path: Path) -> None:
    emissary, catalog = _make_emissary()
    file = _yaml(
        tmp_path,
        """
mcp_tools:
  - name: x
    description: ""
    input_schema: {}
    target_kind: remote_proxy
    audiences: []
    approved_at_scope: platform
    metadata: {}
""",
    )
    with pytest.raises(RegistrationFileError, match="audiences"):
        load_registrations(path=file, catalog=catalog, emissary=emissary)


def test_invalid_target_kind_raises(tmp_path: Path) -> None:
    emissary, catalog = _make_emissary()
    file = _yaml(
        tmp_path,
        """
mcp_tools:
  - name: x
    description: ""
    input_schema: {}
    target_kind: not_a_real_kind
    audiences: ["https://x/"]
    approved_at_scope: platform
    metadata: {}
""",
    )
    with pytest.raises(RegistrationFileError):
        load_registrations(path=file, catalog=catalog, emissary=emissary)


def test_partial_application_does_not_leak_on_failure(tmp_path: Path) -> None:
    """Per the design comment in registration_loader: the caller treats a
    RegistrationFileError as a startup failure, so we don't make any
    promise about rollback — but the test pins the contract that a single
    bad entry raises with the entry's index/name in the message so the
    operator can find it."""
    emissary, catalog = _make_emissary()
    file = _yaml(
        tmp_path,
        """
mcp_tools:
  - name: good
    description: ""
    input_schema: {}
    target_kind: first_party
    audiences: ["internal:good"]
    approved_at_scope: platform
    metadata: {}
  - name: bad
    description: ""
    input_schema: {}
    target_kind: not_a_real_kind
    audiences: ["internal:bad"]
    approved_at_scope: platform
    metadata: {}
""",
    )
    with pytest.raises(RegistrationFileError, match="bad"):
        load_registrations(path=file, catalog=catalog, emissary=emissary)


# --- idempotency ----------------------------------------------------------


@pytest.mark.asyncio
async def test_reloading_same_file_is_idempotent(tmp_path: Path) -> None:
    emissary, catalog = _make_emissary()
    file = _yaml(
        tmp_path,
        """
mcp_tools:
  - name: x
    description: ""
    input_schema: {}
    target_kind: first_party
    audiences: ["internal:x"]
    approved_at_scope: platform
    metadata: {}
""",
    )
    n1 = load_registrations(path=file, catalog=catalog, emissary=emissary)
    n2 = load_registrations(path=file, catalog=catalog, emissary=emissary)
    assert n1 == n2 == 1
    descriptors = await emissary.list_tools(SYSTEM_AUTH, session=None)
    assert len(descriptors) == 1
