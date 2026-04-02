from __future__ import annotations

from stronghold.builders import BuildersRuntime, WorkerName


def test_frank_prompts_load_by_stage_and_version() -> None:
    runtime = BuildersRuntime()
    runtime.register_prompt(WorkerName.FRANK, "acceptance_defined", "v1", "Define criteria.")

    assert runtime.load_prompt(WorkerName.FRANK, "acceptance_defined", "v1") == "Define criteria."
