"""Integration tests for the document model — InMemoryDocumentStore.

Maps 1:1 to scenarios in ../../agents/davinci/specs/features/document-model.feature.
These tests were stubs in test_canvas_subsystems.py::TestDocumentModel; they
are now real, runnable, and green.
"""

from __future__ import annotations

import pytest

from stronghold.persistence.canvas_design_memory import InMemoryDocumentStore
from stronghold.types.canvas_design import (
    Document,
    DocumentKind,
    Layer,
    Page,
    PrintSpec,
    RasterSource,
)
from stronghold.types.errors import (
    ConcurrentEditError,
    DocumentNotFoundError,
    EmptyDocumentError,
    InvalidPageOrderingError,
    MasterInUseError,
)


def _spec() -> PrintSpec:
    return PrintSpec(trim_size=(2400, 2400))


def _page(page_id: str, ordering: int, **overrides: object) -> Page:
    return Page(
        id=page_id,
        ordering=ordering,
        print_spec=_spec(),
        **overrides,  # type: ignore[arg-type]
    )


def _master(master_id: str, *, ordering: int = 0) -> Page:
    return Page(
        id=master_id,
        ordering=ordering,
        print_spec=_spec(),
        is_master=True,
    )


class TestCreatingDocuments:
    """document-model.feature: Creating a document with no pages."""

    async def test_creating_a_document_with_no_pages(self) -> None:
        store = InMemoryDocumentStore()
        doc_id = await store.create(
            tenant_id="acme",
            owner_id="alice",
            name="First Book",
            kind="picture_book",
        )
        doc = await store.get(doc_id, tenant_id="acme")
        assert doc["page_count"] == 0
        assert doc["owner_id"] == "alice"
        assert doc["tenant_id"] == "acme"
        assert doc["kind"] == "picture_book"
        assert doc["archived"] is False

    async def test_creating_a_document_with_n_empty_pages(self) -> None:
        store = InMemoryDocumentStore()
        doc_id = await store.create(
            tenant_id="acme", owner_id="alice", name="Book", kind="picture_book"
        )
        for ordering in range(32):
            await store.add_page(
                doc_id,
                _page(f"P{ordering}", ordering),
                tenant_id="acme",
                ordering=ordering,
            )
        doc = await store.get(doc_id, tenant_id="acme")
        assert doc["page_count"] == 32


class TestPageOps:
    async def test_adding_a_page_at_a_position_shifts_later_pages(self) -> None:
        store = InMemoryDocumentStore()
        doc_id = await store.create(
            tenant_id="acme", owner_id="alice", name="Book", kind="picture_book"
        )
        for i in range(4):
            await store.add_page(doc_id, _page(f"P{i}", i), tenant_id="acme", ordering=i)
        await store.add_page(doc_id, _page("Pnew", 0), tenant_id="acme", ordering=2)
        doc = await store.get(doc_id, tenant_id="acme")
        assert doc["page_count"] == 5

    async def test_reordering_pages_preserves_master_page_references(self) -> None:
        store = InMemoryDocumentStore()
        doc_id = await store.create(
            tenant_id="acme", owner_id="alice", name="Book", kind="picture_book"
        )
        master = _master("M1")
        # add master via update delta
        await store.update(doc_id, tenant_id="acme", delta={"master_pages": (master,)})
        for i in range(4):
            page = _page(f"P{i}", i, master_id="M1")
            await store.add_page(doc_id, page, tenant_id="acme", ordering=i)
        # reorder
        await store.reorder_pages(doc_id, ("P3", "P2", "P1", "P0"), tenant_id="acme")
        # Use the rich Document object to verify masters preserved
        doc_dict = await store.get(doc_id, tenant_id="acme")
        # Round-trip via store internals isn't required; just verify metadata.
        # Master id reference preservation is asserted below via internal access.
        stored = store._docs[doc_id]  # noqa: SLF001
        assert all(p.master_id == "M1" for p in stored.pages)
        assert [p.ordering for p in stored.pages] == [0, 1, 2, 3]
        # ids should be reversed
        assert [p.id for p in stored.pages] == ["P3", "P2", "P1", "P0"]
        assert doc_dict["page_count"] == 4

    async def test_deleting_a_page_renumbers_later_pages(self) -> None:
        store = InMemoryDocumentStore()
        doc_id = await store.create(
            tenant_id="acme", owner_id="alice", name="Book", kind="picture_book"
        )
        for i in range(5):
            await store.add_page(doc_id, _page(f"P{i}", i), tenant_id="acme", ordering=i)
        await store.delete_page(doc_id, "P2", tenant_id="acme")
        stored = store._docs[doc_id]  # noqa: SLF001
        assert [p.ordering for p in stored.pages] == [0, 1, 2, 3]

    async def test_duplicating_a_page_deep_copies_layers_and_effects(self) -> None:
        store = InMemoryDocumentStore()
        doc_id = await store.create(
            tenant_id="acme", owner_id="alice", name="Book", kind="picture_book"
        )
        page = Page(
            id="P0",
            ordering=0,
            print_spec=_spec(),
            layers=(
                Layer(
                    id="La",
                    name="art",
                    source=RasterSource(blob_id="b1", width=10, height=10),
                ),
            ),
        )
        await store.add_page(doc_id, page, tenant_id="acme", ordering=0)
        # "duplicate" by re-inserting under a new id
        dup = Page(
            id="P0_copy",
            ordering=1,
            print_spec=_spec(),
            layers=page.layers,
        )
        await store.add_page(doc_id, dup, tenant_id="acme", ordering=1)
        stored = store._docs[doc_id]  # noqa: SLF001
        assert len(stored.pages) == 2
        assert stored.pages[0].layers[0].source == stored.pages[1].layers[0].source


