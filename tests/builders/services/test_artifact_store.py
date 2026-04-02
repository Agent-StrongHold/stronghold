from __future__ import annotations

from stronghold.builders import ArtifactRef, InMemoryArtifactStore


def test_artifact_store_persists_and_lists_artifacts() -> None:
    store = InMemoryArtifactStore()

    artifact = store.store(
        ArtifactRef(
            type="acceptance_criteria",
            path="runs/run-1/criteria.json",
            producer="frank",
        )
    )

    fetched = store.get(artifact.artifact_id)
    listed = store.list_for_run("run-1")

    assert fetched == artifact
    assert listed == [artifact]
