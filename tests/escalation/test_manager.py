"""Tests for InMemoryEscalationManager."""

from __future__ import annotations

from stronghold.escalation.manager import Escalation, InMemoryEscalationManager


class TestEscalate:
    async def test_escalate_assigns_id_and_pending_status(self) -> None:
        mgr = InMemoryEscalationManager()
        esc = Escalation(
            session_id="sess-1",
            agent_name="artificer",
            user_id="user-1",
            org_id="org-1",
            reason="max_rounds_exceeded",
        )
        result = await mgr.escalate(esc)
        assert result.id.startswith("esc-")
        assert result.status == "pending"
        assert result.created_at > 0

    async def test_escalate_preserves_custom_id(self) -> None:
        mgr = InMemoryEscalationManager()
        esc = Escalation(id="custom-id", org_id="org-1", reason="user_requested")
        result = await mgr.escalate(esc)
        assert result.id == "custom-id"

    async def test_escalate_stores_context(self) -> None:
        mgr = InMemoryEscalationManager()
        ctx = [{"role": "user", "content": "help me"}]
        esc = Escalation(org_id="org-1", reason="timeout", context=ctx)
        result = await mgr.escalate(esc)
        assert result.context == ctx


class TestGet:
    async def test_get_returns_escalation(self) -> None:
        mgr = InMemoryEscalationManager()
        esc = Escalation(org_id="org-1", reason="warden_block")
        created = await mgr.escalate(esc)
        result = await mgr.get(created.id, org_id="org-1")
        assert result is not None
        assert result.id == created.id

    async def test_get_returns_none_for_missing(self) -> None:
        mgr = InMemoryEscalationManager()
        result = await mgr.get("nonexistent", org_id="org-1")
        assert result is None

    async def test_get_enforces_org_scoping(self) -> None:
        mgr = InMemoryEscalationManager()
        esc = Escalation(org_id="org-1", reason="timeout")
        created = await mgr.escalate(esc)
        # Different org cannot see it
        result = await mgr.get(created.id, org_id="org-2")
        assert result is None


class TestListPending:
    async def test_list_pending_returns_only_pending(self) -> None:
        mgr = InMemoryEscalationManager()
        esc1 = await mgr.escalate(Escalation(org_id="org-1", reason="timeout"))
        esc2 = await mgr.escalate(Escalation(org_id="org-1", reason="user_requested"))
        # Resolve esc1
        await mgr.dismiss(esc1.id, org_id="org-1", resolved_by="admin")
        pending = await mgr.list_pending(org_id="org-1")
        assert len(pending) == 1
        assert pending[0].id == esc2.id

    async def test_list_pending_scoped_to_org(self) -> None:
        mgr = InMemoryEscalationManager()
        await mgr.escalate(Escalation(org_id="org-1", reason="timeout"))
        await mgr.escalate(Escalation(org_id="org-2", reason="timeout"))
        pending_org1 = await mgr.list_pending(org_id="org-1")
        pending_org2 = await mgr.list_pending(org_id="org-2")
        assert len(pending_org1) == 1
        assert len(pending_org2) == 1


class TestRespond:
    async def test_respond_changes_status_and_records_response(self) -> None:
        mgr = InMemoryEscalationManager()
        esc = await mgr.escalate(Escalation(org_id="org-1", reason="timeout"))
        ok = await mgr.respond(
            esc.id, org_id="org-1", response="Try restarting", resolved_by="admin-user"
        )
        assert ok is True
        updated = await mgr.get(esc.id, org_id="org-1")
        assert updated is not None
        assert updated.status == "responded"
        assert updated.response == "Try restarting"
        assert updated.resolved_by == "admin-user"
        assert updated.resolved_at > 0

    async def test_respond_fails_for_wrong_org(self) -> None:
        mgr = InMemoryEscalationManager()
        esc = await mgr.escalate(Escalation(org_id="org-1", reason="timeout"))
        ok = await mgr.respond(
            esc.id, org_id="org-2", response="nope", resolved_by="admin"
        )
        assert ok is False

    async def test_respond_fails_for_already_resolved(self) -> None:
        mgr = InMemoryEscalationManager()
        esc = await mgr.escalate(Escalation(org_id="org-1", reason="timeout"))
        await mgr.respond(esc.id, org_id="org-1", response="first", resolved_by="admin")
        # Second respond should fail
        ok = await mgr.respond(esc.id, org_id="org-1", response="second", resolved_by="admin")
        assert ok is False


class TestTakeover:
    async def test_takeover_changes_status(self) -> None:
        mgr = InMemoryEscalationManager()
        esc = await mgr.escalate(Escalation(org_id="org-1", reason="max_rounds_exceeded"))
        ok = await mgr.takeover(esc.id, org_id="org-1", resolved_by="ops-lead")
        assert ok is True
        updated = await mgr.get(esc.id, org_id="org-1")
        assert updated is not None
        assert updated.status == "taken_over"
        assert updated.resolved_by == "ops-lead"

    async def test_takeover_fails_for_already_resolved(self) -> None:
        mgr = InMemoryEscalationManager()
        esc = await mgr.escalate(Escalation(org_id="org-1", reason="timeout"))
        await mgr.takeover(esc.id, org_id="org-1", resolved_by="admin")
        ok = await mgr.takeover(esc.id, org_id="org-1", resolved_by="admin")
        assert ok is False


class TestDismiss:
    async def test_dismiss_changes_status(self) -> None:
        mgr = InMemoryEscalationManager()
        esc = await mgr.escalate(Escalation(org_id="org-1", reason="warden_block"))
        ok = await mgr.dismiss(esc.id, org_id="org-1", resolved_by="admin")
        assert ok is True
        updated = await mgr.get(esc.id, org_id="org-1")
        assert updated is not None
        assert updated.status == "dismissed"
        assert updated.resolved_by == "admin"

    async def test_dismiss_fails_for_already_resolved(self) -> None:
        mgr = InMemoryEscalationManager()
        esc = await mgr.escalate(Escalation(org_id="org-1", reason="timeout"))
        await mgr.dismiss(esc.id, org_id="org-1", resolved_by="admin")
        ok = await mgr.dismiss(esc.id, org_id="org-1", resolved_by="admin")
        assert ok is False
