"""Domain invariant tests for ContextBuilder token budget enforcement.

Invariants under test:
- Soul prompt is NEVER truncated, even when it exceeds the budget
- Matched learnings are dropped first under tight budget (soul survives)
- Promoted learnings survive over matched learnings under tight budget
- When budget is generous, all items are included
"""

from __future__ import annotations

from stronghold.agents.context_builder import _CHARS_PER_TOKEN, ContextBuilder
from stronghold.memory.learnings.store import InMemoryLearningStore
from stronghold.types.agent import AgentIdentity
from stronghold.types.memory import Learning, MemoryScope
from tests.fakes import FakePromptManager


def _make_identity(*, learnings: bool = True) -> AgentIdentity:
    """Build an AgentIdentity with learnings enabled."""
    memory_cfg = {"learnings": True} if learnings else {}
    return AgentIdentity(
        name="test-agent",
        soul_prompt_name="agent.test-agent.soul",
        memory_config=memory_cfg,
    )


def _make_learning(text: str, *, status: str = "active", org_id: str = "org1") -> Learning:
    """Build a learning with the given text and trigger keys extracted from text."""
    words = text.lower().split()[:3]
    return Learning(
        category="tool_correction",
        trigger_keys=words,
        learning=text,
        tool_name="test_tool",
        agent_id="test-agent",
        scope=MemoryScope.AGENT,
        org_id=org_id,
        status=status,
    )


async def _store_learning(store: InMemoryLearningStore, learning: Learning) -> None:
    """Store a learning in the store."""
    await store.store(learning)


class TestSoulNeverTruncated:
    """Soul prompt must NEVER be truncated, even when it exceeds budget."""

    async def test_soul_included_when_exceeds_budget(self) -> None:
        builder = ContextBuilder()
        prompts = FakePromptManager()
        identity = _make_identity()

        # Soul is 200 chars, but budget is only 10 tokens (40 chars)
        soul_text = "X" * 200
        prompts.seed("agent.test-agent.soul", soul_text)

        messages = [{"role": "user", "content": "hello"}]
        result = await builder.build(
            messages,
            identity,
            prompt_manager=prompts,
            system_token_budget=10,
        )

        system_msg = result[0]
        assert system_msg["role"] == "system"
        assert soul_text in system_msg["content"]

    async def test_soul_intact_not_shortened(self) -> None:
        builder = ContextBuilder()
        prompts = FakePromptManager()
        identity = _make_identity()

        soul_text = "A" * 500
        prompts.seed("agent.test-agent.soul", soul_text)

        messages = [{"role": "user", "content": "hello"}]
        result = await builder.build(
            messages,
            identity,
            prompt_manager=prompts,
            system_token_budget=5,
        )

        system_content = result[0]["content"]
        # Full soul must appear -- no truncation
        assert soul_text in system_content
        assert len(soul_text) == 500


class TestSmallBudgetDropsMatchedFirst:
    """Under tight budget, matched learnings are dropped before soul."""

    async def test_matched_learnings_dropped_when_budget_exhausted_by_soul(self) -> None:
        builder = ContextBuilder()
        prompts = FakePromptManager()
        store = InMemoryLearningStore()
        identity = _make_identity()

        # Soul uses all of the budget
        soul_text = "S" * 400
        prompts.seed("agent.test-agent.soul", soul_text)

        # Add a matched learning that would trigger on "hello"
        lr = _make_learning("hello world correction")
        await _store_learning(store, lr)

        # Budget: 100 tokens = 400 chars. Soul uses exactly 400.
        messages = [{"role": "user", "content": "hello world correction"}]
        result = await builder.build(
            messages,
            identity,
            prompt_manager=prompts,
            learning_store=store,
            agent_id="test-agent",
            org_id="org1",
            system_token_budget=100,
        )

        system_content = result[0]["content"]
        # Soul survives
        assert soul_text in system_content
        # Matched learning text should NOT appear (budget exhausted)
        assert "hello world correction" not in system_content

    async def test_soul_present_learnings_absent_under_tight_budget(self) -> None:
        builder = ContextBuilder()
        prompts = FakePromptManager()
        store = InMemoryLearningStore()
        identity = _make_identity()

        soul_text = "Important soul content " * 20  # ~460 chars
        prompts.seed("agent.test-agent.soul", soul_text)

        # Matched learning
        lr = _make_learning("fix the entity id")
        await _store_learning(store, lr)

        # Budget smaller than soul -- learnings get zero space
        budget_tokens = len(soul_text) // _CHARS_PER_TOKEN - 5
        messages = [{"role": "user", "content": "fix the entity id"}]
        result = await builder.build(
            messages,
            identity,
            prompt_manager=prompts,
            learning_store=store,
            agent_id="test-agent",
            org_id="org1",
            system_token_budget=budget_tokens,
        )

        system_content = result[0]["content"]
        assert soul_text in system_content
        assert "fix the entity id" not in system_content


