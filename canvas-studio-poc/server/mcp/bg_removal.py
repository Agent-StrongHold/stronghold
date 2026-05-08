"""Background removal — BFS flood fill from edges with luminance threshold.

Ported from renderingPipeline.js removeBackground(). Uses Pillow instead
of browser canvas API. Removes near-white/grey backgrounds from generated
images so character/prop layers composite properly on top of backgrounds.
"""

from __future__ import annotations

import logging
from collections import deque
from dataclasses import dataclass

from PIL import Image

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class BgRemovalConfig:
    threshold: int = 240
    feather: int = 4
    max_saturation_delta: int = 50


def _luminance(r: int, g: int, b: int) -> float:
    return 0.299 * r + 0.587 * g + 0.114 * b


def _is_bg_color(pixel: tuple[int, int, int, int], threshold: int, max_delta: int) -> bool:
    r, g, b, a = pixel
    if a < 128:
        return True
    lum = _luminance(r, g, b)
    if lum < threshold:
        return False
    max_c = max(r, g, b)
    min_c = min(r, g, b)
    return not max_c - min_c > max_delta


def remove_background(
    image: Image.Image,
    threshold: int = 240,
    feather: int = 4,
    max_saturation_delta: int = 50,
) -> Image.Image:
    img = image.convert("RGBA")
    w, h = img.size
    pixels = img.get_flattened_data()

    mask = [0] * (w * h)

    queue: deque[int] = deque()

    for x in range(w):
        idx_top = x
        if _is_bg_color(pixels[idx_top], threshold, max_saturation_delta):
            mask[idx_top] = 1
            queue.append(idx_top)
        idx_bot = (h - 1) * w + x
        if _is_bg_color(pixels[idx_bot], threshold, max_saturation_delta):
            mask[idx_bot] = 1
            queue.append(idx_bot)

    for y in range(h):
        idx_left = y * w
        if _is_bg_color(pixels[idx_left], threshold, max_saturation_delta):
            mask[idx_left] = 1
            queue.append(idx_left)
        idx_right = y * w + w - 1
        if _is_bg_color(pixels[idx_right], threshold, max_saturation_delta):
            mask[idx_right] = 1
            queue.append(idx_right)

    while queue:
        idx = queue.popleft()
        if mask[idx] != 1:
            continue
        x = idx % w
        y = (idx - x) // w
        if x > 0:
            ni = idx - 1
            if mask[ni] == 0 and _is_bg_color(pixels[ni], threshold, max_saturation_delta):
                mask[ni] = 1
                queue.append(ni)
        if x < w - 1:
            ni = idx + 1
            if mask[ni] == 0 and _is_bg_color(pixels[ni], threshold, max_saturation_delta):
                mask[ni] = 1
                queue.append(ni)
        if y > 0:
            ni = idx - w
            if mask[ni] == 0 and _is_bg_color(pixels[ni], threshold, max_saturation_delta):
                mask[ni] = 1
                queue.append(ni)
        if y < h - 1:
            ni = idx + w
            if mask[ni] == 0 and _is_bg_color(pixels[ni], threshold, max_saturation_delta):
                mask[ni] = 1
                queue.append(ni)

    for i in range(len(mask)):
        if mask[i] == 0:
            mask[i] = 2

    new_pixels = list(pixels)
    if feather > 0:
        for y in range(h):
            for x in range(w):
                idx = y * w + x
                if mask[idx] == 1:
                    new_pixels[idx] = (0, 0, 0, 0)
                elif mask[idx] == 2:
                    min_dist = feather + 1
                    for fy in range(-feather, feather + 1):
                        for fx in range(-feather, feather + 1):
                            nx = x + fx
                            ny = y + fy
                            if nx < 0 or nx >= w or ny < 0 or ny >= h:
                                continue
                            if mask[ny * w + nx] == 1:
                                d = (fx * fx + fy * fy) ** 0.5
                                if d < min_dist:
                                    min_dist = d
                    if min_dist <= feather:
                        alpha = round(255 * (min_dist / feather))
                        r, g, b, _ = new_pixels[idx]
                        new_pixels[idx] = (r, g, b, alpha)
    else:
        for i in range(len(mask)):
            if mask[i] == 1:
                new_pixels[i] = (0, 0, 0, 0)

    result = Image.new("RGBA", (w, h))
    result.putdata(new_pixels)
    return result
