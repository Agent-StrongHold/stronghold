"""Tests for ForgeStrategy — iterative SKILL.md generation with validation."""

from __future__ import annotations

import textwrap

import pytest

from stronghold.agents.forge.strategy import (
    DANGEROUS_PATTERNS,
    ForgeStrategy,
    ValidationError,
    validate_skill_md,
)
from stronghold.types.agent import ReasoningResult
from tests.fakes import FakeLLMClient


def _llm_response(content: str) -> dict[str, object]:
    """Build a FakeLLMClient-compatible response dict."""
    return {
        "id": "chatcmpl-forge",
        "object": "chat.completion",
        "model": "fake-model",
        "choices": [
            {
                "index": 0,
                "message": {"role": "assistant", "content": content},
                "finish_reason": "stop",
            }
        ],
        "usage": {"prompt_tokens": 10, "completion_tokens": 20, "total_tokens": 30},
    }


VALID_SKILL_MD = textwrap.dedent("""\
    ---
    name: hello_world
    description: A simple greeting tool
    version: "1.0"
    trust_tier: skull
    ---

    # hello_world

    ```python
    def run(name: str) -> str:
        return f"Hello, {name}!"
    ```
""")

MISSING_NAME_SKILL = textwrap.dedent("""\
    ---
    description: A tool with no name
    version: "1.0"
    trust_tier: skull
    ---

    # unnamed

    ```python
    def run() -> str:
        return "oops"
    ```
""")

MISSING_DESCRIPTION_SKILL = textwrap.dedent("""\
    ---
    name: nodesc
    version: "1.0"
    trust_tier: skull
    ---

    # nodesc

    ```python
    def run() -> str:
        return "no description"
    ```
""")

MISSING_VERSION_SKILL = textwrap.dedent("""\
    ---
    name: noversion
    description: No version field
    trust_tier: skull
    ---

    # noversion

    ```python
    def run() -> str:
        return "no version"
    ```
""")

MISSING_TRUST_TIER_SKILL = textwrap.dedent("""\
    ---
    name: notrust
    description: No trust tier
    version: "1.0"
    ---

    # notrust

    ```python
    def run() -> str:
        return "no trust tier"
    ```
""")

NO_FRONTMATTER_SKILL = textwrap.dedent("""\
    # no_frontmatter

    ```python
    def run() -> str:
        return "missing frontmatter"
    ```
""")


DANGEROUS_EXEC_SKILL = textwrap.dedent("""\
    ---
    name: evil_exec
    description: Uses exec
    version: "1.0"
    trust_tier: skull
    ---

    # evil_exec

    ```python
    def run(code: str) -> str:
        exec(code)
        return "done"
    ```
""")

DANGEROUS_EVAL_SKILL = textwrap.dedent("""\
    ---
    name: evil_eval
    description: Uses eval
    version: "1.0"
    trust_tier: skull
    ---

    # evil_eval

    ```python
    def run(expr: str) -> str:
        return str(eval(expr))
    ```
""")

DANGEROUS_IMPORT_OS_SKILL = textwrap.dedent("""\
    ---
    name: evil_os
    description: Imports os
    version: "1.0"
    trust_tier: skull
    ---

    # evil_os

    ```python
    import os

    def run() -> str:
        return os.getcwd()
    ```
""")

DANGEROUS_SUBPROCESS_SKILL = textwrap.dedent("""\
    ---
    name: evil_subprocess
    description: Uses subprocess
    version: "1.0"
    trust_tier: skull
    ---

    # evil_subprocess

    ```python
    import subprocess

    def run(cmd: str) -> str:
        return subprocess.check_output(cmd, shell=True).decode()
    ```
""")

DANGEROUS_DUNDER_IMPORT_SKILL = textwrap.dedent("""\
    ---
    name: evil_dunder
    description: Uses __import__
    version: "1.0"
    trust_tier: skull
    ---

    # evil_dunder

    ```python
    def run(module: str) -> object:
        return __import__(module)
    ```
""")


# ── validate_skill_md unit tests ──────────────────────────────────────


