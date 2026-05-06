"""Pre-flight green tests — features/preflight.feature scenarios.

Backed by the in-process PreflightChecker with default rules.
"""

from __future__ import annotations

import pytest

from stronghold.tools.canvas_preflight import (
    BgCoversBleedRule,
    BindingCreepSafeRule,
    DpiMinimumRule,
    EmptyDocumentRule,
    PageCountParityRule,
    PreflightChecker,
    TextInSafeAreaRule,
)
from stronghold.types.canvas_design import (
    BindingKind,
    Document,
    DocumentKind,
    Layer,
    LayerTransform,
    Page,
    PrintSpec,
    RasterSource,
    ReportLevel,
    TextSource,
)
from stronghold.types.errors import RuleNotFoundError

# ─── Fixtures ──────────────────────────────────────────────────────────────


def _spec(**overrides: object) -> PrintSpec:
    base: dict[str, object] = {"trim_size": (2400, 2400), "bleed": 38, "safe_area": 75}
    base.update(overrides)
    return PrintSpec(**base)  # type: ignore[arg-type]


def _bg_layer(layer_id: str, page_spec: PrintSpec) -> Layer:
    """A raster layer that covers the bleed canvas."""
    bw, bh = page_spec.bleed_canvas
    return Layer(
        id=layer_id,
        name="bg",
        source=RasterSource(blob_id="b", width=bw, height=bh),
        transform=LayerTransform(x=0, y=0),
    )


def _text_layer(layer_id: str, *, x: int = 100, y: int = 100) -> Layer:
    return Layer(
        id=layer_id,
        name="caption",
        source=TextSource(content="Hello"),
        transform=LayerTransform(x=x, y=y),
    )


def _doc(
    *,
    page_count: int = 1,
    kind: DocumentKind = DocumentKind.PICTURE_BOOK,
    binding: BindingKind = BindingKind.NONE,
    pages: tuple[Page, ...] | None = None,
) -> Document:
    if pages is None:
        spec = _spec(binding=binding)
        pages = tuple(
            Page(
                id=f"P{i}",
                ordering=i,
                print_spec=spec,
                layers=(_bg_layer(f"bg{i}", spec),),
            )
            for i in range(page_count)
        )
    return Document(
        id="D1",
        tenant_id="acme",
        owner_id="alice",
        name="Book",
        kind=kind,
        pages=pages,
    )


# ─── §22 preflight.feature scenarios ───────────────────────────────────────


class TestCleanFixture:
    """Scenario: Preflight on a clean fixture returns OK."""

    async def test_clean_fixture_is_ok(self) -> None:
        doc = _doc(page_count=4)  # 4 % 4 == 0
        checker = PreflightChecker()
        checker.set_document(doc)
        report = await checker.run(doc.id, tenant_id="acme")
        assert report.level is ReportLevel.OK
        assert report.summary.failures == 0
        assert report.summary.warnings == 0


class TestEmptyDocument:
    """Scenario: Empty document FAILs."""

    async def test_empty_document_fails(self) -> None:
        doc = _doc(page_count=0)
        checker = PreflightChecker()
        checker.set_document(doc)
        report = await checker.run(doc.id, tenant_id="acme")
        assert report.summary.failures == 1
        assert any(c.rule_id == "empty_document" for c in report.checks)


class TestBackgroundBleed:
    """Scenario: Preflight detects missing background bleed."""

    async def test_missing_bleed_coverage_fails(self) -> None:
        spec = _spec()
        # Background is too small to cover the bleed canvas
        too_small_bg = Layer(
            id="bg",
            name="bg",
            source=RasterSource(blob_id="b", width=100, height=100),
        )
        page = Page(id="P0", ordering=0, print_spec=spec, layers=(too_small_bg,))
        doc = _doc(pages=(page,))
        checker = PreflightChecker()
        checker.set_document(doc)
        report = await checker.run(doc.id, tenant_id="acme")
        assert any(c.rule_id == "bg_covers_bleed" for c in report.checks)
        assert report.summary.failures >= 1


class TestTextSafeArea:
    """Scenario: Preflight detects text crossing the safe area."""

    async def test_text_outside_safe_area_fails(self) -> None:
        spec = _spec()
        # Place text at y=10 (outside the y=75..2325 safe rect)
        bad_text = _text_layer("t1", x=0, y=10)
        page = Page(
            id="P0",
            ordering=0,
            print_spec=spec,
            layers=(_bg_layer("bg", spec), bad_text),
        )
        doc = _doc(pages=(page,))
        checker = PreflightChecker()
        checker.set_document(doc)
        report = await checker.run(doc.id, tenant_id="acme")
        assert any(c.rule_id == "text_in_safe_area" for c in report.checks)

    async def test_text_inside_safe_area_passes(self) -> None:
        spec = _spec()
        text = _text_layer("t1", x=200, y=200)
        page = Page(id="P0", ordering=0, print_spec=spec, layers=(_bg_layer("bg", spec), text))
        doc = _doc(pages=(page,))
        checker = PreflightChecker()
        checker.set_document(doc)
        report = await checker.run(doc.id, tenant_id="acme", rule_ids=("text_in_safe_area",))
        assert report.level is ReportLevel.OK


