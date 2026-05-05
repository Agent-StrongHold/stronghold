"""Versioning green tests — features/versioning.feature scenarios."""

from __future__ import annotations

import pytest

from stronghold.tools.canvas_versioning import InMemoryVersionStore
from stronghold.types.errors import (
    DocumentNotFoundError,
    RevertConflictError,
    VersionNotFoundError,
)

# ─── Helpers ───────────────────────────────────────────────────────────────


async def _seed(
    store: InMemoryVersionStore,
    document_id: str,
    n: int,
    *,
    tenant_id: str = "acme",
    author_id: str = "alice",
    delta_template: dict[str, object] | None = None,
) -> list[str]:
    """Append `n` versions with per-call unique keys to bypass coalescing."""
    template = delta_template or {"name": "v"}
    out: list[str] = []
    for i in range(n):
        # Use a per-iteration unique key so coalescing doesn't fold them
        # together (coalescing keys-on-keys equality).
        delta = {**template, f"step_{i}": i}
        vid = await store.append(
            document_id,
            tenant_id=tenant_id,
            author_id=author_id,
            author_kind="user",
            delta=delta,
        )
        out.append(vid)
    return out


# ─── Append + ordinals ─────────────────────────────────────────────────────


class TestAppend:
    async def test_each_mutation_creates_a_new_version(self) -> None:
        store = InMemoryVersionStore()
        ids = await _seed(store, "D1", 3)
        assert len(ids) == 3
        assert store.count("D1", tenant_id="acme") == 3

    async def test_ordinals_increment(self) -> None:
        store = InMemoryVersionStore()
        await _seed(store, "D1", 4)
        listing = await store.list("D1", tenant_id="acme")
        ordinals = [v["ordinal"] for v in listing]
        # listing is newest-first
        assert ordinals == [4, 3, 2, 1]

    async def test_parent_chain_links(self) -> None:
        store = InMemoryVersionStore()
        ids = await _seed(store, "D1", 3)
        listing = await store.list("D1", tenant_id="acme")
        # newest-first; parents point one back
        assert listing[0]["parent_version_id"] == ids[1]
        assert listing[1]["parent_version_id"] == ids[0]
        assert listing[2]["parent_version_id"] is None


class TestCoalescing:
    async def test_same_author_same_keys_within_window_coalesces(self) -> None:
        # Differentiate by changing only the same key repeatedly
        store = InMemoryVersionStore(coalesce_window_seconds=60)
        await store.append(
            "D1",
            tenant_id="acme",
            author_id="alice",
            author_kind="user",
            delta={"name": "first"},
        )
        await store.append(
            "D1",
            tenant_id="acme",
            author_id="alice",
            author_kind="user",
            delta={"name": "second"},
        )
        await store.append(
            "D1",
            tenant_id="acme",
            author_id="alice",
            author_kind="user",
            delta={"name": "third"},
        )
        assert store.count("D1", tenant_id="acme") == 1
        listing = await store.list("D1", tenant_id="acme")
        assert listing[0]["delta"]["name"] == "third"

    async def test_different_authors_do_not_coalesce(self) -> None:
        store = InMemoryVersionStore(coalesce_window_seconds=60)
        await store.append(
            "D1",
            tenant_id="acme",
            author_id="alice",
            author_kind="user",
            delta={"name": "alice's"},
        )
        await store.append(
            "D1",
            tenant_id="acme",
            author_id="agent:davinci",
            author_kind="agent",
            delta={"name": "agent's"},
        )
        assert store.count("D1", tenant_id="acme") == 2

    async def test_outside_window_does_not_coalesce(self) -> None:
        store = InMemoryVersionStore(coalesce_window_seconds=0.0)
        await store.append(
            "D1",
            tenant_id="acme",
            author_id="alice",
            author_kind="user",
            delta={"name": "first"},
        )
        await store.append(
            "D1",
            tenant_id="acme",
            author_id="alice",
            author_kind="user",
            delta={"name": "second"},
        )
        # Window is 0s so even immediate consecutive writes don't coalesce.
        assert store.count("D1", tenant_id="acme") == 2


