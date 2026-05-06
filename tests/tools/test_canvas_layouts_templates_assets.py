"""Document-phase plumbing tests — §10 layouts, §11 templates, §18 assets."""

from __future__ import annotations

import pytest

from stronghold.persistence.canvas_design_memory import InMemoryDocumentStore
from stronghold.tools.canvas_assets import (
    AssetKind,
    HashEmbedder,
    InMemoryAssetStore,
    UploadSourceKind,
)
from stronghold.tools.canvas_layouts import (
    auto_paginate_word_count,
    early_reader_default_layout,
    get_layout,
    layout_apply,
    list_layouts,
    picture_book_default_layout,
)
from stronghold.tools.canvas_templates import (
    InMemoryBrandKitStore,
    InMemoryTemplateStore,
    Template,
    TemplatePage,
    extract_brand_kit_from_logo,
    render_prompt_template,
    template_apply,
)
from stronghold.types.canvas_design import (
    BrandKit,
    BrandKitFonts,
    Color,
    DocumentKind,
    FontRef,
    Layer,
    LayoutKind,
    Page,
    PrintSpec,
    RasterSource,
    TextSource,
)
from stronghold.types.errors import (
    AssetNotFoundError,
    AssetReferenceInUseError,
    AssetUploadValidationError,
    BrandKitExtractionError,
    TemplateApplyError,
    TemplateNotFoundError,
    TemplatePromptTemplateError,
    TemplateTrustViolationError,
)
from stronghold.types.security import Provenance, TrustTier

# ─── §10 Layouts ───────────────────────────────────────────────────────────


def _spec() -> PrintSpec:
    return PrintSpec(trim_size=(1000, 1000), bleed=10, safe_area=20)


class TestLayoutCatalogue:
    def test_lists_all_kinds(self) -> None:
        kinds = list_layouts()
        assert LayoutKind.COVER in kinds
        assert LayoutKind.ART_WITH_CAPTION in kinds

    def test_get_layout_returns_slot_definitions(self) -> None:
        layout = get_layout(LayoutKind.COVER)
        slot_ids = {s.slot_id for s in layout.slots}
        assert {"hero_art", "title", "byline"}.issubset(slot_ids)


class TestLayoutApply:
    def test_apply_creates_required_placeholders(self) -> None:
        page = Page(id="P0", ordering=0, print_spec=_spec())
        positioned = layout_apply(page, LayoutKind.COVER)
        slot_ids = {layer.slot_id for layer in positioned.layers}
        assert {"hero_art", "title", "byline"}.issubset(slot_ids)
        assert positioned.layout_kind is LayoutKind.COVER

    def test_apply_repositions_existing_slot_layers(self) -> None:
        text_layer = Layer(
            id="my-title",
            name="title",
            source=TextSource(content="My Book"),
            slot_id="title",
        )
        page = Page(id="P0", ordering=0, print_spec=_spec(), layers=(text_layer,))
        positioned = layout_apply(page, LayoutKind.TITLE_PAGE)
        title_layers = [layer for layer in positioned.layers if layer.slot_id == "title"]
        # The existing layer is repositioned; no extra placeholder is created
        assert len(title_layers) == 1
        assert title_layers[0].id == "my-title"
        # And it moved to the layout's title bbox (not at 0, 0)
        assert title_layers[0].transform.x > 0

    def test_free_layers_preserved(self) -> None:
        free = Layer(
            id="free",
            name="free",
            source=RasterSource(blob_id="b", width=10, height=10),
        )  # No slot_id
        page = Page(id="P0", ordering=0, print_spec=_spec(), layers=(free,))
        positioned = layout_apply(page, LayoutKind.ART_WITH_CAPTION)
        free_layers = [layer for layer in positioned.layers if layer.slot_id is None]
        assert len(free_layers) == 1
        assert free_layers[0].id == "free"

    def test_optional_slot_not_filled(self) -> None:
        page = Page(id="P0", ordering=0, print_spec=_spec())
        positioned = layout_apply(page, LayoutKind.COVER)
        # subtitle is optional; should NOT have a placeholder
        slot_ids = {layer.slot_id for layer in positioned.layers}
        assert "subtitle" not in slot_ids


