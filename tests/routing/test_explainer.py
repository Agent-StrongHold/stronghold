"""Tests for routing explanation API.

Verifies that explain_selection() and explain_candidates() produce
human-readable routing explanations and candidate breakdowns.
"""

from __future__ import annotations

from stronghold.router.explainer import explain_candidates, explain_selection
from stronghold.types.model import ModelCandidate, ModelSelection
from tests.factories import build_intent


def _make_candidates() -> tuple[ModelCandidate, ...]:
    """Build a realistic set of scored candidates."""
    return (
        ModelCandidate(
            model_id="mistral-large",
            litellm_id="azure/mistral-large",
            provider="azure",
            score=0.85,
            quality=0.68,
            effective_cost=0.002,
            usage_pct=0.30,
            tier="frontier",
        ),
        ModelCandidate(
            model_id="gpt-4o",
            litellm_id="openai/gpt-4o",
            provider="openai",
            score=0.72,
            quality=0.75,
            effective_cost=0.005,
            usage_pct=0.60,
            tier="frontier",
        ),
        ModelCandidate(
            model_id="claude-sonnet",
            litellm_id="anthropic/claude-sonnet",
            provider="anthropic",
            score=0.55,
            quality=0.60,
            effective_cost=0.004,
            usage_pct=0.45,
            tier="large",
        ),
    )


def _make_selection(candidates: tuple[ModelCandidate, ...] | None = None) -> ModelSelection:
    """Build a ModelSelection with candidates."""
    cands = candidates or _make_candidates()
    best = cands[0]
    return ModelSelection(
        model_id=best.model_id,
        litellm_id=best.litellm_id,
        provider=best.provider,
        score=best.score,
        reason="task=code; complexity=moderate; priority=normal",
        candidates=cands,
    )


class TestExplainSelection:
    """Tests for explain_selection()."""

    def test_returns_nonempty_string(self) -> None:
        selection = _make_selection()
        intent = build_intent(task_type="code", keyword_score=4.2)
        result = explain_selection(selection, intent)
        assert isinstance(result, str)
        assert len(result) > 0

    def test_mentions_task_type(self) -> None:
        selection = _make_selection()
        intent = build_intent(task_type="code", keyword_score=4.2)
        result = explain_selection(selection, intent)
        assert "code" in result.lower()

    def test_mentions_selected_model(self) -> None:
        selection = _make_selection()
        intent = build_intent(task_type="code", keyword_score=4.2)
        result = explain_selection(selection, intent)
        assert "mistral-large" in result.lower()

    def test_handles_none_selection(self) -> None:
        """When selection is the fallback path (no candidates), still produces output."""
        fallback = ModelSelection(
            model_id="auto",
            litellm_id="auto",
            provider="unknown",
            score=0.0,
            reason="fallback — no models matched filters",
            candidates=(),
        )
        intent = build_intent(task_type="chat")
        result = explain_selection(fallback, intent)
        assert isinstance(result, str)
        assert len(result) > 0
        assert "fallback" in result.lower()

    def test_mentions_classification_method(self) -> None:
        selection = _make_selection()
        intent = build_intent(task_type="code", classified_by="keywords", keyword_score=4.5)
        result = explain_selection(selection, intent)
        assert "keyword" in result.lower()

    def test_mentions_runner_up_when_close(self) -> None:
        """When there are multiple candidates, mention the runner-up."""
        selection = _make_selection()
        intent = build_intent(task_type="code")
        result = explain_selection(selection, intent)
        # Should mention the runner-up model since there are multiple candidates
        assert "gpt-4o" in result.lower()

    def test_single_candidate_no_runner_up(self) -> None:
        """With only one candidate, no runner-up is mentioned."""
        single = _make_candidates()[:1]
        selection = _make_selection(candidates=single)
        intent = build_intent(task_type="chat")
        result = explain_selection(selection, intent)
        assert "gpt-4o" not in result.lower()


class TestExplainCandidates:
    """Tests for explain_candidates()."""

    def test_returns_list(self) -> None:
        selection = _make_selection()
        intent = build_intent(task_type="code")
        result = explain_candidates(selection, intent)
        assert isinstance(result, list)

    def test_lists_all_candidates(self) -> None:
        selection = _make_selection()
        intent = build_intent(task_type="code")
        result = explain_candidates(selection, intent)
        assert len(result) == 3
        model_ids = [c["model"] for c in result]
        assert "mistral-large" in model_ids
        assert "gpt-4o" in model_ids
        assert "claude-sonnet" in model_ids

    def test_each_candidate_has_score_and_reasons(self) -> None:
        selection = _make_selection()
        intent = build_intent(task_type="code")
        result = explain_candidates(selection, intent)
        for candidate in result:
            assert "model" in candidate
            assert "score" in candidate
            assert "reasons" in candidate
            assert isinstance(candidate["reasons"], list)
            assert len(candidate["reasons"]) > 0

    def test_winner_is_marked(self) -> None:
        selection = _make_selection()
        intent = build_intent(task_type="code")
        result = explain_candidates(selection, intent)
        assert result[0]["selected"] is True
        assert result[1]["selected"] is False

    def test_empty_candidates(self) -> None:
        """Fallback selection with no candidates returns empty list."""
        fallback = ModelSelection(
            model_id="auto",
            litellm_id="auto",
            provider="unknown",
            score=0.0,
            reason="fallback",
            candidates=(),
        )
        intent = build_intent(task_type="chat")
        result = explain_candidates(fallback, intent)
        assert result == []
