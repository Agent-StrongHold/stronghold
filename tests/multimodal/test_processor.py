"""Tests for multi-modal message processing.

Covers: text extraction, image counting, token estimation, URL validation,
image detection, and max-image enforcement.
"""

from __future__ import annotations

from stronghold.multimodal.processor import (
    IMAGE_TOKENS_HIGH_RES,
    IMAGE_TOKENS_LOW_RES,
    MAX_IMAGES_PER_REQUEST,
    count_images,
    estimate_image_tokens,
    extract_text,
    has_images,
    validate_image_urls,
)


# ---------------------------------------------------------------------------
# Helper factories
# ---------------------------------------------------------------------------

def _text_msg(role: str, text: str) -> dict[str, object]:
    """Build a plain text message (string content)."""
    return {"role": role, "content": text}


def _multipart_msg(
    role: str,
    text: str,
    image_urls: list[str],
    *,
    detail: str = "auto",
) -> dict[str, object]:
    """Build a multi-part message with text + image_url parts."""
    parts: list[dict[str, object]] = [{"type": "text", "text": text}]
    for url in image_urls:
        parts.append(
            {"type": "image_url", "image_url": {"url": url, "detail": detail}}
        )
    return {"role": role, "content": parts}


def _image_only_msg(role: str, url: str, *, detail: str = "auto") -> dict[str, object]:
    """Build a message that contains only an image_url part (no text)."""
    return {
        "role": role,
        "content": [
            {"type": "image_url", "image_url": {"url": url, "detail": detail}},
        ],
    }


# ===================================================================
# extract_text
# ===================================================================

class TestExtractText:
    """extract_text must return concatenated text, ignoring images."""

    def test_text_only_string_content(self) -> None:
        msgs = [_text_msg("user", "Hello world")]
        assert extract_text(msgs) == "Hello world"

    def test_text_only_multiple_messages(self) -> None:
        msgs = [
            _text_msg("system", "You are helpful."),
            _text_msg("user", "What is 2+2?"),
        ]
        result = extract_text(msgs)
        assert "You are helpful." in result
        assert "What is 2+2?" in result

    def test_multipart_extracts_text_ignores_image(self) -> None:
        msgs = [
            _multipart_msg("user", "Describe this image", ["https://example.com/img.png"]),
        ]
        result = extract_text(msgs)
        assert "Describe this image" in result
        assert "example.com" not in result

    def test_image_only_message_returns_empty_for_that_part(self) -> None:
        msgs = [_image_only_msg("user", "https://example.com/img.png")]
        result = extract_text(msgs)
        # No text content, so should be empty or whitespace-only
        assert result.strip() == ""

    def test_mixed_string_and_multipart(self) -> None:
        msgs = [
            _text_msg("system", "System prompt"),
            _multipart_msg("user", "Look at this", ["https://example.com/a.png"]),
        ]
        result = extract_text(msgs)
        assert "System prompt" in result
        assert "Look at this" in result

    def test_empty_messages(self) -> None:
        assert extract_text([]) == ""


# ===================================================================
# count_images
# ===================================================================

class TestCountImages:
    """count_images must count image_url parts across all messages."""

    def test_zero_images(self) -> None:
        msgs = [_text_msg("user", "No images here")]
        assert count_images(msgs) == 0

    def test_one_image(self) -> None:
        msgs = [_multipart_msg("user", "One image", ["https://example.com/a.png"])]
        assert count_images(msgs) == 1

    def test_three_images_across_messages(self) -> None:
        msgs = [
            _multipart_msg("user", "Two images", [
                "https://example.com/a.png",
                "https://example.com/b.png",
            ]),
            _multipart_msg("user", "One more", ["https://example.com/c.png"]),
        ]
        assert count_images(msgs) == 3

    def test_string_content_ignored(self) -> None:
        msgs = [_text_msg("user", "image_url is in the text")]
        assert count_images(msgs) == 0


# ===================================================================
# estimate_image_tokens
# ===================================================================

class TestEstimateImageTokens:
    """estimate_image_tokens must use resolution-based estimates."""

    def test_no_images_zero_tokens(self) -> None:
        msgs = [_text_msg("user", "No images")]
        assert estimate_image_tokens(msgs) == 0

    def test_low_res_image(self) -> None:
        msgs = [_multipart_msg("user", "Low res", ["https://example.com/a.png"], detail="low")]
        assert estimate_image_tokens(msgs) == IMAGE_TOKENS_LOW_RES

    def test_high_res_image(self) -> None:
        msgs = [_multipart_msg("user", "High res", ["https://example.com/a.png"], detail="high")]
        assert estimate_image_tokens(msgs) == IMAGE_TOKENS_HIGH_RES

    def test_auto_defaults_to_high_res(self) -> None:
        msgs = [_multipart_msg("user", "Auto", ["https://example.com/a.png"], detail="auto")]
        assert estimate_image_tokens(msgs) == IMAGE_TOKENS_HIGH_RES

    def test_multiple_images_sum(self) -> None:
        msgs = [
            _multipart_msg("user", "Two images", [
                "https://example.com/a.png",
                "https://example.com/b.png",
            ], detail="low"),
        ]
        assert estimate_image_tokens(msgs) == IMAGE_TOKENS_LOW_RES * 2


# ===================================================================
# validate_image_urls
# ===================================================================

