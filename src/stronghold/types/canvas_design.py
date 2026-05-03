"""Canvas Studio design-time types — Da Vinci spec contracts.

Companion to `stronghold.types.canvas`, which holds the OPERATIONAL records
(CanvasRecord/LayerRecord/GenerationJobRecord/etc.) used by the existing
runtime canvas tool. This module holds DESIGN-time contracts derived from
the 33-spec system in `agents/davinci/specs/`:

  - Layer/Effect/Mask/Shape/Text data model (specs §01, §03, §05, §06)
  - PrintSpec / Document model bits (specs §02, §08)
  - StyleLock / BrandKit (specs §09, §11)
  - Correction / CanvasLearning (specs §19, §20)
  - CostForecast / Budget (spec §31)
  - PreflightReport / CheckResult (spec §22)

Every type is frozen and validated at construction. No runtime dependencies
on Pillow / numpy — pure data types so they can be imported anywhere.

Spec cross-refs noted at each section; see agents/davinci/specs/ for full
design docs and agents/davinci/specs/features/ for behaviour scenarios.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import StrEnum
from typing import TYPE_CHECKING, Any

from stronghold.types.errors import (
    ConfigError,
    EffectKindUnknownError,
    EffectParamsError,
)

if TYPE_CHECKING:
    from decimal import Decimal

# ---------------------------------------------------------------------------
# Common primitives
# ---------------------------------------------------------------------------

_HEX_COLOR_RE = re.compile(r"^#(?:[0-9A-Fa-f]{6}|[0-9A-Fa-f]{8})$")


class ColorMode(StrEnum):
    """Page colour-mode for print + screen output (spec §08)."""

    SRGB = "srgb"
    CMYK = "cmyk"
    GRAYSCALE = "grayscale"


class BlendMode(StrEnum):
    """Layer composite blend modes (spec §07)."""

    NORMAL = "normal"
    MULTIPLY = "multiply"
    SCREEN = "screen"
    OVERLAY = "overlay"
    SOFT_LIGHT = "soft_light"
    HARD_LIGHT = "hard_light"
    DARKEN = "darken"
    LIGHTEN = "lighten"
    DIFFERENCE = "difference"
    EXCLUSION = "exclusion"
    COLOR_DODGE = "color_dodge"
    COLOR_BURN = "color_burn"
    HUE = "hue"
    SATURATION = "saturation"
    COLOR = "color"
    LUMINOSITY = "luminosity"


class LayerType(StrEnum):
    """Discriminator for Layer.source variants (spec §01)."""

    RASTER = "raster"
    SHAPE = "shape"
    TEXT = "text"
    GROUP = "group"
    VIDEO = "video"


@dataclass(frozen=True)
class Color:
    """RGB(A) colour as #RRGGBB or #RRGGBBAA hex."""

    value: str

    def __post_init__(self) -> None:
        if not _HEX_COLOR_RE.match(self.value):
            raise ConfigError(
                f"invalid hex colour: {self.value!r} (expected #RRGGBB or #RRGGBBAA)",
                code="COLOR_INVALID",
            )

    @property
    def has_alpha(self) -> bool:
        """True for 8-character #RRGGBBAA values."""
        return len(self.value) == 9


@dataclass(frozen=True)
class BBox:
    """Axis-aligned bounding box in pixels."""

    x: int
    y: int
    width: int
    height: int

    def __post_init__(self) -> None:
        if self.width < 0 or self.height < 0:
            raise ConfigError(
                f"BBox dims must be non-negative: width={self.width}, height={self.height}",
                code="BBOX_INVALID",
            )


@dataclass(frozen=True)
class LayerTransform:
    """Position / scale / rotation in page coordinates."""

    x: int = 0
    y: int = 0
    scale: float = 1.0
    rotation: float = 0.0  # degrees, [-360, 360]

    def __post_init__(self) -> None:
        if self.scale <= 0:
            raise ConfigError(f"scale must be > 0, got {self.scale}", code="TRANSFORM_INVALID")
        if not -360.0 <= self.rotation <= 360.0:
            raise ConfigError(
                f"rotation must be in [-360, 360], got {self.rotation}",
                code="TRANSFORM_INVALID",
            )


# ---------------------------------------------------------------------------
# Effects (spec §01)
# ---------------------------------------------------------------------------


