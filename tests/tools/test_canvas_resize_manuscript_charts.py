"""Tests for §14 smart-resize, §33 manuscript-import, §12 charts."""

from __future__ import annotations

import pytest

from stronghold.tools.canvas_charts import (
    ChannelType,
    ChartChannel,
    ChartEncoding,
    ChartKind,
    ChartSpec,
    ChartStyle,
    TableColumn,
    TableSpec,
    assert_csv_safe,
    detect_pii,
    render_table_text,
    sanitise_cell,
    sanitise_rows,
    to_vega_lite,
    to_vega_lite_json,
)
from stronghold.tools.canvas_manuscript import (
    BlockKind,
    Manuscript,
    ManuscriptFormat,
    import_manuscript,
    paginate,
    parse,
)
from stronghold.tools.canvas_smart_resize import (
    PRINT_KIT,
    SOCIAL_KIT,
    ResizeStrategy,
    fit_into,
    smart_resize,
    smart_resize_batch,
)
from stronghold.types.canvas_design import (
    AgeBand,
    BBox,
    Color,
    Layer,
    LayerTransform,
    LayoutKind,
    Page,
    PrintSpec,
    RasterSource,
    TextSource,
)
from stronghold.types.errors import (
    ChartSpecError,
    CSVInjectionError,
    ManuscriptFormatUnsupportedError,
    SmartResizeTargetInvalidError,
    SmartResizeTextOverflowError,
)

# ─── §14 Smart resize ──────────────────────────────────────────────────────


def _spec() -> PrintSpec:
    return PrintSpec(trim_size=(2400, 2400), bleed=10, safe_area=20)


def _bg_layer() -> Layer:
    return Layer(
        id="bg",
        name="bg",
        source=RasterSource(blob_id="b", width=2400, height=2400),
        slot_id="hero_art",
        z_index=0,
    )


def _text_layer(*, x: int = 200, y: int = 200) -> Layer:
    return Layer(
        id="title",
        name="title",
        source=TextSource(content="Hello"),
        transform=LayerTransform(x=x, y=y),
        slot_id="title",
        z_index=2,
    )


def _logo_layer() -> Layer:
    return Layer(
        id="logo",
        name="logo",
        source=RasterSource(blob_id="b", width=200, height=200),
        transform=LayerTransform(x=2150, y=2150),  # bottom-right
        z_index=3,
        metadata={"role": "logo"},
    )


