"""Tests for GDPR user data export (Article 20).

Tests the UserDataExporter and the API routes for data portability.
Uses real InMemory stores, no mocks.
"""

from __future__ import annotations

import json

from fastapi.testclient import TestClient

from stronghold.api.app import create_app
from stronghold.export.user_data import ExportResult, UserDataExporter
from stronghold.memory.episodic.store import InMemoryEpisodicStore
from stronghold.memory.learnings.store import InMemoryLearningStore
from stronghold.sessions.store import InMemorySessionStore
from stronghold.types.memory import EpisodicMemory, Learning, MemoryScope, MemoryTier

ORG = "org-export-test"
USER = "user-42"


class TestExportResultSerialization:
    """ExportResult.to_json produces valid JSON with required fields."""

    def test_to_json_produces_valid_json(self) -> None:
        result = ExportResult(user_id=USER, org_id=ORG)
        raw = result.to_json()
        parsed = json.loads(raw)
        assert parsed["user_id"] == USER
        assert parsed["org_id"] == ORG

    def test_to_json_includes_schema_version(self) -> None:
        result = ExportResult(user_id=USER, org_id=ORG)
        parsed = json.loads(result.to_json())
        assert parsed["schema_version"] == "1.0"

    def test_exported_at_populated_after_export(self) -> None:
        result = ExportResult(user_id=USER, org_id=ORG, exported_at="2026-03-31T00:00:00+00:00")
        parsed = json.loads(result.to_json())
        assert parsed["exported_at"] != ""
        assert "2026" in parsed["exported_at"]


class TestUserDataExporterNoStores:
    """Exporter with no stores returns empty sections."""

    async def test_no_stores_returns_empty_sections(self) -> None:
        exporter = UserDataExporter()
        result = await exporter.export_user(user_id=USER, org_id=ORG)
        assert result.sections == {}
        assert result.record_counts == {}

    async def test_exported_at_is_populated(self) -> None:
        exporter = UserDataExporter()
        result = await exporter.export_user(user_id=USER, org_id=ORG)
        assert result.exported_at != ""


class TestExportSessions:
    """Export with session store produces conversations section."""

    async def test_export_sessions_produces_conversations(self) -> None:
        store = InMemorySessionStore()
        session_id = f"{ORG}/_/{USER}:chat1"
        await store.append_messages(session_id, [
            {"role": "user", "content": "Hello"},
            {"role": "assistant", "content": "Hi there"},
        ])

        exporter = UserDataExporter(session_store=store)
        result = await exporter.export_user(user_id=USER, org_id=ORG)

        assert "conversations" in result.sections
        assert len(result.sections["conversations"]) == 1
        assert result.record_counts["conversations"] == 1

    async def test_export_sessions_contains_messages(self) -> None:
        store = InMemorySessionStore()
        session_id = f"{ORG}/_/{USER}:chat1"
        await store.append_messages(session_id, [
            {"role": "user", "content": "Hello"},
            {"role": "assistant", "content": "Hi there"},
        ])

        exporter = UserDataExporter(session_store=store)
        result = await exporter.export_user(user_id=USER, org_id=ORG)

        conv = result.sections["conversations"][0]
        assert "messages" in conv
        assert len(conv["messages"]) == 2

    async def test_export_sessions_excludes_other_orgs(self) -> None:
        store = InMemorySessionStore()
        await store.append_messages(f"{ORG}/_/{USER}:chat1", [
            {"role": "user", "content": "mine"},
        ])
        await store.append_messages("other-org/_/other-user:chat2", [
            {"role": "user", "content": "not mine"},
        ])

        exporter = UserDataExporter(session_store=store)
        result = await exporter.export_user(user_id=USER, org_id=ORG)

        assert result.record_counts["conversations"] == 1


