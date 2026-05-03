"""Tests for canvas types — validation, defaults, edge cases.

Maps to behaviour scenarios in agents/davinci/specs/features/. Each
TestX class corresponds to a type or enum group. Tests are real and
runnable; they exercise frozen invariants + per-construction validation.
"""

from __future__ import annotations

from dataclasses import FrozenInstanceError
from datetime import UTC, datetime
from decimal import Decimal

import pytest

from stronghold.types.canvas_design import (
    MAX_EFFECTS_PER_LAYER,
    AgeBand,
    Alignment,
    BBox,
    BindingKind,
    BlendMode,
    BrandKit,
    BrandKitFonts,
    BrandLogo,
    Budget,
    BudgetPeriod,
    BudgetScope,
    BudgetStatus,
    CanvasLearning,
    CanvasLearningScope,
    CheckResult,
    CheckScope,
    Color,
    ColorMode,
    Correction,
    CorrectionContext,
    CorrectionKind,
    CorrectionSource,
    CostForecast,
    DocumentKind,
    Effect,
    EffectKind,
    FixSuggestion,
    FontRef,
    FontWeight,
    FontWidth,
    LayerTransform,
    LayerType,
    LayoutKind,
    LearningRuleKind,
    LightingDirection,
    LineCap,
    LineJoin,
    LineWeight,
    LogoVariant,
    Mask,
    MaskOrigin,
    MoodTag,
    PreflightReport,
    PreflightSummary,
    PrintSpec,
    ReportLevel,
    ShapeKind,
    ShapeStroke,
    StrokePosition,
    StyleLock,
    TextLayout,
    TextStyle,
    TextTransform,
    VerticalAlignment,
)
from stronghold.types.errors import (
    ConfigError,
    EffectKindUnknownError,
    EffectParamsError,
)

# ───────────────────────────── Color ─────────────────────────────


class TestColor:
    def test_valid_rgb(self) -> None:
        c = Color("#FF8800")
        assert c.value == "#FF8800"
        assert not c.has_alpha

    def test_valid_rgba(self) -> None:
        c = Color("#FF880080")
        assert c.has_alpha

    def test_lowercase_hex_accepted(self) -> None:
        Color("#abcdef")

    @pytest.mark.parametrize(
        "bad",
        [
            "FF8800",  # missing #
            "#FFF",  # 3-char short form not supported
            "#GGGGGG",  # invalid hex
            "#FF88000",  # 7 chars
            "#FF880011AA",  # 10 chars
            "",
            "rgb(255,0,0)",
        ],
    )
    def test_invalid_hex_rejected(self, bad: str) -> None:
        with pytest.raises(ConfigError) as exc:
            Color(bad)
        assert exc.value.code == "COLOR_INVALID"

    def test_frozen(self) -> None:
        c = Color("#000000")
        with pytest.raises(FrozenInstanceError):
            c.value = "#FFFFFF"  # type: ignore[misc]


# ───────────────────────────── BBox ─────────────────────────────


class TestBBox:
    def test_default(self) -> None:
        b = BBox(0, 0, 100, 200)
        assert b.x == 0
        assert b.width == 100

    def test_zero_dims_allowed(self) -> None:
        BBox(0, 0, 0, 0)

    def test_negative_dims_rejected(self) -> None:
        with pytest.raises(ConfigError) as exc:
            BBox(0, 0, -1, 100)
        assert exc.value.code == "BBOX_INVALID"
        with pytest.raises(ConfigError):
            BBox(0, 0, 100, -1)


# ───────────────────────────── LayerTransform ─────────────────────────────


class TestLayerTransform:
    def test_defaults(self) -> None:
        t = LayerTransform()
        assert t.x == 0
        assert t.scale == 1.0
        assert t.rotation == 0.0

    def test_negative_scale_rejected(self) -> None:
        with pytest.raises(ConfigError):
            LayerTransform(scale=-1.0)
        with pytest.raises(ConfigError):
            LayerTransform(scale=0.0)

    @pytest.mark.parametrize("rot", [-360.0, 0.0, 360.0])
    def test_rotation_bounds_inclusive(self, rot: float) -> None:
        LayerTransform(rotation=rot)

    @pytest.mark.parametrize("rot", [-360.1, 360.1, 720.0])
    def test_rotation_out_of_range(self, rot: float) -> None:
        with pytest.raises(ConfigError):
            LayerTransform(rotation=rot)


