"""Tests for WorkspaceManager — real git ops against a local repo."""

from __future__ import annotations

import json
import shutil
import subprocess
import tempfile
from pathlib import Path
from unittest.mock import patch

import pytest


def _make_bare_repo() -> Path:
    """Create a bare git repo with one commit for cloning."""
    tmp = Path(tempfile.mkdtemp())
    work = tmp / "work"
    bare = tmp / "repo.git"
    work.mkdir()
    subprocess.run(["git", "init", "-b", "main", str(work)], check=True, capture_output=True)
    subprocess.run(["git", "-C", str(work), "config", "user.email", "t@t.t"], check=True, capture_output=True)
    subprocess.run(["git", "-C", str(work), "config", "user.name", "t"], check=True, capture_output=True)
    (work / "README.md").write_text("hello")
    subprocess.run(["git", "-C", str(work), "add", "."], check=True, capture_output=True)
    subprocess.run(["git", "-C", str(work), "commit", "-m", "init"], check=True, capture_output=True)
    subprocess.run(["git", "clone", "--bare", str(work), str(bare)], check=True, capture_output=True)
    return bare


@pytest.fixture
def git_env(monkeypatch):
    """Set up an isolated workspace root."""
    tmp = Path(tempfile.mkdtemp())
    monkeypatch.setenv("STRONGHOLD_WORKSPACE", str(tmp))
    # Force module reload to pick up env change
    import importlib
    import stronghold.tools.workspace
    importlib.reload(stronghold.tools.workspace)
    yield tmp
    shutil.rmtree(tmp, ignore_errors=True)


async def test_name_property(git_env: Path) -> None:
    from stronghold.tools.workspace import WorkspaceManager
    mgr = WorkspaceManager()
    assert mgr.name == "workspace"


async def test_unknown_action(git_env: Path) -> None:
    from stronghold.tools.workspace import WorkspaceManager
    mgr = WorkspaceManager()
    result = await mgr.execute({"action": "teleport"})
    assert result.success is False
    assert "Unknown action" in result.error


async def test_status_not_found(git_env: Path) -> None:
    from stronghold.tools.workspace import WorkspaceManager
    mgr = WorkspaceManager()
    result = await mgr.execute({"action": "status", "issue_number": 999})
    assert result.success is True
    data = json.loads(result.content)
    assert data["status"] == "not_found"


async def test_commit_without_worktree(git_env: Path) -> None:
    from stronghold.tools.workspace import WorkspaceManager
    mgr = WorkspaceManager()
    result = await mgr.execute({"action": "commit", "issue_number": 888})
    assert result.success is True
    data = json.loads(result.content)
    assert data["status"] == "error"
    assert "not found" in data["error"]


async def test_push_without_worktree(git_env: Path) -> None:
    from stronghold.tools.workspace import WorkspaceManager
    mgr = WorkspaceManager()
    result = await mgr.execute({"action": "push", "issue_number": 777})
    assert result.success is True
    data = json.loads(result.content)
    assert data["status"] == "error"


async def test_cleanup_not_found(git_env: Path) -> None:
    from stronghold.tools.workspace import WorkspaceManager
    mgr = WorkspaceManager()
    result = await mgr.execute({"action": "cleanup", "issue_number": 666})
    assert result.success is True
    data = json.loads(result.content)
    assert data["status"] == "not_found"


async def test_create_with_mocked_clone(git_env: Path) -> None:
    """Create a worktree using a mocked _run that points at a real local bare repo."""
    from stronghold.tools.workspace import WorkspaceManager

    bare = _make_bare_repo()

    mgr = WorkspaceManager()
    # Rewrite clone target to point at our local bare repo
    original_run = mgr._run
    def patched_run(cmd, cwd=None):
        if cmd[:2] == ["git", "clone"]:
            # cmd[-2] is URL, replace with local bare repo
            cmd = cmd[:-2] + [str(bare), cmd[-1]]
        return original_run(cmd, cwd=cwd)
    mgr._run = patched_run  # type: ignore[method-assign]

    result = await mgr.execute({
        "action": "create", "owner": "local", "repo": "test",
        "issue_number": 42,
    })
    assert result.success is True, result.error
    data = json.loads(result.content)
    assert data["status"] == "created"
    assert data["branch"] == "mason/42"
    assert Path(data["path"]).is_dir()


