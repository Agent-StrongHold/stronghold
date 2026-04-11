"""Tests for WorkspaceManager — git clone + worktree management for Mason.

All subprocess.run calls are intercepted by a hand-rolled fake so tests
never touch real git or network. Uses tmp_path for the base dir via the
STRONGHOLD_WORKSPACE env var so each test gets a fresh sandbox.
"""

from __future__ import annotations

import json
import subprocess
from pathlib import Path
from typing import Any

import pytest

from stronghold.tools import workspace as workspace_module
from stronghold.tools.workspace import WORKSPACE_TOOL_DEF, WorkspaceManager


# ---------------------------------------------------------------------------
# Fake subprocess.run
# ---------------------------------------------------------------------------


class _FakeResult:
    """Minimal stand-in for subprocess.CompletedProcess."""

    def __init__(
        self, returncode: int = 0, stdout: str = "", stderr: str = ""
    ) -> None:
        self.returncode = returncode
        self.stdout = stdout
        self.stderr = stderr


def _fake_runner(
    responses: dict[tuple[str, ...], _FakeResult] | None = None,
    default: _FakeResult | None = None,
    captured: list[dict[str, Any]] | None = None,
) -> Any:
    """Build a subprocess.run replacement driven by a command-prefix map."""
    default = default or _FakeResult()
    responses = responses or {}

    def _runner(cmd: list[str], **kwargs: Any) -> _FakeResult:
        if captured is not None:
            captured.append({"cmd": cmd, **kwargs})
        key = tuple(cmd)
        if key in responses:
            return responses[key]
        # Fall back to prefix matching (first N elements)
        for rkey, rval in responses.items():
            if cmd[: len(rkey)] == list(rkey):
                return rval
        return default

    return _runner