# ───────────────────────────── Enums ─────────────────────────────


class TestEnums:
    """Smoke-test that all canvas StrEnums round-trip via their string values."""

    def test_color_mode_values(self) -> None:
        assert ColorMode("srgb") is ColorMode.SRGB
        assert ColorMode("cmyk") is ColorMode.CMYK
        assert ColorMode("grayscale") is ColorMode.GRAYSCALE

    def test_blend_mode_count(self) -> None:
        # Spec §07 promises 16 blend modes
        assert len(list(BlendMode)) == 16
        assert BlendMode.NORMAL.value == "normal"

    def test_layer_type_values(self) -> None:
        assert {m.value for m in LayerType} == {
            "raster",
            "shape",
            "text",
            "group",
            "video",
        }

    def test_age_band_values(self) -> None:
        assert AgeBand.AGE_5_7.value == "5_7"

    def test_layout_kind_count(self) -> None:
        # 15 layouts per spec §10
        assert len(list(LayoutKind)) == 15

    def test_correction_kind_count(self) -> None:
        # 20 correction kinds per spec §19
        assert len(list(CorrectionKind)) == 20

    def test_learning_rule_kind_count(self) -> None:
        # 15 rule kinds per spec §20
        assert len(list(LearningRuleKind)) == 15

    def test_shape_kind_includes_callouts_and_arrows(self) -> None:
        kinds = {m for m in ShapeKind}
        assert ShapeKind.SPEECH_BUBBLE in kinds
        assert ShapeKind.CALLOUT in kinds
        assert ShapeKind.ARROW in kinds

    def test_mood_tag_values(self) -> None:
        assert MoodTag.PLAYFUL.value == "playful"


# ───────────────────────────── Effect ─────────────────────────────


class TestEffect:
    def test_brightness_valid(self) -> None:
        e = Effect(id="e1", kind=EffectKind.BRIGHTNESS, params={"value": 0.2})
        assert e.enabled
        assert e.params["value"] == 0.2

    def test_invert_no_params(self) -> None:
        Effect(id="e2", kind=EffectKind.INVERT, params={})

    def test_disabled_default_true(self) -> None:
        e = Effect(id="e3", kind=EffectKind.SHARPEN, params={"amount": 1.0})
        assert e.enabled

    @pytest.mark.parametrize(
        ("kind", "params"),
        [
            (EffectKind.BRIGHTNESS, {"value": 5.0}),
            (EffectKind.BRIGHTNESS, {"value": -2.0}),
            (EffectKind.GAUSSIAN_BLUR, {"radius_px": -1.0}),
            (EffectKind.GAUSSIAN_BLUR, {"radius_px": 1000.0}),
            (EffectKind.HUE_SHIFT, {"degrees": 360.0}),
            (EffectKind.HUE_SHIFT, {"degrees": -181.0}),
            (EffectKind.EXPOSURE, {"stops": 10.0}),
            (EffectKind.GAMMA, {"value": 0.0}),
            (EffectKind.NOISE_ADD, {"amount": 1.5}),
            (EffectKind.VIGNETTE, {"strength": 2.0, "roundness": 0.5}),
        ],
    )
    def test_param_out_of_range(self, kind: EffectKind, params: dict[str, float]) -> None:
        with pytest.raises(EffectParamsError):
            Effect(id="x", kind=kind, params=params)

    def test_missing_required_param(self) -> None:
        with pytest.raises(EffectParamsError):
            Effect(id="x", kind=EffectKind.BRIGHTNESS, params={})

    def test_non_numeric_param_rejected(self) -> None:
        with pytest.raises(EffectParamsError):
            Effect(id="x", kind=EffectKind.BRIGHTNESS, params={"value": "loud"})

    def test_unknown_kind_in_dict_rules_raises(self) -> None:
        # We can't construct an unknown EffectKind via the enum, but we can
        # simulate the path by patching _EFFECT_PARAM_RULES via subclass; the
        # production code raises EffectKindUnknownError if the kind is missing
        # from the rules table. This is exercised when new kinds are added
        # without rules.
        from stronghold.types import canvas_design as canvas_mod

        orig = canvas_mod._EFFECT_PARAM_RULES.copy()
        try:
            canvas_mod._EFFECT_PARAM_RULES.pop(EffectKind.BRIGHTNESS)
            with pytest.raises(EffectKindUnknownError):
                Effect(id="x", kind=EffectKind.BRIGHTNESS, params={"value": 0.0})
        finally:
            canvas_mod._EFFECT_PARAM_RULES.clear()
            canvas_mod._EFFECT_PARAM_RULES.update(orig)

    def test_max_effects_constant(self) -> None:
        assert MAX_EFFECTS_PER_LAYER == 32