class EffectKind(StrEnum):
    """Non-destructive effects on a Layer's effect stack."""

    # Adjustments (P2 minimum, spec §07)
    BRIGHTNESS = "brightness"
    CONTRAST = "contrast"
    SATURATION = "saturation"
    HUE_SHIFT = "hue_shift"
    EXPOSURE = "exposure"
    GAMMA = "gamma"
    INVERT = "invert"
    # Filters
    GAUSSIAN_BLUR = "gaussian_blur"
    MOTION_BLUR = "motion_blur"
    SHARPEN = "sharpen"
    UNSHARP_MASK = "unsharp_mask"
    NOISE_ADD = "noise_add"
    VIGNETTE = "vignette"
    PIXELATE = "pixelate"
    # Layer styles
    DROP_SHADOW = "drop_shadow"
    INNER_SHADOW = "inner_shadow"
    OUTER_GLOW = "outer_glow"
    INNER_GLOW = "inner_glow"
    STROKE = "stroke"
    GRADIENT_OVERLAY = "gradient_overlay"
    COLOR_OVERLAY = "color_overlay"


# Per-kind param schema: required keys + numeric ranges (inclusive).
# Used by Effect.__post_init__ to validate params at construction time.
_EFFECT_PARAM_RULES: dict[EffectKind, dict[str, tuple[float, float]]] = {
    EffectKind.BRIGHTNESS: {"value": (-1.0, 1.0)},
    EffectKind.CONTRAST: {"value": (-1.0, 1.0)},
    EffectKind.SATURATION: {"value": (-1.0, 1.0)},
    EffectKind.HUE_SHIFT: {"degrees": (-180.0, 180.0)},
    EffectKind.EXPOSURE: {"stops": (-3.0, 3.0)},
    EffectKind.GAMMA: {"value": (0.1, 5.0)},
    EffectKind.INVERT: {},
    EffectKind.GAUSSIAN_BLUR: {"radius_px": (0.0, 100.0)},
    EffectKind.MOTION_BLUR: {"radius_px": (0.0, 100.0), "angle": (-360.0, 360.0)},
    EffectKind.SHARPEN: {"amount": (0.0, 5.0)},
    EffectKind.UNSHARP_MASK: {"radius_px": (0.0, 100.0), "amount": (0.0, 5.0)},
    EffectKind.NOISE_ADD: {"amount": (0.0, 1.0)},
    EffectKind.VIGNETTE: {"strength": (0.0, 1.0), "roundness": (0.0, 1.0)},
    EffectKind.PIXELATE: {"size_px": (1.0, 256.0)},
    EffectKind.DROP_SHADOW: {"dx": (-500.0, 500.0), "dy": (-500.0, 500.0)},
    EffectKind.INNER_SHADOW: {"dx": (-500.0, 500.0), "dy": (-500.0, 500.0)},
    EffectKind.OUTER_GLOW: {"blur": (0.0, 100.0)},
    EffectKind.INNER_GLOW: {"blur": (0.0, 100.0)},
    EffectKind.STROKE: {"width": (0.0, 100.0)},
    EffectKind.GRADIENT_OVERLAY: {},
    EffectKind.COLOR_OVERLAY: {},
}

MAX_EFFECTS_PER_LAYER = 32


@dataclass(frozen=True)
class Effect:
    """A single non-destructive effect entry (spec §01)."""

    id: str
    kind: EffectKind
    params: dict[str, Any] = field(default_factory=dict)
    enabled: bool = True

    def __post_init__(self) -> None:
        rules = _EFFECT_PARAM_RULES.get(self.kind)
        if rules is None:
            raise EffectKindUnknownError(f"unknown effect kind: {self.kind}")
        for key, (lo, hi) in rules.items():
            if key not in self.params:
                raise EffectParamsError(f"effect {self.kind.value} missing required param {key!r}")
            value = self.params[key]
            if not isinstance(value, int | float):
                raise EffectParamsError(
                    f"effect {self.kind.value} param {key!r} must be numeric, "
                    f"got {type(value).__name__}"
                )
            if not lo <= float(value) <= hi:
                raise EffectParamsError(
                    f"effect {self.kind.value} param {key!r}={value} outside [{lo}, {hi}]"
                )


