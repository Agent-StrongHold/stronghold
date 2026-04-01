"""Tests for ContextBuilder token budget enforcement.

Covers:
- Token budget respected (total context never exceeds limit)
- Priority ordering (soul > promoted learnings > matched learnings)
- Lower-priority items dropped when budget is tight
- Empty inputs produce minimal context
- Learnings injected in context when budget allows
- Soul prompt never truncated even if it exceeds budget
- Promoted and matched learnings each get their own XML blocks
- Budget exhaustion drops learnings gracefully
"""

from __future__ import annotations

from stronghold.agents.context_builder import (
    _CHARS_PER_TOKEN,
    ContextBuilder,
    _estimate_tokens,
)
from stronghold.memory.learnings.store import InMemoryLearningStore
from stronghold.types.agent import AgentIdentity
from stronghold.types.memory import Learning, MemoryScope
from tests.fakes import FakePromptManager

# ── Helpers ──────────────────────────────────────────────────────────


def _identity(
    *,
    name: str = "test-agent",
    soul_prompt_name: str = "",
    learnings: bool = True,
) -> AgentIdentity:
    """Build an AgentIdentity with optional learnings enabled."""
    mem_cfg: dict[str, object] = {"learnings": True} if learnings else {}
    return AgentIdentity(
        name=name,
        soul_prompt_name=soul_prompt_name,
        memory_config=mem_cfg,
    )


def _learning(text: str, *, keys: list[str] | None = None, status: str = "active") -> Learning:
    """Build a Learning with the given text and trigger keys."""
    return Learning(
        category="tool_correction",
        trigger_keys=keys or [],
        learning=text,
        tool_name="test_tool",
        agent_id="test-agent",
        scope=MemoryScope.AGENT,
        status=status,
    )


def _system_content(messages: list[dict[str, object]]) -> str:
    """Extract the system message content from a message list."""
    for msg in messages:
        if msg.get("role") == "system":
            return str(msg.get("content", ""))
    return ""


# ── Tests ────────────────────────────────────────────────────────────


class TestEstimateTokens:
    """Unit tests for the _estimate_tokens helper."""

    def test_empty_string(self) -> None:
        assert _estimate_tokens("") == 0

    def test_known_length(self) -> None:
        # 400 chars / 4 chars-per-token = 100 tokens
        text = "a" * 400
        assert _estimate_tokens(text) == 100

    def test_integer_division(self) -> None:
        # 7 chars / 4 = 1 (integer division)
        assert _estimate_tokens("abcdefg") == 1


class TestEmptyInputs:
    """Context builder with no soul, no learnings, no messages."""

    async def test_no_soul_no_learnings_returns_original_messages(self) -> None:
        cb = ContextBuilder()
        pm = FakePromptManager()
        identity = _identity(learnings=False)
        messages: list[dict[str, object]] = [{"role": "user", "content": "hello"}]

        result = await cb.build(messages, identity, prompt_manager=pm)

        # No system message injected — original messages returned as-is
        assert len(result) == 1
        assert result[0]["role"] == "user"

    async def test_empty_messages_with_soul(self) -> None:
        cb = ContextBuilder()
        pm = FakePromptManager()
        pm.seed("agent.test-agent.soul", "You are a test agent.")
        identity = _identity()

        result = await cb.build([], identity, prompt_manager=pm)

        assert len(result) == 1
        assert result[0]["role"] == "system"
        assert result[0]["content"] == "You are a test agent."


class TestSoulPromptPriority:
    """Soul prompt is always included, never truncated."""

    async def test_soul_included_with_generous_budget(self) -> None:
        cb = ContextBuilder()
        pm = FakePromptManager()
        soul = "You are an expert coder."
        pm.seed("agent.coder.soul", soul)
        identity = _identity(name="coder")

        result = await cb.build(
            [{"role": "user", "content": "hi"}],
            identity,
            prompt_manager=pm,
            system_token_budget=4096,
        )

        sys_content = _system_content(result)
        assert soul in sys_content

    async def test_soul_included_even_when_it_exceeds_budget(self) -> None:
        """Soul prompt is never truncated. If it alone exceeds the budget,
        it is still included — but learnings are dropped."""
        cb = ContextBuilder()
        pm = FakePromptManager()
        # Soul: 200 chars = 50 tokens. Budget = 10 tokens (40 chars).
        soul = "X" * 200
        pm.seed("agent.test-agent.soul", soul)

        store = InMemoryLearningStore()
        lr = _learning("This should be dropped", keys=["hi"])
        lr.status = "promoted"
        await store.store(lr)

        identity = _identity()
        result = await cb.build(
            [{"role": "user", "content": "hi"}],
            identity,
            prompt_manager=pm,
            learning_store=store,
            system_token_budget=10,
        )

        sys_content = _system_content(result)
        # Soul present despite exceeding budget
        assert soul in sys_content
        # Learning was dropped (budget went negative after soul)
        assert "This should be dropped" not in sys_content

    async def test_custom_soul_prompt_name(self) -> None:
        cb = ContextBuilder()
        pm = FakePromptManager()
        pm.seed("custom.soul", "I am custom.")
        identity = _identity(soul_prompt_name="custom.soul")

        result = await cb.build(
            [{"role": "user", "content": "hi"}],
            identity,
            prompt_manager=pm,
        )

        assert "I am custom." in _system_content(result)


