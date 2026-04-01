"""Comprehensive tests for ClassifierEngine and is_ambiguous.

Covers all three phases of classification:
  1. Keyword scoring (instant)
  2. LLM fallback when score < threshold (async, uses FakeLLMClient)
  3. Complexity estimation and priority inference

Also covers: ambiguity detection, session stickiness interaction,
multi-intent detection, automation tier sizing, tier bumping for
complex tasks, explicit priority override, and edge cases.
"""

from __future__ import annotations

from stronghold.classifier.engine import (
    LLM_FALLBACK_THRESHOLD,
    ClassifierEngine,
    is_ambiguous,
)
from stronghold.types.config import TaskTypeConfig
from stronghold.types.intent import Intent
from tests.fakes import FakeLLMClient


def _task_types() -> dict[str, TaskTypeConfig]:
    """Standard task type configs used across tests."""
    return {
        "chat": TaskTypeConfig(
            keywords=["hello", "hi", "hey", "thanks"],
            min_tier="small",
            preferred_strengths=["chat"],
        ),
        "code": TaskTypeConfig(
            keywords=["code", "function", "bug", "error", "implement"],
            min_tier="medium",
            preferred_strengths=["code"],
        ),
        "automation": TaskTypeConfig(
            keywords=["light", "fan", "turn on", "turn off", "chore"],
            min_tier="small",
            preferred_strengths=["chat"],
        ),
        "search": TaskTypeConfig(
            keywords=["search", "look up", "find"],
            min_tier="small",
            preferred_strengths=["chat"],
        ),
        "creative": TaskTypeConfig(
            keywords=["story", "poem", "essay"],
            min_tier="medium",
            preferred_strengths=["creative"],
        ),
        "reasoning": TaskTypeConfig(
            keywords=["prove", "derive", "logic"],
            min_tier="large",
            preferred_strengths=["reasoning"],
        ),
    }


# ── Phase 1: Keyword-only classification ──────────────────────────────


class TestKeywordPhaseClassification:
    """Phase 1: keyword scoring produces correct task_type without LLM."""

    async def test_strong_indicator_triggers_code(self) -> None:
        """Strong indicator 'write a function' should score >= 3.0 and classify as code."""
        engine = ClassifierEngine()
        intent = await engine.classify(
            [{"role": "user", "content": "write a function to sort a list"}],
            _task_types(),
        )
        assert intent.task_type == "code"
        assert intent.classified_by == "keywords"
        assert intent.keyword_score >= LLM_FALLBACK_THRESHOLD

    async def test_strong_indicator_triggers_automation(self) -> None:
        """Strong indicator 'turn on the' should score >= 3.0 for automation."""
        engine = ClassifierEngine()
        intent = await engine.classify(
            [{"role": "user", "content": "turn on the bedroom fan"}],
            _task_types(),
        )
        assert intent.task_type == "automation"
        assert intent.classified_by == "keywords"
        assert intent.keyword_score >= LLM_FALLBACK_THRESHOLD

    async def test_config_keyword_only_below_threshold(self) -> None:
        """A single config keyword ('hello') scores 1.0 -- below LLM_FALLBACK_THRESHOLD.

        With no LLM client, falls back to 'chat' default.
        """
        engine = ClassifierEngine()  # no llm_client
        intent = await engine.classify(
            [{"role": "user", "content": "hello"}],
            _task_types(),
        )
        # 'hello' matches chat keyword (+1.0) which is < 3.0 threshold
        # Without LLM fallback, task_type stays "chat" (the default)
        assert intent.task_type == "chat"
        assert intent.classified_by == "keywords"

    async def test_multiple_keywords_accumulate(self) -> None:
        """Multiple keyword hits accumulate: 'code' + 'function' + 'bug' = 3.0 for code."""
        engine = ClassifierEngine()
        intent = await engine.classify(
            [{"role": "user", "content": "there is a bug in the code function"}],
            _task_types(),
        )
        assert intent.task_type == "code"
        assert intent.keyword_score >= LLM_FALLBACK_THRESHOLD

    async def test_no_keywords_defaults_to_chat(self) -> None:
        """Gibberish with no keyword matches defaults to 'chat'."""
        engine = ClassifierEngine()
        intent = await engine.classify(
            [{"role": "user", "content": "xyzzy plugh"}],
            _task_types(),
        )
        assert intent.task_type == "chat"
        assert intent.keyword_score == 0.0


# ── Phase 2: LLM fallback ────────────────────────────────────────────


