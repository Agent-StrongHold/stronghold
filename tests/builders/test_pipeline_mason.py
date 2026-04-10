"""Characterization tests for the Mason TDD stage (write_tests_and_implement).

Scripts FakeLLMClient and a call-counting FakeToolDispatcher to drive 1-2
criteria through the TDD loop and verify locking, commits, and progress posting.
"""

from __future__ import annotations

import json
from types import SimpleNamespace
from typing import Any

import pytest

from stronghold.builders.pipeline import RuntimePipeline, StageResult

from tests.fakes import FakeLLMClient, FakePromptManager


# ── Helpers ──────────────────────────────────────────────────────────


def _make_response(content: str) -> dict[str, Any]:
    return {
        "choices": [{"message": {"content": content}, "finish_reason": "stop"}],
        "usage": {"prompt_tokens": 10, "completion_tokens": 20},
    }


class MasonToolDispatcher:
    """Tool dispatcher that simulates workspace + pytest + git for Mason TDD.

    Tracks pytest call count and returns different outputs on each call to
    simulate the write-test → impl → pass cycle.
    """

    def __init__(self) -> None:
        self.calls: list[tuple[str, dict[str, Any]]] = []
        self.files: dict[str, str] = {}
        self._pytest_call_count = 0
        self.pytest_outputs: list[str] = []  # scripted pytest responses in order
        self.git_calls: list[str] = []

    async def execute(self, tool: str, args: dict[str, Any]) -> str:
        self.calls.append((tool, args))
        action = args.get("action", "")

        if tool == "file_ops":
            if action == "read":
                return self.files.get(args.get("path", ""), "")
            if action == "write":
                self.files[args.get("path", "")] = args.get("content", "")
                return "OK"
            return ""

        if tool == "shell":
            cmd = args.get("command", "")
            if "pytest" in cmd:
                idx = self._pytest_call_count
                self._pytest_call_count += 1
                if idx < len(self.pytest_outputs):
                    return self.pytest_outputs[idx]
                return "1 passed in 0.1s"
            if "ruff" in cmd or "py_compile" in cmd:
                return "OK_SYNTAX"
            if "find" in cmd or "ls" in cmd:
                return "src/stronghold/foo.py"
            return "OK"

        if tool == "git":
            self.git_calls.append(args.get("command", ""))
            return "OK"

        if tool == "github":
            return "OK"

        return "OK"


def _make_run(criteria: list[str] | None = None, td: MasonToolDispatcher | None = None) -> SimpleNamespace:
    run = SimpleNamespace()
    run.run_id = "run-mason-test"
    run.repo = "owner/repo"
    run.issue_number = 42
    run.branch = "mason/42"
    run.artifacts = []
    run.events = []
    run._workspace_path = "/tmp/test-ws"
    run._issue_content = "Fix the bug in foo"
    run._issue_title = "Bug in foo"
    run._analysis = {"affected_files": ["src/stronghold/foo.py"]}
    run._criteria = ["When foo is called, it returns True"] if criteria is None else criteria
    run._locked_criteria = set()
    run._onboarding = "## Test Context\nUse pytest."
    run._file_listing = "src/stronghold/foo.py"
    run._dashboard_listing = ""
    # Pre-populate source file so the stub-detection check doesn't skip commits.
    # The pipeline reads affected_files after the TDD loop and rejects empty/<20-char files.
    if td is not None:
        td.files["src/stronghold/foo.py"] = 'def foo():\n    """Existing implementation."""\n    return False\n'
    return run


def _pipeline(llm: FakeLLMClient, td: MasonToolDispatcher) -> RuntimePipeline:
    pm = FakePromptManager()
    pm.seed("builders.mason.write_first_test", "Write a test for: {{criterion}} {{source_context}} {{feedback_block}}")
    pm.seed("builders.mason.append_test", "Append test for: {{criterion}} {{existing_code}} {{feedback_block}}")
    pm.seed("builders.mason.implement", "Implement: {{test_code}} {{pytest_output}} {{file_path}} {{source_code}} {{issue_content}} {{feedback_block}}")
    pm.seed("builders.auditor.review", "Review stage={{stage}}")
    return RuntimePipeline(llm=llm, tool_dispatcher=td, prompt_manager=pm)


VALID_TEST_CODE = '```python\nimport pytest\n\ndef test_foo_returns_true():\n    assert True\n```'
VALID_IMPL_CODE = '```python\ndef foo():\n    return True\n```'


# ── Tests ────────────────────────────────────────────────────────────