class TestPagination:
    def test_word_count_5_7_uses_60_wpp(self) -> None:
        text = " ".join(["word"] * 600)
        pages = auto_paginate_word_count(text, age_band="5_7")
        assert pages == 10  # 600 / 60

    def test_word_count_9_12_uses_higher_density(self) -> None:
        text = " ".join(["word"] * 250)
        pages = auto_paginate_word_count(text, age_band="9_12")
        assert pages == 1

    def test_empty_text_yields_one_page(self) -> None:
        assert auto_paginate_word_count("", age_band="5_7") == 1


class TestDefaultLayouts:
    def test_picture_book_first_pages(self) -> None:
        assert picture_book_default_layout(0, 32) is LayoutKind.COVER
        assert picture_book_default_layout(1, 32) is LayoutKind.TITLE_PAGE
        assert picture_book_default_layout(2, 32) is LayoutKind.COPYRIGHT_PAGE
        assert picture_book_default_layout(3, 32) is LayoutKind.DEDICATION_PAGE

    def test_picture_book_middle_pages(self) -> None:
        assert picture_book_default_layout(10, 32) is LayoutKind.ART_WITH_CAPTION

    def test_early_reader(self) -> None:
        assert early_reader_default_layout(0) is LayoutKind.COVER
        assert early_reader_default_layout(5) is LayoutKind.ART_WITH_BODY


# ─── §11 Templates ─────────────────────────────────────────────────────────


class TestTemplateRegistry:
    async def test_lists_bundled_templates(self) -> None:
        store = InMemoryTemplateStore()
        listing = await store.list(tenant_id="acme")
        ids = {t.id for t in listing}
        assert "builtin-picture-book-classic-32" in ids
        assert "builtin-movie-poster" in ids
        assert "builtin-infographic-a2" in ids

    async def test_filter_by_doc_kind(self) -> None:
        store = InMemoryTemplateStore()
        listing = await store.list(tenant_id="acme", doc_kind=DocumentKind.PICTURE_BOOK)
        assert all(t.doc_kind is DocumentKind.PICTURE_BOOK for t in listing)

    async def test_get_unknown_template_raises(self) -> None:
        store = InMemoryTemplateStore()
        with pytest.raises(TemplateNotFoundError):
            await store.get("missing", tenant_id="acme")

    async def test_publish_tenant_template(self) -> None:
        store = InMemoryTemplateStore()
        tmpl = Template(
            id="tenant-1",
            tenant_id="acme",
            owner_id="alice",
            name="My Cover",
            category="picture_book",
            doc_kind=DocumentKind.PICTURE_BOOK,
            pages=(TemplatePage(ordering=0, layout_kind=LayoutKind.COVER),),
        )
        await store.publish(tmpl)
        loaded = await store.get("tenant-1", tenant_id="acme")
        assert loaded.id == "tenant-1"

    async def test_tenant_only_excludes_bundled(self) -> None:
        store = InMemoryTemplateStore()
        listing = await store.list(tenant_id="acme", tenant_only=True)
        assert listing == []


class TestPromptTemplate:
    def test_substitutes_variables(self) -> None:
        out = render_prompt_template(
            "a {{character}} riding a {{vehicle}}",
            {"character": "wizard", "vehicle": "broom"},
        )
        assert out == "a wizard riding a broom"

    def test_undeclared_variable_raises(self) -> None:
        with pytest.raises(TemplatePromptTemplateError):
            render_prompt_template("a {{missing}}", {"declared": "x"})

    def test_no_placeholders_passes_through(self) -> None:
        assert render_prompt_template("plain text", {}) == "plain text"