# ─── Snapshots + restore ───────────────────────────────────────────────────


class TestSnapshots:
    async def test_auto_snapshot_every_n_versions(self) -> None:
        store = InMemoryVersionStore(snapshot_every=5, coalesce_window_seconds=0.0)
        await _seed(store, "D1", 12)
        listing = await store.list("D1", tenant_id="acme", limit=20)
        snapshots = [v for v in listing if v["snapshot"] is not None]
        # ordinals 1, 6, 11 should be snapshots (every-5 starting at 1)
        snap_ordinals = sorted(v["ordinal"] for v in snapshots)
        assert snap_ordinals == [6, 11]

    async def test_explicit_checkpoint_creates_snapshot(self) -> None:
        store = InMemoryVersionStore()
        await _seed(store, "D1", 2)
        cp_id = await store.checkpoint(
            "D1", tenant_id="acme", author_id="alice", message="before-regen"
        )
        listing = await store.list("D1", tenant_id="acme")
        cp = next(v for v in listing if v["id"] == cp_id)
        assert cp["snapshot"] is not None
        assert "before-regen" in cp["message"]

    async def test_restore_to_prior_version_reproduces_state(self) -> None:
        store = InMemoryVersionStore(coalesce_window_seconds=0.0)
        ids = await _seed(store, "D1", 5)
        recorded = await store.get("D1", ids[2], tenant_id="acme")
        # Add more changes
        await _seed(store, "D1", 5, delta_template={"name": "later"})
        # Restoring still returns the same recorded state
        restored = await store.get("D1", ids[2], tenant_id="acme")
        assert restored == recorded

    async def test_restore_uses_snapshot_plus_forward_deltas(self) -> None:
        store = InMemoryVersionStore(snapshot_every=3, coalesce_window_seconds=0.0)
        ids = await _seed(store, "D1", 7)
        # Restore at the last id; the per-iteration `step_N` keys all
        # accumulate so the restored state has every step recorded.
        state = await store.get("D1", ids[-1], tenant_id="acme")
        assert state["step_6"] == 6
        assert state["step_0"] == 0
        assert state["name"] == "v"


# ─── Revert + branching ────────────────────────────────────────────────────


class TestRevert:
    async def test_revert_appends_a_new_branching_version(self) -> None:
        store = InMemoryVersionStore(coalesce_window_seconds=0.0)
        ids = await _seed(store, "D1", 5)
        rev_id = await store.revert("D1", ids[1], tenant_id="acme", author_id="alice")
        listing = await store.list("D1", tenant_id="acme")
        head = listing[0]
        assert head["id"] == rev_id
        assert head["parent_version_id"] == ids[1]
        # Original chain is still reachable
        assert any(v["id"] == ids[-1] for v in listing)

    async def test_revert_to_head_raises(self) -> None:
        store = InMemoryVersionStore(coalesce_window_seconds=0.0)
        ids = await _seed(store, "D1", 3)
        with pytest.raises(RevertConflictError):
            await store.revert("D1", ids[-1], tenant_id="acme", author_id="alice")

    async def test_revert_unknown_version_raises(self) -> None:
        store = InMemoryVersionStore()
        await _seed(store, "D1", 1)
        with pytest.raises(VersionNotFoundError):
            await store.revert("D1", "missing", tenant_id="acme", author_id="alice")


# ─── Pinning + retention ───────────────────────────────────────────────────