# ---------------------------------------------------------------------------
# Masks (spec §03)
# ---------------------------------------------------------------------------


class MaskOrigin(StrEnum):
    """How a mask was generated."""

    BBOX = "bbox"
    POLYGON = "polygon"
    BRUSH = "brush"
    AUTO_SUBJECT = "auto_subject"
    AUTO_BACKGROUND = "auto_background"
    PROMPT = "prompt"
    UPLOADED = "uploaded"


@dataclass(frozen=True)
class Mask:
    """Greyscale alpha mask (spec §03)."""

    id: str
    width: int
    height: int
    data: bytes  # PNG single-channel L mode
    origin: MaskOrigin
    feather: int = 0
    invert: bool = False
    metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if self.width <= 0 or self.height <= 0:
            raise ConfigError(
                f"mask dims must be > 0, got {self.width}x{self.height}",
                code="MASK_DIMS_INVALID",
            )
        if self.feather < 0:
            raise ConfigError(
                f"mask feather must be >= 0, got {self.feather}",
                code="MASK_FEATHER_INVALID",
            )


# ---------------------------------------------------------------------------
# Text (spec §05)
# ---------------------------------------------------------------------------


class FontWeight(StrEnum):
    THIN = "thin"
    EXTRA_LIGHT = "extra_light"
    LIGHT = "light"
    REGULAR = "regular"
    MEDIUM = "medium"
    SEMI_BOLD = "semi_bold"
    BOLD = "bold"
    EXTRA_BOLD = "extra_bold"
    BLACK = "black"


class FontWidth(StrEnum):
    CONDENSED = "condensed"
    NORMAL = "normal"
    EXPANDED = "expanded"


class TextTransform(StrEnum):
    NONE = "none"
    UPPERCASE = "uppercase"
    LOWERCASE = "lowercase"
    TITLECASE = "titlecase"


class Alignment(StrEnum):
    LEFT = "left"
    CENTER = "center"
    RIGHT = "right"
    JUSTIFY = "justify"


class VerticalAlignment(StrEnum):
    TOP = "top"
    MIDDLE = "middle"
    BOTTOM = "bottom"


@dataclass(frozen=True)
class TextStyle:
    """Glyph-level style for a text layer (spec §05)."""

    font_family: str = "Inter"
    font_weight: FontWeight = FontWeight.REGULAR
    font_width: FontWidth = FontWidth.NORMAL
    font_slant: float = 0.0
    size_px: int = 48
    color: Color = field(default_factory=lambda: Color("#000000"))
    letter_spacing: float = 0.0
    word_spacing: float = 0.0
    line_height: float = 1.2
    underline: bool = False
    strikethrough: bool = False
    text_transform: TextTransform = TextTransform.NONE
    fill_image_id: str | None = None

    def __post_init__(self) -> None:
        if self.size_px <= 0:
            raise ConfigError(f"size_px must be > 0, got {self.size_px}", code="TEXT_SIZE_INVALID")
        if self.line_height <= 0:
            raise ConfigError(
                f"line_height must be > 0, got {self.line_height}", code="TEXT_LINE_HEIGHT_INVALID"
            )


@dataclass(frozen=True)
class TextLayout:
    """Block-level layout for a text layer (spec §05)."""

    alignment: Alignment = Alignment.LEFT
    vertical_alignment: VerticalAlignment = VerticalAlignment.TOP
    max_width_px: int | None = None
    max_lines: int | None = None
    hyphenate: bool = False
    on_path_id: str | None = None

    def __post_init__(self) -> None:
        if self.max_width_px is not None and self.max_width_px <= 0:
            raise ConfigError(
                f"max_width_px must be > 0, got {self.max_width_px}",
                code="TEXT_LAYOUT_INVALID",
            )
        if self.max_lines is not None and self.max_lines <= 0:
            raise ConfigError(
                f"max_lines must be > 0, got {self.max_lines}",
                code="TEXT_LAYOUT_INVALID",
            )


# ---------------------------------------------------------------------------
# Shapes (spec §06)
# ---------------------------------------------------------------------------


class ShapeKind(StrEnum):
    RECTANGLE = "rectangle"
    ELLIPSE = "ellipse"
    LINE = "line"
    POLYLINE = "polyline"
    POLYGON = "polygon"
    PATH = "path"
    ARROW = "arrow"
    STAR = "star"
    SPEECH_BUBBLE = "speech_bubble"
    CALLOUT = "callout"
    RIBBON = "ribbon"
    BANNER = "banner"