# ───────────────────────────── Mask ─────────────────────────────


class TestMask:
    def _make(self, **overrides: object) -> Mask:
        defaults: dict[str, object] = {
            "id": "m1",
            "width": 100,
            "height": 100,
            "data": b"\x00" * 4,
            "origin": MaskOrigin.BBOX,
        }
        defaults.update(overrides)
        return Mask(**defaults)  # type: ignore[arg-type]

    def test_valid_default(self) -> None:
        m = self._make()
        assert m.feather == 0
        assert m.invert is False
        assert m.origin is MaskOrigin.BBOX

    def test_negative_dims_rejected(self) -> None:
        with pytest.raises(ConfigError):
            self._make(width=0, height=10)
        with pytest.raises(ConfigError):
            self._make(width=10, height=-1)

    def test_negative_feather_rejected(self) -> None:
        with pytest.raises(ConfigError):
            self._make(feather=-1)

    def test_invert_default_false(self) -> None:
        assert self._make().invert is False

    @pytest.mark.parametrize(
        "origin",
        [
            MaskOrigin.BBOX,
            MaskOrigin.POLYGON,
            MaskOrigin.BRUSH,
            MaskOrigin.AUTO_SUBJECT,
            MaskOrigin.AUTO_BACKGROUND,
            MaskOrigin.PROMPT,
            MaskOrigin.UPLOADED,
        ],
    )
    def test_all_origins_accepted(self, origin: MaskOrigin) -> None:
        self._make(origin=origin)


# ───────────────────────────── TextStyle / TextLayout ─────────────────────────────


class TestTextStyle:
    def test_defaults(self) -> None:
        s = TextStyle()
        assert s.font_family == "Inter"
        assert s.font_weight is FontWeight.REGULAR
        assert s.font_width is FontWidth.NORMAL
        assert s.size_px == 48
        assert s.color.value == "#000000"
        assert s.text_transform is TextTransform.NONE

    def test_invalid_size(self) -> None:
        with pytest.raises(ConfigError):
            TextStyle(size_px=0)
        with pytest.raises(ConfigError):
            TextStyle(size_px=-1)

    def test_invalid_line_height(self) -> None:
        with pytest.raises(ConfigError):
            TextStyle(line_height=0.0)


class TestTextLayout:
    def test_defaults(self) -> None:
        layout = TextLayout()
        assert layout.alignment is Alignment.LEFT
        assert layout.vertical_alignment is VerticalAlignment.TOP
        assert layout.max_width_px is None
        assert layout.hyphenate is False

    def test_max_width_must_be_positive(self) -> None:
        with pytest.raises(ConfigError):
            TextLayout(max_width_px=0)
        with pytest.raises(ConfigError):
            TextLayout(max_width_px=-1)

    def test_max_lines_must_be_positive(self) -> None:
        with pytest.raises(ConfigError):
            TextLayout(max_lines=0)
        with pytest.raises(ConfigError):
            TextLayout(max_lines=-1)


# ───────────────────────────── Shapes ─────────────────────────────


class TestShapeStroke:
    def test_defaults(self) -> None:
        s = ShapeStroke(color=Color("#000000"))
        assert s.width == 1.0
        assert s.cap is LineCap.BUTT
        assert s.join is LineJoin.MITER
        assert s.position is StrokePosition.CENTER

    def test_negative_width_rejected(self) -> None:
        with pytest.raises(ConfigError):
            ShapeStroke(color=Color("#000000"), width=-0.01)

    def test_zero_width_allowed(self) -> None:
        ShapeStroke(color=Color("#000000"), width=0.0)


# ───────────────────────────── PrintSpec ─────────────────────────────