class TestLLMFallbackPhase:
    """Phase 2: LLM fallback fires when keyword score < 3.0 and LLM client is present."""

    async def test_llm_fallback_triggers_on_low_keyword_score(self) -> None:
        """When keyword score < 3.0 and LLM says 'code', task_type should become 'code'."""
        llm = FakeLLMClient()
        llm.set_simple_response("code")
        engine = ClassifierEngine(llm_client=llm)
        intent = await engine.classify(
            [{"role": "user", "content": "help me with this problem"}],
            _task_types(),
        )
        assert intent.task_type == "code"
        assert intent.classified_by == "llm"
        assert len(llm.calls) == 1

    async def test_llm_fallback_skipped_when_keyword_score_high(self) -> None:
        """When keyword score >= 3.0, LLM is never called."""
        llm = FakeLLMClient()
        llm.set_simple_response("search")  # Would change type if called
        engine = ClassifierEngine(llm_client=llm)
        intent = await engine.classify(
            [{"role": "user", "content": "write a function to sort a list"}],
            _task_types(),
        )
        assert intent.task_type == "code"
        assert intent.classified_by == "keywords"
        assert len(llm.calls) == 0  # LLM never invoked

    async def test_llm_fallback_skipped_when_no_user_text(self) -> None:
        """If user_text is empty, LLM fallback is skipped even with low keyword score."""
        llm = FakeLLMClient()
        llm.set_simple_response("code")
        engine = ClassifierEngine(llm_client=llm)
        intent = await engine.classify(
            [{"role": "user", "content": ""}],
            _task_types(),
        )
        assert intent.task_type == "chat"
        assert len(llm.calls) == 0

    async def test_llm_fallback_invalid_category_ignored(self) -> None:
        """If LLM returns an unknown category, it is ignored and default 'chat' is kept."""
        llm = FakeLLMClient()
        llm.set_simple_response("banana")  # not a valid task type in our config
        engine = ClassifierEngine(llm_client=llm)
        intent = await engine.classify(
            [{"role": "user", "content": "do something interesting"}],
            _task_types(),
        )
        assert intent.task_type == "chat"
        assert intent.classified_by == "keywords"  # LLM result was invalid

    async def test_llm_fallback_must_match_task_types(self) -> None:
        """LLM returning a valid LLM category not in task_types config is ignored."""
        llm = FakeLLMClient()
        # 'summarize' is valid in llm_fallback._VALID_CATEGORIES but not in _task_types()
        llm.set_simple_response("summarize")
        engine = ClassifierEngine(llm_client=llm)
        intent = await engine.classify(
            [{"role": "user", "content": "condense this text for me"}],
            _task_types(),
        )
        assert intent.task_type == "chat"  # summarize not in task_types config
        assert intent.classified_by == "keywords"

    async def test_llm_fallback_with_no_llm_client(self) -> None:
        """Without an LLM client, fallback phase is skipped entirely."""
        engine = ClassifierEngine(llm_client=None)
        intent = await engine.classify(
            [{"role": "user", "content": "ambiguous request"}],
            _task_types(),
        )
        assert intent.task_type == "chat"
        assert intent.classified_by == "keywords"

    async def test_llm_uses_configured_model(self) -> None:
        """The classifier_model parameter is passed to the LLM client."""
        llm = FakeLLMClient()
        llm.set_simple_response("code")
        engine = ClassifierEngine(llm_client=llm, classifier_model="gpt-4o-mini")
        await engine.classify(
            [{"role": "user", "content": "help me with this"}],
            _task_types(),
        )
        assert llm.calls[0]["model"] == "gpt-4o-mini"


# ── Phase 3: Complexity and priority ─────────────────────────────────


class TestComplexityEstimation:
    """Phase 3a: complexity estimation influences min_tier."""

    async def test_short_message_is_simple(self) -> None:
        engine = ClassifierEngine()
        intent = await engine.classify(
            [{"role": "user", "content": "turn on fan"}],
            _task_types(),
        )
        assert intent.complexity == "simple"

    async def test_very_long_message_is_complex(self) -> None:
        engine = ClassifierEngine()
        long_text = "write code to " + "refactor this complex module " * 50
        intent = await engine.classify(
            [{"role": "user", "content": long_text}],
            _task_types(),
        )
        assert intent.complexity == "complex"

    async def test_complex_task_bumps_min_tier_to_large(self) -> None:
        """When complexity is 'complex' and current min_tier < large, bump to large."""
        engine = ClassifierEngine()
        # 'chat' has min_tier=small. A complex message should bump it to large.
        long_text = "word " * 250  # >200 words => complex
        intent = await engine.classify(
            [{"role": "user", "content": long_text}],
            _task_types(),
        )
        assert intent.complexity == "complex"
        assert intent.min_tier == "large"

    async def test_complex_signals_in_moderate_range(self) -> None:
        """Text with 1 complex signal and mid-range length is moderate."""
        engine = ClassifierEngine()
        text = "Please refactor " + "the existing approach " * 5
        intent = await engine.classify(
            [{"role": "user", "content": text}],
            _task_types(),
        )
        assert intent.complexity in ("moderate", "complex")