class TestPromotedLearnings:
    """Promoted learnings appear after soul, in their own XML block."""

    async def test_promoted_learnings_injected(self) -> None:
        cb = ContextBuilder()
        pm = FakePromptManager()
        pm.seed("agent.test-agent.soul", "Soul.")

        store = InMemoryLearningStore()
        lr = _learning("Use entity_id fan.bedroom", keys=["fan"])
        await store.store(lr)
        # Promote it
        lr.status = "promoted"

        identity = _identity()
        result = await cb.build(
            [{"role": "user", "content": "turn on fan"}],
            identity,
            prompt_manager=pm,
            learning_store=store,
            org_id="",
            system_token_budget=4096,
        )

        sys_content = _system_content(result)
        assert '<stronghold:corrections type="promoted">' in sys_content
        assert "Use entity_id fan.bedroom" in sys_content

    async def test_promoted_learnings_dropped_when_budget_exhausted(self) -> None:
        cb = ContextBuilder()
        pm = FakePromptManager()
        # Soul uses most of the budget: 80 chars = 20 tokens
        soul = "S" * 80
        pm.seed("agent.test-agent.soul", soul)

        store = InMemoryLearningStore()
        # Each promoted learning is long — 100 chars
        for i in range(5):
            lr = _learning("P" * 100 + f" #{i}", keys=["fan"])
            await store.store(lr)
            lr.status = "promoted"

        identity = _identity()
        # Budget = 25 tokens = 100 chars. Soul uses 80, leaving 20 for learnings.
        result = await cb.build(
            [{"role": "user", "content": "fan"}],
            identity,
            prompt_manager=pm,
            learning_store=store,
            system_token_budget=25,
        )

        sys_content = _system_content(result)
        assert soul in sys_content
        # Not enough room for any 100-char promoted learning (overhead + entry > 20 chars)
        assert "promoted" not in sys_content or sys_content.count("- P") == 0

    async def test_promoted_not_injected_when_learnings_disabled(self) -> None:
        cb = ContextBuilder()
        pm = FakePromptManager()
        pm.seed("agent.test-agent.soul", "Soul.")

        store = InMemoryLearningStore()
        lr = _learning("Should not appear", keys=["hi"])
        await store.store(lr)
        lr.status = "promoted"

        identity = _identity(learnings=False)
        result = await cb.build(
            [{"role": "user", "content": "hi"}],
            identity,
            prompt_manager=pm,
            learning_store=store,
        )

        sys_content = _system_content(result)
        assert "Should not appear" not in sys_content


class TestMatchedLearnings:
    """Matched learnings appear after promoted, based on keyword relevance."""

    async def test_matched_learnings_injected_by_keyword(self) -> None:
        cb = ContextBuilder()
        pm = FakePromptManager()
        pm.seed("agent.test-agent.soul", "Soul.")

        store = InMemoryLearningStore()
        lr = _learning("Use full path for bedroom light", keys=["bedroom", "light"])
        await store.store(lr)

        identity = _identity()
        result = await cb.build(
            [{"role": "user", "content": "turn on bedroom light"}],
            identity,
            prompt_manager=pm,
            learning_store=store,
            agent_id="test-agent",
            system_token_budget=4096,
        )

        sys_content = _system_content(result)
        assert '<stronghold:corrections type="matched">' in sys_content
        assert "Use full path for bedroom light" in sys_content

    async def test_matched_not_injected_without_keyword_match(self) -> None:
        cb = ContextBuilder()
        pm = FakePromptManager()
        pm.seed("agent.test-agent.soul", "Soul.")

        store = InMemoryLearningStore()
        lr = _learning("Irrelevant learning", keys=["garage", "door"])
        await store.store(lr)

        identity = _identity()
        result = await cb.build(
            [{"role": "user", "content": "turn on bedroom light"}],
            identity,
            prompt_manager=pm,
            learning_store=store,
            agent_id="test-agent",
            system_token_budget=4096,
        )

        sys_content = _system_content(result)
        assert "Irrelevant learning" not in sys_content

    async def test_matched_learnings_dropped_when_budget_tight(self) -> None:
        cb = ContextBuilder()
        pm = FakePromptManager()
        # Soul: 60 chars = 15 tokens
        soul = "S" * 60
        pm.seed("agent.test-agent.soul", soul)

        store = InMemoryLearningStore()
        # Long matched learning
        lr = _learning("M" * 200, keys=["fan"])
        await store.store(lr)

        identity = _identity()
        # Budget = 20 tokens = 80 chars. Soul uses 60, leaving 20.
        result = await cb.build(
            [{"role": "user", "content": "fan"}],
            identity,
            prompt_manager=pm,
            learning_store=store,
            agent_id="test-agent",
            system_token_budget=20,
        )

        sys_content = _system_content(result)
        assert soul in sys_content
        # Matched learning too big to fit
        assert "M" * 200 not in sys_content


