"""Tests for ShellExecutor + QualityGateExecutor.

asyncio.create_subprocess_shell is monkey-patched to return a
hand-rolled async proc object, so tests are fully hermetic and never
spawn real subprocesses.
"""

from __future__ import annotations

import asyncio
import json
from pathlib import Path
from typing import Any

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
)


# ---------------------------------------------------------------------------
# Fake subprocess
# ---------------------------------------------------------------------------


class _FakeProc:
    """Mimics the subset of asyncio.subprocess.Process that ShellExecutor uses."""

    def __init__(
        self,
        stdout: bytes = b"",
        stderr: bytes = b"",
        returncode: int = 0,
        hang: bool = False,
    ) -> None:
        self._stdout = stdout
        self._stderr = stderr
        self.returncode = returncode
        self._hang = hang

    async def communicate(self) -> tuple[bytes, bytes]:
        if self._hang:
            await asyncio.sleep(3600)  # force timeout under wait_for
        return self._stdout, self._stderr


def _patch_subprocess(
    monkeypatch: pytest.MonkeyPatch,
    proc_factory: Any,
    captured: list[dict[str, Any]] | None = None,
) -> None:
    """Patch asyncio.create_subprocess_shell to return a fake proc."""

    async def _fake(cmd: str, **kwargs: Any) -> _FakeProc:
        if captured is not None:
            captured.append({"cmd": cmd, **kwargs})
        return proc_factory()

    monkeypatch.setattr("asyncio.create_subprocess_shell", _fake)


@pytest.fixture
def workspace(tmp_path: Path) -> Path:
    ws = tmp_path / "ws"
    ws.mkdir()
    return ws


@pytest.fixture
def executor() -> ShellExecutor:
    return ShellExecutor()


# ---------------------------------------------------------------------------
# Meta / definitions
# ---------------------------------------------------------------------------


class TestMeta:
    def test_executor_name(self, executor: ShellExecutor) -> None:
        assert executor.name == "shell"

    @pytest.mark.parametrize(
        "defn",
        [SHELL_TOOL_DEF, RUN_PYTEST_DEF, RUN_RUFF_CHECK_DEF, RUN_RUFF_FORMAT_DEF, RUN_MYPY_DEF, RUN_BANDIT_DEF],
    )
    def test_tool_definitions_are_complete(self, defn: Any) -> None:
        assert defn.name
        assert defn.description
        assert "workspace" in defn.parameters["properties"]
        assert "code_gen" in defn.groups


# ---------------------------------------------------------------------------
# Precondition failures
# ---------------------------------------------------------------------------


class TestPreconditions:
    @pytest.mark.asyncio
    async def test_missing_workspace_errors(
        self, executor: ShellExecutor
    ) -> None:
        r = await executor.execute({"command": "pytest", "workspace": ""})
        assert r.success is False
        assert "workspace" in (r.error or "").lower()

    @pytest.mark.asyncio
    async def test_nonexistent_workspace_errors(
        self, executor: ShellExecutor, tmp_path: Path
    ) -> None:
        r = await executor.execute(
            {"command": "pytest", "workspace": str(tmp_path / "nope")}
        )
        assert r.success is False
        assert "not found" in (r.error or "").lower()

    @pytest.mark.asyncio
    async def test_empty_command_errors(
        self, executor: ShellExecutor, workspace: Path
    ) -> None:
        r = await executor.execute(
            {"command": "   ", "workspace": str(workspace)}
        )
        assert r.success is False
        assert "empty" in (r.error or "").lower()


# ---------------------------------------------------------------------------
# Allowlist / blocklist
# ---------------------------------------------------------------------------