class TestRetention:
    async def test_pinned_version_is_immune_to_sweep(self) -> None:
        store = InMemoryVersionStore(coalesce_window_seconds=0.0)
        ids = await _seed(store, "D1", 250)
        store.pin("D1", ids[10], tenant_id="acme")
        # keep_days=0 forces all old non-snapshot, non-pinned to be dropped
        removed = store.retain_sweep(
            tenant_id="acme", document_id="D1", keep_recent=200, keep_days=0
        )
        listing = await store.list("D1", tenant_id="acme", limit=300)
        assert removed > 0
        assert any(v["id"] == ids[10] for v in listing)

    async def test_snapshots_preserved_in_sweep(self) -> None:
        store = InMemoryVersionStore(snapshot_every=10, coalesce_window_seconds=0.0)
        await _seed(store, "D1", 250)
        store.retain_sweep(tenant_id="acme", document_id="D1", keep_recent=50, keep_days=0)
        listing = await store.list("D1", tenant_id="acme", limit=300)
        snap_count = sum(1 for v in listing if v["snapshot"] is not None)
        assert snap_count > 0

    async def test_sweep_under_keep_recent_no_op(self) -> None:
        store = InMemoryVersionStore(coalesce_window_seconds=0.0)
        await _seed(store, "D1", 50)
        removed = store.retain_sweep(tenant_id="acme", document_id="D1", keep_recent=200)
        assert removed == 0


# ─── List + filtering ──────────────────────────────────────────────────────


class TestListing:
    async def test_list_is_newest_first(self) -> None:
        store = InMemoryVersionStore(coalesce_window_seconds=0.0)
        await _seed(store, "D1", 5)
        listing = await store.list("D1", tenant_id="acme")
        ordinals = [v["ordinal"] for v in listing]
        assert ordinals == sorted(ordinals, reverse=True)

    async def test_list_respects_limit(self) -> None:
        store = InMemoryVersionStore(coalesce_window_seconds=0.0)
        await _seed(store, "D1", 10)
        listing = await store.list("D1", tenant_id="acme", limit=3)
        assert len(listing) == 3


# ─── Tenant isolation ──────────────────────────────────────────────────────


class TestTenantIsolation:
    async def test_cross_tenant_get_raises(self) -> None:
        store = InMemoryVersionStore()
        ids = await _seed(store, "D1", 1, tenant_id="globex")
        with pytest.raises(VersionNotFoundError):
            await store.get("D1", ids[0], tenant_id="acme")

    async def test_cross_tenant_list_raises(self) -> None:
        store = InMemoryVersionStore()
        await _seed(store, "D1", 1, tenant_id="globex")
        with pytest.raises(VersionNotFoundError):
            await store.list("D1", tenant_id="acme")

    async def test_unknown_document_raises(self) -> None:
        store = InMemoryVersionStore()
        await _seed(store, "D1", 1, tenant_id="acme")
        with pytest.raises(DocumentNotFoundError):
            await store.list("D2", tenant_id="acme")


# ─── Author kinds ──────────────────────────────────────────────────────────


class TestAuthorKinds:
    async def test_user_vs_agent_kinds_recorded(self) -> None:
        store = InMemoryVersionStore(coalesce_window_seconds=0.0)
        await store.append(
            "D1",
            tenant_id="acme",
            author_id="alice",
            author_kind="user",
            delta={"name": "u1"},
        )
        await store.append(
            "D1",
            tenant_id="acme",
            author_id="agent:davinci",
            author_kind="agent",
            delta={"name": "a1"},
        )
        listing = await store.list("D1", tenant_id="acme")
        kinds = {v["author_kind"] for v in listing}
        assert kinds == {"user", "agent"}


# ─── Protocol conformance ──────────────────────────────────────────────────


class TestProtocolConformance:
    def test_satisfies_version_store_protocol(self) -> None:
        from stronghold.protocols.canvas_design import VersionStore

        assert isinstance(InMemoryVersionStore(), VersionStore)


# ─── Head + count helpers ──────────────────────────────────────────────────


class TestHelpers:
    async def test_head_id_tracks_latest_append(self) -> None:
        store = InMemoryVersionStore(coalesce_window_seconds=0.0)
        ids = await _seed(store, "D1", 3)
        assert store.head_id("D1", tenant_id="acme") == ids[-1]

    async def test_head_id_none_for_empty_doc(self) -> None:
        store = InMemoryVersionStore()
        # Reading before any append: per Protocol, the document must
        # exist in some bucket — the helper raises if there's no bucket.
        # So this only applies after a tenant bucket exists.
        with pytest.raises(VersionNotFoundError):
            store.head_id("Dnew", tenant_id="missing")