class TestDpiMinimum:
    """Scenario: Preflight detects raster below print DPI."""

    async def test_low_dpi_raster_fails(self) -> None:
        spec = _spec()  # 2400x2400 trim
        small_layer = Layer(
            id="r1",
            name="hero",
            source=RasterSource(blob_id="b", width=800, height=800),
        )
        page = Page(
            id="P0",
            ordering=0,
            print_spec=spec,
            layers=(_bg_layer("bg", spec), small_layer),
        )
        doc = _doc(pages=(page,))
        checker = PreflightChecker()
        checker.set_document(doc)
        report = await checker.run(doc.id, tenant_id="acme", rule_ids=("dpi_minimum",))
        assert any(c.rule_id == "dpi_minimum" for c in report.checks)


class TestPageCountParity:
    """Scenario: Picture book with odd page count → WARN."""

    async def test_picture_book_odd_count_warns(self) -> None:
        doc = _doc(page_count=33)
        checker = PreflightChecker(rules=(PageCountParityRule(),))
        checker.set_document(doc)
        report = await checker.run(doc.id, tenant_id="acme")
        assert report.level is ReportLevel.WARN
        assert report.summary.warnings == 1

    async def test_picture_book_multiple_of_4_no_warn(self) -> None:
        doc = _doc(page_count=32)
        checker = PreflightChecker(rules=(PageCountParityRule(),))
        checker.set_document(doc)
        report = await checker.run(doc.id, tenant_id="acme")
        assert report.summary.warnings == 0

    async def test_non_picture_book_skipped(self) -> None:
        doc = _doc(page_count=33, kind=DocumentKind.POSTER)
        checker = PreflightChecker(rules=(PageCountParityRule(),))
        checker.set_document(doc)
        report = await checker.run(doc.id, tenant_id="acme")
        assert report.summary.warnings == 0


class TestBindingCreep:
    """Scenario: Saddle-stitch with too many pages WARNs."""

    async def test_saddle_stitch_over_64_warns(self) -> None:
        doc = _doc(page_count=96, binding=BindingKind.SADDLE_STITCH)
        checker = PreflightChecker(rules=(BindingCreepSafeRule(),))
        checker.set_document(doc)
        report = await checker.run(doc.id, tenant_id="acme")
        assert report.summary.warnings == 1

    async def test_perfect_binding_high_count_does_not_warn(self) -> None:
        doc = _doc(page_count=200, binding=BindingKind.PERFECT)
        checker = PreflightChecker(rules=(BindingCreepSafeRule(),))
        checker.set_document(doc)
        report = await checker.run(doc.id, tenant_id="acme")
        assert report.summary.warnings == 0


class TestSilencing:
    """Scenarios: Silenced rule does not surface; tenant rule cannot be silenced."""

    async def test_silenced_rule_does_not_surface(self) -> None:
        spec = _spec()
        bad_text = _text_layer("t1", x=0, y=10)
        page = Page(id="P0", ordering=0, print_spec=spec, layers=(_bg_layer("bg", spec), bad_text))
        doc = _doc(pages=(page,))
        checker = PreflightChecker(rules=(TextInSafeAreaRule(),))
        checker.silence("text_in_safe_area", "t1")
        checker.set_document(doc)
        report = await checker.run(doc.id, tenant_id="acme")
        assert report.summary.failures == 0

    def test_tenant_isolation_rule_cannot_be_silenced(self) -> None:
        checker = PreflightChecker()
        with pytest.raises(RuleNotFoundError):
            checker.silence("tenant_assets_only")


class TestRuleListing:
    def test_list_rules_returns_default_set(self) -> None:
        checker = PreflightChecker()
        rules = checker.list_rules()
        assert "empty_document" in rules
        assert "bg_covers_bleed" in rules
        assert "text_in_safe_area" in rules
        assert "dpi_minimum" in rules

    def test_construct_with_explicit_rules(self) -> None:
        checker = PreflightChecker(rules=(EmptyDocumentRule(),))
        assert checker.list_rules() == ("empty_document",)


class TestProtocolConformance:
    def test_satisfies_preflight_checker_protocol(self) -> None:
        from stronghold.protocols.canvas_design import (
            PreflightChecker as PreflightCheckerProtocol,
        )

        assert isinstance(PreflightChecker(), PreflightCheckerProtocol)

    def test_rule_classes_satisfy_preflight_rule_protocol(self) -> None:
        from stronghold.protocols.canvas_design import PreflightRule

        for rule in (
            EmptyDocumentRule(),
            BgCoversBleedRule(),
            TextInSafeAreaRule(),
            DpiMinimumRule(),
            PageCountParityRule(),
            BindingCreepSafeRule(),
        ):
            assert isinstance(rule, PreflightRule)


class TestMultipleFailures:
    async def test_multiple_findings_summary_correct(self) -> None:
        spec = _spec()
        # Page with both: missing-bleed bg + text outside safe area
        bg_too_small = Layer(
            id="bg", name="bg", source=RasterSource(blob_id="b", width=100, height=100)
        )
        bad_text = _text_layer("t1", x=0, y=10)
        page = Page(id="P0", ordering=0, print_spec=spec, layers=(bg_too_small, bad_text))
        doc = _doc(pages=(page,))
        checker = PreflightChecker(
            rules=(BgCoversBleedRule(), TextInSafeAreaRule()),
        )
        checker.set_document(doc)
        report = await checker.run(doc.id, tenant_id="acme")
        assert report.summary.failures == 2
        assert report.summary.total == 2
        assert report.level is ReportLevel.FAIL