class TestValidateImageUrls:
    """validate_image_urls must block private IPs, bad schemes, bad URLs."""

    def test_valid_public_urls(self) -> None:
        msgs = [
            _multipart_msg("user", "Valid", [
                "https://cdn.example.com/image.png",
                "https://images.unsplash.com/photo.jpg",
            ]),
        ]
        errors = validate_image_urls(msgs)
        assert errors == []

    def test_blocks_private_ip_10(self) -> None:
        msgs = [_multipart_msg("user", "SSRF", ["https://10.0.0.1/secret.png"])]
        errors = validate_image_urls(msgs)
        assert len(errors) == 1
        assert "private" in errors[0].lower() or "blocked" in errors[0].lower()

    def test_blocks_private_ip_192_168(self) -> None:
        msgs = [_multipart_msg("user", "SSRF", ["https://192.168.1.1/secret.png"])]
        errors = validate_image_urls(msgs)
        assert len(errors) == 1

    def test_blocks_private_ip_172(self) -> None:
        msgs = [_multipart_msg("user", "SSRF", ["https://172.16.0.1/secret.png"])]
        errors = validate_image_urls(msgs)
        assert len(errors) == 1

    def test_blocks_localhost(self) -> None:
        msgs = [_multipart_msg("user", "SSRF", ["https://localhost/secret.png"])]
        errors = validate_image_urls(msgs)
        assert len(errors) == 1

    def test_blocks_127_0_0_1(self) -> None:
        msgs = [_multipart_msg("user", "SSRF", ["https://127.0.0.1/secret.png"])]
        errors = validate_image_urls(msgs)
        assert len(errors) == 1

    def test_blocks_non_http_scheme_ftp(self) -> None:
        msgs = [_multipart_msg("user", "Bad scheme", ["ftp://example.com/image.png"])]
        errors = validate_image_urls(msgs)
        assert len(errors) == 1
        assert "scheme" in errors[0].lower() or "http" in errors[0].lower()

    def test_blocks_non_http_scheme_file(self) -> None:
        msgs = [_multipart_msg("user", "Bad scheme", ["file:///etc/passwd"])]
        errors = validate_image_urls(msgs)
        assert len(errors) == 1

    def test_blocks_javascript_scheme(self) -> None:
        msgs = [_multipart_msg("user", "XSS", ["javascript:alert(1)"])]
        errors = validate_image_urls(msgs)
        assert len(errors) == 1

    def test_allows_data_uri(self) -> None:
        """data: URIs are used for inline base64 images — should be allowed."""
        msgs = [
            _multipart_msg("user", "Inline", ["data:image/png;base64,iVBORw0KGgo="]),
        ]
        errors = validate_image_urls(msgs)
        assert errors == []

    def test_no_images_no_errors(self) -> None:
        msgs = [_text_msg("user", "Just text")]
        errors = validate_image_urls(msgs)
        assert errors == []

    def test_multiple_errors_reported(self) -> None:
        msgs = [
            _multipart_msg("user", "Multiple bad", [
                "https://10.0.0.1/a.png",
                "ftp://example.com/b.png",
            ]),
        ]
        errors = validate_image_urls(msgs)
        assert len(errors) == 2


# ===================================================================
# has_images
# ===================================================================

class TestHasImages:
    """has_images must correctly detect image_url content parts."""

    def test_true_with_image(self) -> None:
        msgs = [_multipart_msg("user", "Has image", ["https://example.com/img.png"])]
        assert has_images(msgs) is True

    def test_false_text_only(self) -> None:
        msgs = [_text_msg("user", "No images")]
        assert has_images(msgs) is False

    def test_false_empty(self) -> None:
        assert has_images([]) is False

    def test_true_image_only_no_text(self) -> None:
        msgs = [_image_only_msg("user", "https://example.com/img.png")]
        assert has_images(msgs) is True


# ===================================================================
# MAX_IMAGES_PER_REQUEST validation
# ===================================================================

class TestMaxImagesValidation:
    """Validation should flag when image count exceeds MAX_IMAGES_PER_REQUEST."""

    def test_at_limit_passes(self) -> None:
        urls = [f"https://example.com/{i}.png" for i in range(MAX_IMAGES_PER_REQUEST)]
        msgs = [_multipart_msg("user", "At limit", urls)]
        errors = validate_image_urls(msgs)
        assert errors == []

    def test_over_limit_fails(self) -> None:
        urls = [f"https://example.com/{i}.png" for i in range(MAX_IMAGES_PER_REQUEST + 1)]
        msgs = [_multipart_msg("user", "Over limit", urls)]
        errors = validate_image_urls(msgs)
        assert any("max" in e.lower() or "exceed" in e.lower() or "limit" in e.lower() for e in errors)


# ===================================================================
# Edge cases
# ===================================================================

class TestEdgeCases:
    """Edge cases: empty content, missing fields, unusual structures."""

    def test_message_with_none_content(self) -> None:
        msgs: list[dict[str, object]] = [{"role": "user", "content": None}]
        # Should not crash
        assert extract_text(msgs) == ""
        assert count_images(msgs) == 0
        assert has_images(msgs) is False

    def test_message_with_empty_list_content(self) -> None:
        msgs: list[dict[str, object]] = [{"role": "user", "content": []}]
        assert extract_text(msgs) == ""
        assert count_images(msgs) == 0

    def test_part_missing_type_field(self) -> None:
        msgs: list[dict[str, object]] = [
            {"role": "user", "content": [{"text": "no type field"}]},
        ]
        # Should handle gracefully
        assert extract_text(msgs) == ""
        assert count_images(msgs) == 0

    def test_image_url_part_missing_url(self) -> None:
        msgs: list[dict[str, object]] = [
            {
                "role": "user",
                "content": [
                    {"type": "image_url", "image_url": {}},
                ],
            },
        ]
        errors = validate_image_urls(msgs)
        # Missing URL should produce an error
        assert len(errors) == 1
