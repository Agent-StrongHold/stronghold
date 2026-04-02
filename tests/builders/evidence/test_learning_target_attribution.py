from __future__ import annotations

from stronghold.builders import ArtifactRef


def test_learning_targets_can_be_attributed_to_mason_frank_or_workflow() -> None:
    mason_learning = ArtifactRef(
        type="learning_artifact",
        path="runs/run-1/learning-mason.json",
        producer="auditor",
        metadata={"target": "mason"},
    )
    frank_learning = ArtifactRef(
        type="learning_artifact",
        path="runs/run-1/learning-frank.json",
        producer="auditor",
        metadata={"target": "frank"},
    )
    workflow_learning = ArtifactRef(
        type="learning_artifact",
        path="runs/run-1/learning-workflow.json",
        producer="auditor",
        metadata={"target": "builders_workflow"},
    )

    assert mason_learning.metadata["target"] == "mason"
    assert frank_learning.metadata["target"] == "frank"
    assert workflow_learning.metadata["target"] == "builders_workflow"
