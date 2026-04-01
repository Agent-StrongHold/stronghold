"""Classifier feedback loop — self-calibrating intent classification.

Retrospective labeling: compares classified task_type vs actual tools used,
then adjusts keyword weights so the classifier improves over time.

Weight adjustment rules:
  +0.1 per keyword on correct classification
  -0.1 per keyword on incorrect classification
  Bounded to [0.0, 5.0]

Ground truth is derived from actual tools used via a tool→task_type map.
When multiple tools map to different task types, majority vote decides.
Ties are broken in favor of the classified type (benefit of the doubt).
"""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass

WEIGHT_INCREMENT: float = 0.1
WEIGHT_DECREMENT: float = 0.1
WEIGHT_MIN: float = 0.0
WEIGHT_MAX: float = 5.0


@dataclass
class _Outcome:
    """A single recorded classification outcome."""

    classified_type: str
    actual_type: str
    keywords_matched: list[str]
    correct: bool


class ClassifierFeedback:
    """Tracks classifier outcomes and produces keyword weight adjustments.

    Args:
        tool_task_map: Mapping from tool name to the task_type that tool implies.
    """

    def __init__(self, tool_task_map: dict[str, str]) -> None:
        self._tool_task_map = tool_task_map
        self._outcomes: list[_Outcome] = []
        self._keyword_deltas: dict[str, float] = {}

    def record_outcome(
        self,
        classified_type: str,
        actual_tools: list[str],
        keywords_matched: list[str],
    ) -> None:
        """Record a classification outcome for retrospective analysis.

        Args:
            classified_type: The task_type the classifier predicted.
            actual_tools: Tools the agent actually invoked during execution.
            keywords_matched: Keywords that contributed to the classification.
        """
        actual_type = self._resolve_actual_type(classified_type, actual_tools)
        correct = classified_type == actual_type

        outcome = _Outcome(
            classified_type=classified_type,
            actual_type=actual_type,
            keywords_matched=keywords_matched,
            correct=correct,
        )
        self._outcomes.append(outcome)

        # Update keyword deltas
        for kw in keywords_matched:
            if kw not in self._keyword_deltas:
                self._keyword_deltas[kw] = 0.0
            if correct:
                self._keyword_deltas[kw] += WEIGHT_INCREMENT
            else:
                self._keyword_deltas[kw] -= WEIGHT_DECREMENT

    def get_weight_adjustments(self) -> dict[str, float]:
        """Return bounded keyword weight adjustments.

        Each keyword's cumulative adjustment is clamped to [0.0, 5.0].
        """
        return {
            kw: max(WEIGHT_MIN, min(WEIGHT_MAX, delta))
            for kw, delta in self._keyword_deltas.items()
        }

    def get_accuracy_stats(self) -> dict[str, object]:
        """Return accuracy statistics.

        Returns:
            Dict with keys: total, correct, incorrect, accuracy, per_type.
        """
        total = len(self._outcomes)
        correct = sum(1 for o in self._outcomes if o.correct)
        incorrect = total - correct
        accuracy = correct / total if total > 0 else 0.0

        # Per-type breakdown
        per_type: dict[str, dict[str, int]] = {}
        for outcome in self._outcomes:
            ct = outcome.classified_type
            if ct not in per_type:
                per_type[ct] = {"total": 0, "correct": 0, "incorrect": 0}
            per_type[ct]["total"] += 1
            if outcome.correct:
                per_type[ct]["correct"] += 1
            else:
                per_type[ct]["incorrect"] += 1

        return {
            "total": total,
            "correct": correct,
            "incorrect": incorrect,
            "accuracy": accuracy,
            "per_type": per_type,
        }

    def _resolve_actual_type(
        self,
        classified_type: str,
        actual_tools: list[str],
    ) -> str:
        """Determine the actual task type from tools used.

        Uses majority vote among tool→task_type mappings.
        If no tools or all tools are unknown, returns classified_type.
        On a tie, the classified_type wins (benefit of the doubt).
        """
        if not actual_tools:
            return classified_type

        type_counts: Counter[str] = Counter()
        for tool in actual_tools:
            task_type = self._tool_task_map.get(tool)
            if task_type is not None:
                type_counts[task_type] += 1

        if not type_counts:
            return classified_type

        max_count = max(type_counts.values())
        top_types = [t for t, c in type_counts.items() if c == max_count]

        # Tie-break: favor classified_type
        if classified_type in top_types:
            return classified_type
        return top_types[0]