class LineCap(StrEnum):
    BUTT = "butt"
    ROUND = "round"
    SQUARE = "square"


class LineJoin(StrEnum):
    MITER = "miter"
    ROUND = "round"
    BEVEL = "bevel"


class StrokePosition(StrEnum):
    INSIDE = "inside"
    CENTER = "center"
    OUTSIDE = "outside"


@dataclass(frozen=True)
class ShapeStroke:
    """Stroke properties for a shape (spec §06)."""

    color: Color
    width: float = 1.0
    dash_pattern: tuple[float, ...] = ()
    cap: LineCap = LineCap.BUTT
    join: LineJoin = LineJoin.MITER
    position: StrokePosition = StrokePosition.CENTER

    def __post_init__(self) -> None:
        if self.width < 0:
            raise ConfigError(
                f"stroke width must be >= 0, got {self.width}",
                code="STROKE_WIDTH_INVALID",
            )


# ---------------------------------------------------------------------------
# Print spec & document (specs §02, §08)
# ---------------------------------------------------------------------------


class BindingKind(StrEnum):
    NONE = "none"
    SADDLE_STITCH = "saddle_stitch"
    PERFECT = "perfect"
    SPIRAL = "spiral"
    HARDCOVER = "hardcover"


class DocumentKind(StrEnum):
    PICTURE_BOOK = "picture_book"
    EARLY_READER = "early_reader"
    POSTER = "poster"
    INFOGRAPHIC = "infographic"
    OPEN_CANVAS = "open_canvas"
    VIDEO_OVERLAY = "video_overlay"


class AgeBand(StrEnum):
    AGE_0_3 = "0_3"
    AGE_3_5 = "3_5"
    AGE_5_7 = "5_7"
    AGE_7_9 = "7_9"
    AGE_9_12 = "9_12"
    TEEN = "teen"
    GENERAL = "general"


@dataclass(frozen=True)
class PrintSpec:
    """Per-Page print specification (spec §08)."""

    trim_size: tuple[int, int]
    dpi: int = 300
    bleed: int = 38
    safe_area: int = 75
    color_mode: ColorMode = ColorMode.SRGB
    icc_profile: str | None = None
    binding: BindingKind = BindingKind.NONE

    def __post_init__(self) -> None:
        w, h = self.trim_size
        if w <= 0 or h <= 0:
            raise ConfigError(
                f"trim_size must be positive, got {self.trim_size}",
                code="PRINT_SPEC_INVALID",
            )
        if self.dpi <= 0:
            raise ConfigError(f"dpi must be > 0, got {self.dpi}", code="PRINT_SPEC_INVALID")
        if self.bleed < 0 or self.safe_area < 0:
            raise ConfigError("bleed and safe_area must be >= 0", code="PRINT_SPEC_INVALID")

    @property
    def bleed_canvas(self) -> tuple[int, int]:
        """Outer canvas dims = trim + 2 × bleed each side."""
        w, h = self.trim_size
        return (w + 2 * self.bleed, h + 2 * self.bleed)

    @property
    def safe_rect(self) -> BBox:
        """Inner safe area as a BBox in trim coordinates."""
        w, h = self.trim_size
        return BBox(
            x=self.safe_area,
            y=self.safe_area,
            width=max(0, w - 2 * self.safe_area),
            height=max(0, h - 2 * self.safe_area),
        )


# ---------------------------------------------------------------------------
# Style lock (spec §09)
# ---------------------------------------------------------------------------


class LineWeight(StrEnum):
    FINE = "fine"
    MEDIUM = "medium"
    BOLD = "bold"
    MIXED = "mixed"


class LightingDirection(StrEnum):
    NATURAL = "natural"
    DRAMATIC = "dramatic"
    FLAT = "flat"
    RIM = "rim"
    NONE = "none"


class MoodTag(StrEnum):
    PLAYFUL = "playful"
    EPIC = "epic"
    QUIET = "quiet"
    DARK = "dark"
    BRIGHT = "bright"
    DREAMY = "dreamy"
    GRITTY = "gritty"