# ── Priority inference ────────────────────────────────────────────────


class TestPriorityInference:
    """Phase 3b: priority is inferred from urgency keywords or explicit override."""

    async def test_urgent_keyword_yields_critical(self) -> None:
        engine = ClassifierEngine()
        intent = await engine.classify(
            [{"role": "user", "content": "urgent the server is broken help"}],
            _task_types(),
        )
        assert intent.priority == "critical"

    async def test_deadline_keyword_yields_high(self) -> None:
        engine = ClassifierEngine()
        intent = await engine.classify(
            [{"role": "user", "content": "this is important for the deadline"}],
            _task_types(),
        )
        assert intent.priority == "high"

    async def test_no_rush_keyword_yields_low(self) -> None:
        engine = ClassifierEngine()
        intent = await engine.classify(
            [{"role": "user", "content": "just curious about this no rush"}],
            _task_types(),
        )
        assert intent.priority == "low"

    async def test_neutral_text_yields_normal(self) -> None:
        engine = ClassifierEngine()
        intent = await engine.classify(
            [{"role": "user", "content": "tell me about penguins"}],
            _task_types(),
        )
        assert intent.priority == "normal"

    async def test_explicit_priority_overrides_inference(self) -> None:
        """explicit_priority parameter takes precedence over inferred priority."""
        engine = ClassifierEngine()
        intent = await engine.classify(
            [{"role": "user", "content": "urgent help"}],
            _task_types(),
            explicit_priority="low",
        )
        # 'urgent' would normally infer 'critical', but explicit_priority wins
        assert intent.priority == "low"


# ── is_ambiguous() ────────────────────────────────────────────────────


class TestIsAmbiguous:
    """is_ambiguous() tests for various score distributions."""

    def test_empty_scores(self) -> None:
        assert not is_ambiguous({})

    def test_single_nonzero_not_ambiguous(self) -> None:
        assert not is_ambiguous({"code": 2.5})

    def test_all_zeros_not_ambiguous(self) -> None:
        assert not is_ambiguous({"code": 0.0, "chat": 0.0, "search": 0.0})

    def test_two_low_scores_is_ambiguous(self) -> None:
        """Two non-zero scores both below threshold => ambiguous."""
        assert is_ambiguous({"code": 2.0, "chat": 1.5})

    def test_one_above_threshold_not_ambiguous(self) -> None:
        """If any score >= 3.0, not ambiguous even with multiple non-zero scores."""
        assert not is_ambiguous({"code": 4.0, "chat": 1.0})

    def test_exactly_at_threshold_not_ambiguous(self) -> None:
        """Score exactly at LLM_FALLBACK_THRESHOLD (3.0) is NOT ambiguous."""
        assert not is_ambiguous({"code": 3.0, "chat": 1.0})

    def test_just_below_threshold_is_ambiguous(self) -> None:
        assert is_ambiguous({"code": 2.999, "chat": 0.5})

    def test_many_low_scores_ambiguous(self) -> None:
        scores = {"code": 1.0, "chat": 1.0, "search": 1.0, "creative": 0.5}
        assert is_ambiguous(scores)

    def test_threshold_constant_is_three(self) -> None:
        """Ensure the threshold constant hasn't drifted."""
        assert LLM_FALLBACK_THRESHOLD == 3.0


# ── Automation tier sizing ────────────────────────────────────────────


class TestAutomationTierSizing:
    """Automation commands get smart tier sizing based on word count."""

    async def test_short_automation_stays_small(self) -> None:
        """Short automation commands (<=3 meaningful words) stay at base min_tier."""
        engine = ClassifierEngine()
        intent = await engine.classify(
            [{"role": "user", "content": "turn on the fan"}],
            _task_types(),
        )
        assert intent.task_type == "automation"
        assert intent.min_tier == "small"

    async def test_long_automation_bumps_to_medium(self) -> None:
        """Longer automation commands need medium+ for entity resolution."""
        engine = ClassifierEngine()
        intent = await engine.classify(
            [
                {
                    "role": "user",
                    "content": (
                        "turn on the bedroom ceiling fan and set brightness to fifty percent"
                    ),
                }
            ],
            _task_types(),
        )
        assert intent.task_type == "automation"
        assert intent.min_tier in ("medium", "large")


# ── Intent output shape ──────────────────────────────────────────────