class TestBudgetEnforcement:
    """Total system prompt respects token budget."""

    async def test_total_context_within_budget(self) -> None:
        cb = ContextBuilder()
        pm = FakePromptManager()
        soul = "You are a helpful agent."
        pm.seed("agent.test-agent.soul", soul)

        store = InMemoryLearningStore()
        for i in range(20):
            lr = _learning(f"Learning number {i}", keys=["hello"])
            await store.store(lr)

        # Also add promoted
        for i in range(10):
            lr2 = _learning(f"Promoted tip {i}", keys=["hello"])
            await store.store(lr2)
            lr2.status = "promoted"

        identity = _identity()
        budget = 100  # 400 chars
        result = await cb.build(
            [{"role": "user", "content": "hello"}],
            identity,
            prompt_manager=pm,
            learning_store=store,
            agent_id="test-agent",
            system_token_budget=budget,
        )

        sys_content = _system_content(result)
        # Soul is always present (not counted against budget for truncation)
        assert soul in sys_content
        # Verify the non-soul portion respects budget
        non_soul = sys_content.replace(soul, "")
        # Non-soul chars should be within the remaining budget
        remaining_budget_chars = (budget * _CHARS_PER_TOKEN) - len(soul)
        # Allow some slack for the "\n\n" joiners
        assert len(non_soul) <= remaining_budget_chars + 20  # +20 for separator overhead

    async def test_partial_promoted_learnings_fit(self) -> None:
        """When budget allows some but not all promoted learnings, only a subset is included."""
        cb = ContextBuilder()
        pm = FakePromptManager()
        pm.seed("agent.test-agent.soul", "Soul.")

        store = InMemoryLearningStore()
        # Each promoted learning: "- " + 40 chars = 42 chars per entry
        for i in range(10):
            lr = _learning("A" * 40 + f"_{i}", keys=["hi"])
            await store.store(lr)
            lr.status = "promoted"

        identity = _identity()
        # Budget: soul(5 chars) + overhead for XML tags (~80 chars) + space for ~2 entries
        # 2 entries ~= 84 chars each. Total needed = 5 + 80 + 168 = 253.
        # Set budget to allow soul + ~3 entries = 300 chars = 75 tokens.
        result = await cb.build(
            [{"role": "user", "content": "hi"}],
            identity,
            prompt_manager=pm,
            learning_store=store,
            system_token_budget=75,
        )

        sys_content = _system_content(result)
        # At least one promoted learning included
        assert "promoted" in sys_content
        # But not all 10 (budget too small)
        assert sys_content.count("- A") < 10

    async def test_promoted_before_matched_priority(self) -> None:
        """Promoted learnings consume budget before matched learnings."""
        cb = ContextBuilder()
        pm = FakePromptManager()
        pm.seed("agent.test-agent.soul", "Soul.")

        store = InMemoryLearningStore()
        # Big promoted learning that eats most of the budget
        lr_promoted = _learning("P" * 150, keys=["hello"])
        await store.store(lr_promoted)
        lr_promoted.status = "promoted"

        # Matched learning that would fit if promoted wasn't there
        lr_matched = _learning("Matched insight", keys=["hello"])
        await store.store(lr_matched)

        identity = _identity()
        # Budget: soul(5) + promoted(~160 + overhead ~80) = ~245. ~250 chars = 62 tokens.
        # Not enough room for matched after promoted.
        result = await cb.build(
            [{"role": "user", "content": "hello"}],
            identity,
            prompt_manager=pm,
            learning_store=store,
            agent_id="test-agent",
            system_token_budget=62,
        )

        sys_content = _system_content(result)
        # Promoted consumed the budget
        assert "P" * 150 in sys_content
        # Matched was dropped
        assert "Matched insight" not in sys_content


