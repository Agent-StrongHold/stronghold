from __future__ import annotations

from stronghold.builders import ArtifactRef, InMemoryArtifactStore


def test_structured_audit_findings_become_learning_artifacts() -> None:
    store = InMemoryArtifactStore()

    audit_report = store.store(
        ArtifactRef(
            type="audit_report",
            path="runs/run-1/audit-report.json",
            producer="auditor",
            metadata={"finding_count": 1},
        )
    )
    learning_artifact = store.store(
        ArtifactRef(
            type="learning_artifact",
            path="runs/run-1/learning.json",
            producer="auditor",
            metadata={
                "source_artifact_id": audit_report.artifact_id,
                "target": "mason",
                "category": "review_feedback",
            },
        )
    )

    stored = store.list_for_run("run-1")

    assert [artifact.type for artifact in stored] == ["audit_report", "learning_artifact"]
    assert learning_artifact.metadata["source_artifact_id"] == audit_report.artifact_id
    assert learning_artifact.metadata["target"] == "mason"
