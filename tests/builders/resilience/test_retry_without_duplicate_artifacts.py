from __future__ import annotations

from stronghold.builders import ArtifactRef, InMemoryArtifactStore


def test_retries_do_not_create_duplicate_durable_artifacts() -> None:
    store = InMemoryArtifactStore()
    artifact = ArtifactRef(
        artifact_id="art_same",
        type="validation_report",
        path="runs/run-1/validation.json",
        producer="mason",
    )

    store.store(artifact)
    store.store(artifact)

    assert store.list_for_run("run-1") == [artifact]