class TestValidateSkillMd:
    """Unit tests for the validate_skill_md function."""

    def test_valid_skill_passes(self) -> None:
        errors = validate_skill_md(VALID_SKILL_MD)
        assert errors == []

    def test_missing_frontmatter(self) -> None:
        errors = validate_skill_md(NO_FRONTMATTER_SKILL)
        assert any("frontmatter" in e.lower() for e in errors)

    def test_missing_name(self) -> None:
        errors = validate_skill_md(MISSING_NAME_SKILL)
        assert any("name" in e.lower() for e in errors)

    def test_missing_description(self) -> None:
        errors = validate_skill_md(MISSING_DESCRIPTION_SKILL)
        assert any("description" in e.lower() for e in errors)

    def test_missing_version(self) -> None:
        errors = validate_skill_md(MISSING_VERSION_SKILL)
        assert any("version" in e.lower() for e in errors)

    def test_missing_trust_tier(self) -> None:
        errors = validate_skill_md(MISSING_TRUST_TIER_SKILL)
        assert any("trust_tier" in e.lower() for e in errors)

    @pytest.mark.parametrize(
        "skill_md, pattern",
        [
            (DANGEROUS_EXEC_SKILL, "exec("),
            (DANGEROUS_EVAL_SKILL, "eval("),
            (DANGEROUS_IMPORT_OS_SKILL, "import os"),
            (DANGEROUS_SUBPROCESS_SKILL, "subprocess"),
            (DANGEROUS_DUNDER_IMPORT_SKILL, "__import__"),
        ],
        ids=["exec", "eval", "import_os", "subprocess", "dunder_import"],
    )
    def test_dangerous_pattern_rejected(self, skill_md: str, pattern: str) -> None:
        errors = validate_skill_md(skill_md)
        assert any(pattern in e for e in errors), f"Expected error mentioning {pattern!r}"

    def test_multiple_errors_returned(self) -> None:
        """A skill with both missing fields AND dangerous code gets all errors."""
        bad_skill = textwrap.dedent("""\
            ---
            name: bad
            ---

            # bad

            ```python
            exec("boom")
            ```
        """)
        errors = validate_skill_md(bad_skill)
        # Should have at least missing description, version, trust_tier AND exec(
        assert len(errors) >= 3

    def test_empty_input(self) -> None:
        errors = validate_skill_md("")
        assert len(errors) > 0


# ── DANGEROUS_PATTERNS constant ───────────────────────────────────────


class TestDangerousPatterns:
    """Ensure the constant is defined with the required patterns."""

    def test_contains_all_required(self) -> None:
        expected = ["exec(", "eval(", "import os", "subprocess", "__import__"]
        for pat in expected:
            assert pat in DANGEROUS_PATTERNS, f"{pat!r} missing from DANGEROUS_PATTERNS"


# ── ForgeStrategy integration tests ──────────────────────────────────


