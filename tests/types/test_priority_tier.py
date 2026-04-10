"""Tests for priority_tier field on AgentIdentity (ADR-K8S-014)."""

from __future__ import annotations

from stronghold.types.agent import AgentIdentity


def test_default_priority_tier_is_p2() -> None:
    identity = AgentIdentity(name="test-agent")
    assert identity.priority_tier == "P2"


def test_priority_tier_round_trip() -> None:
    for tier in ("P0", "P1", "P2", "P3", "P4", "P5"):
        identity = AgentIdentity(name="test-agent", priority_tier=tier)
        assert identity.priority_tier == tier


def test_priority_tier_preserved_in_dataclass() -> None:
    identity = AgentIdentity(
        name="mason",
        version="2.0.0",
        priority_tier="P5",
        trust_tier="t1",
    )
    assert identity.name == "mason"
    assert identity.priority_tier == "P5"
    assert identity.trust_tier == "t1"