class TestExistingSystemMessage:
    """Handles pre-existing system messages in the input."""

    async def test_prepends_to_existing_system_message(self) -> None:
        cb = ContextBuilder()
        pm = FakePromptManager()
        pm.seed("agent.test-agent.soul", "Soul prefix.")
        identity = _identity()

        messages: list[dict[str, object]] = [
            {"role": "system", "content": "Existing system content."},
            {"role": "user", "content": "hello"},
        ]

        result = await cb.build(messages, identity, prompt_manager=pm)

        sys_content = _system_content(result)
        # Soul is prepended to existing system message
        assert sys_content.startswith("Soul prefix.")
        assert "Existing system content." in sys_content

    async def test_inserts_system_when_none_exists(self) -> None:
        cb = ContextBuilder()
        pm = FakePromptManager()
        pm.seed("agent.test-agent.soul", "New system.")
        identity = _identity()

        messages: list[dict[str, object]] = [
            {"role": "user", "content": "hello"},
        ]

        result = await cb.build(messages, identity, prompt_manager=pm)

        assert result[0]["role"] == "system"
        assert result[0]["content"] == "New system."
        assert result[1]["role"] == "user"


class TestUserTextExtraction:
    """Matched learnings use the last user message for keyword matching."""

    async def test_uses_last_user_message_for_matching(self) -> None:
        cb = ContextBuilder()
        pm = FakePromptManager()
        pm.seed("agent.test-agent.soul", "Soul.")

        store = InMemoryLearningStore()
        lr = _learning("Use dimmer for lamp", keys=["lamp"])
        await store.store(lr)

        identity = _identity()
        messages: list[dict[str, object]] = [
            {"role": "user", "content": "turn on the fan"},
            {"role": "assistant", "content": "Done."},
            {"role": "user", "content": "now dim the lamp"},
        ]

        result = await cb.build(
            messages,
            identity,
            prompt_manager=pm,
            learning_store=store,
            agent_id="test-agent",
            system_token_budget=4096,
        )

        sys_content = _system_content(result)
        # "lamp" matches the last user message
        assert "Use dimmer for lamp" in sys_content

    async def test_no_user_message_skips_matched(self) -> None:
        cb = ContextBuilder()
        pm = FakePromptManager()
        pm.seed("agent.test-agent.soul", "Soul.")

        store = InMemoryLearningStore()
        lr = _learning("Should not match", keys=["anything"])
        await store.store(lr)

        identity = _identity()
        # Only assistant messages — no user text to match against
        messages: list[dict[str, object]] = [
            {"role": "assistant", "content": "I was already talking."},
        ]

        result = await cb.build(
            messages,
            identity,
            prompt_manager=pm,
            learning_store=store,
            agent_id="test-agent",
            system_token_budget=4096,
        )

        sys_content = _system_content(result)
        assert "Should not match" not in sys_content


class TestNoLearningStore:
    """When no learning_store is provided, only soul prompt is included."""

    async def test_soul_only_without_store(self) -> None:
        cb = ContextBuilder()
        pm = FakePromptManager()
        pm.seed("agent.test-agent.soul", "Just the soul.")
        identity = _identity()

        result = await cb.build(
            [{"role": "user", "content": "hello"}],
            identity,
            prompt_manager=pm,
            # No learning_store
            system_token_budget=4096,
        )

        sys_content = _system_content(result)
        assert sys_content == "Just the soul."
        assert "corrections" not in sys_content


class TestOrgIsolation:
    """Learnings are scoped by org_id — cross-org learnings are invisible."""

    async def test_org_scoped_learnings_not_leaked(self) -> None:
        cb = ContextBuilder()
        pm = FakePromptManager()
        pm.seed("agent.test-agent.soul", "Soul.")

        store = InMemoryLearningStore()
        # Learning for org-A
        lr_a = _learning("Org-A secret", keys=["hello"])
        lr_a.org_id = "org-A"
        await store.store(lr_a)

        # Learning for org-B
        lr_b = _learning("Org-B secret", keys=["hello"])
        lr_b.org_id = "org-B"
        await store.store(lr_b)

        identity = _identity()
        # Build context for org-A
        result = await cb.build(
            [{"role": "user", "content": "hello"}],
            identity,
            prompt_manager=pm,
            learning_store=store,
            agent_id="test-agent",
            org_id="org-A",
            system_token_budget=4096,
        )

        sys_content = _system_content(result)
        assert "Org-A secret" in sys_content
        assert "Org-B secret" not in sys_content