class TestForgeStrategy:
    """Integration tests using FakeLLMClient."""

    def test_default_max_iterations(self) -> None:
        strategy = ForgeStrategy()
        assert strategy.max_iterations == 10

    def test_custom_max_iterations(self) -> None:
        strategy = ForgeStrategy(max_iterations=5)
        assert strategy.max_iterations == 5

    async def test_valid_skill_first_attempt(self) -> None:
        """LLM returns valid SKILL.md on first try -> immediate success."""
        llm = FakeLLMClient()
        llm.set_responses(_llm_response(VALID_SKILL_MD))
        strategy = ForgeStrategy(max_iterations=10)

        result = await strategy.reason(
            messages=[{"role": "user", "content": "Create a greeting tool"}],
            model="fake-model",
            llm=llm,
        )

        assert isinstance(result, ReasoningResult)
        assert result.done is True
        assert result.response is not None
        assert "hello_world" in result.response
        assert len(llm.calls) == 1

    async def test_invalid_then_valid(self) -> None:
        """LLM returns invalid SKILL.md, gets error feedback, then returns valid."""
        llm = FakeLLMClient()
        llm.set_responses(
            _llm_response(MISSING_NAME_SKILL),
            _llm_response(VALID_SKILL_MD),
        )
        strategy = ForgeStrategy(max_iterations=10)

        result = await strategy.reason(
            messages=[{"role": "user", "content": "Create a tool"}],
            model="fake-model",
            llm=llm,
        )

        assert result.done is True
        assert result.response is not None
        assert "hello_world" in result.response
        assert len(llm.calls) == 2

    async def test_dangerous_pattern_then_valid(self) -> None:
        """LLM returns dangerous code, gets feedback, then returns safe code."""
        llm = FakeLLMClient()
        llm.set_responses(
            _llm_response(DANGEROUS_EXEC_SKILL),
            _llm_response(VALID_SKILL_MD),
        )
        strategy = ForgeStrategy(max_iterations=10)

        result = await strategy.reason(
            messages=[{"role": "user", "content": "Create a tool"}],
            model="fake-model",
            llm=llm,
        )

        assert result.done is True
        assert result.response is not None
        assert "hello_world" in result.response
        assert len(llm.calls) == 2

    async def test_error_feedback_in_messages(self) -> None:
        """Verify that validation errors are fed back to the LLM."""
        llm = FakeLLMClient()
        llm.set_responses(
            _llm_response(MISSING_NAME_SKILL),
            _llm_response(VALID_SKILL_MD),
        )
        strategy = ForgeStrategy(max_iterations=10)

        await strategy.reason(
            messages=[{"role": "user", "content": "Create a tool"}],
            model="fake-model",
            llm=llm,
        )

        # Second call should have error feedback in messages
        second_call_messages = llm.calls[1]["messages"]
        # The last message before the second call should contain error info
        feedback_found = any(
            "name" in str(msg.get("content", "")).lower()
            for msg in second_call_messages
            if msg.get("role") == "user"
        )
        assert feedback_found, "Validation errors should be fed back to the LLM"

    async def test_max_iterations_exhausted(self) -> None:
        """All iterations produce invalid SKILL.md -> failure with error."""
        llm = FakeLLMClient()
        # All responses are invalid (missing name)
        llm.set_responses(*[_llm_response(MISSING_NAME_SKILL) for _ in range(3)])
        strategy = ForgeStrategy(max_iterations=3)

        result = await strategy.reason(
            messages=[{"role": "user", "content": "Create a tool"}],
            model="fake-model",
            llm=llm,
        )

        assert result.done is True
        assert result.response is not None
        assert "failed" in result.response.lower() or "error" in result.response.lower()
        assert len(llm.calls) == 3

    async def test_token_tracking(self) -> None:
        """Token counts from all iterations are accumulated."""
        llm = FakeLLMClient()
        llm.set_responses(
            _llm_response(MISSING_NAME_SKILL),
            _llm_response(VALID_SKILL_MD),
        )
        strategy = ForgeStrategy(max_iterations=10)

        result = await strategy.reason(
            messages=[{"role": "user", "content": "Create a tool"}],
            model="fake-model",
            llm=llm,
        )

        # Each fake response has 10 prompt + 20 completion tokens
        assert result.input_tokens == 20
        assert result.output_tokens == 40

    async def test_returns_reasoning_result(self) -> None:
        """Strategy returns a proper ReasoningResult."""
        llm = FakeLLMClient()
        llm.set_responses(_llm_response(VALID_SKILL_MD))
        strategy = ForgeStrategy()

        result = await strategy.reason(
            messages=[{"role": "user", "content": "Create a tool"}],
            model="fake-model",
            llm=llm,
        )

        assert isinstance(result, ReasoningResult)
        assert result.done is True

    async def test_multiple_validation_errors_all_fed_back(self) -> None:
        """When a skill has multiple errors, all are included in feedback."""
        bad_skill = textwrap.dedent("""\
            ---
            name: bad
            ---

            # bad

            ```python
            exec("boom")
            ```
        """)
        llm = FakeLLMClient()
        llm.set_responses(
            _llm_response(bad_skill),
            _llm_response(VALID_SKILL_MD),
        )
        strategy = ForgeStrategy(max_iterations=10)

        await strategy.reason(
            messages=[{"role": "user", "content": "Create a tool"}],
            model="fake-model",
            llm=llm,
        )

        second_call_messages = llm.calls[1]["messages"]
        feedback_content = ""
        for msg in second_call_messages:
            if msg.get("role") == "user":
                feedback_content += str(msg.get("content", ""))

        # Should mention both missing fields and dangerous pattern
        assert "description" in feedback_content.lower() or "version" in feedback_content.lower()
        assert "exec(" in feedback_content

    async def test_reasoning_trace_on_success(self) -> None:
        """Successful creation includes a reasoning trace."""
        llm = FakeLLMClient()
        llm.set_responses(_llm_response(VALID_SKILL_MD))
        strategy = ForgeStrategy()

        result = await strategy.reason(
            messages=[{"role": "user", "content": "Create a tool"}],
            model="fake-model",
            llm=llm,
        )

        assert result.reasoning_trace != ""

    async def test_reasoning_trace_on_failure(self) -> None:
        """Exhausted iterations include a reasoning trace with error info."""
        llm = FakeLLMClient()
        llm.set_responses(_llm_response(MISSING_NAME_SKILL))
        strategy = ForgeStrategy(max_iterations=1)

        result = await strategy.reason(
            messages=[{"role": "user", "content": "Create a tool"}],
            model="fake-model",
            llm=llm,
        )

        assert result.reasoning_trace != ""
        assert "1" in result.reasoning_trace  # iteration count


# ── ValidationError type ─────────────────────────────────────────────


class TestValidationError:
    """Ensure ValidationError is a proper exception."""

    def test_is_exception(self) -> None:
        err = ValidationError("bad frontmatter")
        assert isinstance(err, Exception)

    def test_stores_errors(self) -> None:
        err = ValidationError("test", errors=["err1", "err2"])
        assert err.errors == ["err1", "err2"]
