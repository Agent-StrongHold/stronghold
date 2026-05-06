"""Accessibility helpers + rules (spec §25).

WCAG contrast (AA + AAA), Daltonism (simulated colour-blind) palette
checks, age-band reading-level targets, alt-text registry, and
dyslexia-mode toggle. Pure-data: no network calls, no LLM. Production
swaps a vision-LLM alt-text generator into the Protocol shape.
"""

from __future__ import annotations

import dataclasses
from dataclasses import dataclass
from datetime import UTC, datetime
from enum import StrEnum

from stronghold.types.canvas_design import AgeBand, Color
from stronghold.types.errors import (
    AltTextRequiredError,
    ContrastFailedError,
)

# ---------------------------------------------------------------------------
# WCAG contrast
# ---------------------------------------------------------------------------


def _channel_to_linear(c: int) -> float:
    cs = c / 255.0
    if cs <= 0.03928:
        return float(cs / 12.92)
    return float(((cs + 0.055) / 1.055) ** 2.4)


def relative_luminance(rgb: tuple[int, int, int]) -> float:
    """WCAG relative luminance (linearised RGB → Y)."""
    r, g, b = rgb
    return (
        0.2126 * _channel_to_linear(r)
        + 0.7152 * _channel_to_linear(g)
        + 0.0722 * _channel_to_linear(b)
    )


def contrast_ratio(a: tuple[int, int, int], b: tuple[int, int, int]) -> float:
    la = relative_luminance(a)
    lb = relative_luminance(b)
    lighter, darker = max(la, lb), min(la, lb)
    return (lighter + 0.05) / (darker + 0.05)


class WcagLevel(StrEnum):
    FAIL = "fail"
    AA = "aa"  # 4.5:1 normal / 3:1 large
    AAA = "aaa"  # 7:1 normal / 4.5:1 large


def wcag_level(
    foreground: tuple[int, int, int],
    background: tuple[int, int, int],
    *,
    is_large_text: bool = False,
) -> WcagLevel:
    ratio = contrast_ratio(foreground, background)
    aaa_threshold = 4.5 if is_large_text else 7.0
    aa_threshold = 3.0 if is_large_text else 4.5
    if ratio >= aaa_threshold:
        return WcagLevel.AAA
    if ratio >= aa_threshold:
        return WcagLevel.AA
    return WcagLevel.FAIL


def assert_contrast(
    foreground: Color,
    background: Color,
    *,
    is_large_text: bool = False,
    require: WcagLevel = WcagLevel.AA,
) -> None:
    """Raise ContrastFailedError if the pair fails the requested level."""
    fg = _hex_to_rgb(foreground.value)
    bg = _hex_to_rgb(background.value)
    level = wcag_level(fg, bg, is_large_text=is_large_text)
    needed = (WcagLevel.AA, WcagLevel.AAA) if require is WcagLevel.AA else (WcagLevel.AAA,)
    if level not in needed:
        raise ContrastFailedError(
            f"contrast {contrast_ratio(fg, bg):.2f} fails {require.value} "
            f"({foreground.value} on {background.value})"
        )


# ---------------------------------------------------------------------------
# Daltonism (colour-blind) simulation
# ---------------------------------------------------------------------------


class DaltonismKind(StrEnum):
    DEUTERANOPIA = "deuteranopia"  # green-blind
    PROTANOPIA = "protanopia"  # red-blind
    TRITANOPIA = "tritanopia"  # blue-blind


# Brettel/Vienot/Mollon matrices (3x3 in linear sRGB; cheap approximations).
_MATRICES: dict[DaltonismKind, tuple[tuple[float, float, float], ...]] = {
    DaltonismKind.DEUTERANOPIA: (
        (0.625, 0.375, 0.0),
        (0.7, 0.3, 0.0),
        (0.0, 0.3, 0.7),
    ),
    DaltonismKind.PROTANOPIA: (
        (0.567, 0.433, 0.0),
        (0.558, 0.442, 0.0),
        (0.0, 0.242, 0.758),
    ),
    DaltonismKind.TRITANOPIA: (
        (0.95, 0.05, 0.0),
        (0.0, 0.433, 0.567),
        (0.0, 0.475, 0.525),
    ),
}


def simulate_daltonism(
    rgb: tuple[int, int, int],
    kind: DaltonismKind,
) -> tuple[int, int, int]:
    matrix = _MATRICES[kind]
    out: list[int] = []
    for row in matrix:
        v = sum(row[i] * rgb[i] for i in range(3))
        out.append(max(0, min(255, int(round(v)))))
    return (out[0], out[1], out[2])


def palette_colourblind_safe(
    palette: tuple[Color, ...],
    *,
    min_distance: float = 30.0,
) -> tuple[bool, list[tuple[int, int, DaltonismKind]]]:
    """Return (is_safe, list_of_failing_pairs).

    Each failing pair = (i, j, kind) — palette indices and the colourblind
    kind under which the pair becomes too similar.
    """
    failing: list[tuple[int, int, DaltonismKind]] = []
    palette_rgb = [_hex_to_rgb(c.value) for c in palette]
    for kind in DaltonismKind:
        simulated = [simulate_daltonism(rgb, kind) for rgb in palette_rgb]
        for i in range(len(simulated)):
            for j in range(i + 1, len(simulated)):
                d = _euclidean_rgb(simulated[i], simulated[j])
                if d < min_distance:
                    failing.append((i, j, kind))
    return (not failing), failing


