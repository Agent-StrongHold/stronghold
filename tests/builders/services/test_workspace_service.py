from __future__ import annotations

from stronghold.builders import InMemoryWorkspaceService


def test_workspace_service_creates_and_resolves_workspace_refs() -> None:
    service = InMemoryWorkspaceService()

    workspace = service.create(
        run_id="run-1",
        repo="org/repo",
        branch="builders/42-run-1",
    )

    resolved = service.resolve(workspace.workspace_id)

    assert resolved == workspace
    assert resolved.run_id == "run-1"
    assert resolved.repo == "org/repo"
    assert resolved.branch == "builders/42-run-1"
    assert resolved.path.endswith("/run-1")