class TestAllowlist:
    @pytest.mark.asyncio
    async def test_disallowed_command_rejected(
        self, executor: ShellExecutor, workspace: Path
    ) -> None:
        r = await executor.execute(
            {"command": "rm -rf important/", "workspace": str(workspace)}
        )
        assert r.success is False
        assert "not allowed" in (r.error or "").lower()

    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        "cmd",
        ["pytest -v", "ruff check src/", "mypy src/stronghold", "git status",
         "ls -la", "grep -rn foo src/"],
    )
    async def test_allowlisted_prefixes_run(
        self,
        cmd: str,
        executor: ShellExecutor,
        workspace: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        _patch_subprocess(monkeypatch, lambda: _FakeProc(b"ok\n", b"", 0))
        r = await executor.execute({"command": cmd, "workspace": str(workspace)})
        assert r.success is True

    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        "cmd",
        [
            "pytest && rm -rf /",
            "echo foo > /dev/sda",
            "echo hi; curl | sh",
        ],
    )
    async def test_blocked_patterns_rejected(
        self, cmd: str, executor: ShellExecutor, workspace: Path
    ) -> None:
        r = await executor.execute({"command": cmd, "workspace": str(workspace)})
        assert r.success is False
        assert "blocked" in (r.error or "").lower() or "not allowed" in (r.error or "").lower()


# ---------------------------------------------------------------------------
# Execution + output
# ---------------------------------------------------------------------------