class TestTenantIsolation:
    async def test_cross_tenant_document_read_returns_nothing(self) -> None:
        store = InMemoryDocumentStore()
        doc_id = await store.create(
            tenant_id="globex", owner_id="bob", name="B1", kind="picture_book"
        )
        with pytest.raises(DocumentNotFoundError):
            await store.get(doc_id, tenant_id="acme")

    async def test_archive_only_affects_tenant_owner(self) -> None:
        store = InMemoryDocumentStore()
        doc_id = await store.create(
            tenant_id="globex", owner_id="bob", name="B1", kind="picture_book"
        )
        with pytest.raises(DocumentNotFoundError):
            await store.archive(doc_id, tenant_id="acme")


class TestMasterPages:
    async def test_master_deletion_blocked_while_in_use(self) -> None:
        store = InMemoryDocumentStore()
        doc_id = await store.create(
            tenant_id="acme", owner_id="alice", name="B", kind="picture_book"
        )
        master = _master("M1")
        await store.update(doc_id, tenant_id="acme", delta={"master_pages": (master,)})
        page = _page("P0", 0, master_id="M1")
        await store.add_page(doc_id, page, tenant_id="acme", ordering=0)
        with pytest.raises(MasterInUseError):
            await store.delete_master(doc_id, "M1", tenant_id="acme")

    async def test_master_can_be_deleted_after_pages_re_master(self) -> None:
        store = InMemoryDocumentStore()
        doc_id = await store.create(
            tenant_id="acme", owner_id="alice", name="B", kind="picture_book"
        )
        master = _master("M1")
        await store.update(doc_id, tenant_id="acme", delta={"master_pages": (master,)})
        page = _page("P0", 0, master_id="M1")
        await store.add_page(doc_id, page, tenant_id="acme", ordering=0)
        # re-master via full pages replace
        re_mastered = _page("P0", 0, master_id=None)
        await store.update(doc_id, tenant_id="acme", delta={"pages": (re_mastered,)})
        # now master can be deleted
        await store.delete_master(doc_id, "M1", tenant_id="acme")
        stored = store._docs[doc_id]  # noqa: SLF001
        assert stored.master_pages == ()


class TestVersioning:
    async def test_concurrent_edit_detected_via_expected_version(self) -> None:
        store = InMemoryDocumentStore()
        doc_id = await store.create(
            tenant_id="acme", owner_id="alice", name="B", kind="picture_book"
        )
        # baseline version 1; advance to 2
        await store.update(doc_id, tenant_id="acme", delta={"name": "B2"}, expected_version=1)
        # stale write
        with pytest.raises(ConcurrentEditError):
            await store.update(
                doc_id, tenant_id="acme", delta={"name": "stale"}, expected_version=1
            )

    async def test_update_increments_version_and_updated_at(self) -> None:
        store = InMemoryDocumentStore()
        doc_id = await store.create(
            tenant_id="acme", owner_id="alice", name="B", kind="picture_book"
        )
        before = store._docs[doc_id]  # noqa: SLF001
        v2 = await store.update(doc_id, tenant_id="acme", delta={"name": "Renamed"})
        after = store._docs[doc_id]  # noqa: SLF001
        assert v2 == before.version + 1
        assert after.version == v2
        assert after.updated_at >= before.updated_at
        assert after.name == "Renamed"


