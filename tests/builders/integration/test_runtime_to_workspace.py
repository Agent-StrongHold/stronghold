from __future__ import annotations

from stronghold.builders import BuildersOrchestrator, InMemoryWorkspaceService, WorkerName


def test_runtime_uses_workspace_reference_from_core_contract() -> None:
    workspaces = InMemoryWorkspaceService()
    workspace = workspaces.create(
        run_id="run-1",
        repo="org/repo",
        branch="builders/42-run-1",
    )

    orchestrator = BuildersOrchestrator()
    orchestrator.create_run(
        run_id="run-1",
        repo="org/repo",
        issue_number=42,
        branch="builders/42-run-1",
        workspace_ref=workspace.workspace_id,
        initial_stage="acceptance_defined",
        initial_worker=WorkerName.FRANK,
    )

    request = orchestrator.build_request("run-1")
    resolved = workspaces.resolve(request.workspace_ref)

    assert request.workspace_ref == workspace.workspace_id
    assert resolved.path == "/workspace/run-1"