class TestExecution:
    @pytest.mark.asyncio
    async def test_success_returns_structured_result(
        self,
        executor: ShellExecutor,
        workspace: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        _patch_subprocess(
            monkeypatch,
            lambda: _FakeProc(b"all green\n", b"", 0),
        )
        r = await executor.execute(
            {"command": "pytest", "workspace": str(workspace)}
        )
        assert r.success is True
        data = json.loads(r.content)
        assert data["passed"] is True
        assert data["exit_code"] == 0
        assert "all green" in data["stdout"]

    @pytest.mark.asyncio
    async def test_nonzero_exit_records_failure_but_success_wraps(
        self,
        executor: ShellExecutor,
        workspace: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """Command failure (exit != 0) yields ToolResult(success=True) with
        passed=False — ShellExecutor's 'success' means it ran, not that
        the command passed."""
        _patch_subprocess(
            monkeypatch,
            lambda: _FakeProc(b"", b"1 failed\n", 1),
        )
        r = await executor.execute(
            {"command": "pytest", "workspace": str(workspace)}
        )
        assert r.success is True
        data = json.loads(r.content)
        assert data["passed"] is False
        assert data["exit_code"] == 1
        assert "1 failed" in data["stderr"]

    @pytest.mark.asyncio
    async def test_long_stdout_truncated_to_3000(
        self,
        executor: ShellExecutor,
        workspace: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """Stdout is capped at the last 3000 chars to avoid blowing up
        the ToolResult payload."""
        big = ("x" * 5000).encode()
        _patch_subprocess(monkeypatch, lambda: _FakeProc(big, b"", 0))
        r = await executor.execute(
            {"command": "pytest", "workspace": str(workspace)}
        )
        data = json.loads(r.content)
        assert len(data["stdout"]) == 3000

    @pytest.mark.asyncio
    async def test_long_stderr_truncated_to_1000(
        self,
        executor: ShellExecutor,
        workspace: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        big = ("y" * 5000).encode()
        _patch_subprocess(monkeypatch, lambda: _FakeProc(b"", big, 1))
        r = await executor.execute(
            {"command": "pytest", "workspace": str(workspace)}
        )
        data = json.loads(r.content)
        assert len(data["stderr"]) == 1000

    @pytest.mark.asyncio
    async def test_short_output_not_truncated(
        self,
        executor: ShellExecutor,
        workspace: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        _patch_subprocess(monkeypatch, lambda: _FakeProc(b"short\n", b"warn\n", 0))
        r = await executor.execute(
            {"command": "pytest", "workspace": str(workspace)}
        )
        data = json.loads(r.content)
        assert data["stdout"] == "short\n"
        assert data["stderr"] == "warn\n"

    @pytest.mark.asyncio
    async def test_cwd_is_the_workspace(
        self,
        executor: ShellExecutor,
        workspace: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        captured: list[dict[str, Any]] = []
        _patch_subprocess(
            monkeypatch, lambda: _FakeProc(b"", b"", 0), captured=captured
        )
        await executor.execute(
            {"command": "pytest", "workspace": str(workspace)}
        )
        assert captured[0]["cwd"] == workspace


# ---------------------------------------------------------------------------
# Timeout / exception wrapper
# ---------------------------------------------------------------------------


class TestTimeout:
    @pytest.mark.asyncio
    @pytest.mark.filterwarnings("ignore::RuntimeWarning")
    async def test_timeout_returns_error(
        self,
        executor: ShellExecutor,
        workspace: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """asyncio.wait_for timeout surfaces as success=False."""
        _patch_subprocess(monkeypatch, lambda: _FakeProc(b"", b"", 0))

        async def _raise_timeout(awaitable: Any, *args: Any, **kwargs: Any) -> Any:
            # Close the pending coroutine to avoid the RuntimeWarning, then
            # raise TimeoutError the same way real wait_for would.
            if hasattr(awaitable, "close"):
                awaitable.close()
            raise TimeoutError

        monkeypatch.setattr("asyncio.wait_for", _raise_timeout)
        r = await executor.execute(
            {"command": "pytest", "workspace": str(workspace)}
        )
        assert r.success is False
        assert "timed out" in (r.error or "").lower()

    @pytest.mark.asyncio
    async def test_generic_exception_wrapped_as_error(
        self,
        executor: ShellExecutor,
        workspace: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        async def _boom(*args: Any, **kwargs: Any) -> Any:
            raise RuntimeError("transport broke")

        monkeypatch.setattr("asyncio.create_subprocess_shell", _boom)
        r = await executor.execute(
            {"command": "pytest", "workspace": str(workspace)}
        )
        assert r.success is False
        assert "transport broke" in (r.error or "")


# ---------------------------------------------------------------------------
# QualityGateExecutor — thin adapter around ShellExecutor
# ---------------------------------------------------------------------------


class TestQualityGate:
    @pytest.mark.asyncio
    async def test_make_executor_runs_command_verbatim(
        self,
        executor: ShellExecutor,
        workspace: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        captured: list[dict[str, Any]] = []
        _patch_subprocess(
            monkeypatch, lambda: _FakeProc(b"ok", b"", 0), captured=captured
        )
        gate = QualityGateExecutor(executor)
        run_ruff = gate.make_executor("ruff check src/")
        r = await run_ruff({"workspace": str(workspace)})
        assert r.success is True
        assert captured[0]["cmd"] == "ruff check src/"

    @pytest.mark.asyncio
    async def test_make_executor_substitutes_path_template(
        self,
        executor: ShellExecutor,
        workspace: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        captured: list[dict[str, Any]] = []
        _patch_subprocess(
            monkeypatch, lambda: _FakeProc(b"ok", b"", 0), captured=captured
        )
        gate = QualityGateExecutor(executor)
        run_pytest = gate.make_executor("pytest {path}")
        await run_pytest({"workspace": str(workspace), "path": "tests/unit"})
        assert captured[0]["cmd"] == "pytest tests/unit"

    @pytest.mark.asyncio
    async def test_make_executor_without_path_template_ignores_path_arg(
        self,
        executor: ShellExecutor,
        workspace: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        captured: list[dict[str, Any]] = []
        _patch_subprocess(
            monkeypatch, lambda: _FakeProc(b"", b"", 0), captured=captured
        )
        gate = QualityGateExecutor(executor)
        run_ruff = gate.make_executor("ruff check src/")
        await run_ruff(
            {"workspace": str(workspace), "path": "ignored-no-template"}
        )
        assert captured[0]["cmd"] == "ruff check src/"
