"""Feature extractor — local pixel-based hair/skin/eye classification from photos.

Ported from featureExtractor.js. Analyzes uploaded reference photos using
pixel sampling (no AI) to extract hair color, skin tone, and eye color.
Used as fallback when AI vision analysis is unavailable or blocked.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

from PIL import Image

logger = logging.getLogger(__name__)


@dataclass
class ExtractedFeatures:
    hair_color: str | None = None
    skin_tone: str | None = None
    eye_color: str | None = None
    description: str = ""


def _rgb_to_hsl(r: int, g: int, b: int) -> tuple[float, float, float]:
    r_f, g_f, b_f = r / 255, g / 255, b / 255
    mx = max(r_f, g_f, b_f)
    mn = min(r_f, g_f, b_f)
    lum = (mx + mn) / 2

    if mx == mn:
        return (0.0, 0.0, lum * 100)

    d = mx - mn
    s = d / (2 - mx - mn) if lum > 0.5 else d / (mx + mn)

    if mx == r_f:
        h = ((g_f - b_f) / d + (6 if g_f < b_f else 0)) / 6
    elif mx == g_f:
        h = ((b_f - r_f) / d + 2) / 6
    else:
        h = ((r_f - g_f) / d + 4) / 6

    return (h * 360, s * 100, lum * 100)


def _classify_hair_color(h: float, s: float, lum: float) -> str:
    if lum < 15:
        return "very dark black"
    if lum < 25 and s < 30:
        return "black"
    if lum < 30 and 15 < h < 40:
        return "very dark brown"
    if lum < 40 and 10 < h < 45 and s > 20:
        return "dark brown"
    if lum < 50 and 10 < h < 45:
        return "brown"
    if lum < 50 and 5 < h < 20 and s < 25:
        return "dark ash brown"
    if lum < 55 and 15 < h < 40 and s > 30:
        return "medium brown"
    if 40 <= lum < 55 and 20 < h < 50 and s > 40:
        return "auburn"
    if 35 <= lum < 55 and 5 < h < 25 and s > 50:
        return "reddish brown"
    if 40 <= lum < 55 and 10 < h < 30 and s < 25:
        return "ash blonde"
    if 50 <= lum < 70 and 15 < h < 45 and s > 25:
        return "light brown or dark blonde"
    if 55 <= lum < 75 and 20 < h < 50:
        return "dirty blonde"
    if 60 <= lum < 80 and s < 25:
        return "blonde"
    if 60 <= lum < 80 and 20 < h < 50 and s > 30:
        return "golden blonde"
    if 70 <= lum < 90 and s < 20:
        return "light blonde"
    if lum >= 75:
        return "very light blonde or white"
    if 0 < h < 15 and s > 40:
        return "red"
    if 5 < h < 30 and s > 30 and lum < 50:
        return "ginger"
    if s < 15 and lum > 40:
        return "grey or silver"
    return "brown"


def _classify_skin_tone(h: float, s: float, lum: float) -> str:
    if lum < 30:
        return "deep dark brown"
    if lum < 40 and 15 < h < 35:
        return "dark brown"
    if lum < 50 and 15 < h < 40:
        return "warm medium brown"
    if lum < 55 and 10 < h < 35:
        return "medium olive or tan"
    if lum < 60 and 15 < h < 40 and s > 30:
        return "warm light brown"
    if lum < 65 and 10 < h < 35:
        return "light tan or olive"
    if lum < 70 and 15 < h < 40:
        return "warm fair with golden undertones"
    if lum < 75 and s > 20:
        return "fair with warm undertones"
    if lum < 75:
        return "fair with cool undertones"
    if lum < 80:
        return "very fair or porcelain"
    return "very fair or pale"


def _classify_eye_color(r: int, g: int, b: int) -> str:
    h, s, lum = _rgb_to_hsl(r, g, b)
    if lum < 20:
        return "very dark brown, almost black"
    if lum < 30 and s < 40:
        return "dark brown"
    if lum < 40 and s < 50:
        return "brown"
    if lum < 45 and 20 < h < 50 and s > 30:
        return "warm brown with amber flecks"
    if 25 < h < 50 and s > 40 and 35 < lum < 55:
        return "hazel"
    if 20 < h < 45 and s > 50 and lum > 40:
        return "amber"
    if 50 < h < 170 and s > 20 and 25 < lum < 55:
        return "green"
    if 170 < h < 260 and s > 15 and 20 < lum < 50:
        return "blue"
    if 170 < h < 260 and s > 15 and lum >= 50:
        return "light blue"
    if 170 < h < 260 and s < 15:
        return "grey-blue"
    if s < 15 and lum < 40:
        return "dark grey"
    if s < 20 and lum >= 40:
        return "grey"
    return "brown"


def _sample_region(
    pixels: list[tuple[int, int, int, int]],
    img_w: int,
    cx: int,
    cy: int,
    radius: int,
) -> tuple[int, int, int] | None:
    r_sum = g_sum = b_sum = 0
    count = 0
    for dy in range(-radius, radius + 1):
        for dx in range(-radius, radius + 1):
            if dx * dx + dy * dy > radius * radius:
                continue
            x = cx + dx
            y = cy + dy
            if x < 0 or x >= img_w or y < 0 or y >= len(pixels) // img_w:
                continue
            idx = y * img_w + x
            if idx >= len(pixels):
                continue
            a = pixels[idx][3]
            if a < 128:
                continue
            r_sum += pixels[idx][0]
            g_sum += pixels[idx][1]
            b_sum += pixels[idx][2]
            count += 1
    if count == 0:
        return None
    return (round(r_sum / count), round(g_sum / count), round(b_sum / count))


def extract_features(image: Image.Image) -> ExtractedFeatures:
    img = image.convert("RGBA")
    max_dim = 512
    scale = min(max_dim / img.width, max_dim / img.height, 1.0)
    if scale < 1.0:
        new_w = round(img.width * scale)
        new_h = round(img.height * scale)
        img = img.resize((new_w, new_h), Image.Resampling.LANCZOS)

    w, h = img.size
    pixels = img.get_flattened_data()

    features = ExtractedFeatures()

    head_top_y = round(h * 0.05)
    head_cy = round(h * 0.18)
    head_cx = round(w * 0.5)
    head_r = round(min(w, h) * 0.06)

    hair_sample = _sample_region(pixels, w, head_cx, head_top_y, head_r)
    if hair_sample:
        hsl = _rgb_to_hsl(*hair_sample)
        features.hair_color = _classify_hair_color(*hsl)

    forehead_r = round(head_r * 0.5)
    forehead_y = round(head_cy - head_r * 0.3)
    forehead_sample = _sample_region(pixels, w, head_cx, forehead_y, forehead_r)
    if forehead_sample:
        hsl = _rgb_to_hsl(*forehead_sample)
        features.skin_tone = _classify_skin_tone(*hsl)

    eye_y = round(head_cy + head_r * 0.15)
    left_eye_x = round(head_cx - head_r * 0.5)
    right_eye_x = round(head_cx + head_r * 0.5)
    eye_r = max(round(head_r * 0.2), 1)
    left_eye = _sample_region(pixels, w, left_eye_x, eye_y, eye_r)
    right_eye = _sample_region(pixels, w, right_eye_x, eye_y, eye_r)
    eye_sample = left_eye or right_eye
    if eye_sample:
        features.eye_color = _classify_eye_color(*eye_sample)

    parts = []
    if features.hair_color:
        parts.append(f"{features.hair_color} hair")
    if features.skin_tone:
        parts.append(f"{features.skin_tone} skin")
    if features.eye_color:
        parts.append(f"{features.eye_color} eyes")
    features.description = ", ".join(parts)

    return features


def build_photo_derived_design(features: ExtractedFeatures, base_design: str = "") -> str:
    if not features.description:
        return base_design or ""

    design = base_design or "a child character"

    if features.hair_color:
        design = f"{features.hair_color} hair, {design}"

    if features.skin_tone:
        design = f"{features.skin_tone} skin, {design}"

    if features.eye_color:
        design = f"{features.eye_color} eyes, {design}"

    return f"Based on reference photos: {features.description}. {design}"
