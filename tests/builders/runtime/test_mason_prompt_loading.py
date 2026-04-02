from __future__ import annotations

from stronghold.builders import BuildersRuntime, WorkerName


def test_mason_prompts_load_by_stage_and_version() -> None:
    runtime = BuildersRuntime()
    runtime.register_prompt(WorkerName.MASON, "implementation_started", "v1", "Implement the change.")

    assert runtime.load_prompt(WorkerName.MASON, "implementation_started", "v1") == "Implement the change."
