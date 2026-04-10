"""Tests for priority_tier loading from agent.yaml (ADR-K8S-014)."""

from __future__ import annotations

from pathlib import Path

import yaml

from stronghold.agents.factory import _build_identity_from_manifest


def test_manifest_with_priority_tier() -> None:
    manifest = {"name": "mason", "priority_tier": "P5"}
    identity = _build_identity_from_manifest(manifest)
    assert identity.priority_tier == "P5"


def test_manifest_without_priority_tier_defaults_p2() -> None:
    manifest = {"name": "legacy-agent"}
    identity = _build_identity_from_manifest(manifest)
    assert identity.priority_tier == "P2"


def test_all_agent_yamls_have_priority_tier() -> None:
    agents_dir = Path("agents")
    if not agents_dir.exists():
        return  # skip if running from different cwd
    for agent_dir in sorted(agents_dir.iterdir()):
        yaml_path = agent_dir / "agent.yaml"
        if not yaml_path.exists():
            continue
        data = yaml.safe_load(yaml_path.read_text())
        assert "priority_tier" in data, f"{yaml_path} missing priority_tier"
        assert data["priority_tier"] in (
            "P0", "P1", "P2", "P3", "P4", "P5",
        ), f"{yaml_path} has invalid priority_tier: {data['priority_tier']}"


def test_loaded_identities_match_yaml_assignments() -> None:
    expected = {
        "arbiter": "P1",
        "artificer": "P2",
        "auditor": "P3",
        "davinci": "P2",
        "default": "P1",
        "fabulist": "P2",
        "frank": "P5",
        "mason": "P5",
        "ranger": "P1",
        "scribe": "P1",
        "warden-at-arms": "P1",
    }
    agents_dir = Path("agents")
    if not agents_dir.exists():
        return
    for name, tier in expected.items():
        yaml_path = agents_dir / name / "agent.yaml"
        if not yaml_path.exists():
            continue
        data = yaml.safe_load(yaml_path.read_text())
        identity = _build_identity_from_manifest(data)
        assert identity.priority_tier == tier, (
            f"{name}: expected {tier}, got {identity.priority_tier}"
        )
