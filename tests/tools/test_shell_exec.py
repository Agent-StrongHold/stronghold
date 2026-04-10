"""Tests for ShellExecutor + QualityGateExecutor."""

from __future__ import annotations

import json
import tempfile
from pathlib import Path

import pytest

from stronghold.tools.shell_exec import (
    RUN_BANDIT_DEF,
    RUN_MYPY_DEF,
    RUN_PYTEST_DEF,
    RUN_RUFF_CHECK_DEF,
    RUN_RUFF_FORMAT_DEF,
    SHELL_TOOL_DEF,
    QualityGateExecutor,
    ShellExecutor,
    _ALLOWED_PREFIXES,
    _BLOCKED_PATTERNS,
)


@pytest.fixture
def workspace() -> Path:
    return Path(tempfile.mkdtemp())


async def test_name() -> None:
    assert ShellExecutor().name == "shell"


async def test_tool_defs_exist() -> None:
    assert SHELL_TOOL_DEF.name == "shell"
    assert RUN_PYTEST_DEF.name == "run_pytest"
    assert RUN_RUFF_CHECK_DEF.name == "run_ruff_check"
    assert RUN_RUFF_FORMAT_DEF.name == "run_ruff_format"
    assert RUN_MYPY_DEF.name == "run_mypy"
    assert RUN_BANDIT_DEF.name == "run_bandit"


async def test_allowed_prefixes_defined() -> None:
    assert "pytest" in _ALLOWED_PREFIXES
    assert "ruff" in _ALLOWED_PREFIXES


async def test_blocked_patterns_defined() -> None:
    assert "rm -rf /" in _BLOCKED_PATTERNS
    assert any("curl" in p for p in _BLOCKED_PATTERNS)


async def test_missing_workspace_error() -> None:
    ex = ShellExecutor()
    result = await ex.execute({"command": "echo hi"})
    assert result.success is False
    assert "workspace" in result.error


async def test_nonexistent_workspace_error() -> None:
    ex = ShellExecutor()
    result = await ex.execute({"command": "echo hi", "workspace": "/nope"})
    assert result.success is False
    assert "not found" in result.error


async def test_empty_command_error(workspace: Path) -> None:
    ex = ShellExecutor()
    result = await ex.execute({"command": "   ", "workspace": str(workspace)})
    assert result.success is False
    assert "empty" in result.error.lower()


async def test_disallowed_command_blocked(workspace: Path) -> None:
    ex = ShellExecutor()
    result = await ex.execute({"command": "sudo rm -rf /", "workspace": str(workspace)})
    assert result.success is False
    assert "not allowed" in result.error


async def test_blocked_pattern_rejected(workspace: Path) -> None:
    ex = ShellExecutor()
    # rm starts with 'rm ' — that's not in allowed prefixes so this test hits allowlist first
    # Use an allowed prefix with a blocked pattern
    result = await ex.execute({
        "command": "ls; rm -rf /", "workspace": str(workspace),
    })
    assert result.success is False
    # Could be blocked by either allowlist (semicolon breaks prefix match) or pattern check
    assert "allowed" in result.error or "blocked" in result.error


async def test_echo_succeeds(workspace: Path) -> None:
    ex = ShellExecutor()
    result = await ex.execute({"command": "echo hello", "workspace": str(workspace)})
    assert result.success is True
    data = json.loads(result.content)
    assert data["passed"] is True
    assert data["exit_code"] == 0
    assert "hello" in data["stdout"]


async def test_ls_succeeds(workspace: Path) -> None:
    (workspace / "file1.txt").write_text("x")
    ex = ShellExecutor()
    result = await ex.execute({"command": "ls", "workspace": str(workspace)})
    assert result.success is True
    data = json.loads(result.content)
    assert "file1.txt" in data["stdout"]


async def test_nonzero_exit_passed_false(workspace: Path) -> None:
    ex = ShellExecutor()
    result = await ex.execute({
        "command": "grep nonexistent /dev/null",
        "workspace": str(workspace),
    })
    assert result.success is True  # Tool ran
    data = json.loads(result.content)
    # grep returns 1 if no match
    assert data["passed"] is False
    assert data["exit_code"] != 0


async def test_stdout_truncated_to_3000(workspace: Path) -> None:
    """Long output should be truncated to last 3000 chars."""
    ex = ShellExecutor()
    # echo 4000 'x' characters
    result = await ex.execute({
        "command": "echo " + ("x" * 5000),
        "workspace": str(workspace),
    })
    data = json.loads(result.content)
    assert len(data["stdout"]) <= 3001  # 3000 + newline tolerance


# ── QualityGateExecutor ─────────────────────────────────────────────


async def test_quality_gate_make_executor(workspace: Path) -> None:
    shell = ShellExecutor()
    qg = QualityGateExecutor(shell)
    ex = qg.make_executor("echo gate-ran")
    result = await ex({"workspace": str(workspace)})
    assert result.success is True
    data = json.loads(result.content)
    assert "gate-ran" in data["stdout"]


async def test_quality_gate_template_substitution(workspace: Path) -> None:
    """{path} in template is replaced with path arg."""
    shell = ShellExecutor()
    qg = QualityGateExecutor(shell)
    ex = qg.make_executor("echo testing {path}")
    result = await ex({"workspace": str(workspace), "path": "tests/unit"})
    data = json.loads(result.content)
    assert "testing tests/unit" in data["stdout"]


async def test_quality_gate_no_path_template(workspace: Path) -> None:
    """Template without {path} doesn't require path arg."""
    shell = ShellExecutor()
    qg = QualityGateExecutor(shell)
    ex = qg.make_executor("echo no-template")
    result = await ex({"workspace": str(workspace)})
    assert result.success is True
