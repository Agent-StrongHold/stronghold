from __future__ import annotations

from stronghold.builders import ArtifactRef, InMemoryArtifactStore


def test_runtime_writes_artifacts_through_artifact_store_contract() -> None:
    store = InMemoryArtifactStore()
    artifact = ArtifactRef(
        type="validation_report",
        path="runs/run-1/validation.json",
        producer="mason",
    )

    stored = store.store(artifact)

    assert store.get(stored.artifact_id) == stored
    assert store.list_for_run("run-1") == [stored]
