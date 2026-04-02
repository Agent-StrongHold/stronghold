from __future__ import annotations

import pytest

from stronghold.builders import (
    ArtifactRef,
    BuildersOrchestrator,
    BuildersRuntime,
    InMemoryArtifactStore,
    RunResult,
    RunStatus,
    WorkerName,
)


@pytest.mark.asyncio
async def test_pr_audit_can_trigger_rework_and_then_pass() -> None:
    orchestrator = BuildersOrchestrator()
    runtime = BuildersRuntime()
    artifacts = InMemoryArtifactStore()

    orchestrator.create_run(
        run_id="run-1",
        repo="org/repo",
        issue_number=42,
        branch="builders/42-run-1",
        workspace_ref="ws-1",
        initial_stage="implementation_ready",
        initial_worker=WorkerName.AUDITOR,
    )

    async def auditor_rework(request):  # type: ignore[no-untyped-def]
        return RunResult(
            run_id=request.run_id,
            worker=request.worker,
            stage=request.stage,
            status=RunStatus.PASSED,
            summary="Rework required",
            artifacts=[
                ArtifactRef(
                    type="audit_report",
                    path="runs/run-1/audit-rework.json",
                    producer="auditor",
                    metadata={"verdict": "rework", "target": "mason"},
                )
            ],
        )

    async def mason_rework(request):  # type: ignore[no-untyped-def]
        return RunResult(
            run_id=request.run_id,
            worker=request.worker,
            stage=request.stage,
            status=RunStatus.PASSED,
            summary="Mason rework complete",
        )

    async def auditor_pass(request):  # type: ignore[no-untyped-def]
        return RunResult(
            run_id=request.run_id,
            worker=request.worker,
            stage=request.stage,
            status=RunStatus.PASSED,
            summary="Audit passed",
            artifacts=[
                ArtifactRef(
                    type="audit_report",
                    path="runs/run-1/audit-pass.json",
                    producer="auditor",
                    metadata={"verdict": "pass"},
                )
            ],
        )

    runtime.register(WorkerName.AUDITOR, "implementation_ready", auditor_rework)
    runtime.register(WorkerName.MASON, "implementation_started", mason_rework)

    first_audit = await runtime.execute(orchestrator.build_request("run-1"))
    for artifact in first_audit.artifacts:
        artifacts.store(artifact)
    orchestrator.apply_result(first_audit)

    orchestrator.advance_stage("run-1", "acceptance_defined", next_worker=WorkerName.FRANK)
    orchestrator.advance_stage("run-1", "tests_written")
    orchestrator.advance_stage("run-1", "implementation_started", next_worker=WorkerName.MASON)
    mason_result = await runtime.execute(orchestrator.build_request("run-1"))
    orchestrator.apply_result(mason_result, next_stage="implementation_ready")

    runtime.register(WorkerName.AUDITOR, "implementation_ready", auditor_pass)
    orchestrator.get_run("run-1").current_worker = WorkerName.AUDITOR
    second_audit = await runtime.execute(orchestrator.build_request("run-1"))
    for artifact in second_audit.artifacts:
        artifacts.store(artifact)
    orchestrator.apply_result(second_audit)

    assert artifacts.list_for_run("run-1")[0].metadata["verdict"] == "rework"
    assert artifacts.list_for_run("run-1")[-1].metadata["verdict"] == "pass"