class TestMasonTDD:
    async def test_single_criterion_happy_path(self) -> None:
        """One criterion, test passes immediately → locked, committed."""
        llm = FakeLLMClient()
        llm.set_responses(
            _make_response(VALID_TEST_CODE),      # write_first_test
            # pytest will return "1 passed" (no impl needed — test passes trivially)
        )
        td = MasonToolDispatcher()
        # First pytest: compilation check passes (no SyntaxError/ImportError)
        # Second pytest: "1 passed" — all green
        td.pytest_outputs = ["1 passed in 0.1s", "1 passed in 0.1s", "1 passed in 0.1s"]

        p = _pipeline(llm, td)
        run = _make_run(criteria=["foo returns True"], td=td)
        result = await p.write_tests_and_implement(run)

        assert result.success is True
        assert run._locked_criteria == {0}

    async def test_single_criterion_commits(self) -> None:
        """After locking a criterion, git commit is called."""
        llm = FakeLLMClient()
        llm.set_responses(_make_response(VALID_TEST_CODE))
        td = MasonToolDispatcher()
        td.pytest_outputs = ["1 passed in 0.1s"] * 5

        p = _pipeline(llm, td)
        run = _make_run(criteria=["foo works"], td=td)
        await p.write_tests_and_implement(run)

        commit_calls = [c for c in td.git_calls if "commit" in c]
        assert len(commit_calls) >= 1
        assert "criterion 1" in commit_calls[0].lower() or "#42" in commit_calls[0]

    async def test_no_criteria_returns_failure(self) -> None:
        llm = FakeLLMClient()
        td = MasonToolDispatcher()
        p = _pipeline(llm, td)
        run = _make_run(criteria=[])
        result = await p.write_tests_and_implement(run)
        assert result.success is False

    async def test_locked_criteria_skipped(self) -> None:
        """Pre-locked criteria are skipped entirely."""
        llm = FakeLLMClient()
        llm.set_responses(
            _make_response(VALID_TEST_CODE),  # only for criterion 1
        )
        td = MasonToolDispatcher()
        td.pytest_outputs = ["1 passed in 0.1s"] * 5

        p = _pipeline(llm, td)
        run = _make_run(criteria=["already done", "needs work"], td=td)
        run._locked_criteria = {0}  # criterion 0 is locked
        result = await p.write_tests_and_implement(run)

        # Only criterion 1 should have been processed
        assert result.success is True
        assert 0 in run._locked_criteria  # still locked
        assert 1 in run._locked_criteria  # newly locked

    async def test_two_criteria_both_lock(self) -> None:
        """Two criteria, both pass → both locked."""
        llm = FakeLLMClient()
        llm.set_responses(
            _make_response(VALID_TEST_CODE),   # criterion 0: write test
            _make_response(VALID_TEST_CODE),   # criterion 1: append test
        )
        td = MasonToolDispatcher()
        td.pytest_outputs = [
            "1 passed in 0.1s",  # criterion 0: compilation check
            "1 passed in 0.1s",  # criterion 0: impl check (passes trivially)
            "1 passed in 0.1s",  # criterion 0: final check
            "2 passed in 0.1s",  # criterion 1: compilation check
            "2 passed in 0.1s",  # criterion 1: impl check
            "2 passed in 0.1s",  # criterion 1: final check
        ]

        p = _pipeline(llm, td)
        run = _make_run(criteria=["foo works", "bar works"], td=td)
        result = await p.write_tests_and_implement(run)

        assert result.success is True
        assert run._locked_criteria == {0, 1}

    async def test_impl_attempt_runs_when_test_fails(self) -> None:
        """When initial test run shows failures, impl is attempted."""
        llm = FakeLLMClient()
        llm.set_responses(
            _make_response(VALID_TEST_CODE),   # write test
            _make_response(VALID_IMPL_CODE),   # implement (first impl attempt)
        )
        td = MasonToolDispatcher()
        td.pytest_outputs = [
            "0 passed, 1 failed in 0.1s",   # compilation check: no syntax error
            "0 passed, 1 failed in 0.1s",   # first pytest in impl loop: test fails
            "1 passed in 0.1s",              # after impl: test passes
            "1 passed in 0.1s",              # final check
        ]

        p = _pipeline(llm, td)
        run = _make_run(criteria=["foo returns True"], td=td)
        result = await p.write_tests_and_implement(run)

        assert result.success is True
        # impl code was written
        impl_writes = [
            (t, a) for t, a in td.calls
            if t == "file_ops" and a.get("action") == "write"
            and "foo.py" in a.get("path", "")
        ]
        assert len(impl_writes) >= 1

    async def test_records_model_stats(self) -> None:
        """After a TDD run, model stats should be recorded."""
        # Reset class-level stats
        RuntimePipeline._model_stats.clear()

        llm = FakeLLMClient()
        llm.set_responses(_make_response(VALID_TEST_CODE))
        td = MasonToolDispatcher()
        td.pytest_outputs = ["1 passed in 0.1s"] * 5

        p = _pipeline(llm, td)
        run = _make_run(criteria=["foo works"], td=td)
        await p.write_tests_and_implement(run)

        stats = RuntimePipeline.get_model_stats()
        # The mason model should have at least one attempt recorded
        assert len(stats) >= 1

    async def test_posts_progress_to_issue(self) -> None:
        """Progress comments are posted to GitHub for each criterion."""
        llm = FakeLLMClient()
        llm.set_responses(_make_response(VALID_TEST_CODE))
        td = MasonToolDispatcher()
        td.pytest_outputs = ["1 passed in 0.1s"] * 5

        p = _pipeline(llm, td)
        run = _make_run(criteria=["foo works"], td=td)
        await p.write_tests_and_implement(run)

        github_posts = [
            (t, a) for t, a in td.calls
            if t == "github" and a.get("action") == "post_pr_comment"
        ]
        assert len(github_posts) >= 1