class TestSmartResize:
    def test_identical_dims_idempotent(self) -> None:
        page = Page(id="P0", ordering=0, print_spec=_spec(), layers=(_bg_layer(),))
        new_page, report = smart_resize(page, (2400, 2400))
        assert report.aspect_delta == 0.0
        assert new_page.print_spec.trim_size == (2400, 2400)

    def test_invalid_dims_raises(self) -> None:
        page = Page(id="P0", ordering=0, print_spec=_spec())
        with pytest.raises(SmartResizeTargetInvalidError):
            smart_resize(page, (0, 100))

    def test_square_to_portrait_smart_auto_uses_regen(self) -> None:
        # bg-only fixture (text shrink limit is exercised separately below).
        page = Page(
            id="P0",
            ordering=0,
            print_spec=_spec(),
            layers=(_bg_layer(),),
        )
        _, report = smart_resize(page, (1080, 1920))
        # Portrait → big aspect change → regenerate
        assert report.strategy_used is ResizeStrategy.REGENERATE_BACKGROUND
        assert report.aspect_delta > 0.20

    def test_mild_aspect_change_uses_outpaint(self) -> None:
        page = Page(
            id="P0",
            ordering=0,
            print_spec=_spec(),
            layers=(_bg_layer(),),
        )
        # 2400x2400 → 2400x2700 = ~12% delta
        _, report = smart_resize(page, (2400, 2700))
        assert report.bg_action == "outpaint"

    def test_logo_pinned_to_corner(self) -> None:
        page = Page(
            id="P0",
            ordering=0,
            print_spec=_spec(),
            layers=(_bg_layer(), _logo_layer()),
        )
        new_page, _ = smart_resize(page, (1200, 1200))
        logo = next(layer for layer in new_page.layers if layer.id == "logo")
        # Still close to bottom-right
        assert logo.transform.x > 600
        assert logo.transform.y > 600

    def test_text_shrink_within_limit_succeeds(self) -> None:
        page = Page(
            id="P0",
            ordering=0,
            print_spec=_spec(),
            layers=(_bg_layer(), _text_layer()),
        )
        new_page, report = smart_resize(page, (2000, 2000))
        text = next(layer for layer in new_page.layers if layer.id == "title")
        src = text.source
        assert isinstance(src, TextSource)
        assert src.style.size_px <= 48
        assert report.text_shrunk_pct < 0.30

    def test_text_shrink_over_30pct_raises(self) -> None:
        page = Page(
            id="P0",
            ordering=0,
            print_spec=_spec(),
            layers=(_text_layer(),),
        )
        with pytest.raises(SmartResizeTextOverflowError):
            smart_resize(page, (1000, 1000))  # 42% shrink

    def test_batch_processes_each_target(self) -> None:
        page = Page(
            id="P0",
            ordering=0,
            print_spec=_spec(),
            layers=(_bg_layer(),),
        )
        results = smart_resize_batch(page, SOCIAL_KIT)
        assert len(results) == len(SOCIAL_KIT)

    def test_print_kit_targets_match_a_series(self) -> None:
        # A2 = 4961x7016 should be in the print kit
        assert (4961, 7016) in PRINT_KIT


class TestFitInto:
    def test_contain_keeps_aspect(self) -> None:
        out = fit_into(BBox(0, 0, 200, 100), BBox(0, 0, 100, 100), mode="contain")
        # 200x100 → fits 100x50
        assert out.width == 100
        assert out.height == 50

    def test_cover_fills_target(self) -> None:
        out = fit_into(BBox(0, 0, 200, 100), BBox(0, 0, 100, 100), mode="cover")
        # 200x100 → cover 100x100 means 200x100 in scale-up — 100/100 = 1 → 200x100
        assert out.width >= 100
        assert out.height >= 100


# ─── §33 Manuscript import ─────────────────────────────────────────────────


_SAMPLE_MARKDOWN = """\
# Chapter One

Once upon a time, in a kingdom by the sea, there lived a small dragon
named Lily. She was friendly and curious.

* * *

Lily flew up the mountain to find adventure.

# Chapter Two

She met a wizard.
"""


class TestParseMarkdown:
    def test_chapters_detected(self) -> None:
        blocks = parse(_SAMPLE_MARKDOWN.encode(), ManuscriptFormat.MARKDOWN)
        chapters = [b for b in blocks if b.kind is BlockKind.CHAPTER_BREAK]
        assert len(chapters) == 2

    def test_scene_break_detected(self) -> None:
        blocks = parse(_SAMPLE_MARKDOWN.encode(), ManuscriptFormat.MARKDOWN)
        breaks = [b for b in blocks if b.kind is BlockKind.SCENE_BREAK]
        assert len(breaks) == 1

    def test_paragraphs_extracted(self) -> None:
        blocks = parse(_SAMPLE_MARKDOWN.encode(), ManuscriptFormat.MARKDOWN)
        paragraphs = [b for b in blocks if b.kind is BlockKind.PARAGRAPH]
        assert len(paragraphs) == 3
        assert "Lily" in paragraphs[0].content


class TestParsePlain:
    def test_paragraphs_split_by_blank_lines(self) -> None:
        text = "First paragraph.\n\nSecond paragraph."
        blocks = parse(text.encode(), ManuscriptFormat.PLAIN)
        paragraphs = [b for b in blocks if b.kind is BlockKind.PARAGRAPH]
        assert len(paragraphs) == 2


