"""ToolCatalog: scope-aware approved-tool registry.

The catalog records which fingerprints are approved at which scope. A
principal's view is the union across their scope chain (USER + TEAM + ORG +
PLATFORM); ``lookup`` returns the narrowest matching entry.

The in-memory implementation here is the canonical reference and the test
fake. A persistent implementation (Postgres / Cosmos) may live alongside it
without changing the public surface.
"""

from __future__ import annotations

from collections import defaultdict
from typing import TYPE_CHECKING

from stronghold.types.auth import SYSTEM_ORG_ID
from stronghold.types.security import (
    CatalogEntry,
    Scope,
    ToolFingerprint,
)

if TYPE_CHECKING:
    from collections.abc import Callable

    from stronghold.types.auth import AuthContext


# Scope precedence: narrowest → widest. ``lookup`` walks this order and
# returns the first matching entry the principal qualifies for.
_SCOPE_PRECEDENCE: tuple[Scope, ...] = (
    Scope.USER,
    Scope.TEAM,
    Scope.ORG,
    Scope.PLATFORM,
)


def _principal_qualifies(entry: CatalogEntry, auth: AuthContext) -> bool:
    if entry.approved_at_scope is Scope.PLATFORM:
        return True
    if entry.approved_at_scope is Scope.ORG:
        return bool(auth.org_id) and auth.org_id == entry.org_id
    if entry.approved_at_scope is Scope.TEAM:
        return (
            bool(auth.org_id)
            and auth.org_id == entry.org_id
            and bool(auth.team_id)
            and auth.team_id == entry.team_id
        )
    if entry.approved_at_scope is Scope.USER:
        return (
            bool(auth.org_id)
            and auth.org_id == entry.org_id
            and bool(auth.user_id)
            and auth.user_id == entry.user_id
        )
    return False


class InMemoryToolCatalog:
    """Reference implementation of the ``ToolCatalog`` protocol."""

    def __init__(self) -> None:
        # (fingerprint_value, scope) -> entry. Same fingerprint may be
        # approved at multiple scopes simultaneously; lookup walks
        # narrow-to-wide.
        self._entries: dict[tuple[str, Scope], CatalogEntry] = {}
        # fingerprint_value -> ToolFingerprint (rehydration helper).
        self._fingerprints: dict[str, ToolFingerprint] = {}
        # name -> set[fingerprint_value] (rug-pull diagnostics).
        self._by_name: dict[str, set[str]] = defaultdict(set)
        self._subscribers: list[Callable[[], None]] = []

    # --- mutation surface (used by promotion/admin paths) ----------------

    def approve(self, fingerprint: ToolFingerprint, entry: CatalogEntry) -> None:
        """Approve a fingerprint at the entry's scope."""
        self._entries[(fingerprint.value, entry.approved_at_scope)] = entry
        self._fingerprints[fingerprint.value] = fingerprint
        self._by_name[fingerprint.name].add(fingerprint.value)
        self._notify()

    def revoke(self, fingerprint: ToolFingerprint, scope: Scope | None = None) -> None:
        """Revoke an approval. If ``scope`` is None, revokes at all scopes."""
        if scope is None:
            keys = [k for k in self._entries if k[0] == fingerprint.value]
        else:
            keys = [(fingerprint.value, scope)]
        for key in keys:
            self._entries.pop(key, None)
        # Garbage-collect empty name index.
        if not any(k[0] == fingerprint.value for k in self._entries):
            self._fingerprints.pop(fingerprint.value, None)
            self._by_name[fingerprint.name].discard(fingerprint.value)
            if not self._by_name[fingerprint.name]:
                del self._by_name[fingerprint.name]
        self._notify()

    # --- read surface (the protocol) -------------------------------------

    def lookup(
        self,
        fingerprint: ToolFingerprint,
        auth: AuthContext,
    ) -> CatalogEntry | None:
        for scope in _SCOPE_PRECEDENCE:
            entry = self._entries.get((fingerprint.value, scope))
            if entry is None:
                continue
            if _principal_qualifies(entry, auth):
                return entry
        # SYSTEM identity (SYSTEM_ORG_ID) sees every approval.
        if auth.org_id == SYSTEM_ORG_ID:
            for scope in _SCOPE_PRECEDENCE:
                entry = self._entries.get((fingerprint.value, scope))
                if entry is not None:
                    return entry
        return None

    def approvals_for(self, auth: AuthContext) -> frozenset[ToolFingerprint]:
        out: set[ToolFingerprint] = set()
        for (fp_value, _scope), entry in self._entries.items():
            if _principal_qualifies(entry, auth) or auth.org_id == SYSTEM_ORG_ID:
                fp = self._fingerprints.get(fp_value)
                if fp is not None:
                    out.add(fp)
        return frozenset(out)

    def fingerprints_with_name(self, name: str) -> frozenset[str]:
        """Return fingerprint values registered under a tool name.

        Used by Sentinel's tool-declaration validator to detect rug-pulls
        (name in catalog, schema drifted).
        """
        return frozenset(self._by_name.get(name, set()))

    def subscribe_changes(
        self,
        callback: Callable[[], None],
    ) -> Callable[[], None]:
        self._subscribers.append(callback)

        def unsubscribe() -> None:
            if callback in self._subscribers:
                self._subscribers.remove(callback)

        return unsubscribe

    def _notify(self) -> None:
        for cb in list(self._subscribers):
            cb()