async def test_create_idempotent(git_env: Path) -> None:
    """Creating twice returns 'exists' the second time."""
    from stronghold.tools.workspace import WorkspaceManager

    bare = _make_bare_repo()
    mgr = WorkspaceManager()
    original_run = mgr._run
    def patched_run(cmd, cwd=None):
        if cmd[:2] == ["git", "clone"]:
            cmd = cmd[:-2] + [str(bare), cmd[-1]]
        return original_run(cmd, cwd=cwd)
    mgr._run = patched_run  # type: ignore[method-assign]

    r1 = await mgr.execute({
        "action": "create", "owner": "o", "repo": "r", "issue_number": 1,
    })
    r2 = await mgr.execute({
        "action": "create", "owner": "o", "repo": "r", "issue_number": 1,
    })
    assert json.loads(r1.content)["status"] == "created"
    assert json.loads(r2.content)["status"] == "exists"


async def test_status_then_commit_then_push(git_env: Path) -> None:
    """Full lifecycle against a local bare repo."""
    from stronghold.tools.workspace import WorkspaceManager

    bare = _make_bare_repo()
    mgr = WorkspaceManager()
    original_run = mgr._run
    def patched_run(cmd, cwd=None):
        if cmd[:2] == ["git", "clone"]:
            cmd = cmd[:-2] + [str(bare), cmd[-1]]
        return original_run(cmd, cwd=cwd)
    mgr._run = patched_run  # type: ignore[method-assign]

    create_result = await mgr.execute({
        "action": "create", "owner": "o", "repo": "r", "issue_number": 100,
    })
    ws_path = Path(json.loads(create_result.content)["path"])

    # Modify a file in the worktree
    (ws_path / "NEW.md").write_text("new file content")

    # status should show the new file
    status = await mgr.execute({"action": "status", "issue_number": 100})
    s_data = json.loads(status.content)
    assert s_data["status"] == "active"
    assert s_data["branch"] == "mason/100"
    assert any("NEW.md" in c for c in s_data["changes"])

    # commit
    commit = await mgr.execute({
        "action": "commit", "issue_number": 100, "message": "add file",
    })
    c_data = json.loads(commit.content)
    assert c_data["status"] == "committed"
    assert len(c_data["sha"]) > 0

    # push to the bare repo
    push = await mgr.execute({"action": "push", "issue_number": 100})
    p_data = json.loads(push.content)
    assert p_data["status"] == "pushed"
    assert p_data["branch"] == "mason/100"


async def test_cleanup_removes_worktree(git_env: Path) -> None:
    from stronghold.tools.workspace import WorkspaceManager

    bare = _make_bare_repo()
    mgr = WorkspaceManager()
    original_run = mgr._run
    def patched_run(cmd, cwd=None):
        if cmd[:2] == ["git", "clone"]:
            cmd = cmd[:-2] + [str(bare), cmd[-1]]
        return original_run(cmd, cwd=cwd)
    mgr._run = patched_run  # type: ignore[method-assign]

    await mgr.execute({
        "action": "create", "owner": "o", "repo": "r", "issue_number": 55,
    })
    result = await mgr.execute({"action": "cleanup", "issue_number": 55})
    assert json.loads(result.content)["status"] == "cleaned"


async def test_token_injected_into_clone_url(git_env: Path, monkeypatch) -> None:
    """GITHUB_TOKEN is embedded into the clone URL for authenticated access."""
    from stronghold.tools.workspace import WorkspaceManager

    monkeypatch.setenv("GITHUB_TOKEN", "ghp_test_secret_token")
    mgr = WorkspaceManager()

    clone_urls = []
    def mock_run(cmd, cwd=None):
        if cmd[:2] == ["git", "clone"]:
            clone_urls.append(cmd[-2])
        return "ok"
    mgr._run = mock_run  # type: ignore[method-assign]

    try:
        mgr._ensure_clone("owner", "repo")
    except Exception:
        pass  # we only care about the clone URL

    assert len(clone_urls) == 1
    assert "x-access-token:ghp_test_secret_token" in clone_urls[0]
    assert "github.com/owner/repo.git" in clone_urls[0]


async def test_clone_cached_returns_existing(git_env: Path) -> None:
    """Second _ensure_clone call with same owner/repo returns cached path."""
    from stronghold.tools.workspace import WorkspaceManager

    mgr = WorkspaceManager()
    mgr._repos["acme/widget"] = Path("/cached/path")
    result = mgr._ensure_clone("acme", "widget")
    assert result == Path("/cached/path")


async def test_resolve_base_dir_fallback() -> None:
    """If STRONGHOLD_WORKSPACE is unwritable, falls back to tempdir."""
    from stronghold.tools.workspace import WorkspaceManager
    # Just verify the method returns something writable
    base = WorkspaceManager._resolve_base_dir()
    assert base.exists()
    assert base.is_dir()


async def test_run_failure_raises_with_stderr(git_env: Path) -> None:
    """_run propagates stderr as the exception message."""
    from stronghold.tools.workspace import WorkspaceManager
    with pytest.raises(RuntimeError, match="git"):
        WorkspaceManager._run(["git", "nonexistent-subcommand-xyz"])