class TestTemplateApply:
    async def test_apply_picture_book_creates_document(self) -> None:
        templates = InMemoryTemplateStore()
        documents = InMemoryDocumentStore()
        tmpl = await templates.get("builtin-picture-book-classic-32", tenant_id="acme")
        doc_id = await template_apply(
            tmpl,
            variables={
                "title": "Lily and the Dragon",
                "byline": "Alice Smith",
                "hero_prompt": "a watercolour dragon",
            },
            tenant_id="acme",
            owner_id="alice",
            document_store=documents,
            template_store=templates,
        )
        doc = await documents.get(doc_id, tenant_id="acme")
        assert doc["page_count"] == 4
        assert doc["name"] == "Lily and the Dragon"

    async def test_apply_missing_required_variable_raises(self) -> None:
        templates = InMemoryTemplateStore()
        documents = InMemoryDocumentStore()
        tmpl = await templates.get("builtin-movie-poster", tenant_id="acme")
        with pytest.raises(TemplateApplyError):
            await template_apply(
                tmpl,
                variables={"title": "X"},  # missing hero_prompt
                tenant_id="acme",
                owner_id="alice",
                document_store=documents,
            )

    async def test_apply_uses_default_for_optional_variable(self) -> None:
        templates = InMemoryTemplateStore()
        documents = InMemoryDocumentStore()
        tmpl = await templates.get("builtin-movie-poster", tenant_id="acme")
        # cta has default "In theatres now" — omitting it should still apply
        doc_id = await template_apply(
            tmpl,
            variables={"title": "Something", "hero_prompt": "epic art"},
            tenant_id="acme",
            owner_id="alice",
            document_store=documents,
        )
        assert isinstance(doc_id, str)

    async def test_uses_count_increments(self) -> None:
        templates = InMemoryTemplateStore()
        documents = InMemoryDocumentStore()
        tmpl = await templates.get("builtin-movie-poster", tenant_id="acme")
        before = tmpl.uses_count
        await template_apply(
            tmpl,
            variables={"title": "X", "hero_prompt": "y"},
            tenant_id="acme",
            owner_id="alice",
            document_store=documents,
            template_store=templates,
        )
        after = await templates.get("builtin-movie-poster", tenant_id="acme")
        assert after.uses_count == before + 1

    async def test_low_trust_template_rejected(self) -> None:
        documents = InMemoryDocumentStore()
        unsafe = Template(
            id="t4",
            tenant_id="acme",
            owner_id="alice",
            name="x",
            category="picture_book",
            doc_kind=DocumentKind.PICTURE_BOOK,
            pages=(),
            trust_tier=TrustTier.T4,
            provenance=Provenance.COMMUNITY,
        )
        with pytest.raises(TemplateTrustViolationError):
            await template_apply(
                unsafe,
                variables={},
                tenant_id="acme",
                owner_id="alice",
                document_store=documents,
            )


class TestBrandKit:
    async def test_create_and_list(self) -> None:
        store = InMemoryBrandKitStore()
        fonts = BrandKitFonts(
            display=FontRef(family="Inter"),
            body=FontRef(family="Atkinson Hyperlegible"),
        )
        kit = BrandKit(
            id="k1",
            tenant_id="acme",
            owner_id="alice",
            name="Acme",
            palette=tuple(Color(c) for c in ("#FF0000", "#00FF00", "#0000FF")),
            fonts=fonts,
        )
        await store.create(kit)
        listing = await store.list_for_tenant(tenant_id="acme")
        assert len(listing) == 1
        assert listing[0].name == "Acme"

    async def test_get_unknown_raises(self) -> None:
        store = InMemoryBrandKitStore()
        with pytest.raises(TemplateNotFoundError):
            await store.get("missing", tenant_id="acme")

    async def test_apply_to_document_sets_brand_kit_id(self) -> None:
        store = InMemoryBrandKitStore()
        documents = InMemoryDocumentStore()
        doc_id = await documents.create(
            tenant_id="acme", owner_id="alice", name="B", kind="picture_book"
        )
        kit = BrandKit(
            id="k1",
            tenant_id="acme",
            owner_id="alice",
            name="x",
            palette=(Color("#000000"), Color("#FFFFFF"), Color("#FF0000")),
            fonts=BrandKitFonts(
                display=FontRef(family="Inter"),
                body=FontRef(family="Inter"),
            ),
        )
        await store.create(kit)
        await store.apply_to_document(doc_id, "k1", tenant_id="acme", document_store=documents)
        doc_dict = await documents.get(doc_id, tenant_id="acme")
        assert doc_dict["brand_kit_id"] == "k1"


class TestExtractBrandKit:
    def test_extract_from_logo_with_palette(self) -> None:
        kit = extract_brand_kit_from_logo(
            tenant_id="acme",
            owner_id="alice",
            name="Acme",
            logo_bytes=b"some-logo-bytes",
            palette=("#FF0000", "#00FF00", "#0000FF", "#FFFF00"),
        )
        assert len(kit.palette) == 4
        assert kit.tenant_id == "acme"

    def test_empty_logo_rejected(self) -> None:
        with pytest.raises(BrandKitExtractionError):
            extract_brand_kit_from_logo(
                tenant_id="acme",
                owner_id="alice",
                name="x",
                logo_bytes=b"",
            )

    def test_invalid_palette_size_rejected(self) -> None:
        with pytest.raises(BrandKitExtractionError):
            extract_brand_kit_from_logo(
                tenant_id="acme",
                owner_id="alice",
                name="x",
                logo_bytes=b"data",
                palette=("#FF0000", "#00FF00"),  # only 2 — invalid
            )