class TestPrintSpec:
    def test_defaults(self) -> None:
        p = PrintSpec(trim_size=(2400, 2400))
        assert p.dpi == 300
        assert p.bleed == 38
        assert p.safe_area == 75
        assert p.color_mode is ColorMode.SRGB
        assert p.binding is BindingKind.NONE

    def test_bleed_canvas_math(self) -> None:
        p = PrintSpec(trim_size=(2400, 2400), bleed=38)
        assert p.bleed_canvas == (2476, 2476)

    def test_safe_rect_math(self) -> None:
        p = PrintSpec(trim_size=(2400, 2400), safe_area=75)
        rect = p.safe_rect
        assert rect == BBox(75, 75, 2250, 2250)

    def test_safe_rect_clamps_at_zero(self) -> None:
        # Safe area larger than half of trim is clamped to 0 width/height
        p = PrintSpec(trim_size=(100, 100), safe_area=100)
        rect = p.safe_rect
        assert rect.width == 0
        assert rect.height == 0

    @pytest.mark.parametrize(
        "trim",
        [(0, 100), (100, 0), (-1, 100)],
    )
    def test_invalid_trim_rejected(self, trim: tuple[int, int]) -> None:
        with pytest.raises(ConfigError):
            PrintSpec(trim_size=trim)

    def test_invalid_dpi_rejected(self) -> None:
        with pytest.raises(ConfigError):
            PrintSpec(trim_size=(100, 100), dpi=0)

    def test_negative_bleed_rejected(self) -> None:
        with pytest.raises(ConfigError):
            PrintSpec(trim_size=(100, 100), bleed=-1)

    def test_negative_safe_area_rejected(self) -> None:
        with pytest.raises(ConfigError):
            PrintSpec(trim_size=(100, 100), safe_area=-1)


# ───────────────────────────── StyleLock ─────────────────────────────


class TestStyleLock:
    def _palette(self, n: int) -> tuple[Color, ...]:
        return tuple(Color(f"#FF00{i:02X}") for i in range(n))

    def _make(self, **overrides: object) -> StyleLock:
        defaults: dict[str, object] = {
            "id": "sl1",
            "tenant_id": "t",
            "owner_id": "u",
            "name": "warrior-knight",
            "rendering_style_prompt": "watercolour, soft, warm",
            "palette": self._palette(5),
        }
        defaults.update(overrides)
        return StyleLock(**defaults)  # type: ignore[arg-type]

    def test_defaults(self) -> None:
        s = self._make()
        assert s.line_weight is LineWeight.MEDIUM
        assert s.lighting is LightingDirection.NATURAL
        assert s.mood is MoodTag.PLAYFUL
        assert s.drift_threshold == 0.25
        assert s.version == 1
        assert s.lora_id is None

    @pytest.mark.parametrize("n", [3, 4, 5, 6, 7])
    def test_palette_size_3_to_7_ok(self, n: int) -> None:
        self._make(palette=self._palette(n))

    @pytest.mark.parametrize("n", [0, 1, 2, 8, 12])
    def test_palette_size_invalid(self, n: int) -> None:
        with pytest.raises(ConfigError):
            self._make(palette=self._palette(n))

    @pytest.mark.parametrize("threshold", [-0.01, 1.01])
    def test_drift_threshold_bounds(self, threshold: float) -> None:
        with pytest.raises(ConfigError):
            self._make(drift_threshold=threshold)

    def test_version_must_be_positive(self) -> None:
        with pytest.raises(ConfigError):
            self._make(version=0)


# ───────────────────────────── BrandKit ─────────────────────────────