@pytest.fixture
def wm_base(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Redirect the workspace base dir to tmp_path."""
    base = tmp_path / "ws-base"
    monkeypatch.setattr(workspace_module, "DEFAULT_WORKSPACE_ROOT", base)
    return base


@pytest.fixture
def wm(wm_base: Path, monkeypatch: pytest.MonkeyPatch) -> WorkspaceManager:
    """Build a WorkspaceManager with default (no-op) subprocess behavior."""
    monkeypatch.setattr(subprocess, "run", _fake_runner())
    return WorkspaceManager()


# ---------------------------------------------------------------------------
# Meta / base resolution
# ---------------------------------------------------------------------------


class TestMeta:
    def test_executor_name(self, wm: WorkspaceManager) -> None:
        assert wm.name == "workspace"

    def test_tool_definition_has_all_actions(self) -> None:
        actions = set(WORKSPACE_TOOL_DEF.parameters["properties"]["action"]["enum"])
        assert actions == {"create", "status", "commit", "push", "cleanup"}

    def test_resolves_base_dir_under_configured_root(
        self, wm: WorkspaceManager, wm_base: Path
    ) -> None:
        assert wm._base == wm_base
        assert wm_base.is_dir()


class TestBaseDirFallback:
    def test_falls_back_to_tempdir_when_primary_unwritable(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Simulate primary failing mkdir (OSError) and verify the
        tempdir candidate is taken."""
        primary = tmp_path / "primary"  # never created — we'll make it fail
        fallback_dir = tmp_path / "fallback"
        monkeypatch.setattr(workspace_module, "DEFAULT_WORKSPACE_ROOT", primary)

        import tempfile

        monkeypatch.setattr(tempfile, "gettempdir", lambda: str(fallback_dir))

        original_mkdir = Path.mkdir

        def mkdir_with_block(self: Path, *args: Any, **kwargs: Any) -> None:
            if self == primary:
                msg = "simulated ro fs"
                raise OSError(msg)
            return original_mkdir(self, *args, **kwargs)

        monkeypatch.setattr(Path, "mkdir", mkdir_with_block)
        monkeypatch.setattr(subprocess, "run", _fake_runner())

        mgr = WorkspaceManager()
        assert mgr._base == fallback_dir / "stronghold-workspace"
        assert mgr._base.is_dir()

    def test_raises_when_no_candidate_writable(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(
            workspace_module,
            "DEFAULT_WORKSPACE_ROOT",
            tmp_path / "ro1",
        )
        import tempfile

        monkeypatch.setattr(tempfile, "gettempdir", lambda: str(tmp_path / "ro2"))

        def always_fail(self: Path, *args: Any, **kwargs: Any) -> None:
            msg = "ro"
            raise OSError(msg)

        monkeypatch.setattr(Path, "mkdir", always_fail)
        monkeypatch.setattr(subprocess, "run", _fake_runner())

        with pytest.raises(RuntimeError, match="No writable workspace root"):
            WorkspaceManager()


# ---------------------------------------------------------------------------
# execute() dispatch
# ---------------------------------------------------------------------------


class TestExecuteDispatch:
    @pytest.mark.asyncio
    async def test_unknown_action_returns_failure(
        self, wm: WorkspaceManager
    ) -> None:
        r = await wm.execute({"action": "nuke"})
        assert r.success is False
        assert "unknown action" in (r.error or "").lower()

    @pytest.mark.asyncio
    async def test_handler_exception_wrapped_as_failure(
        self, wm: WorkspaceManager, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Any exception from the action handler surfaces as
        ToolResult(success=False, error=...) — not an unhandled raise."""

        def boom(_args: dict[str, Any]) -> dict[str, str]:
            msg = "handler exploded"
            raise RuntimeError(msg)

        monkeypatch.setattr(wm, "_create", boom)
        r = await wm.execute({"action": "create"})
        assert r.success is False
        assert "handler exploded" in (r.error or "")


# ---------------------------------------------------------------------------
# _ensure_clone
# ---------------------------------------------------------------------------


class TestEnsureClone:
    def test_uses_token_in_url_when_present(
        self,
        wm: WorkspaceManager,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        monkeypatch.setenv("GITHUB_TOKEN", "ghp_fake_token")
        captured: list[dict[str, Any]] = []
        monkeypatch.setattr(subprocess, "run", _fake_runner(captured=captured))
        wm._ensure_clone("owner", "repo")
        clone_cmd = next(
            c for c in captured if c["cmd"][:2] == ["git", "clone"]
        )
        assert "x-access-token:ghp_fake_token" in clone_cmd["cmd"][-2]

    def test_no_token_uses_public_url(
        self,
        wm: WorkspaceManager,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        monkeypatch.delenv("GITHUB_TOKEN", raising=False)
        captured: list[dict[str, Any]] = []
        monkeypatch.setattr(subprocess, "run", _fake_runner(captured=captured))
        wm._ensure_clone("owner", "repo")
        clone_cmd = next(
            c for c in captured if c["cmd"][:2] == ["git", "clone"]
        )
        assert "x-access-token" not in clone_cmd["cmd"][-2]
        assert "github.com/owner/repo" in clone_cmd["cmd"][-2]

    def test_second_call_returns_cached_path_without_reclone(
        self,
        wm: WorkspaceManager,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        captured: list[dict[str, Any]] = []
        monkeypatch.setattr(subprocess, "run", _fake_runner(captured=captured))
        first = wm._ensure_clone("owner", "repo")
        before_second = len(captured)
        second = wm._ensure_clone("owner", "repo")
        after_second = len(captured)
        assert first == second
        assert before_second == after_second, "second clone ran subprocess"

    def test_existing_on_disk_repo_is_reused(
        self,
        wm: WorkspaceManager,
        wm_base: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """If the repo dir already exists (leftover from a previous run),
        _ensure_clone must not re-clone."""
        (wm_base / "repos" / "repo").mkdir(parents=True)
        captured: list[dict[str, Any]] = []
        monkeypatch.setattr(subprocess, "run", _fake_runner(captured=captured))
        path = wm._ensure_clone("owner", "repo")
        assert path.exists()
        # No git clone calls expected
        assert not any(
            c["cmd"][:2] == ["git", "clone"] for c in captured
        )


# ---------------------------------------------------------------------------
# _create
# ---------------------------------------------------------------------------


class TestCreate:
    @pytest.mark.asyncio
    async def test_create_returns_branch_and_path(
        self,
        wm: WorkspaceManager,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        monkeypatch.setattr(subprocess, "run", _fake_runner())
        r = await wm.execute(
            {
                "action": "create",
                "owner": "acme",
                "repo": "widgets",
                "issue_number": 42,
            }
        )
        assert r.success is True
        payload = json.loads(r.content)
        assert payload["status"] == "created"
        assert payload["branch"] == "mason/42"
        assert "mason-42" in payload["path"]

    @pytest.mark.asyncio
    async def test_create_with_existing_worktree_returns_exists(
        self,
        wm: WorkspaceManager,
        wm_base: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        (wm_base / "worktrees" / "mason-99").mkdir(parents=True)
        monkeypatch.setattr(subprocess, "run", _fake_runner())
        r = await wm.execute(
            {
                "action": "create",
                "owner": "acme",
                "repo": "widgets",
                "issue_number": 99,
            }
        )
        payload = json.loads(r.content)
        assert payload["status"] == "exists"

    @pytest.mark.asyncio
    async def test_create_honors_explicit_branch(
        self,
        wm: WorkspaceManager,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        r = await wm.execute(
            {
                "action": "create",
                "owner": "acme",
                "repo": "widgets",
                "issue_number": 7,
                "branch": "feat/custom-branch",
            }
        )
        payload = json.loads(r.content)
        assert payload["branch"] == "feat/custom-branch"


# ---------------------------------------------------------------------------
# _status / _commit / _push / _cleanup
# ---------------------------------------------------------------------------


class TestStatus:
    @pytest.mark.asyncio
    async def test_status_missing_worktree(
        self, wm: WorkspaceManager
    ) -> None:
        r = await wm.execute({"action": "status", "issue_number": 101})
        payload = json.loads(r.content)
        assert payload["status"] == "not_found"

    @pytest.mark.asyncio
    async def test_status_with_changes_parsed(
        self,
        wm: WorkspaceManager,
        wm_base: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        (wm_base / "worktrees" / "mason-5").mkdir(parents=True)
        responses = {
            ("git", "status", "--porcelain"): _FakeResult(
                stdout=" M file.py\n?? newfile.py\n"
            ),
            ("git", "branch", "--show-current"): _FakeResult(stdout="mason/5\n"),
        }
        monkeypatch.setattr(subprocess, "run", _fake_runner(responses))
        r = await wm.execute({"action": "status", "issue_number": 5})
        payload = json.loads(r.content)
        assert payload["status"] == "active"
        assert payload["branch"] == "mason/5"
        assert len(payload["changes"]) == 2

    @pytest.mark.asyncio
    async def test_status_with_clean_worktree(
        self,
        wm: WorkspaceManager,
        wm_base: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        (wm_base / "worktrees" / "mason-6").mkdir(parents=True)
        responses = {
            ("git", "status", "--porcelain"): _FakeResult(stdout=""),
            ("git", "branch", "--show-current"): _FakeResult(stdout="mason/6\n"),
        }
        monkeypatch.setattr(subprocess, "run", _fake_runner(responses))
        r = await wm.execute({"action": "status", "issue_number": 6})
        payload = json.loads(r.content)
        assert payload["changes"] == []


class TestCommit:
    @pytest.mark.asyncio
    async def test_commit_missing_worktree(
        self, wm: WorkspaceManager
    ) -> None:
        r = await wm.execute({"action": "commit", "issue_number": 77})
        payload = json.loads(r.content)
        assert payload["status"] == "error"

    @pytest.mark.asyncio
    async def test_commit_returns_sha(
        self,
        wm: WorkspaceManager,
        wm_base: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        (wm_base / "worktrees" / "mason-10").mkdir(parents=True)
        responses = {
            ("git", "rev-parse", "HEAD"): _FakeResult(stdout="abc123def\n"),
        }
        monkeypatch.setattr(subprocess, "run", _fake_runner(responses))
        r = await wm.execute(
            {
                "action": "commit",
                "issue_number": 10,
                "message": "fix: update logic",
            }
        )
        payload = json.loads(r.content)
        assert payload["status"] == "committed"
        assert payload["sha"] == "abc123def"


class TestPush:
    @pytest.mark.asyncio
    async def test_push_missing_worktree(
        self, wm: WorkspaceManager
    ) -> None:
        r = await wm.execute({"action": "push", "issue_number": 202})
        payload = json.loads(r.content)
        assert payload["status"] == "error"

    @pytest.mark.asyncio
    async def test_push_returns_branch(
        self,
        wm: WorkspaceManager,
        wm_base: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        (wm_base / "worktrees" / "mason-3").mkdir(parents=True)
        captured: list[dict[str, Any]] = []
        responses = {
            ("git", "branch", "--show-current"): _FakeResult(stdout="mason/3\n"),
        }
        monkeypatch.setattr(
            subprocess, "run", _fake_runner(responses, captured=captured)
        )
        r = await wm.execute({"action": "push", "issue_number": 3})
        payload = json.loads(r.content)
        assert payload["status"] == "pushed"
        assert payload["branch"] == "mason/3"
        # Confirm push command ran
        assert any(c["cmd"][:3] == ["git", "push", "-u"] for c in captured)


class TestCleanup:
    @pytest.mark.asyncio
    async def test_cleanup_missing_worktree(
        self, wm: WorkspaceManager
    ) -> None:
        r = await wm.execute({"action": "cleanup", "issue_number": 999})
        payload = json.loads(r.content)
        assert payload["status"] == "not_found"

    @pytest.mark.asyncio
    async def test_cleanup_removes_directory_via_git_worktree(
        self,
        wm: WorkspaceManager,
        wm_base: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        # Seed a cached repo and a worktree
        repo_dir = wm_base / "repos" / "widgets"
        repo_dir.mkdir(parents=True)
        wm._repos["acme/widgets"] = repo_dir
        worktree_dir = wm_base / "worktrees" / "mason-11"
        worktree_dir.mkdir(parents=True)

        # Make git worktree remove actually delete the dir
        def deleting_runner(cmd: list[str], **kwargs: Any) -> _FakeResult:
            if cmd[:3] == ["git", "worktree"] and cmd[3] == "remove":
                import shutil as _shutil

                _shutil.rmtree(cmd[4], ignore_errors=True)
            return _FakeResult()

        monkeypatch.setattr(subprocess, "run", deleting_runner)
        r = await wm.execute({"action": "cleanup", "issue_number": 11})
        payload = json.loads(r.content)
        assert payload["status"] == "cleaned"
        assert not worktree_dir.exists()

    @pytest.mark.asyncio
    async def test_cleanup_falls_back_to_rmtree(
        self,
        wm: WorkspaceManager,
        wm_base: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """When `git worktree remove` fails (raises), the fallback
        `shutil.rmtree` path is taken."""
        worktree_dir = wm_base / "worktrees" / "mason-20"
        worktree_dir.mkdir(parents=True)
        # No repos seeded → the for-loop over _repos.values() is empty,
        # falling through to shutil.rmtree.
        monkeypatch.setattr(subprocess, "run", _fake_runner())
        r = await wm.execute({"action": "cleanup", "issue_number": 20})
        payload = json.loads(r.content)
        assert payload["status"] == "cleaned"
        assert not worktree_dir.exists()

    @pytest.mark.asyncio
    async def test_cleanup_with_repo_but_git_remove_fails(
        self,
        wm: WorkspaceManager,
        wm_base: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """If git worktree remove raises for the cached repo, the loop
        continues and shutil.rmtree does the final cleanup."""
        wm._repos["acme/widgets"] = wm_base / "repos" / "widgets"
        (wm_base / "repos" / "widgets").mkdir(parents=True)
        worktree_dir = wm_base / "worktrees" / "mason-21"
        worktree_dir.mkdir(parents=True)

        def always_fail_runner(cmd: list[str], **kwargs: Any) -> _FakeResult:
            # _run() wraps non-zero return codes in RuntimeError
            return _FakeResult(returncode=1, stderr="worktree remove failed")

        monkeypatch.setattr(subprocess, "run", always_fail_runner)
        r = await wm.execute({"action": "cleanup", "issue_number": 21})
        payload = json.loads(r.content)
        assert payload["status"] == "cleaned"
        assert not worktree_dir.exists()


# ---------------------------------------------------------------------------
# _run helper — raise on non-zero exit
# ---------------------------------------------------------------------------


class TestRunHelper:
    def test_run_raises_on_nonzero_exit(
        self,
        wm: WorkspaceManager,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        def fail_runner(cmd: list[str], **kwargs: Any) -> _FakeResult:
            return _FakeResult(returncode=2, stderr="fatal: bad ref\n")

        monkeypatch.setattr(subprocess, "run", fail_runner)
        with pytest.raises(RuntimeError, match="fatal: bad ref"):
            wm._run(["git", "fetch", "origin"])

    def test_run_falls_back_to_stdout_on_empty_stderr(
        self,
        wm: WorkspaceManager,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        def fail_runner(cmd: list[str], **kwargs: Any) -> _FakeResult:
            return _FakeResult(returncode=1, stdout="stdout error\n", stderr="")

        monkeypatch.setattr(subprocess, "run", fail_runner)
        with pytest.raises(RuntimeError, match="stdout error"):
            wm._run(["git", "status"])

    def test_run_returns_stdout_on_success(
        self,
        wm: WorkspaceManager,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        monkeypatch.setattr(
            subprocess,
            "run",
            lambda cmd, **kw: _FakeResult(returncode=0, stdout="hello\n"),
        )
        assert wm._run(["echo", "hello"]) == "hello\n"
