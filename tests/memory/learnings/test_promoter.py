"""Comprehensive tests for LearningPromoter.

Covers:
  - Auto-promotion threshold (at, below, above)
  - Promoted learning format (status, tool_name, hit_count preserved)
  - Idempotent promotion (re-running doesn't duplicate)
  - Org scoping (cross-org isolation)
  - Approval gate path (queue, approve, reject, promote)
  - Skill mutation lifecycle (forge + mutation_store)
  - Edge cases (empty store, no tool_name, forge errors)
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from stronghold.memory.learnings.approval import LearningApprovalGate
from stronghold.memory.learnings.promoter import LearningPromoter
from stronghold.memory.learnings.store import InMemoryLearningStore
from stronghold.memory.mutations import InMemorySkillMutationStore
from stronghold.types.skill import SkillDefinition
from tests.factories import build_learning

if TYPE_CHECKING:
    from stronghold.types.memory import Learning


# ── Helpers ───────────────────────────────────────────────────────────


class StubForge:
    """Forge that records calls and returns configurable results."""

    def __init__(self, result: dict[str, Any] | None = None) -> None:
        self.calls: list[tuple[str, Learning]] = []
        self._result = result or {
            "status": "mutated",
            "old_hash": "aaa",
            "new_hash": "bbb",
        }

    async def forge(self, request: str) -> SkillDefinition:
        return SkillDefinition(name="stub-skill")

    async def mutate(self, skill_name: str, learning: Learning) -> dict[str, Any]:
        self.calls.append((skill_name, learning))
        return self._result


class RaisingForge:
    """Forge that raises on mutate()."""

    async def forge(self, request: str) -> SkillDefinition:
        return SkillDefinition(name="stub-skill")

    async def mutate(self, skill_name: str, learning: Learning) -> dict[str, Any]:
        msg = "forge exploded"
        raise RuntimeError(msg)


class GateFriendlyStore(InMemoryLearningStore):
    """InMemoryLearningStore that returns all active learnings on empty query.

    The gate path in LearningPromoter calls ``find_relevant("")`` to
    enumerate candidates.  The base in-memory store requires keyword
    matches, so an empty query always returns [].  This subclass handles
    the empty-query case by returning every active learning that passes
    org-scoping, which is the semantics a real Postgres implementation
    would provide (full-table scan with WHERE status='active').
    """

    async def find_relevant(
        self,
        user_text: str,
        *,
        agent_id: str | None = None,
        org_id: str = "",
        max_results: int = 10,
    ) -> list[Learning]:
        if user_text:
            return await super().find_relevant(
                user_text,
                agent_id=agent_id,
                org_id=org_id,
                max_results=max_results,
            )
        # Empty query: return all active, org-filtered learnings
        results: list[Learning] = []
        for lr in self._learnings:
            if lr.status != "active":
                continue
            if agent_id and lr.agent_id != agent_id:
                continue
            if org_id and lr.org_id != org_id:
                continue
            if not org_id and lr.org_id:
                continue
            results.append(lr)
            if len(results) >= max_results:
                break
        return results


async def _seed_learning(
    store: InMemoryLearningStore,
    *,
    hit_count: int = 0,
    tool_name: str = "ha_control",
    org_id: str = "",
    trigger_keys: list[str] | None = None,
    status: str = "active",
) -> Learning:
    """Store a learning with given attributes and return it (with assigned id)."""
    lr = build_learning(
        hit_count=hit_count,
        tool_name=tool_name,
        org_id=org_id,
        trigger_keys=trigger_keys or ["fan", "bedroom"],
        status=status,
    )
    await store.store(lr)
    return lr


# ── Auto-promotion threshold ─────────────────────────────────────────


class TestAutoPromotionThreshold:
    """check_and_promote (no gate) promotes exactly at threshold."""

    async def test_below_threshold_not_promoted(self) -> None:
        store = InMemoryLearningStore()
        await _seed_learning(store, hit_count=4)
        promoter = LearningPromoter(store, threshold=5)

        promoted = await promoter.check_and_promote()

        assert promoted == []

    async def test_exactly_at_threshold_promoted(self) -> None:
        store = InMemoryLearningStore()
        await _seed_learning(store, hit_count=5)
        promoter = LearningPromoter(store, threshold=5)

        promoted = await promoter.check_and_promote()

        assert len(promoted) == 1
        assert promoted[0].status == "promoted"

    async def test_above_threshold_promoted(self) -> None:
        store = InMemoryLearningStore()
        await _seed_learning(store, hit_count=20)
        promoter = LearningPromoter(store, threshold=5)

        promoted = await promoter.check_and_promote()

        assert len(promoted) == 1

    async def test_custom_threshold_respected(self) -> None:
        store = InMemoryLearningStore()
        await _seed_learning(store, hit_count=3)
        promoter = LearningPromoter(store, threshold=3)

        promoted = await promoter.check_and_promote()

        assert len(promoted) == 1

    async def test_empty_store_returns_empty(self) -> None:
        store = InMemoryLearningStore()
        promoter = LearningPromoter(store, threshold=5)

        promoted = await promoter.check_and_promote()

        assert promoted == []


# ── Promoted learning format ─────────────────────────────────────────


class TestPromotedLearningFormat:
    """Promoted learnings retain their original data with status='promoted'."""

    async def test_status_set_to_promoted(self) -> None:
        store = InMemoryLearningStore()
        await _seed_learning(store, hit_count=10)
        promoter = LearningPromoter(store, threshold=5)

        promoted = await promoter.check_and_promote()

        assert promoted[0].status == "promoted"

    async def test_tool_name_preserved(self) -> None:
        store = InMemoryLearningStore()
        await _seed_learning(store, hit_count=10, tool_name="shell_exec")
        promoter = LearningPromoter(store, threshold=5)

        promoted = await promoter.check_and_promote()

        assert promoted[0].tool_name == "shell_exec"

    async def test_hit_count_preserved(self) -> None:
        store = InMemoryLearningStore()
        await _seed_learning(store, hit_count=42)
        promoter = LearningPromoter(store, threshold=5)

        promoted = await promoter.check_and_promote()

        assert promoted[0].hit_count == 42

    async def test_id_assigned(self) -> None:
        store = InMemoryLearningStore()
        await _seed_learning(store, hit_count=10)
        promoter = LearningPromoter(store, threshold=5)

        promoted = await promoter.check_and_promote()

        assert promoted[0].id is not None
        assert promoted[0].id >= 1

    async def test_learning_text_preserved(self) -> None:
        store = InMemoryLearningStore()
        lr = build_learning(
            hit_count=10,
            learning="When user says 'bedroom fan', use entity_id fan.bedroom_ceiling",
        )
        await store.store(lr)
        promoter = LearningPromoter(store, threshold=5)

        promoted = await promoter.check_and_promote()

        assert "bedroom fan" in promoted[0].learning


# ── Idempotent promotion ─────────────────────────────────────────────


class TestIdempotentPromotion:
    """Running check_and_promote twice doesn't re-promote or duplicate."""

    async def test_second_run_returns_empty(self) -> None:
        store = InMemoryLearningStore()
        await _seed_learning(store, hit_count=10)
        promoter = LearningPromoter(store, threshold=5)

        first = await promoter.check_and_promote()
        second = await promoter.check_and_promote()

        assert len(first) == 1
        assert second == []

    async def test_promoted_count_stable_after_multiple_runs(self) -> None:
        store = InMemoryLearningStore()
        await _seed_learning(store, hit_count=10, trigger_keys=["alpha"])
        await _seed_learning(store, hit_count=10, trigger_keys=["beta"])
        promoter = LearningPromoter(store, threshold=5)

        first = await promoter.check_and_promote()
        second = await promoter.check_and_promote()
        third = await promoter.check_and_promote()

        assert len(first) == 2
        assert second == []
        assert third == []

    async def test_get_promoted_stable_across_runs(self) -> None:
        store = InMemoryLearningStore()
        await _seed_learning(store, hit_count=10)
        promoter = LearningPromoter(store, threshold=5)

        await promoter.check_and_promote()
        await promoter.check_and_promote()

        all_promoted = await store.get_promoted()
        assert len(all_promoted) == 1