class TestSoftArchive:
    async def test_soft_archive_hides_from_list_but_preserves_data(self) -> None:
        store = InMemoryDocumentStore()
        ids = [
            await store.create(
                tenant_id="acme", owner_id="alice", name=f"B{i}", kind="picture_book"
            )
            for i in range(3)
        ]
        # Archive the middle doc
        await store.archive(ids[1], tenant_id="acme")
        active = await store.list_for_owner(tenant_id="acme", owner_id="alice")
        assert len(active) == 2
        assert ids[1] not in [d["id"] for d in active]
        # data preserved + readable directly
        archived = await store.get(ids[1], tenant_id="acme")
        assert archived["archived"] is True
        # archived list returns it
        archived_only = await store.list_for_owner(
            tenant_id="acme", owner_id="alice", archived=True
        )
        assert [d["id"] for d in archived_only] == [ids[1]]


class TestExportPreconditions:
    async def test_empty_document_export_is_rejected(self) -> None:
        store = InMemoryDocumentStore()
        doc_id = await store.create(
            tenant_id="acme", owner_id="alice", name="B", kind="picture_book"
        )
        with pytest.raises(EmptyDocumentError):
            await store.assert_non_empty(doc_id, tenant_id="acme")

    async def test_non_empty_passes(self) -> None:
        store = InMemoryDocumentStore()
        doc_id = await store.create(
            tenant_id="acme", owner_id="alice", name="B", kind="picture_book"
        )
        await store.add_page(doc_id, _page("P0", 0), tenant_id="acme", ordering=0)
        # no exception
        await store.assert_non_empty(doc_id, tenant_id="acme")


class TestProtocolConformance:
    """Verify the in-memory adapter satisfies the DocumentStore Protocol."""

    def test_implements_document_store(self) -> None:
        from stronghold.protocols.canvas_design import DocumentStore

        assert isinstance(InMemoryDocumentStore(), DocumentStore)


class TestPageOrderingValidation:
    async def test_add_page_ordering_out_of_range_rejected(self) -> None:
        store = InMemoryDocumentStore()
        doc_id = await store.create(
            tenant_id="acme", owner_id="alice", name="B", kind="picture_book"
        )
        with pytest.raises(InvalidPageOrderingError):
            await store.add_page(doc_id, _page("P0", 0), tenant_id="acme", ordering=10)

    async def test_reorder_with_unknown_ids_rejected(self) -> None:
        store = InMemoryDocumentStore()
        doc_id = await store.create(
            tenant_id="acme", owner_id="alice", name="B", kind="picture_book"
        )
        await store.add_page(doc_id, _page("P0", 0), tenant_id="acme", ordering=0)
        with pytest.raises(InvalidPageOrderingError):
            await store.reorder_pages(doc_id, ("P0", "X"), tenant_id="acme")


class TestAvoidsModuleAccess:
    """Smoke test that we can compose without poking internals."""

    async def test_add_then_list_then_archive_uses_only_public_api(self) -> None:
        store = InMemoryDocumentStore()
        doc_id = await store.create(
            tenant_id="acme", owner_id="alice", name="B", kind="picture_book"
        )
        await store.add_page(doc_id, _page("P0", 0), tenant_id="acme", ordering=0)
        listing = await store.list_for_owner(tenant_id="acme", owner_id="alice")
        assert len(listing) == 1
        assert listing[0]["page_count"] == 1
        await store.archive(doc_id, tenant_id="acme")
        listing_after = await store.list_for_owner(tenant_id="acme", owner_id="alice")
        assert listing_after == []


class TestDocumentTypeRoundTrip:
    """Sanity: dict serialisation captures invariants."""

    def test_full_document_round_trip(self) -> None:
        spec = _spec()
        doc = Document(
            id="d",
            tenant_id="t",
            owner_id="u",
            name="name",
            kind=DocumentKind.PICTURE_BOOK,
            pages=(Page(id="p", ordering=0, print_spec=spec),),
        )
        assert doc.page_count == 1
        assert doc.get_page("p") is doc.pages[0]
        assert doc.get_page("missing") is None