class TestBrandKit:
    def _fonts(self) -> BrandKitFonts:
        return BrandKitFonts(
            display=FontRef(family="Playfair", weight=FontWeight.BOLD),
            body=FontRef(family="Atkinson Hyperlegible"),
        )

    def _palette(self, n: int) -> tuple[Color, ...]:
        return tuple(Color(f"#0F00{i:02X}") for i in range(n))

    def _make(self, **overrides: object) -> BrandKit:
        defaults: dict[str, object] = {
            "id": "bk1",
            "tenant_id": "t",
            "owner_id": "u",
            "name": "Acme",
            "palette": self._palette(5),
            "fonts": self._fonts(),
        }
        defaults.update(overrides)
        return BrandKit(**defaults)  # type: ignore[arg-type]

    def test_defaults(self) -> None:
        kit = self._make()
        assert kit.spacing_unit == 8
        assert kit.voice_prompt == ""
        assert kit.logos == ()

    def test_palette_bounds(self) -> None:
        with pytest.raises(ConfigError):
            self._make(palette=self._palette(2))
        with pytest.raises(ConfigError):
            self._make(palette=self._palette(8))

    def test_spacing_must_be_positive(self) -> None:
        with pytest.raises(ConfigError):
            self._make(spacing_unit=0)

    def test_logos_can_have_variants(self) -> None:
        logo_a = BrandLogo(blob_id="b1", variant=LogoVariant.PRIMARY)
        logo_b = BrandLogo(blob_id="b2", variant=LogoVariant.MONOCHROME)
        kit = self._make(logos=(logo_a, logo_b))
        assert len(kit.logos) == 2


# ───────────────────────────── Correction ─────────────────────────────


class TestCorrection:
    def _ctx(self) -> CorrectionContext:
        return CorrectionContext(doc_kind=DocumentKind.PICTURE_BOOK, age_band=AgeBand.AGE_5_7)

    def _make(self, **overrides: object) -> Correction:
        defaults: dict[str, object] = {
            "id": "c1",
            "tenant_id": "t",
            "user_id": "u",
            "document_id": "d",
            "page_id": "p",
            "session_id": "s",
            "kind": CorrectionKind.FONT_CHANGE,
            "source": CorrectionSource.DIRECT_MANIP,
            "before": {"font": "Comic Sans"},
            "after": {"font": "Atkinson Hyperlegible"},
            "context": self._ctx(),
        }
        defaults.update(overrides)
        return Correction(**defaults)  # type: ignore[arg-type]

    def test_defaults(self) -> None:
        c = self._make()
        assert c.layer_id is None
        assert c.signal_strength == 1.0
        assert c.reverted is False
        assert isinstance(c.timestamp, datetime)

    @pytest.mark.parametrize("strength", [0.1, 1.0, 2.0])
    def test_signal_bounds_inclusive(self, strength: float) -> None:
        self._make(signal_strength=strength)

    @pytest.mark.parametrize("strength", [0.0, 0.05, 2.01, -1.0])
    def test_signal_out_of_range(self, strength: float) -> None:
        with pytest.raises(ConfigError):
            self._make(signal_strength=strength)


# ───────────────────────────── CanvasLearning ─────────────────────────────


class TestCanvasLearning:
    def _make(self, **overrides: object) -> CanvasLearning:
        defaults: dict[str, object] = {
            "id": "l1",
            "tenant_id": "t",
            "rule_kind": LearningRuleKind.PREFER_FONT_FAMILY,
            "rule_data": {"family": "Atkinson Hyperlegible"},
            "scope": CanvasLearningScope.USER,
        }
        defaults.update(overrides)
        return CanvasLearning(**defaults)  # type: ignore[arg-type]

    def test_defaults(self) -> None:
        learning = self._make()
        assert learning.confidence == 0.5
        assert learning.weight == 1.0
        assert learning.hit_count == 1
        assert learning.pinned is False

    @pytest.mark.parametrize("conf", [-0.01, 1.01])
    def test_confidence_bounds(self, conf: float) -> None:
        with pytest.raises(ConfigError):
            self._make(confidence=conf)

    @pytest.mark.parametrize("weight", [-0.01, 1.01])
    def test_weight_bounds(self, weight: float) -> None:
        with pytest.raises(ConfigError):
            self._make(weight=weight)

    def test_hit_count_minimum(self) -> None:
        with pytest.raises(ConfigError):
            self._make(hit_count=0)


# ───────────────────────────── Cost / Budget ─────────────────────────────