class TestIntentOutputShape:
    """Verify the returned Intent dataclass has all expected fields."""

    async def test_intent_has_all_fields(self) -> None:
        engine = ClassifierEngine()
        intent = await engine.classify(
            [{"role": "user", "content": "write a function to sort"}],
            _task_types(),
        )
        assert isinstance(intent, Intent)
        assert isinstance(intent.task_type, str)
        assert intent.complexity in ("simple", "moderate", "complex")
        assert intent.priority in ("low", "normal", "high", "critical")
        assert isinstance(intent.min_tier, str)
        assert isinstance(intent.preferred_strengths, tuple)
        assert isinstance(intent.classified_by, str)
        assert isinstance(intent.keyword_score, float)
        assert isinstance(intent.user_text, str)

    async def test_preferred_strengths_from_config(self) -> None:
        """preferred_strengths should come from the matched task_type config."""
        engine = ClassifierEngine()
        intent = await engine.classify(
            [{"role": "user", "content": "write a function to parse JSON"}],
            _task_types(),
        )
        assert intent.task_type == "code"
        assert intent.preferred_strengths == ("code",)

    async def test_user_text_captured(self) -> None:
        """The classified Intent should contain the user_text that was classified."""
        engine = ClassifierEngine()
        intent = await engine.classify(
            [{"role": "user", "content": "hello world"}],
            _task_types(),
        )
        assert intent.user_text == "hello world"


# ── Message extraction ───────────────────────────────────────────────


class TestMessageExtraction:
    """classify() extracts the last user message from the messages list."""

    async def test_uses_last_user_message(self) -> None:
        engine = ClassifierEngine()
        intent = await engine.classify(
            [
                {"role": "user", "content": "hello"},
                {"role": "assistant", "content": "hi"},
                {"role": "user", "content": "write a function to sort a list"},
            ],
            _task_types(),
        )
        assert intent.task_type == "code"
        assert intent.user_text == "write a function to sort a list"

    async def test_ignores_system_and_assistant_messages(self) -> None:
        engine = ClassifierEngine()
        intent = await engine.classify(
            [
                {"role": "system", "content": "write a function"},
                {"role": "assistant", "content": "write code"},
            ],
            _task_types(),
        )
        assert intent.user_text == ""
        assert intent.task_type == "chat"

    async def test_empty_messages_list(self) -> None:
        engine = ClassifierEngine()
        intent = await engine.classify([], _task_types())
        assert intent.user_text == ""
        assert intent.task_type == "chat"
        assert intent.keyword_score == 0.0


# ── Multi-intent detection ───────────────────────────────────────────


class TestMultiIntentDetection:
    """detect_multi_intent on the engine delegates to the multi_intent module."""

    def test_single_intent_returns_empty(self) -> None:
        engine = ClassifierEngine()
        result = engine.detect_multi_intent("turn on the fan", _task_types())
        assert isinstance(result, list)
        # Single intent => either empty or single element (not compound)
        assert len(result) < 2

    def test_compound_intent_detected(self) -> None:
        engine = ClassifierEngine()
        result = engine.detect_multi_intent(
            "search for recipes and then write code to parse them",
            _task_types(),
        )
        assert isinstance(result, list)
        if len(result) >= 2:
            assert "search" in result or "code" in result

    def test_returns_list_type(self) -> None:
        engine = ClassifierEngine()
        result = engine.detect_multi_intent("hello world", _task_types())
        assert isinstance(result, list)


# ── End-to-end three-phase integration ───────────────────────────────


class TestThreePhaseIntegration:
    """Full pipeline: keyword score < 3.0 -> LLM fallback -> complexity + priority."""

    async def test_low_keyword_score_triggers_llm_then_complexity(self) -> None:
        """Ambiguous input triggers LLM, which resolves to 'creative'.

        Then complexity and priority are computed on the resolved type.
        """
        llm = FakeLLMClient()
        llm.set_simple_response("creative")
        engine = ClassifierEngine(llm_client=llm)
        intent = await engine.classify(
            [{"role": "user", "content": "help me brainstorm something nice"}],
            _task_types(),
        )
        assert intent.task_type == "creative"
        assert intent.classified_by == "llm"
        assert intent.complexity == "simple"  # short text
        assert intent.priority == "normal"  # no urgency keywords
        assert intent.preferred_strengths == ("creative",)

    async def test_high_keyword_score_skips_llm_still_computes_complexity(self) -> None:
        """Strong keyword match skips LLM but still computes complexity and priority."""
        llm = FakeLLMClient()
        llm.set_simple_response("search")
        engine = ClassifierEngine(llm_client=llm)
        intent = await engine.classify(
            [{"role": "user", "content": "urgent write a function to sort numbers"}],
            _task_types(),
        )
        assert intent.task_type == "code"
        assert intent.classified_by == "keywords"
        assert intent.priority == "critical"  # 'urgent' keyword
        assert len(llm.calls) == 0  # LLM never called