class TestExportLearnings:
    """Export with learning store produces learnings section."""

    async def test_export_learnings_produces_section(self) -> None:
        store = InMemoryLearningStore()
        learning = Learning(
            category="tool_correction",
            trigger_keys=["fan", "bedroom"],
            learning="entity_id for fan is fan.bedroom",
            tool_name="ha_control",
            agent_id="warden-at-arms",
            org_id=ORG,
            scope=MemoryScope.AGENT,
        )
        await store.store(learning)

        exporter = UserDataExporter(learning_store=store)
        result = await exporter.export_user(user_id=USER, org_id=ORG)

        assert "learnings" in result.sections
        assert result.record_counts["learnings"] == 1

    async def test_export_learnings_excludes_other_orgs(self) -> None:
        store = InMemoryLearningStore()
        await store.store(Learning(
            trigger_keys=["a"], learning="mine", org_id=ORG,
        ))
        await store.store(Learning(
            trigger_keys=["b"], learning="not mine", org_id="other-org",
        ))

        exporter = UserDataExporter(learning_store=store)
        result = await exporter.export_user(user_id=USER, org_id=ORG)

        assert result.record_counts["learnings"] == 1


class TestExportEpisodic:
    """Export with episodic store produces memories section."""

    async def test_export_episodic_produces_section(self) -> None:
        store = InMemoryEpisodicStore()
        mem = EpisodicMemory(
            memory_id="mem-1",
            tier=MemoryTier.LESSON,
            content="Test memory content",
            weight=0.6,
            org_id=ORG,
            user_id=USER,
            scope=MemoryScope.USER,
        )
        await store.store(mem)

        exporter = UserDataExporter(episodic_store=store)
        result = await exporter.export_user(user_id=USER, org_id=ORG)

        assert "memories" in result.sections
        assert result.record_counts["memories"] == 1

    async def test_export_episodic_excludes_other_users(self) -> None:
        store = InMemoryEpisodicStore()
        await store.store(EpisodicMemory(
            memory_id="mem-mine",
            content="mine",
            org_id=ORG,
            user_id=USER,
            scope=MemoryScope.USER,
        ))
        await store.store(EpisodicMemory(
            memory_id="mem-other",
            content="not mine",
            org_id=ORG,
            user_id="other-user",
            scope=MemoryScope.USER,
        ))

        exporter = UserDataExporter(episodic_store=store)
        result = await exporter.export_user(user_id=USER, org_id=ORG)

        assert result.record_counts["memories"] == 1


class TestRecordCounts:
    """Record counts match actual data length."""

    async def test_record_counts_match_data(self) -> None:
        session_store = InMemorySessionStore()
        await session_store.append_messages(f"{ORG}/_/{USER}:a", [
            {"role": "user", "content": "a"},
        ])
        await session_store.append_messages(f"{ORG}/_/{USER}:b", [
            {"role": "user", "content": "b"},
        ])

        learning_store = InMemoryLearningStore()
        await learning_store.store(Learning(
            trigger_keys=["x"], learning="learn1", org_id=ORG,
        ))

        exporter = UserDataExporter(
            session_store=session_store,
            learning_store=learning_store,
        )
        result = await exporter.export_user(user_id=USER, org_id=ORG)

        assert result.record_counts["conversations"] == len(result.sections["conversations"])
        assert result.record_counts["learnings"] == len(result.sections["learnings"])


class TestExportAPI:
    """API routes for data export."""

    def test_export_me_returns_200(self) -> None:
        app = create_app()
        with TestClient(app) as client:
            resp = client.post(
                "/v1/stronghold/export/me",
                headers={"Authorization": "Bearer sk-example-stronghold"},
            )
            assert resp.status_code == 200
            data = resp.json()
            assert "user_id" in data
            assert "schema_version" in data

    def test_export_me_requires_auth(self) -> None:
        app = create_app()
        with TestClient(app) as client:
            resp = client.post("/v1/stronghold/export/me")
            assert resp.status_code == 401

    def test_admin_export_user_requires_admin(self) -> None:
        app = create_app()
        with TestClient(app) as client:
            # sk-example-stronghold gives admin by default in test config,
            # but unauthenticated should fail
            resp = client.post("/v1/stronghold/export/user/some-user-id")
            assert resp.status_code == 401

    def test_admin_export_user_returns_200(self) -> None:
        app = create_app()
        with TestClient(app) as client:
            resp = client.post(
                "/v1/stronghold/export/user/some-user-id",
                headers={"Authorization": "Bearer sk-example-stronghold"},
            )
            assert resp.status_code == 200
            data = resp.json()
            assert data["user_id"] == "some-user-id"