@dataclass(frozen=True)
class StyleLock:
    """Cross-page art-direction constraint (spec §09)."""

    id: str
    tenant_id: str
    owner_id: str
    name: str
    rendering_style_prompt: str
    palette: tuple[Color, ...]
    line_weight: LineWeight = LineWeight.MEDIUM
    lighting: LightingDirection = LightingDirection.NATURAL
    mood: MoodTag = MoodTag.PLAYFUL
    document_id: str | None = None
    reference_image_blob_id: str | None = None
    reference_palette_extracted: bool = False
    lora_id: str | None = None
    drift_threshold: float = 0.25
    version: int = 1
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    updated_at: datetime = field(default_factory=lambda: datetime.now(UTC))

    def __post_init__(self) -> None:
        if not 3 <= len(self.palette) <= 7:
            raise ConfigError(
                f"palette must contain 3..7 colours, got {len(self.palette)}",
                code="STYLE_LOCK_PALETTE_INVALID",
            )
        if not 0.0 <= self.drift_threshold <= 1.0:
            raise ConfigError(
                f"drift_threshold must be in [0,1], got {self.drift_threshold}",
                code="STYLE_LOCK_THRESHOLD_INVALID",
            )
        if self.version < 1:
            raise ConfigError(
                f"version must be >= 1, got {self.version}", code="STYLE_LOCK_VERSION_INVALID"
            )


# ---------------------------------------------------------------------------
# Brand kit (spec §11)
# ---------------------------------------------------------------------------


class LogoVariant(StrEnum):
    PRIMARY = "primary"
    SECONDARY = "secondary"
    MONOCHROME = "monochrome"
    ICON = "icon"


@dataclass(frozen=True)
class FontRef:
    """Reference to a registered font."""

    family: str
    weight: FontWeight = FontWeight.REGULAR
    width: FontWidth = FontWidth.NORMAL


@dataclass(frozen=True)
class BrandKitFonts:
    """Font roles within a BrandKit."""

    display: FontRef
    body: FontRef
    mono: FontRef | None = None
    decorative: FontRef | None = None


@dataclass(frozen=True)
class BrandLogo:
    blob_id: str
    variant: LogoVariant = LogoVariant.PRIMARY
    color_mode: ColorMode = ColorMode.SRGB


@dataclass(frozen=True)
class BrandKit:
    """Tenant-scoped palette + fonts + logos (spec §11)."""

    id: str
    tenant_id: str
    owner_id: str
    name: str
    palette: tuple[Color, ...]
    fonts: BrandKitFonts
    logos: tuple[BrandLogo, ...] = ()
    voice_prompt: str = ""
    spacing_unit: int = 8
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    updated_at: datetime = field(default_factory=lambda: datetime.now(UTC))

    def __post_init__(self) -> None:
        if not 3 <= len(self.palette) <= 7:
            raise ConfigError(
                f"BrandKit palette must contain 3..7 colours, got {len(self.palette)}",
                code="BRAND_KIT_PALETTE_INVALID",
            )
        if self.spacing_unit <= 0:
            raise ConfigError(
                f"spacing_unit must be > 0, got {self.spacing_unit}",
                code="BRAND_KIT_SPACING_INVALID",
            )


# ---------------------------------------------------------------------------
# Layouts (spec §10)
# ---------------------------------------------------------------------------


class LayoutKind(StrEnum):
    FULL_BLEED = "full_bleed"
    ART_WITH_CAPTION = "art_with_caption"
    ART_WITH_BODY = "art_with_body"
    DOUBLE_SPREAD = "double_spread"
    TEXT_ONLY = "text_only"
    VIGNETTE = "vignette"
    COVER = "cover"
    TITLE_PAGE = "title_page"
    COPYRIGHT_PAGE = "copyright_page"
    DEDICATION_PAGE = "dedication_page"
    FRONT_MATTER = "front_matter"
    BACK_MATTER = "back_matter"
    POSTER = "poster"
    INFOGRAPHIC_GRID = "infographic_grid"
    INFOGRAPHIC_FLOW = "infographic_flow"


# ---------------------------------------------------------------------------
# Corrections (spec §19)
# ---------------------------------------------------------------------------