# ─── §18 Assets ────────────────────────────────────────────────────────────


class TestAssetCreate:
    async def test_create_character_asset(self) -> None:
        store = InMemoryAssetStore()
        asset = await store.create(
            tenant_id="acme",
            owner_id="alice",
            kind=AssetKind.CHARACTER,
            name="Lily the Dragon",
            primary_blob_id="blob-1",
            primary_blob_bytes=b"image-bytes",
            tags=("fantasy", "dragon"),
        )
        assert asset.kind is AssetKind.CHARACTER
        assert asset.tags == ("fantasy", "dragon")
        # Embedding is computed from bytes
        assert asset.embedding is not None
        assert len(asset.embedding) > 0

    async def test_create_upload_requires_rights(self) -> None:
        store = InMemoryAssetStore()
        with pytest.raises(AssetUploadValidationError):
            await store.create(
                tenant_id="acme",
                owner_id="alice",
                kind=AssetKind.UPLOAD,
                name="logo",
                primary_blob_id="b1",
                rights_acknowledged=False,
            )

    async def test_svg_upload_strips_scripts(self) -> None:
        store = InMemoryAssetStore()
        # We can't easily verify that the bytes were sanitised end-to-end
        # without exposing internals; the embedding computation includes
        # the sanitised bytes, so two uploads (with vs without scripts)
        # produce the same embedding.
        with_scripts = b"<svg><script>alert(1)</script><circle/></svg>"
        clean = b"<svg><circle/></svg>"
        a = await store.create(
            tenant_id="acme",
            owner_id="alice",
            kind=AssetKind.UPLOAD,
            name="a",
            primary_blob_id="b-a",
            primary_blob_bytes=with_scripts,
            source_kind=UploadSourceKind.SVG,
        )
        b = await store.create(
            tenant_id="acme",
            owner_id="alice",
            kind=AssetKind.UPLOAD,
            name="b",
            primary_blob_id="b-b",
            primary_blob_bytes=clean,
            source_kind=UploadSourceKind.SVG,
        )
        assert a.embedding == b.embedding


class TestAssetSearch:
    async def test_tag_search(self) -> None:
        store = InMemoryAssetStore()
        await store.create(
            tenant_id="acme",
            owner_id="alice",
            kind=AssetKind.CHARACTER,
            name="Lily",
            primary_blob_id="b1",
            tags=("fantasy", "dragon"),
        )
        await store.create(
            tenant_id="acme",
            owner_id="alice",
            kind=AssetKind.PROP,
            name="Sword",
            primary_blob_id="b2",
            tags=("weapon", "fantasy"),
        )
        results = await store.search(tenant_id="acme", tags=("dragon",))
        names = {a.name for a in results}
        assert names == {"Lily"}

    async def test_substring_search(self) -> None:
        store = InMemoryAssetStore()
        await store.create(
            tenant_id="acme",
            owner_id="alice",
            kind=AssetKind.CHARACTER,
            name="Lily the Dragon",
            primary_blob_id="b1",
        )
        results = await store.search(
            tenant_id="acme",
            query="dragon",
            mode="substring",
        )
        assert {a.name for a in results} == {"Lily the Dragon"}

    async def test_semantic_search_ranks_similar(self) -> None:
        store = InMemoryAssetStore()
        await store.create(
            tenant_id="acme",
            owner_id="alice",
            kind=AssetKind.CHARACTER,
            name="A",
            primary_blob_id="b1",
            primary_blob_bytes=b"identical-bytes",
        )
        await store.create(
            tenant_id="acme",
            owner_id="alice",
            kind=AssetKind.CHARACTER,
            name="B",
            primary_blob_id="b2",
            primary_blob_bytes=b"completely-different-bytes",
        )
        results = await store.search(
            tenant_id="acme",
            mode="semantic",
            query_bytes=b"identical-bytes",
        )
        # Most-similar should be the asset whose bytes match
        assert results[0].name == "A"

    async def test_kind_filter(self) -> None:
        store = InMemoryAssetStore()
        await store.create(
            tenant_id="acme",
            owner_id="alice",
            kind=AssetKind.CHARACTER,
            name="C",
            primary_blob_id="b1",
        )
        await store.create(
            tenant_id="acme",
            owner_id="alice",
            kind=AssetKind.PROP,
            name="P",
            primary_blob_id="b2",
        )
        results = await store.list_for_tenant(tenant_id="acme", kind=AssetKind.PROP)
        assert {a.name for a in results} == {"P"}


