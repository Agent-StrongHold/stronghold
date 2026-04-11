"""Unit tests for skills route pure-helper functions.

Targets lines that are hard to hit via TestClient: the pure functions
_select_forge_model, _sanitize_generated_skill, _ensure_skill_body, _check_csrf.
"""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest
from fastapi import HTTPException

from stronghold.api.routes.skills import (
    _check_csrf,
    _ensure_skill_body,
    _sanitize_generated_skill,
    _select_forge_model,
)


# ── _select_forge_model ─────────────────────────────────────────────


def _container_with_models(models: dict) -> SimpleNamespace:
    return SimpleNamespace(config=SimpleNamespace(models=models))


def test_select_forge_model_prefers_mistral_large() -> None:
    c = _container_with_models(
        {
            "mistral-large": {"litellm_id": "mistral/mistral-large-latest"},
            "gemini-flash": {"litellm_id": "gemini/flash"},
        }
    )
    assert _select_forge_model(c) == "mistral/mistral-large-latest"


def test_select_forge_model_falls_back_to_mistral_small() -> None:
    c = _container_with_models(
        {"mistral-small": {"litellm_id": "mistral/mistral-small"}}
    )
    assert _select_forge_model(c) == "mistral/mistral-small"


def test_select_forge_model_falls_back_to_gemini_flash() -> None:
    c = _container_with_models({"gemini-flash": {"litellm_id": "gemini/flash-2"}})
    assert _select_forge_model(c) == "gemini/flash-2"


def test_select_forge_model_uses_first_available_when_no_preferred() -> None:
    c = _container_with_models({"random-model": {"litellm_id": "provider/random"}})
    assert _select_forge_model(c) == "provider/random"


def test_select_forge_model_hardcoded_default_when_no_models() -> None:
    c = _container_with_models({})
    assert _select_forge_model(c) == "mistral/mistral-large-latest"


def test_select_forge_model_skips_non_dict_entries() -> None:
    c = _container_with_models(
        {"broken": "not-a-dict", "good": {"litellm_id": "provider/ok"}}
    )
    assert _select_forge_model(c) == "provider/ok"


def test_select_forge_model_skips_dict_without_litellm_id() -> None:
    c = _container_with_models(
        {"incomplete": {"description": "no litellm_id"}, "real": {"litellm_id": "p/m"}}
    )
    assert _select_forge_model(c) == "p/m"


def test_select_forge_model_handles_missing_models_attr() -> None:
    c = SimpleNamespace(config=SimpleNamespace())
    assert _select_forge_model(c) == "mistral/mistral-large-latest"


def test_select_forge_model_handles_none_models() -> None:
    c = SimpleNamespace(config=SimpleNamespace(models=None))
    assert _select_forge_model(c) == "mistral/mistral-large-latest"


# ── _sanitize_generated_skill ───────────────────────────────────────


def test_sanitize_strips_markdown_fence() -> None:
    content = "```markdown\n---\nname: foo\n---\nbody\n```"
    result = _sanitize_generated_skill(content)
    assert not result.startswith("```")
    assert "---\nname: foo" in result


def test_sanitize_strips_md_fence_variant() -> None:
    content = "```md\n---\nname: bar\n---\nbody\n```"
    result = _sanitize_generated_skill(content)
    assert "bar" in result
    assert "```" not in result


def test_sanitize_strips_plain_fence() -> None:
    content = "```\n---\nname: bar\n---\n```"
    result = _sanitize_generated_skill(content)
    assert "bar" in result


def test_sanitize_trims_preamble_before_frontmatter() -> None:
    content = "Here's the skill:\n---\nname: clean\n---\nbody"
    result = _sanitize_generated_skill(content)
    assert result.startswith("---")


def test_sanitize_leaves_clean_input_alone() -> None:
    content = "---\nname: already-clean\n---\nbody"
    assert _sanitize_generated_skill(content) == content


# ── _ensure_skill_body ──────────────────────────────────────────────


def test_ensure_body_adds_body_when_only_frontmatter() -> None:
    content = '---\nname: lonely\ndescription: "helps with X"\n---'
    result = _ensure_skill_body(content)
    assert "Use this skill when helps with x" in result
    assert "---" in result


def test_ensure_body_default_description_when_missing() -> None:
    content = "---\nname: nodesc\n---"
    result = _ensure_skill_body(content)
    assert "Use this skill when" in result


def test_ensure_body_leaves_content_with_body_alone() -> None:
    content = "---\nname: has-body\n---\n\nActual body text here."
    result = _ensure_skill_body(content)
    assert result == content


def test_ensure_body_description_unquoted() -> None:
    content = "---\nname: unquoted\ndescription: some helper\n---"
    result = _ensure_skill_body(content)
    assert "some helper" in result.lower()


# ── _check_csrf ─────────────────────────────────────────────────────


def _make_request(method: str, headers: dict, cookies: dict | None = None) -> MagicMock:
    req = MagicMock()
    req.method = method
    req.headers = headers
    req.cookies = cookies or {}
    return req


def test_check_csrf_allows_get() -> None:
    req = _make_request("GET", {})
    _check_csrf(req)  # no raise


def test_check_csrf_allows_bearer_token() -> None:
    req = _make_request("POST", {"authorization": "Bearer sk-123"})
    _check_csrf(req)  # no raise


def test_check_csrf_allows_when_no_cookies() -> None:
    req = _make_request("POST", {})
    _check_csrf(req)  # no cookies = not a browser


def test_check_csrf_rejects_cookie_auth_without_header() -> None:
    req = _make_request("POST", {}, cookies={"session": "abc"})
    with pytest.raises(HTTPException) as exc:
        _check_csrf(req)
    assert exc.value.status_code == 403
    assert "CSRF" in exc.value.detail


def test_check_csrf_allows_cookie_auth_with_header() -> None:
    req = _make_request(
        "POST",
        {"x-stronghold-request": "1"},
        cookies={"session": "abc"},
    )
    _check_csrf(req)


def test_check_csrf_rejects_put_without_header() -> None:
    req = _make_request("PUT", {}, cookies={"session": "abc"})
    with pytest.raises(HTTPException):
        _check_csrf(req)


def test_check_csrf_rejects_delete_without_header() -> None:
    req = _make_request("DELETE", {}, cookies={"session": "abc"})
    with pytest.raises(HTTPException):
        _check_csrf(req)
