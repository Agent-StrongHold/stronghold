"""Bootstrap loader: approve catalog entries + register Emissary backends.

Reads a YAML file describing approved MCP tools and, for each one:

1. Computes the canonical fingerprint over (name, description, input_schema).
2. Approves the fingerprint in the ``ToolCatalog`` at the declared scope.
3. Registers the backend with the ``Emissary`` so dispatch is wired.

The two operations are coupled by design — a tool that's catalog-approved
but missing a backend would 503 on every call, and a backend that's not
catalog-approved is unreachable. Loading them from a single source keeps
the two in sync.

Schema (YAML):

.. code-block:: yaml

    mcp_tools:
      - name: github_search
        description: Search GitHub repositories
        input_schema:
          type: object
          properties:
            q: {type: string}
        target_kind: remote_proxy   # remote_proxy | local_host | first_party | composite
        audiences:
          - https://api.github.com/
        declared_caps:
          - read:issues
        trust_tier: t1              # t0 | t1 | t2 | t3 | t4 | skull
        provenance: admin           # builtin | admin | user | community
        approved_at_scope: platform # user | team | org | platform
        org_id: ""                  # required for org/team/user scopes
        team_id: ""                 # required for team/user scopes
        user_id: ""                 # required for user scope
        session_affinity: false
        metadata:
          server_uri: https://api.github.com/mcp   # for remote_proxy
          # server_name: github                    # for local_host (MCPRegistry key)

The loader is idempotent on the fingerprint level — re-loading the same
file is a no-op (catalog approve is keyed on (fingerprint, scope), and
register_backend overwrites by fingerprint).
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any

import yaml

from stronghold.mcp.emissary import BackendRegistration
from stronghold.security import tool_fingerprint as fingerprinter
from stronghold.types.security import (
    CatalogEntry,
    Provenance,
    Scope,
    TargetKind,
    TrustTier,
)

if TYPE_CHECKING:
    from stronghold.mcp.emissary import Emissary
    from stronghold.security.tool_catalog import InMemoryToolCatalog

logger = logging.getLogger("stronghold.mcp.registration_loader")


class RegistrationFileError(ValueError):
    """Raised when the YAML file is malformed or an entry fails validation."""


def load_registrations(
    *,
    path: str | Path,
    catalog: InMemoryToolCatalog,
    emissary: Emissary,
) -> int:
    """Load + approve + register every entry in the YAML file.

    Returns the number of entries successfully registered. Raises
    ``RegistrationFileError`` on the first malformed entry — the caller
    should treat partial application as a startup failure.
    """
    file = Path(path)
    if not file.is_file():
        raise RegistrationFileError(f"mcp_tools_file does not exist: {path}")

    try:
        raw = yaml.safe_load(file.read_text()) or {}
    except yaml.YAMLError as exc:
        raise RegistrationFileError(f"YAML parse error in {path}: {exc}") from exc

    entries = raw.get("mcp_tools") or []
    if not isinstance(entries, list):
        raise RegistrationFileError(
            f"{path}: top-level 'mcp_tools' must be a list, got {type(entries).__name__}",
        )

    count = 0
    for index, entry in enumerate(entries):
        if not isinstance(entry, dict):
            raise RegistrationFileError(f"{path}: entry #{index} is not a mapping")
        try:
            _apply_entry(entry, catalog=catalog, emissary=emissary)
        except (KeyError, ValueError, TypeError) as exc:
            name = entry.get("name") if isinstance(entry, dict) else "?"
            raise RegistrationFileError(
                f"{path}: entry #{index} ({name!r}) invalid: {exc}",
            ) from exc
        count += 1

    logger.info("Loaded %d mcp_tools registrations from %s", count, path)
    return count


def _apply_entry(
    entry: dict[str, Any],
    *,
    catalog: InMemoryToolCatalog,
    emissary: Emissary,
) -> None:
    declaration = {
        "name": _required_str(entry, "name"),
        "description": str(entry.get("description", "")),
        "input_schema": dict(entry.get("input_schema") or {}),
    }
    fingerprint = fingerprinter.compute(declaration)

    target_kind = TargetKind(_required_str(entry, "target_kind"))
    scope = Scope(_required_str(entry, "approved_at_scope"))
    trust_tier = TrustTier(entry.get("trust_tier", TrustTier.T3.value))
    provenance = Provenance(entry.get("provenance", Provenance.ADMIN.value))
    audiences = frozenset(str(a) for a in entry.get("audiences") or [])
    declared_caps = frozenset(str(c) for c in entry.get("declared_caps") or [])
    if not audiences:
        raise ValueError("audiences must be non-empty")

    catalog.approve(
        fingerprint,
        CatalogEntry(
            fingerprint=fingerprint,
            trust_tier=trust_tier,
            provenance=provenance,
            approved_at_scope=scope,
            org_id=str(entry.get("org_id", "")),
            team_id=str(entry.get("team_id", "")),
            user_id=str(entry.get("user_id", "")),
            allowed_audiences=audiences,
            declared_caps=declared_caps,
            approved_at=datetime.now(UTC),
            approved_by=str(entry.get("approved_by", "registration_loader")),
        ),
    )

    metadata_in = entry.get("metadata") or {}
    if not isinstance(metadata_in, dict):
        raise ValueError("metadata must be a mapping")
    emissary.register_backend(
        BackendRegistration(
            fingerprint=fingerprint,
            target_kind=target_kind,
            audiences=audiences,
            session_affinity=bool(entry.get("session_affinity", False)),
            metadata={str(k): str(v) for k, v in metadata_in.items()},
        ),
    )


def _required_str(entry: dict[str, Any], key: str) -> str:
    value = entry.get(key)
    if not isinstance(value, str) or not value:
        raise ValueError(f"required string field '{key}' missing or empty")
    return value
