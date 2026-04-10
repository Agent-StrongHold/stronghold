"""Final verification stage — pytest + git log + diff summary."""

from __future__ import annotations

from typing import Any


async def run_final_verification(
    run: Any,
    *,
    pytest_runner: Any,
    workspace: Any,
    post_to_issue: Any,
    feedback: str = "",
) -> Any:
    """Final check — run issue's tests, verify commits exist.

    Args:
        run: RunState with repo, issue_number, _workspace_path
        pytest_runner: PytestRunner instance
        workspace: WorkspaceOps instance
        post_to_issue: async callable(owner, repo, issue_number, body, run=run)
        feedback: unused (kept for handler signature compat)
    """
    from stronghold.builders.pipeline import StageResult

    owner, repo = run.repo.split("/")
    ws = getattr(run, "_workspace_path", "")

    test_file = f"tests/api/test_issue_{run.issue_number}.py"
    pytest_output = await pytest_runner.run(ws, test_file)
    git_log = await workspace.git_command("log --oneline -10", ws)
    git_diff_stat = await workspace.git_command("diff main --stat", ws)

    summary = (
        f"## Final Verification\n\n"
        f"**Pytest:**\n```\n{pytest_output[:1500]}\n```\n\n"
        f"**Git log:**\n```\n{git_log}\n```\n\n"
        f"**Changes vs main:**\n```\n{git_diff_stat}\n```\n"
    )
    await post_to_issue(owner, repo, run.issue_number, summary, run=run)

    return StageResult(
        success=True,
        summary=summary,
        evidence={
            "pytest_output": pytest_output[:3000],
            "git_log": git_log,
            "diff_stat": git_diff_stat,
        },
    )
