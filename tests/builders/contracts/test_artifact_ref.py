from __future__ import annotations

from stronghold.builders import ArtifactRef


def test_artifact_ref_generates_id_and_preserves_metadata() -> None:
    artifact = ArtifactRef(
        type="acceptance_criteria",
        path="runs/run-1/criteria.json",
        producer="frank",
        metadata={"source": "issue-42"},
    )

    assert artifact.artifact_id.startswith("art_")
    assert artifact.metadata["source"] == "issue-42"