class CorrectionKind(StrEnum):
    TEXT_EDIT = "text_edit"
    FONT_CHANGE = "font_change"
    COLOR_CHANGE = "color_change"
    TRANSFORM_MOVE = "transform_move"
    TRANSFORM_SCALE = "transform_scale"
    TRANSFORM_ROTATE = "transform_rotate"
    REGEN_WITH_NEW_PROMPT = "regen_with_new_prompt"
    REORDER = "reorder"
    DELETE = "delete"
    REPLACE_PROP = "replace_prop"
    REPLACE_CHARACTER = "replace_character"
    EFFECT_ADD = "effect_add"
    EFFECT_REMOVE = "effect_remove"
    EFFECT_PARAMS_CHANGE = "effect_params_change"
    BLEND_MODE_CHANGE = "blend_mode_change"
    OPACITY_CHANGE = "opacity_change"
    PAGE_REORDER = "page_reorder"
    LAYOUT_APPLY = "layout_apply"
    ALT_TEXT_EDIT = "alt_text_edit"
    UNDO = "undo"


class CorrectionSource(StrEnum):
    DIRECT_MANIP = "direct_manip"
    CHAT = "chat"
    AUTO_FIX = "auto_fix"
    WIZARD = "wizard"


@dataclass(frozen=True)
class CorrectionContext:
    """Surrounding state captured at correction time (spec §19)."""

    doc_kind: DocumentKind
    age_band: AgeBand | None = None
    brand_kit_id: str | None = None
    style_lock_id: str | None = None
    page_kind: str = ""
    surrounding_layer_kinds: tuple[str, ...] = ()
    prior_corrections_in_session: int = 0


_SIGNAL_LOW = 0.1
_SIGNAL_HIGH = 2.0


@dataclass(frozen=True)
class Correction:
    """A user-attributable change captured for learning (spec §19)."""

    id: str
    tenant_id: str
    user_id: str
    document_id: str
    page_id: str
    session_id: str
    kind: CorrectionKind
    source: CorrectionSource
    before: dict[str, Any]
    after: dict[str, Any]
    context: CorrectionContext
    layer_id: str | None = None
    inferred_intent: str = ""
    signal_strength: float = 1.0
    reverted: bool = False
    reverted_at: datetime | None = None
    timestamp: datetime = field(default_factory=lambda: datetime.now(UTC))
    agent_version_id: str = ""

    def __post_init__(self) -> None:
        if not _SIGNAL_LOW <= self.signal_strength <= _SIGNAL_HIGH:
            raise ConfigError(
                f"signal_strength must be in [{_SIGNAL_LOW}, {_SIGNAL_HIGH}], "
                f"got {self.signal_strength}",
                code="CORRECTION_SIGNAL_INVALID",
            )


# ---------------------------------------------------------------------------
# Learning (spec §20) — extends existing Stronghold Learning model
# ---------------------------------------------------------------------------


class LearningRuleKind(StrEnum):
    PREFER_FONT_FAMILY = "prefer_font_family"
    PREFER_PALETTE_COLOR = "prefer_palette_color"
    PREFER_FONT_WEIGHT = "prefer_font_weight"
    PREFER_TEXT_TRANSFORM = "prefer_text_transform"
    PREFER_LAYOUT = "prefer_layout"
    PREFER_ASSET_VARIANT = "prefer_asset_variant"
    PREFER_PROMPT_SUFFIX = "prefer_prompt_suffix"
    PREFER_BLEND_MODE = "prefer_blend_mode"
    AVOID_FONT_FAMILY = "avoid_font_family"
    AVOID_PALETTE_COLOR = "avoid_palette_color"
    AVOID_PROMPT_TERMS = "avoid_prompt_terms"
    CHARACTER_REFINEMENT = "character_refinement"
    STYLE_LOCK_DRIFT = "style_lock_drift"
    REQUIRES_BRAND_KIT_USE = "requires_brand_kit_use"
    REQUIRES_ACCESSIBILITY_FONT = "requires_accessibility_font"


class CanvasLearningScope(StrEnum):
    """Canvas-domain Learning scopes (extends Stronghold's MemoryScope)."""

    TENANT = "tenant"
    USER = "user"
    DOCUMENT = "document"
    ASSET = "asset"