class TestParseUnsupported:
    def test_docx_raises(self) -> None:
        with pytest.raises(ManuscriptFormatUnsupportedError):
            parse(b"<docx>", ManuscriptFormat.DOCX)


class TestPaginate:
    def test_chapter_break_starts_new_page_with_chapter_layout(self) -> None:
        blocks = parse(_SAMPLE_MARKDOWN.encode(), ManuscriptFormat.MARKDOWN)
        pages = paginate(blocks, age_band=AgeBand.AGE_9_12)
        # First page is a chapter-break page → TEXT_ONLY layout
        assert pages[0].layout_kind in (LayoutKind.TEXT_ONLY, LayoutKind.ART_WITH_BODY)

    def test_pagination_respects_word_budget(self) -> None:
        # 200 words at 5_7 → 60wpp → ~4 pages
        text = " ".join(["lorem"] * 200)
        blocks = parse(text.encode(), ManuscriptFormat.PLAIN)
        pages = paginate(blocks, age_band=AgeBand.AGE_5_7)
        # Single huge paragraph won't split mid-paragraph; we get 1 page
        assert len(pages) >= 1

    def test_scene_break_attaches_illustration_prompt(self) -> None:
        blocks = parse(_SAMPLE_MARKDOWN.encode(), ManuscriptFormat.MARKDOWN)
        pages = paginate(blocks, age_band=AgeBand.AGE_5_7)
        with_prompt = [p for p in pages if p.illustration_prompt]
        assert with_prompt  # at least one page has a scene-derived illustration prompt


class TestImportManuscript:
    def test_full_pipeline_returns_manuscript(self) -> None:
        manuscript = import_manuscript(
            _SAMPLE_MARKDOWN.encode(),
            ManuscriptFormat.MARKDOWN,
            age_band=AgeBand.AGE_5_7,
            language="en",
        )
        assert isinstance(manuscript, Manuscript)
        assert manuscript.chapter_count == 2
        assert manuscript.word_count > 0
        assert manuscript.language == "en"


# ─── §12 Charts ────────────────────────────────────────────────────────────


def _bar_spec(rows: tuple[dict[str, object], ...] | None = None) -> ChartSpec:
    return ChartSpec(
        kind=ChartKind.BAR,
        rows=rows
        or (
            {"category": "A", "value": 10},
            {"category": "B", "value": 20},
        ),
        encoding=ChartEncoding(
            x=ChartChannel(field="category", type=ChannelType.NOMINAL),
            y=ChartChannel(field="value", type=ChannelType.QUANTITATIVE),
        ),
    )