# ---------------------------------------------------------------------------
# Reading level
# ---------------------------------------------------------------------------


_AGE_TARGETS: dict[AgeBand, tuple[int, int]] = {
    # (max_words_per_sentence, max_avg_word_length)
    AgeBand.AGE_0_3: (8, 5),
    AgeBand.AGE_3_5: (10, 5),
    AgeBand.AGE_5_7: (15, 6),
    AgeBand.AGE_7_9: (20, 7),
    AgeBand.AGE_9_12: (28, 8),
    AgeBand.TEEN: (40, 9),
    AgeBand.GENERAL: (40, 9),
}


@dataclass(frozen=True)
class ReadingLevelReport:
    age_band: AgeBand
    avg_words_per_sentence: float
    avg_word_length: float
    target_words_per_sentence: int
    target_word_length: int
    appropriate: bool


def assess_reading_level(text: str, age_band: AgeBand) -> ReadingLevelReport:
    sentences = [s for s in _split_sentences(text) if s.strip()]
    words = text.split()
    if not sentences or not words:
        target = _AGE_TARGETS[age_band]
        return ReadingLevelReport(
            age_band=age_band,
            avg_words_per_sentence=0.0,
            avg_word_length=0.0,
            target_words_per_sentence=target[0],
            target_word_length=target[1],
            appropriate=True,
        )
    avg_wps = len(words) / len(sentences)
    avg_wl = sum(len(w) for w in words) / len(words)
    target = _AGE_TARGETS[age_band]
    appropriate = avg_wps <= target[0] and avg_wl <= target[1]
    return ReadingLevelReport(
        age_band=age_band,
        avg_words_per_sentence=avg_wps,
        avg_word_length=avg_wl,
        target_words_per_sentence=target[0],
        target_word_length=target[1],
        appropriate=appropriate,
    )


# ---------------------------------------------------------------------------
# Alt-text registry
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class AltText:
    layer_id: str
    text: str
    user_supplied: bool
    updated_at: datetime = dataclasses.field(default_factory=lambda: datetime.now(UTC))


class InMemoryAltTextStore:
    def __init__(self) -> None:
        self._by_layer: dict[str, dict[str, AltText]] = {}

    def set(
        self,
        layer_id: str,
        text: str,
        *,
        tenant_id: str,
        user_supplied: bool = True,
    ) -> AltText:
        bucket = self._by_layer.setdefault(tenant_id, {})
        existing = bucket.get(layer_id)
        # User-supplied alt always wins over auto-generated
        if existing is not None and existing.user_supplied and not user_supplied:
            return existing
        alt = AltText(layer_id=layer_id, text=text, user_supplied=user_supplied)
        bucket[layer_id] = alt
        return alt

    def get(self, layer_id: str, *, tenant_id: str) -> AltText | None:
        return self._by_layer.get(tenant_id, {}).get(layer_id)

    def assert_present(self, layer_id: str, *, tenant_id: str) -> None:
        if self.get(layer_id, tenant_id=tenant_id) is None:
            raise AltTextRequiredError(f"layer {layer_id!r} has no alt-text")


def auto_generate_alt_text(image_summary: str) -> str:
    """Mock alt-text generator. Production path uses a vision-LLM."""
    summary = image_summary.strip() or "an illustration"
    # Strip leading "an image of"-style prefixes
    for prefix in ("an image of", "a picture of", "an illustration of"):
        if summary.lower().startswith(prefix):
            summary = summary[len(prefix) :].lstrip(", ")
    return summary


# ---------------------------------------------------------------------------
# Dyslexia mode
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class DyslexiaModeOverrides:
    """Drop-in style adjustments when dyslexia mode is enabled (spec §25)."""

    body_font_family: str = "Atkinson Hyperlegible"
    letter_spacing_em: float = 0.05
    line_height: float = 1.6
    background_color: Color = Color("#FFF8E7")  # cream
    italics_disabled: bool = True
    justify_disabled: bool = True


def dyslexia_overrides() -> DyslexiaModeOverrides:
    return DyslexiaModeOverrides()


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _hex_to_rgb(hex_str: str) -> tuple[int, int, int]:
    h = hex_str.lstrip("#")
    return (int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16))


def _euclidean_rgb(a: tuple[int, int, int], b: tuple[int, int, int]) -> float:
    return float(((a[0] - b[0]) ** 2 + (a[1] - b[1]) ** 2 + (a[2] - b[2]) ** 2) ** 0.5)


def _split_sentences(text: str) -> list[str]:
    import re

    return [s.strip() for s in re.split(r"[.!?]+", text) if s.strip()]