# ── Org scoping ──────────────────────────────────────────────────────


class TestOrgScoping:
    """Promotions respect multi-tenant isolation via org_id."""

    async def test_org_a_learnings_invisible_to_org_b(self) -> None:
        store = InMemoryLearningStore()
        await _seed_learning(store, hit_count=10, org_id="org-a", trigger_keys=["alpha"])
        await _seed_learning(store, hit_count=10, org_id="org-b", trigger_keys=["beta"])
        promoter = LearningPromoter(store, threshold=5)

        promoted_a = await promoter.check_and_promote(org_id="org-a")
        promoted_b = await promoter.check_and_promote(org_id="org-b")

        assert len(promoted_a) == 1
        assert promoted_a[0].org_id == "org-a"
        assert len(promoted_b) == 1
        assert promoted_b[0].org_id == "org-b"

    async def test_empty_org_does_not_promote_scoped_learnings(self) -> None:
        """System caller (org_id='') must not promote org-scoped learnings."""
        store = InMemoryLearningStore()
        await _seed_learning(store, hit_count=10, org_id="org-x")
        promoter = LearningPromoter(store, threshold=5)

        promoted = await promoter.check_and_promote(org_id="")

        assert promoted == []

    async def test_org_scoped_get_promoted_filters(self) -> None:
        store = InMemoryLearningStore()
        await _seed_learning(store, hit_count=10, org_id="org-a", trigger_keys=["x"])
        await _seed_learning(store, hit_count=10, org_id="org-b", trigger_keys=["y"])
        promoter = LearningPromoter(store, threshold=5)

        await promoter.check_and_promote(org_id="org-a")
        await promoter.check_and_promote(org_id="org-b")

        visible_a = await store.get_promoted(org_id="org-a")
        visible_b = await store.get_promoted(org_id="org-b")
        assert len(visible_a) == 1
        assert visible_a[0].org_id == "org-a"
        assert len(visible_b) == 1
        assert visible_b[0].org_id == "org-b"

    async def test_unscoped_learning_promoted_by_system_caller(self) -> None:
        """Learnings with org_id='' can be promoted by a system caller (org_id='')."""
        store = InMemoryLearningStore()
        await _seed_learning(store, hit_count=10, org_id="")
        promoter = LearningPromoter(store, threshold=5)

        promoted = await promoter.check_and_promote(org_id="")

        assert len(promoted) == 1
        assert promoted[0].org_id == ""


