"""Tests for FileOpsExecutor — sandboxed read/write/list/mkdir/exists."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from stronghold.tools.file_ops import FILE_OPS_TOOL_DEF, FileOpsExecutor


@pytest.fixture
def workspace(tmp_path: Path) -> Path:
    """A fresh sandbox directory per test."""
    ws = tmp_path / "ws"
    ws.mkdir()
    return ws


@pytest.fixture
def executor() -> FileOpsExecutor:
    return FileOpsExecutor()


# ---------------------------------------------------------------------------
# Definition + name
# ---------------------------------------------------------------------------


class TestMeta:
    def test_executor_name(self, executor: FileOpsExecutor) -> None:
        assert executor.name == "file_ops"

    def test_tool_definition_declares_all_actions(self) -> None:
        enum = FILE_OPS_TOOL_DEF.parameters["properties"]["action"]["enum"]
        assert set(enum) == {"read", "write", "list", "mkdir", "exists"}

    def test_tool_definition_requires_action_and_path(self) -> None:
        assert set(FILE_OPS_TOOL_DEF.parameters["required"]) == {"action", "path"}


# ---------------------------------------------------------------------------
# Precondition failures
# ---------------------------------------------------------------------------


class TestPreconditions:
    @pytest.mark.asyncio
    async def test_missing_workspace_errors(
        self, executor: FileOpsExecutor
    ) -> None:
        result = await executor.execute({"action": "read", "path": "x"})
        assert result.success is False
        assert "workspace" in (result.error or "").lower()

    @pytest.mark.asyncio
    async def test_nonexistent_workspace_errors(
        self, executor: FileOpsExecutor, tmp_path: Path
    ) -> None:
        bogus = tmp_path / "does-not-exist"
        result = await executor.execute(
            {"action": "read", "path": "x", "workspace": str(bogus)}
        )
        assert result.success is False
        assert "not found" in (result.error or "").lower()

    @pytest.mark.asyncio
    async def test_path_escape_via_dotdot_blocked(
        self, executor: FileOpsExecutor, workspace: Path, tmp_path: Path
    ) -> None:
        """`../secret` must not escape the workspace root."""
        (tmp_path / "secret").write_text("nope")
        result = await executor.execute(
            {
                "action": "read",
                "path": "../secret",
                "workspace": str(workspace),
            }
        )
        assert result.success is False
        assert "escape" in (result.error or "").lower()

    @pytest.mark.asyncio
    async def test_unknown_action_errors(
        self, executor: FileOpsExecutor, workspace: Path
    ) -> None:
        result = await executor.execute(
            {"action": "rm", "path": "x", "workspace": str(workspace)}
        )
        assert result.success is False
        assert "unknown action" in (result.error or "").lower()


# ---------------------------------------------------------------------------
# read / write / exists
# ---------------------------------------------------------------------------


class TestReadWrite:
    @pytest.mark.asyncio
    async def test_write_then_read_roundtrips(
        self, executor: FileOpsExecutor, workspace: Path
    ) -> None:
        w = await executor.execute(
            {
                "action": "write",
                "path": "note.txt",
                "content": "hello\n",
                "workspace": str(workspace),
            }
        )
        assert w.success is True
        payload = json.loads(w.content)
        assert payload["status"] == "ok"
        assert payload["path"] == "note.txt"
        assert payload["bytes"] == 6

        r = await executor.execute(
            {"action": "read", "path": "note.txt", "workspace": str(workspace)}
        )
        assert r.success is True
        assert r.content == "hello\n"

    @pytest.mark.asyncio
    async def test_write_creates_parent_dirs(
        self, executor: FileOpsExecutor, workspace: Path
    ) -> None:
        result = await executor.execute(
            {
                "action": "write",
                "path": "deep/nested/dir/file.txt",
                "content": "x",
                "workspace": str(workspace),
            }
        )
        assert result.success is True
        assert (workspace / "deep/nested/dir/file.txt").read_text() == "x"

    @pytest.mark.asyncio
    async def test_read_missing_file_errors(
        self, executor: FileOpsExecutor, workspace: Path
    ) -> None:
        result = await executor.execute(
            {"action": "read", "path": "absent.txt", "workspace": str(workspace)}
        )
        assert result.success is False
        assert "not found" in (result.error or "").lower()

    @pytest.mark.asyncio
    async def test_exists_reports_file(
        self, executor: FileOpsExecutor, workspace: Path
    ) -> None:
        (workspace / "present.txt").write_text("x")
        result = await executor.execute(
            {"action": "exists", "path": "present.txt", "workspace": str(workspace)}
        )
        assert result.success is True
        assert json.loads(result.content) == {"exists": True, "is_file": True}

    @pytest.mark.asyncio
    async def test_exists_reports_missing(
        self, executor: FileOpsExecutor, workspace: Path
    ) -> None:
        result = await executor.execute(
            {"action": "exists", "path": "nope.txt", "workspace": str(workspace)}
        )
        assert result.success is True
        assert json.loads(result.content) == {"exists": False, "is_file": False}

    @pytest.mark.asyncio
    async def test_exists_reports_directory_as_not_file(
        self, executor: FileOpsExecutor, workspace: Path
    ) -> None:
        (workspace / "subdir").mkdir()
        result = await executor.execute(
            {"action": "exists", "path": "subdir", "workspace": str(workspace)}
        )
        assert result.success is True
        assert json.loads(result.content) == {"exists": True, "is_file": False}


# ---------------------------------------------------------------------------
# list / mkdir
# ---------------------------------------------------------------------------


class TestListAndMkdir:
    @pytest.mark.asyncio
    async def test_list_recursive_sorted(
        self, executor: FileOpsExecutor, workspace: Path
    ) -> None:
        (workspace / "a.txt").write_text("1")
        (workspace / "b.txt").write_text("2")
        (workspace / "dir").mkdir()
        (workspace / "dir" / "c.txt").write_text("3")
        result = await executor.execute(
            {"action": "list", "path": ".", "workspace": str(workspace)}
        )
        assert result.success is True
        entries = json.loads(result.content)
        assert entries == sorted(entries)
        assert "a.txt" in entries
        assert "b.txt" in entries
        assert "dir/c.txt" in entries

    @pytest.mark.asyncio
    async def test_list_excludes_git_directory(
        self, executor: FileOpsExecutor, workspace: Path
    ) -> None:
        (workspace / ".git").mkdir()
        (workspace / ".git" / "HEAD").write_text("ref")
        (workspace / "real.txt").write_text("x")
        result = await executor.execute(
            {"action": "list", "path": ".", "workspace": str(workspace)}
        )
        entries = json.loads(result.content)
        assert "real.txt" in entries
        assert not any(".git" in e for e in entries)

    @pytest.mark.asyncio
    async def test_list_caps_at_200_entries(
        self, executor: FileOpsExecutor, workspace: Path
    ) -> None:
        for i in range(250):
            (workspace / f"f{i:04d}.txt").write_text("x")
        result = await executor.execute(
            {"action": "list", "path": ".", "workspace": str(workspace)}
        )
        entries = json.loads(result.content)
        assert len(entries) == 200

    @pytest.mark.asyncio
    async def test_list_on_non_directory_errors(
        self, executor: FileOpsExecutor, workspace: Path
    ) -> None:
        (workspace / "file.txt").write_text("x")
        result = await executor.execute(
            {"action": "list", "path": "file.txt", "workspace": str(workspace)}
        )
        assert result.success is False
        assert "not a directory" in (result.error or "").lower()

    @pytest.mark.asyncio
    async def test_mkdir_creates_nested_directories(
        self, executor: FileOpsExecutor, workspace: Path
    ) -> None:
        result = await executor.execute(
            {"action": "mkdir", "path": "a/b/c", "workspace": str(workspace)}
        )
        assert result.success is True
        assert json.loads(result.content) == {"status": "ok"}
        assert (workspace / "a" / "b" / "c").is_dir()

    @pytest.mark.asyncio
    async def test_mkdir_is_idempotent(
        self, executor: FileOpsExecutor, workspace: Path
    ) -> None:
        (workspace / "already").mkdir()
        result = await executor.execute(
            {"action": "mkdir", "path": "already", "workspace": str(workspace)}
        )
        assert result.success is True


# ---------------------------------------------------------------------------
# Exception path — generic try/except wrapper
# ---------------------------------------------------------------------------


class TestExceptionHandling:
    @pytest.mark.asyncio
    async def test_unreadable_file_surfaces_error(
        self, executor: FileOpsExecutor, workspace: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """If read_text raises, the executor must return a failure
        ToolResult rather than propagating the exception."""
        (workspace / "f.txt").write_text("x")
        real_read_text = Path.read_text

        def boom(self: Path, *args: object, **kwargs: object) -> str:
            if self.name == "f.txt":
                msg = "simulated decode error"
                raise OSError(msg)
            return real_read_text(self, *args, **kwargs)

        monkeypatch.setattr(Path, "read_text", boom)
        result = await executor.execute(
            {"action": "read", "path": "f.txt", "workspace": str(workspace)}
        )
        assert result.success is False
        assert "simulated decode error" in (result.error or "")