class TestPromotedSurvivesOverMatched:
    """Promoted learnings have higher priority than matched learnings."""

    async def test_promoted_included_matched_dropped_under_tight_budget(self) -> None:
        builder = ContextBuilder()
        prompts = FakePromptManager()
        store = InMemoryLearningStore()
        identity = _make_identity()

        # Small soul to leave some budget
        soul_text = "Be helpful."
        prompts.seed("agent.test-agent.soul", soul_text)

        # Add a promoted learning (short)
        promoted_lr = _make_learning("promoted correction")
        promoted_lr.status = "promoted"
        await _store_learning(store, promoted_lr)

        # Add a matched learning
        matched_lr = _make_learning("matched correction about keywords")
        await _store_learning(store, matched_lr)

        # Budget: enough for soul + promoted, but not matched
        soul_chars = len(soul_text)
        promoted_entry = f"- {promoted_lr.learning}"
        promoted_overhead = (
            len('<stronghold:corrections type="promoted">')
            + len("</stronghold:corrections>")
            + 2
            + len(promoted_entry)
            + 1
        )
        # Set budget to fit soul + promoted but barely
        budget_chars = soul_chars + promoted_overhead + 10
        budget_tokens = budget_chars // _CHARS_PER_TOKEN

        messages = [{"role": "user", "content": "matched correction about keywords"}]
        result = await builder.build(
            messages,
            identity,
            prompt_manager=prompts,
            learning_store=store,
            agent_id="test-agent",
            org_id="org1",
            system_token_budget=budget_tokens,
        )

        system_content = result[0]["content"]
        # Promoted learning should be present
        assert "promoted correction" in system_content
        # Matched learning should be absent (budget exhausted by soul + promoted)
        assert "matched correction about keywords" not in system_content


class TestGenerousBudgetIncludesAll:
    """When budget is generous, all items (soul + promoted + matched) are included."""

    async def test_all_items_included_with_large_budget(self) -> None:
        builder = ContextBuilder()
        prompts = FakePromptManager()
        store = InMemoryLearningStore()
        identity = _make_identity()

        soul_text = "Agent soul prompt."
        prompts.seed("agent.test-agent.soul", soul_text)

        # Promoted
        promoted_lr = _make_learning("promoted tip A")
        promoted_lr.status = "promoted"
        await _store_learning(store, promoted_lr)

        # Matched (trigger keys match user text)
        matched_lr = _make_learning("matched tip B about widgets")
        await _store_learning(store, matched_lr)

        # Very generous budget: 10000 tokens
        messages = [{"role": "user", "content": "matched tip B about widgets"}]
        result = await builder.build(
            messages,
            identity,
            prompt_manager=prompts,
            learning_store=store,
            agent_id="test-agent",
            org_id="org1",
            system_token_budget=10000,
        )

        system_content = result[0]["content"]
        assert soul_text in system_content
        assert "promoted tip A" in system_content
        assert "matched tip B about widgets" in system_content

    async def test_multiple_learnings_all_fit(self) -> None:
        builder = ContextBuilder()
        prompts = FakePromptManager()
        store = InMemoryLearningStore()
        identity = _make_identity()

        prompts.seed("agent.test-agent.soul", "Soul.")

        # Multiple promoted
        for i in range(3):
            lr = _make_learning(f"promoted rule {i}")
            lr.status = "promoted"
            # Use unique trigger keys to avoid dedup
            lr.trigger_keys = [f"promo{i}"]
            await _store_learning(store, lr)

        # Multiple matched
        for i in range(3):
            lr = _make_learning(f"matched rule {i} about gadgets")
            lr.trigger_keys = ["gadgets", f"rule{i}"]
            await _store_learning(store, lr)

        messages = [{"role": "user", "content": "gadgets rule0 rule1 rule2"}]
        result = await builder.build(
            messages,
            identity,
            prompt_manager=prompts,
            learning_store=store,
            agent_id="test-agent",
            org_id="org1",
            system_token_budget=50000,
        )

        system_content = result[0]["content"]
        assert "Soul." in system_content
        for i in range(3):
            assert f"promoted rule {i}" in system_content
            assert f"matched rule {i} about gadgets" in system_content