class TestAssetDelete:
    async def test_archive_hides_from_listing(self) -> None:
        store = InMemoryAssetStore()
        asset = await store.create(
            tenant_id="acme",
            owner_id="alice",
            kind=AssetKind.PROP,
            name="x",
            primary_blob_id="b1",
        )
        await store.archive(asset.id, tenant_id="acme")
        listing = await store.list_for_tenant(tenant_id="acme")
        assert listing == []

    async def test_hard_delete_blocked_when_referenced(self) -> None:
        store = InMemoryAssetStore()
        asset = await store.create(
            tenant_id="acme",
            owner_id="alice",
            kind=AssetKind.PROP,
            name="x",
            primary_blob_id="b1",
        )
        store.record_reference(asset.id, "doc-1", tenant_id="acme")
        with pytest.raises(AssetReferenceInUseError):
            await store.hard_delete(asset.id, tenant_id="acme")

    async def test_hard_delete_after_release(self) -> None:
        store = InMemoryAssetStore()
        asset = await store.create(
            tenant_id="acme",
            owner_id="alice",
            kind=AssetKind.PROP,
            name="x",
            primary_blob_id="b1",
        )
        store.record_reference(asset.id, "doc-1", tenant_id="acme")
        store.release_reference(asset.id, "doc-1", tenant_id="acme")
        await store.hard_delete(asset.id, tenant_id="acme")
        with pytest.raises(AssetNotFoundError):
            await store.get(asset.id, tenant_id="acme")


class TestInsert:
    async def test_insert_creates_layer_at_position(self) -> None:
        store = InMemoryAssetStore()
        asset = await store.create(
            tenant_id="acme",
            owner_id="alice",
            kind=AssetKind.PROP,
            name="x",
            primary_blob_id="b1",
        )
        layer = store.insert_into_layer(asset, page_id="P0", position=(50, 60))
        assert layer.transform.x == 50
        assert layer.transform.y == 60
        assert isinstance(layer.source, RasterSource)
        assert layer.source.blob_id == "b1"


class TestEmbedderUnavailable:
    async def test_create_without_embedder_succeeds(self) -> None:
        store = InMemoryAssetStore(embedder=HashEmbedder(fail=True))
        asset = await store.create(
            tenant_id="acme",
            owner_id="alice",
            kind=AssetKind.PROP,
            name="x",
            primary_blob_id="b1",
            primary_blob_bytes=b"data",
        )
        # Embedding back-fills as None when embedder offline (asset still created)
        assert asset.embedding is None

    async def test_semantic_search_falls_back_when_embedder_offline(self) -> None:
        store = InMemoryAssetStore()
        await store.create(
            tenant_id="acme",
            owner_id="alice",
            kind=AssetKind.PROP,
            name="dragon-prop",
            primary_blob_id="b1",
        )
        # Replace the embedder mid-flight to force the offline path
        store._embedder = HashEmbedder(fail=True)  # noqa: SLF001
        results = await store.search(
            tenant_id="acme",
            mode="semantic",
            query="dragon",
            query_bytes=b"x",
        )
        assert any(a.name == "dragon-prop" for a in results)


class TestTenantIsolation:
    async def test_cross_tenant_get_raises(self) -> None:
        store = InMemoryAssetStore()
        asset = await store.create(
            tenant_id="globex",
            owner_id="bob",
            kind=AssetKind.PROP,
            name="x",
            primary_blob_id="b1",
        )
        with pytest.raises(AssetNotFoundError):
            await store.get(asset.id, tenant_id="acme")

    async def test_cross_tenant_search_returns_nothing(self) -> None:
        store = InMemoryAssetStore()
        await store.create(
            tenant_id="globex",
            owner_id="bob",
            kind=AssetKind.PROP,
            name="x",
            primary_blob_id="b1",
            tags=("a",),
        )
        results = await store.search(tenant_id="acme", tags=("a",))
        assert results == []
