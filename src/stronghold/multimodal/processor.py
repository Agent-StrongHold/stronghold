"""Multi-modal message processing -- extract text, validate images, estimate tokens.

Handles the OpenAI multi-part content format where message content can be either
a plain string or a list of typed parts (text, image_url).  Provides utilities for:
- Text extraction (for classifier/keyword scoring -- ignores images)
- Image counting and token estimation
- URL validation with SSRF prevention (private IP blocking)
"""

from __future__ import annotations

import re
from typing import Any
from urllib.parse import urlparse

# Image token estimates (OpenAI convention)
IMAGE_TOKENS_LOW_RES = 765
IMAGE_TOKENS_HIGH_RES = 1105
MAX_IMAGE_SIZE_BYTES = 20 * 1024 * 1024  # 20 MB
MAX_IMAGES_PER_REQUEST = 5

# Private IP ranges to block (SSRF prevention)
_PRIVATE_RANGES = [
    re.compile(r"^10\."),
    re.compile(r"^172\.(1[6-9]|2\d|3[01])\."),
    re.compile(r"^192\.168\."),
    re.compile(r"^127\."),
    re.compile(r"^0\."),
    re.compile(r"^localhost", re.IGNORECASE),
]


def _iter_parts(
    messages: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Iterate over all content parts across all messages.

    For string content, yields nothing (callers should handle strings separately).
    For list content, yields each dict part.
    """
    parts: list[dict[str, Any]] = []
    for msg in messages:
        content = msg.get("content")
        if isinstance(content, list):
            for part in content:
                if isinstance(part, dict):
                    parts.append(part)
    return parts


def extract_text(messages: list[dict[str, Any]]) -> str:
    """Extract text content from potentially multi-modal messages.

    For classifier and keyword scoring -- ignores images.
    Handles both string content and list-of-parts content.
    """
    text_parts: list[str] = []
    for msg in messages:
        content = msg.get("content")
        if isinstance(content, str):
            text_parts.append(content)
        elif isinstance(content, list):
            for part in content:
                if isinstance(part, dict) and part.get("type") == "text":
                    text_parts.append(str(part.get("text", "")))
    return "\n".join(text_parts) if text_parts else ""


def count_images(messages: list[dict[str, Any]]) -> int:
    """Count image_url parts in messages."""
    count = 0
    for part in _iter_parts(messages):
        if part.get("type") == "image_url":
            count += 1
    return count


def estimate_image_tokens(messages: list[dict[str, Any]]) -> int:
    """Estimate token cost of images in messages.

    Uses OpenAI convention: low detail = 765 tokens, high/auto = 1105 tokens.
    """
    total = 0
    for part in _iter_parts(messages):
        if part.get("type") == "image_url":
            image_info = part.get("image_url", {})
            detail = image_info.get("detail", "auto") if isinstance(image_info, dict) else "auto"
            if detail == "low":
                total += IMAGE_TOKENS_LOW_RES
            else:
                total += IMAGE_TOKENS_HIGH_RES
    return total


def _is_private_host(hostname: str) -> bool:
    """Check if a hostname resolves to a private/internal address."""
    return any(pattern.search(hostname) for pattern in _PRIVATE_RANGES)


def validate_image_urls(messages: list[dict[str, Any]]) -> list[str]:
    """Validate image URLs. Returns list of error messages (empty = all valid).

    Checks:
    - URL format (parseable)
    - Not a private IP (SSRF prevention)
    - Scheme is http, https, or data (for inline base64)
    - Total image count does not exceed MAX_IMAGES_PER_REQUEST
    """
    errors: list[str] = []
    image_count = 0

    for part in _iter_parts(messages):
        if part.get("type") != "image_url":
            continue

        image_count += 1
        image_info = part.get("image_url", {})
        url = image_info.get("url", "") if isinstance(image_info, dict) else ""

        if not url:
            errors.append("Image URL is empty or missing")
            continue

        # data: URIs are allowed (inline base64 images)
        if url.startswith("data:"):
            continue

        try:
            parsed = urlparse(url)
        except Exception:
            errors.append(f"Invalid URL format: {url}")
            continue

        # Scheme check
        if parsed.scheme not in ("http", "https"):
            errors.append(f"Invalid URL scheme '{parsed.scheme}' — only http/https allowed: {url}")
            continue

        # SSRF: block private IPs
        hostname = parsed.hostname or ""
        if _is_private_host(hostname):
            errors.append(f"Blocked private/internal URL: {url}")

    # Max images check
    if image_count > MAX_IMAGES_PER_REQUEST:
        errors.append(f"Too many images: {image_count} exceeds limit of {MAX_IMAGES_PER_REQUEST}")

    return errors


def has_images(messages: list[dict[str, Any]]) -> bool:
    """Check if messages contain any image content."""
    return any(part.get("type") == "image_url" for part in _iter_parts(messages))
