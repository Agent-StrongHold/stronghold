"""Correction store green tests — features/corrections.feature."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from stronghold.tools.canvas_corrections import (
    InMemoryCorrectionStore,
    MockIntentInferrer,
)
from stronghold.types.canvas_design import (
    AgeBand,
    CorrectionContext,
    CorrectionKind,
    CorrectionSource,
    DocumentKind,
)


def _ctx() -> CorrectionContext:
    return CorrectionContext(doc_kind=DocumentKind.PICTURE_BOOK, age_band=AgeBand.AGE_5_7)


async def _capture(
    store: InMemoryCorrectionStore,
    *,
    kind: CorrectionKind = CorrectionKind.FONT_CHANGE,
    source: CorrectionSource = CorrectionSource.DIRECT_MANIP,
    layer_id: str | None = "L1",
    document_id: str = "D1",
    user_id: str = "alice",
    tenant_id: str = "acme",
    before: dict[str, object] | None = None,
    after: dict[str, object] | None = None,
) -> object:
    return await store.capture(
        tenant_id=tenant_id,
        user_id=user_id,
        document_id=document_id,
        page_id="P0",
        layer_id=layer_id,
        session_id="S",
        kind=kind,
        source=source,
        before=before or {"font": "Comic Sans"},
        after=after or {"font": "Atkinson Hyperlegible"},
        context=_ctx(),
    )


# ─── Capture basics ────────────────────────────────────────────────────────


class TestCaptureBasics:
    async def test_direct_manip_font_change(self) -> None:
        store = InMemoryCorrectionStore()
        c = await _capture(store)
        assert c.kind is CorrectionKind.FONT_CHANGE  # type: ignore[attr-defined]
        assert c.source is CorrectionSource.DIRECT_MANIP  # type: ignore[attr-defined]
        assert c.before == {"font": "Comic Sans"}  # type: ignore[attr-defined]
        assert c.after == {"font": "Atkinson Hyperlegible"}  # type: ignore[attr-defined]

    async def test_chat_source_recorded_separately(self) -> None:
        store = InMemoryCorrectionStore()
        c = await _capture(store, source=CorrectionSource.CHAT)
        assert c.source is CorrectionSource.CHAT  # type: ignore[attr-defined]


# ─── Coalescing ────────────────────────────────────────────────────────────


class TestCoalescing:
    async def test_rapid_same_layer_same_kind_coalesces(self) -> None:
        store = InMemoryCorrectionStore()
        await _capture(store, after={"font": "Inter"})
        await _capture(store, after={"font": "Roboto"})
        await _capture(store, after={"font": "Atkinson Hyperlegible"})
        listing = await store.list_for_user(tenant_id="acme", user_id="alice")
        assert len(listing) == 1
        assert listing[0].after == {"font": "Atkinson Hyperlegible"}

    async def test_different_layers_do_not_coalesce(self) -> None:
        store = InMemoryCorrectionStore()
        await _capture(store, layer_id="L1")
        await _capture(store, layer_id="L2")
        listing = await store.list_for_user(tenant_id="acme", user_id="alice")
        assert len(listing) == 2

    async def test_different_kinds_do_not_coalesce(self) -> None:
        store = InMemoryCorrectionStore()
        await _capture(store, kind=CorrectionKind.FONT_CHANGE)
        await _capture(
            store,
            kind=CorrectionKind.COLOR_CHANGE,
            after={"color": "#FF0000"},
        )
        listing = await store.list_for_user(tenant_id="acme", user_id="alice")
        assert len(listing) == 2


# ─── Tenant isolation ──────────────────────────────────────────────────────


class TestTenantIsolation:
    async def test_cross_tenant_list_returns_nothing(self) -> None:
        store = InMemoryCorrectionStore()
        await _capture(store, tenant_id="globex", user_id="bob")
        listing = await store.list_for_user(tenant_id="acme", user_id="bob")
        assert listing == []


# ─── User-data deletion ────────────────────────────────────────────────────


class TestUserDataDeletion:
    async def test_delete_for_user_removes_only_users(self) -> None:
        store = InMemoryCorrectionStore()
        await _capture(store, user_id="alice")
        await _capture(store, user_id="alice", layer_id="L2")
        await _capture(store, user_id="bob", layer_id="LB")
        deleted = await store.delete_for_user(tenant_id="acme", user_id="alice")
        assert deleted == 2
        # Bob's data still present
        bobs = await store.list_for_user(tenant_id="acme", user_id="bob")
        assert len(bobs) == 1


# ─── Mark reverted ─────────────────────────────────────────────────────────


class TestMarkReverted:
    async def test_mark_reverted_flips_flag(self) -> None:
        store = InMemoryCorrectionStore()
        c = await _capture(store)
        await store.mark_reverted(c.id, tenant_id="acme")  # type: ignore[attr-defined]
        listing = await store.list_for_user(tenant_id="acme", user_id="alice")
        assert listing[0].reverted is True
        assert listing[0].reverted_at is not None

    async def test_mark_reverted_unknown_id_silent(self) -> None:
        store = InMemoryCorrectionStore()
        await store.mark_reverted("missing", tenant_id="acme")
        # No exception


# ─── Aggregatable filter ───────────────────────────────────────────────────


class TestAggregatableFilter:
    async def test_wizard_source_excluded_from_aggregation(self) -> None:
        store = InMemoryCorrectionStore()
        await _capture(store, source=CorrectionSource.WIZARD)
        items = await store.list_aggregatable(tenant_id="acme", user_id="alice")
        assert items == []

    async def test_reverted_excluded(self) -> None:
        store = InMemoryCorrectionStore()
        c = await _capture(store)
        await store.mark_reverted(c.id, tenant_id="acme")  # type: ignore[attr-defined]
        items = await store.list_aggregatable(tenant_id="acme", user_id="alice")
        assert items == []

    async def test_since_filters_old(self) -> None:
        store = InMemoryCorrectionStore()
        await _capture(store, layer_id="L1")
        future = datetime.now(UTC) + timedelta(seconds=10)
        items = await store.list_aggregatable(tenant_id="acme", user_id="alice", since=future)
        assert items == []


# ─── Intent inference cache ────────────────────────────────────────────────


class TestIntentInference:
    async def test_intent_cached_by_before_after_hash(self) -> None:
        inferrer = MockIntentInferrer()
        store = InMemoryCorrectionStore(intent_inferrer=inferrer)
        await _capture(store, layer_id="L1")
        await _capture(store, layer_id="L2")  # different layer, same before/after
        # Both calls share the same before/after content → cache hit
        assert inferrer.call_count == 1


# ─── Brand-kit signal strength ─────────────────────────────────────────────


class TestSignalStrength:
    async def test_brand_kit_color_change_starts_stronger(self) -> None:
        store = InMemoryCorrectionStore()
        c = await _capture(
            store,
            kind=CorrectionKind.COLOR_CHANGE,
            after={"color": "#FFAA00", "source": "brand_kit"},
            before={"color": "#000000"},
        )
        assert c.signal_strength == 1.5  # type: ignore[attr-defined]

    async def test_default_signal_strength(self) -> None:
        store = InMemoryCorrectionStore()
        c = await _capture(store)
        assert c.signal_strength == 1.0  # type: ignore[attr-defined]
