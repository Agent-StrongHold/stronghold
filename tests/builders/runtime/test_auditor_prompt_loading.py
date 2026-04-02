from __future__ import annotations

from stronghold.builders import BuildersRuntime, WorkerName


def test_auditor_prompts_load_by_stage_and_version() -> None:
    runtime = BuildersRuntime()
    runtime.register_prompt(WorkerName.AUDITOR, "pr_audit", "v1", "Audit the PR.")

    assert runtime.load_prompt(WorkerName.AUDITOR, "pr_audit", "v1") == "Audit the PR."