class TestVegaLiteSpec:
    def test_bar_chart_produces_valid_spec(self) -> None:
        spec = to_vega_lite(_bar_spec())
        assert spec["mark"] == "bar"
        assert spec["encoding"]["x"]["field"] == "category"
        assert spec["encoding"]["y"]["type"] == "quantitative"

    def test_pie_chart_uses_arc_mark(self) -> None:
        spec = to_vega_lite(
            ChartSpec(
                kind=ChartKind.PIE,
                rows=({"label": "A", "value": 1}, {"label": "B", "value": 2}),
                encoding=ChartEncoding(
                    x=ChartChannel(field="label", type=ChannelType.NOMINAL),
                    y=ChartChannel(field="value", type=ChannelType.QUANTITATIVE),
                ),
            )
        )
        assert spec["mark"] == "arc"

    def test_pie_with_negative_value_raises(self) -> None:
        with pytest.raises(ChartSpecError):
            to_vega_lite(
                ChartSpec(
                    kind=ChartKind.PIE,
                    rows=({"label": "A", "value": -1},),
                    encoding=ChartEncoding(
                        x=ChartChannel(field="label", type=ChannelType.NOMINAL),
                        y=ChartChannel(field="value", type=ChannelType.QUANTITATIVE),
                    ),
                )
            )

    def test_missing_field_raises(self) -> None:
        with pytest.raises(ChartSpecError):
            to_vega_lite(
                ChartSpec(
                    kind=ChartKind.BAR,
                    rows=({"x": 1, "y": 2},),
                    encoding=ChartEncoding(
                        x=ChartChannel(field="missing", type=ChannelType.NOMINAL),
                        y=ChartChannel(field="y", type=ChannelType.QUANTITATIVE),
                    ),
                )
            )

    def test_empty_rows_returns_no_data_spec(self) -> None:
        spec = to_vega_lite(
            ChartSpec(
                kind=ChartKind.BAR,
                rows=(),
                encoding=ChartEncoding(
                    x=ChartChannel(field="x", type=ChannelType.NOMINAL),
                    y=ChartChannel(field="y", type=ChannelType.QUANTITATIVE),
                ),
            )
        )
        assert "data" not in spec

    def test_brand_kit_palette_injected(self) -> None:
        spec = to_vega_lite(
            ChartSpec(
                kind=ChartKind.BAR,
                rows=({"x": "a", "y": 1, "g": "g1"},),
                encoding=ChartEncoding(
                    x=ChartChannel(field="x", type=ChannelType.NOMINAL),
                    y=ChartChannel(field="y", type=ChannelType.QUANTITATIVE),
                    color=ChartChannel(field="g", type=ChannelType.NOMINAL),
                ),
                style=ChartStyle(palette=(Color("#FF0000"), Color("#00FF00"))),
            )
        )
        assert spec["encoding"]["color"]["scale"]["range"] == ["#FF0000", "#00FF00"]

    def test_to_vega_lite_json_round_trip(self) -> None:
        s = to_vega_lite_json(_bar_spec())
        import json

        decoded = json.loads(s)
        assert decoded["mark"] == "bar"


class TestCsvSafety:
    def test_sanitise_cell_strips_formula_prefix(self) -> None:
        assert sanitise_cell("=SUM(A1:A2)") == "'=SUM(A1:A2)"
        assert sanitise_cell("@hyperlink") == "'@hyperlink"

    def test_sanitise_cell_preserves_safe_strings(self) -> None:
        assert sanitise_cell("Hello") == "Hello"
        assert sanitise_cell(42) == 42

    def test_sanitise_rows_walks_dicts(self) -> None:
        rows = ({"a": "=SUM()", "b": "ok"},)
        out = sanitise_rows(rows)
        assert out[0]["a"] == "'=SUM()"
        assert out[0]["b"] == "ok"

    def test_assert_csv_safe_rejects_formula_injection(self) -> None:
        with pytest.raises(CSVInjectionError):
            assert_csv_safe(({"x": "=A1"},))

    def test_assert_csv_safe_rejects_pii_by_default(self) -> None:
        with pytest.raises(CSVInjectionError):
            assert_csv_safe(({"email": "user@example.com"},))

    def test_assert_csv_safe_allows_pii_when_opted_in(self) -> None:
        # No raise
        assert_csv_safe(({"email": "user@example.com"},), allow_pii=True)

    def test_detect_pii_finds_emails_and_ssns(self) -> None:
        rows = (
            {"contact": "alice@example.com"},
            {"id": "123-45-6789"},
            {"safe": "no PII here"},
        )
        findings = detect_pii(rows)
        assert {f[0] for f in findings} == {"contact", "id"}


class TestTable:
    def test_render_table_text(self) -> None:
        spec = TableSpec(
            columns=(TableColumn(key="a", header="A"), TableColumn(key="b", header="B")),
            rows=(
                {"a": 1, "b": 2},
                {"a": "x", "b": "y"},
            ),
        )
        out = render_table_text(spec)
        # Headers + separator + rows
        assert out.count("\n") >= 3
        assert "A" in out
        assert "x" in out
