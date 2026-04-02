from __future__ import annotations

from stronghold.builders import InMemoryWorkspaceService


def test_workspace_cleanup_archives_workspace_by_default() -> None:
    service = InMemoryWorkspaceService()
    workspace = service.create(
        run_id="run-1",
        repo="org/repo",
        branch="builders/42-run-1",
    )

    updated = service.cleanup(workspace.workspace_id)

    assert updated.status == "archived"
    assert service.resolve(workspace.workspace_id).status == "archived"
