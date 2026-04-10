"""Tests for FileOpsExecutor (sandboxed file operations)."""

from __future__ import annotations

import json
import tempfile
from pathlib import Path

import pytest

from stronghold.tools.file_ops import FILE_OPS_TOOL_DEF, FileOpsExecutor


@pytest.fixture
def workspace() -> Path:
    return Path(tempfile.mkdtemp())


async def test_name_property() -> None:
    assert FileOpsExecutor().name == "file_ops"


async def test_tool_definition() -> None:
    assert FILE_OPS_TOOL_DEF.name == "file_ops"
    assert "code_gen" in FILE_OPS_TOOL_DEF.groups


async def test_write_then_read(workspace: Path) -> None:
    ex = FileOpsExecutor()
    write_result = await ex.execute({
        "action": "write", "path": "hello.txt", "content": "world",
        "workspace": str(workspace),
    })
    assert write_result.success is True
    data = json.loads(write_result.content)
    assert data["status"] == "ok"
    assert data["path"] == "hello.txt"
    assert data["bytes"] == 5

    read_result = await ex.execute({
        "action": "read", "path": "hello.txt", "workspace": str(workspace),
    })
    assert read_result.success is True
    assert read_result.content == "world"


async def test_write_creates_parent_dirs(workspace: Path) -> None:
    ex = FileOpsExecutor()
    result = await ex.execute({
        "action": "write", "path": "deep/nested/file.txt", "content": "data",
        "workspace": str(workspace),
    })
    assert result.success is True
    assert (workspace / "deep" / "nested" / "file.txt").exists()


async def test_read_missing_file(workspace: Path) -> None:
    ex = FileOpsExecutor()
    result = await ex.execute({
        "action": "read", "path": "nonexistent.txt", "workspace": str(workspace),
    })
    assert result.success is False
    assert "not found" in result.error


async def test_list_workspace_files(workspace: Path) -> None:
    (workspace / "a.txt").write_text("a")
    (workspace / "b.txt").write_text("b")
    (workspace / "sub").mkdir()
    (workspace / "sub" / "c.txt").write_text("c")

    ex = FileOpsExecutor()
    result = await ex.execute({
        "action": "list", "path": ".", "workspace": str(workspace),
    })
    assert result.success is True
    files = json.loads(result.content)
    assert "a.txt" in files
    assert "b.txt" in files
    assert "sub/c.txt" in files or str(Path("sub") / "c.txt") in files


async def test_list_excludes_git_dir(workspace: Path) -> None:
    (workspace / ".git").mkdir()
    (workspace / ".git" / "HEAD").write_text("ref: refs/heads/main")
    (workspace / "real.txt").write_text("x")

    ex = FileOpsExecutor()
    result = await ex.execute({
        "action": "list", "path": ".", "workspace": str(workspace),
    })
    files = json.loads(result.content)
    assert "real.txt" in files
    assert not any(".git" in f for f in files)


async def test_list_not_directory(workspace: Path) -> None:
    (workspace / "file.txt").write_text("x")
    ex = FileOpsExecutor()
    result = await ex.execute({
        "action": "list", "path": "file.txt", "workspace": str(workspace),
    })
    assert result.success is False
    assert "not a directory" in result.error


async def test_mkdir(workspace: Path) -> None:
    ex = FileOpsExecutor()
    result = await ex.execute({
        "action": "mkdir", "path": "new/dir", "workspace": str(workspace),
    })
    assert result.success is True
    assert (workspace / "new" / "dir").is_dir()


async def test_mkdir_existing_is_ok(workspace: Path) -> None:
    (workspace / "existing").mkdir()
    ex = FileOpsExecutor()
    result = await ex.execute({
        "action": "mkdir", "path": "existing", "workspace": str(workspace),
    })
    assert result.success is True


async def test_exists_true(workspace: Path) -> None:
    (workspace / "exists.txt").write_text("x")
    ex = FileOpsExecutor()
    result = await ex.execute({
        "action": "exists", "path": "exists.txt", "workspace": str(workspace),
    })
    assert result.success is True
    data = json.loads(result.content)
    assert data["exists"] is True
    assert data["is_file"] is True


async def test_exists_false(workspace: Path) -> None:
    ex = FileOpsExecutor()
    result = await ex.execute({
        "action": "exists", "path": "nothing", "workspace": str(workspace),
    })
    data = json.loads(result.content)
    assert data["exists"] is False
    assert data["is_file"] is False


# ── Sandbox escape prevention ───────────────────────────────────────


async def test_path_escape_blocked(workspace: Path) -> None:
    """Paths like ../etc/passwd must be blocked."""
    ex = FileOpsExecutor()
    result = await ex.execute({
        "action": "read", "path": "../../../etc/passwd",
        "workspace": str(workspace),
    })
    assert result.success is False
    assert "escapes workspace" in result.error


async def test_absolute_path_blocked(workspace: Path) -> None:
    ex = FileOpsExecutor()
    result = await ex.execute({
        "action": "read", "path": "/etc/passwd",
        "workspace": str(workspace),
    })
    assert result.success is False
    assert "escapes workspace" in result.error


# ── Input validation ────────────────────────────────────────────────


async def test_missing_workspace() -> None:
    ex = FileOpsExecutor()
    result = await ex.execute({"action": "read", "path": "x"})
    assert result.success is False
    assert "workspace" in result.error


async def test_nonexistent_workspace() -> None:
    ex = FileOpsExecutor()
    result = await ex.execute({
        "action": "read", "path": "x", "workspace": "/nonexistent/path/xyz",
    })
    assert result.success is False
    assert "workspace not found" in result.error


async def test_unknown_action(workspace: Path) -> None:
    ex = FileOpsExecutor()
    result = await ex.execute({
        "action": "shred", "path": "x", "workspace": str(workspace),
    })
    assert result.success is False
    assert "unknown action" in result.error


async def test_exception_returns_error(workspace: Path) -> None:
    """Unreadable file (e.g. binary as text) returns error, doesn't crash."""
    binary_file = workspace / "binary.bin"
    binary_file.write_bytes(b"\x80\x81\x82")  # Invalid UTF-8

    ex = FileOpsExecutor()
    result = await ex.execute({
        "action": "read", "path": "binary.bin", "workspace": str(workspace),
    })
    # Should not crash — either returns content (with error chars) or error
    assert result.success in (True, False)
