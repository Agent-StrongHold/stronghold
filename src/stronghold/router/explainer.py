"""Human-readable routing explanations."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from stronghold.types.intent import Intent
    from stronghold.types.model import ModelSelection


def explain_selection(selection: ModelSelection, intent: Intent) -> str:
    """Generate a 1-2 sentence explanation of why this model was selected.

    Handles both normal selections (with candidates) and fallback selections
    (no candidates, score=0).
    """
    # Fallback path — no candidates scored
    if not selection.candidates:
        return (
            f"{intent.task_type.capitalize()} task detected "
            f"(classified by {intent.classified_by}). "
            f"Fallback to {selection.model_id} — no models matched routing filters."
        )

    best = selection.candidates[0]

    # Build classification context
    classification_note = f"keyword score {intent.keyword_score}"
    if intent.classified_by == "llm":
        classification_note = "LLM classification"
    elif intent.classified_by == "hint":
        classification_note = "explicit hint"

    # Build advantage description
    advantages: list[str] = []
    advantages.append(f"quality {best.quality}")
    if best.tier:
        advantages.append(f"{best.tier} tier")
    if best.usage_pct < 0.5:
        advantages.append("low quota usage")

    advantage_str = ", ".join(advantages)

    summary = (
        f"{intent.task_type.capitalize()} task detected ({classification_note}). "
        f"{selection.model_id} selected: {advantage_str}."
    )

    # Mention runner-up if there are multiple candidates
    if len(selection.candidates) > 1:
        runner = selection.candidates[1]
        gap = round(best.score - runner.score, 4)
        summary += f" Runner-up: {runner.model_id} (score gap {gap})."

    return summary


def explain_candidates(
    selection: ModelSelection,
    intent: Intent,
) -> list[dict[str, Any]]:
    """Generate detailed breakdown of all candidates and their scores.

    Returns a list of dicts, one per candidate, each containing:
    - model: the model_id
    - score: the computed score
    - selected: whether this candidate was chosen
    - tier: the model tier
    - quality: adjusted quality
    - effective_cost: cost after scarcity adjustments
    - usage_pct: current quota usage percentage
    - reasons: list of human-readable reason strings
    """
    if not selection.candidates:
        return []

    result: list[dict[str, Any]] = []
    best_id = selection.model_id

    for candidate in selection.candidates:
        reasons: list[str] = []

        # Quality assessment
        if candidate.quality >= 0.8:
            reasons.append("high quality model")
        elif candidate.quality >= 0.5:
            reasons.append("moderate quality")
        else:
            reasons.append("lower quality")

        # Tier info
        reasons.append(f"{candidate.tier} tier")

        # Cost assessment
        if candidate.effective_cost < 0.001:
            reasons.append("very low cost")
        elif candidate.effective_cost < 0.01:
            reasons.append("moderate cost")
        else:
            reasons.append("higher cost")

        # Quota headroom
        if candidate.usage_pct < 0.3:
            reasons.append("plenty of quota remaining")
        elif candidate.usage_pct < 0.7:
            reasons.append("moderate quota usage")
        else:
            reasons.append("high quota usage")

        # Selection outcome
        is_selected = candidate.model_id == best_id
        if is_selected:
            reasons.append(f"SELECTED (score {candidate.score})")
        else:
            gap = round(selection.score - candidate.score, 4)
            reasons.append(f"not selected (score gap {gap} vs winner)")

        result.append(
            {
                "model": candidate.model_id,
                "score": candidate.score,
                "selected": is_selected,
                "tier": candidate.tier,
                "quality": candidate.quality,
                "effective_cost": candidate.effective_cost,
                "usage_pct": candidate.usage_pct,
                "reasons": reasons,
            }
        )

    return result