class TestCostForecast:
    def test_defaults(self) -> None:
        f = CostForecast(
            action="generate",
            selected_model="flux-schnell",
            estimated_cost_usd=Decimal("0.04"),
        )
        assert f.cache_hit is False
        assert f.estimated_tokens_in == 0

    def test_negative_cost_rejected(self) -> None:
        with pytest.raises(ConfigError):
            CostForecast(
                action="x",
                selected_model="x",
                estimated_cost_usd=Decimal("-1"),
            )

    def test_cache_hit_zero_cost_allowed(self) -> None:
        # Cache hit forecasts use zero cost
        f = CostForecast(
            action="generate",
            selected_model="flux-schnell",
            estimated_cost_usd=Decimal("0"),
            cache_hit=True,
        )
        assert f.cache_hit is True
        assert f.estimated_cost_usd == Decimal("0")


class TestBudget:
    def _make(self, **overrides: object) -> Budget:
        defaults: dict[str, object] = {
            "id": "b1",
            "scope": BudgetScope.USER,
            "scope_id": "u1",
            "period": BudgetPeriod.DAILY,
            "cap_usd": Decimal("5.00"),
        }
        defaults.update(overrides)
        return Budget(**defaults)  # type: ignore[arg-type]

    def test_defaults(self) -> None:
        b = self._make()
        assert b.warn_at_pct == 80
        assert b.hard_block is True

    def test_cap_must_be_positive(self) -> None:
        with pytest.raises(ConfigError):
            self._make(cap_usd=Decimal("0"))
        with pytest.raises(ConfigError):
            self._make(cap_usd=Decimal("-1"))

    @pytest.mark.parametrize("pct", [-1, 101, 200])
    def test_warn_pct_bounds(self, pct: int) -> None:
        with pytest.raises(ConfigError):
            self._make(warn_at_pct=pct)

    def test_status_enum_values(self) -> None:
        assert {s.value for s in BudgetStatus} == {"ok", "warn", "blocked"}


# ───────────────────────────── Pre-flight ─────────────────────────────


class TestPreflight:
    def test_check_result_default_optional_fields(self) -> None:
        cr = CheckResult(
            rule_id="text_in_safe_area",
            scope=CheckScope.LAYER,
            level=ReportLevel.FAIL,
            message="Text crosses safe-area boundary",
        )
        assert cr.scope_id == ""
        assert cr.detail == {}
        assert cr.fix_suggestion is None

    def test_check_result_with_fix(self) -> None:
        fix = FixSuggestion(action="transform_layer", arguments={"x": 100}, reasoning="...")
        cr = CheckResult(
            rule_id="text_in_safe_area",
            scope=CheckScope.LAYER,
            level=ReportLevel.FAIL,
            message="...",
            fix_suggestion=fix,
        )
        assert cr.fix_suggestion is fix

    def test_summary_fields(self) -> None:
        s = PreflightSummary(total=10, ok=7, warnings=2, failures=1)
        assert s.total == 10

    def test_report_includes_checks_and_summary(self) -> None:
        r = PreflightReport(
            document_id="d1",
            level=ReportLevel.WARN,
            checks=(),
            summary=PreflightSummary(total=0, ok=0, warnings=0, failures=0),
        )
        assert r.level is ReportLevel.WARN
        assert isinstance(r.generated_at, datetime)
        assert r.generated_at.tzinfo is UTC


# ───────────────────────────── Frozen invariant smoke ─────────────────────────────


class TestFrozen:
    """All canvas dataclasses are frozen — mutation raises."""

    def test_color_frozen(self) -> None:
        c = Color("#000000")
        with pytest.raises(FrozenInstanceError):
            c.value = "#FFFFFF"  # type: ignore[misc]

    def test_bbox_frozen(self) -> None:
        b = BBox(0, 0, 1, 1)
        with pytest.raises(FrozenInstanceError):
            b.x = 99  # type: ignore[misc]

    def test_layer_transform_frozen(self) -> None:
        t = LayerTransform()
        with pytest.raises(FrozenInstanceError):
            t.scale = 2.0  # type: ignore[misc]

    def test_text_style_frozen(self) -> None:
        s = TextStyle()
        with pytest.raises(FrozenInstanceError):
            s.size_px = 24  # type: ignore[misc]

    def test_print_spec_frozen(self) -> None:
        p = PrintSpec(trim_size=(100, 100))
        with pytest.raises(FrozenInstanceError):
            p.dpi = 72  # type: ignore[misc]

    def test_font_ref_frozen(self) -> None:
        f = FontRef(family="Inter")
        with pytest.raises(FrozenInstanceError):
            f.family = "Roboto"  # type: ignore[misc]