# ── Approval gate path ──────────────────────────────────────────────
# The gate path calls find_relevant("") to enumerate candidates.
# InMemoryLearningStore requires keyword matches so empty queries
# return [].  GateFriendlyStore handles this by returning all active
# learnings on an empty query, matching real Postgres semantics.


class TestApprovalGatePath:
    """With approval_gate, promotion requires admin approval."""

    async def test_gate_queues_pending_instead_of_auto_promoting(self) -> None:
        store = GateFriendlyStore()
        gate = LearningApprovalGate()
        await _seed_learning(store, hit_count=10)
        promoter = LearningPromoter(store, threshold=5, approval_gate=gate)

        promoted = await promoter.check_and_promote()

        # Nothing auto-promoted; approval queued instead
        assert promoted == []
        pending = gate.get_pending()
        assert len(pending) == 1

    async def test_approved_learning_gets_promoted(self) -> None:
        store = GateFriendlyStore()
        gate = LearningApprovalGate()
        lr = await _seed_learning(store, hit_count=10)
        promoter = LearningPromoter(store, threshold=5, approval_gate=gate)

        # First run: queues approval
        await promoter.check_and_promote()
        # Admin approves
        gate.approve(lr.id or 0, reviewer="admin-alice")
        # Second run: processes approved
        promoted = await promoter.check_and_promote()

        assert len(promoted) == 1
        assert promoted[0].id == lr.id

    async def test_rejected_learning_not_promoted(self) -> None:
        store = GateFriendlyStore()
        gate = LearningApprovalGate()
        lr = await _seed_learning(store, hit_count=10)
        promoter = LearningPromoter(store, threshold=5, approval_gate=gate)

        await promoter.check_and_promote()
        gate.reject(lr.id or 0, reviewer="admin-bob", reason="not useful")
        promoted = await promoter.check_and_promote()

        assert promoted == []

    async def test_gate_with_forge_triggers_mutation_on_approval(self) -> None:
        store = GateFriendlyStore()
        gate = LearningApprovalGate()
        mutation_store = InMemorySkillMutationStore()
        forge = StubForge()
        lr = await _seed_learning(store, hit_count=10, tool_name="web_search")
        promoter = LearningPromoter(
            store,
            threshold=5,
            skill_forge=forge,
            mutation_store=mutation_store,
            approval_gate=gate,
        )

        await promoter.check_and_promote()
        gate.approve(lr.id or 0, reviewer="admin")
        promoted = await promoter.check_and_promote()

        assert len(promoted) == 1
        assert len(forge.calls) == 1
        assert forge.calls[0][0] == "web_search"
        mutations = await mutation_store.list_mutations()
        assert len(mutations) == 1

    async def test_gate_marks_promoted_after_processing(self) -> None:
        store = GateFriendlyStore()
        gate = LearningApprovalGate()
        lr = await _seed_learning(store, hit_count=10)
        promoter = LearningPromoter(store, threshold=5, approval_gate=gate)

        await promoter.check_and_promote()
        gate.approve(lr.id or 0, reviewer="admin")
        await promoter.check_and_promote()

        # After promotion, it should be marked as promoted in the gate
        all_approvals = gate.get_all()
        assert len(all_approvals) == 1
        assert all_approvals[0]["status"] == "promoted"

    async def test_gate_below_threshold_not_queued(self) -> None:
        """Learnings below threshold are not queued for approval."""
        store = GateFriendlyStore()
        gate = LearningApprovalGate()
        await _seed_learning(store, hit_count=2)
        promoter = LearningPromoter(store, threshold=5, approval_gate=gate)

        await promoter.check_and_promote()

        pending = gate.get_pending()
        assert pending == []


