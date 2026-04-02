from __future__ import annotations

from stronghold.builders import BuildersRuntime, WorkerName


def test_runtime_enforces_role_and_stage_specific_tool_access() -> None:
    runtime = BuildersRuntime()
    runtime.register_tools(WorkerName.FRANK, "acceptance_defined", ("read_repo", "write_tests"))
    runtime.register_tools(WorkerName.MASON, "implementation_started", ("read_repo", "write_code", "run_ci"))
    runtime.register_tools(WorkerName.AUDITOR, "pr_audit", ("read_pr", "write_review"))

    assert runtime.allowed_tools(WorkerName.FRANK, "acceptance_defined") == ("read_repo", "write_tests")
    assert runtime.allowed_tools(WorkerName.MASON, "implementation_started") == (
        "read_repo",
        "write_code",
        "run_ci",
    )
    assert runtime.allowed_tools(WorkerName.AUDITOR, "pr_audit") == ("read_pr", "write_review")
    assert runtime.allowed_tools(WorkerName.FRANK, "implementation_started") == ()