@dataclass(frozen=True)
class CanvasLearning:
    """A promoted preference derived from Corrections (spec §20).

    Distinct from `stronghold.types.memory.Learning` (which is general
    fail→succeed pattern from tool history); CanvasLearning is taste/style
    focused and produced by §30 critics.
    """

    id: str
    tenant_id: str
    rule_kind: LearningRuleKind
    rule_data: dict[str, Any]
    scope: CanvasLearningScope
    confidence: float = 0.5
    weight: float = 1.0
    hit_count: int = 1
    user_id: str | None = None
    document_id: str | None = None
    asset_id: str | None = None
    pinned: bool = False
    contradicts: tuple[str, ...] = ()
    evidence: tuple[str, ...] = ()
    last_reinforced_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))

    def __post_init__(self) -> None:
        if not 0.0 <= self.confidence <= 1.0:
            raise ConfigError(
                f"confidence must be in [0, 1], got {self.confidence}",
                code="LEARNING_CONFIDENCE_INVALID",
            )
        if not 0.0 <= self.weight <= 1.0:
            raise ConfigError(
                f"weight must be in [0, 1], got {self.weight}",
                code="LEARNING_WEIGHT_INVALID",
            )
        if self.hit_count < 1:
            raise ConfigError(
                f"hit_count must be >= 1, got {self.hit_count}",
                code="LEARNING_HIT_COUNT_INVALID",
            )


# ---------------------------------------------------------------------------
# Cost & budget (spec §31)
# ---------------------------------------------------------------------------


class BudgetScope(StrEnum):
    USER = "user"
    DOCUMENT = "document"
    TENANT = "tenant"


class BudgetPeriod(StrEnum):
    DAILY = "daily"
    MONTHLY = "monthly"
    LIFETIME = "lifetime"


class BudgetStatus(StrEnum):
    OK = "ok"
    WARN = "warn"
    BLOCKED = "blocked"


@dataclass(frozen=True)
class CostForecast:
    """Pre-call cost prediction (spec §31)."""

    action: str
    selected_model: str
    estimated_cost_usd: Decimal
    estimated_tokens_in: int = 0
    estimated_tokens_out: int = 0
    estimated_pixels: int = 0
    estimated_duration_seconds: int = 0
    cache_hit: bool = False

    def __post_init__(self) -> None:
        if self.estimated_cost_usd < 0:
            raise ConfigError(
                f"estimated_cost_usd must be >= 0, got {self.estimated_cost_usd}",
                code="COST_FORECAST_INVALID",
            )


@dataclass(frozen=True)
class Budget:
    """Per-scope cap with optional hard block (spec §31)."""

    id: str
    scope: BudgetScope
    scope_id: str
    period: BudgetPeriod
    cap_usd: Decimal
    warn_at_pct: int = 80
    hard_block: bool = True
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    updated_at: datetime = field(default_factory=lambda: datetime.now(UTC))

    def __post_init__(self) -> None:
        if self.cap_usd <= 0:
            raise ConfigError(f"cap_usd must be > 0, got {self.cap_usd}", code="BUDGET_CAP_INVALID")
        if not 0 <= self.warn_at_pct <= 100:
            raise ConfigError(
                f"warn_at_pct must be in [0, 100], got {self.warn_at_pct}",
                code="BUDGET_WARN_INVALID",
            )


# ---------------------------------------------------------------------------
# Pre-flight (spec §22)
# ---------------------------------------------------------------------------


class ReportLevel(StrEnum):
    OK = "ok"
    WARN = "warn"
    FAIL = "fail"


class CheckScope(StrEnum):
    DOCUMENT = "document"
    PAGE = "page"
    LAYER = "layer"


@dataclass(frozen=True)
class FixSuggestion:
    """Machine-applicable fix for a preflight finding (spec §22)."""

    action: str
    arguments: dict[str, Any]
    reasoning: str


@dataclass(frozen=True)
class CheckResult:
    rule_id: str
    scope: CheckScope
    level: ReportLevel
    message: str
    scope_id: str = ""
    detail: dict[str, Any] = field(default_factory=dict)
    fix_suggestion: FixSuggestion | None = None


@dataclass(frozen=True)
class PreflightSummary:
    total: int
    ok: int
    warnings: int
    failures: int


@dataclass(frozen=True)
class PreflightReport:
    document_id: str
    level: ReportLevel
    checks: tuple[CheckResult, ...]
    summary: PreflightSummary
    generated_at: datetime = field(default_factory=lambda: datetime.now(UTC))