# ── Skill mutation lifecycle ─────────────────────────────────────────


class TestSkillMutationLifecycle:
    """Forge + mutation_store interactions during promotion."""

    async def test_mutation_records_skill_name_and_hashes(self) -> None:
        store = InMemoryLearningStore()
        mutation_store = InMemorySkillMutationStore()
        forge = StubForge({"status": "mutated", "old_hash": "old111", "new_hash": "new222"})
        await _seed_learning(store, hit_count=10, tool_name="deploy_tool")
        promoter = LearningPromoter(
            store,
            threshold=5,
            skill_forge=forge,
            mutation_store=mutation_store,
        )

        await promoter.check_and_promote()

        mutations = await mutation_store.list_mutations()
        assert len(mutations) == 1
        assert mutations[0].skill_name == "deploy_tool"
        assert mutations[0].old_prompt_hash == "old111"
        assert mutations[0].new_prompt_hash == "new222"

    async def test_no_mutation_when_tool_name_empty(self) -> None:
        store = InMemoryLearningStore()
        mutation_store = InMemorySkillMutationStore()
        forge = StubForge()
        await _seed_learning(store, hit_count=10, tool_name="")
        promoter = LearningPromoter(
            store,
            threshold=5,
            skill_forge=forge,
            mutation_store=mutation_store,
        )

        await promoter.check_and_promote()

        assert forge.calls == []
        mutations = await mutation_store.list_mutations()
        assert len(mutations) == 0

    async def test_no_mutation_when_forge_absent(self) -> None:
        store = InMemoryLearningStore()
        mutation_store = InMemorySkillMutationStore()
        await _seed_learning(store, hit_count=10, tool_name="ha_control")
        promoter = LearningPromoter(
            store,
            threshold=5,
            skill_forge=None,
            mutation_store=mutation_store,
        )

        await promoter.check_and_promote()

        mutations = await mutation_store.list_mutations()
        assert len(mutations) == 0

    async def test_forge_error_status_does_not_record_mutation(self) -> None:
        store = InMemoryLearningStore()
        mutation_store = InMemorySkillMutationStore()
        forge = StubForge({"status": "error", "error": "template missing"})
        await _seed_learning(store, hit_count=10, tool_name="ha_control")
        promoter = LearningPromoter(
            store,
            threshold=5,
            skill_forge=forge,
            mutation_store=mutation_store,
        )

        promoted = await promoter.check_and_promote()

        assert len(promoted) == 1  # still promoted
        mutations = await mutation_store.list_mutations()
        assert len(mutations) == 0  # but no mutation recorded

    async def test_forge_exception_does_not_block_promotion(self) -> None:
        store = InMemoryLearningStore()
        await _seed_learning(store, hit_count=10, tool_name="ha_control")
        promoter = LearningPromoter(
            store,
            threshold=5,
            skill_forge=RaisingForge(),
        )

        promoted = await promoter.check_and_promote()

        assert len(promoted) == 1
        assert promoted[0].status == "promoted"

    async def test_multiple_learnings_each_trigger_mutation(self) -> None:
        store = InMemoryLearningStore()
        mutation_store = InMemorySkillMutationStore()
        forge = StubForge()
        await _seed_learning(store, hit_count=10, tool_name="tool_a", trigger_keys=["aaa"])
        await _seed_learning(store, hit_count=10, tool_name="tool_b", trigger_keys=["bbb"])
        promoter = LearningPromoter(
            store,
            threshold=5,
            skill_forge=forge,
            mutation_store=mutation_store,
        )

        promoted = await promoter.check_and_promote()

        assert len(promoted) == 2
        assert len(forge.calls) == 2
        tool_names = {c[0] for c in forge.calls}
        assert tool_names == {"tool_a", "tool_b"}
        mutations = await mutation_store.list_mutations()
        assert len(mutations) == 2
