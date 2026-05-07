"""Tests for module-level helper functions in agents/base.py."""

from stronghold.agents.base import _detect_tool_failures


class TestDetectToolFailures:
    def test_empty_history_is_not_failure(self) -> None:
        assert _detect_tool_failures([]) is False

    def test_successful_result_is_not_failure(self) -> None:
        history = [{"tool_name": "read_file", "result": "file contents here"}]
        assert _detect_tool_failures(history) is False

    def test_error_prefix_detected(self) -> None:
        history = [{"tool_name": "run_pytest", "result": "Error: 3 tests failed"}]
        assert _detect_tool_failures(history) is True

    def test_lowercase_error_in_result_detected(self) -> None:
        history = [{"tool_name": "run_mypy", "result": "found error in type check"}]
        assert _detect_tool_failures(history) is True

    def test_mixed_history_any_failure_counts(self) -> None:
        history = [
            {"tool_name": "read_file", "result": "ok"},
            {"tool_name": "run_pytest", "result": "Error: 1 test failed"},
        ]
        assert _detect_tool_failures(history) is True

    def test_all_successful_returns_false(self) -> None:
        history = [
            {"tool_name": "read_file", "result": "contents"},
            {"tool_name": "list_files", "result": "['a.py', 'b.py']"},
        ]
        assert _detect_tool_failures(history) is False

    def test_missing_result_key_not_failure(self) -> None:
        history = [{"tool_name": "read_file"}]
        assert _detect_tool_failures(history) is False

    def test_error_beyond_50_chars_not_detected(self) -> None:
        # "error" appearing after the first 50 chars is not flagged
        history = [{"tool_name": "tool", "result": "x" * 60 + "error here"}]
        assert _detect_tool_failures(history) is False
