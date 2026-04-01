"""Learning evaluator: A/B holdout, contradiction detection, and decay.

Supports data-driven learning management:
- Random holdout (10%) to measure learning effectiveness via A/B comparison
- Outcome tracking per learning to compute injected vs withheld success rates
- Contradiction detection across learnings with overlapping keywords
- Time-based decay for unused learnings
"""

from __future__ import annotations

import logging
import random
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from stronghold.types.memory import Learning

logger = logging.getLogger("stronghold.evaluator")

# Default holdout rate: 10% of learnings withheld for A/B measurement
DEFAULT_HOLDOUT_RATE: float = 0.10

# Default decay: learnings unused for 30 days lose weight
DEFAULT_DECAY_DAYS: int = 30

# Weight floor: learnings never decay below this
DECAY_WEIGHT_FLOOR: float = 0.1

# Per-decay-period weight reduction
DECAY_STEP: float = 0.1

# Minimum keyword overlap ratio to flag as potential contradiction
CONTRADICTION_OVERLAP_THRESHOLD: float = 0.5


@dataclass
class OutcomeRecord:
    """Tracks a single A/B outcome for a learning."""

    learning_id: int
    injected: bool
    tool_succeeded: bool
    recorded_at: datetime = field(default_factory=lambda: datetime.now(UTC))


class LearningEvaluator:
    """Evaluates learning effectiveness via A/B holdout, detects contradictions, applies decay.

    This is a stateful, in-memory evaluator for dev/test use.
    Production would persist outcomes to PostgreSQL.
    """

    def __init__(
        self,
        holdout_rate: float = DEFAULT_HOLDOUT_RATE,
        rng: random.Random | None = None,
    ) -> None:
        self._holdout_rate = holdout_rate
        self._rng = rng or random.Random()  # noqa: S311
        self._outcomes: list[OutcomeRecord] = []

    def should_inject(self, learning: Learning) -> bool:
        """Decide whether to inject this learning or withhold it for A/B measurement.

        Returns True if the learning should be injected into context.
        Returns False (holdout) ~10% of the time for A/B comparison.
        """
        return self._rng.random() >= self._holdout_rate

    def record_outcome(
        self,
        learning_id: int,
        *,
        injected: bool,
        tool_succeeded: bool,
    ) -> None:
        """Record an A/B outcome for a learning.

        Args:
            learning_id: The learning's ID.
            injected: Whether the learning was injected (True) or withheld (False).
            tool_succeeded: Whether the subsequent tool call succeeded.
        """
        self._outcomes.append(
            OutcomeRecord(
                learning_id=learning_id,
                injected=injected,
                tool_succeeded=tool_succeeded,
            )
        )

    def get_effectiveness(self, learning_id: int) -> dict[str, float | int]:
        """Compute A/B effectiveness metrics for a learning.

        Returns:
            Dict with keys:
                injected_success_rate: success rate when learning was injected
                withheld_success_rate: success rate when learning was withheld
                delta: injected_success_rate - withheld_success_rate (positive = helpful)
                trials: total number of outcome records for this learning
        """
        injected_total = 0
        injected_success = 0
        withheld_total = 0
        withheld_success = 0

        for outcome in self._outcomes:
            if outcome.learning_id != learning_id:
                continue
            if outcome.injected:
                injected_total += 1
                if outcome.tool_succeeded:
                    injected_success += 1
            else:
                withheld_total += 1
                if outcome.tool_succeeded:
                    withheld_success += 1

        injected_rate = injected_success / injected_total if injected_total > 0 else 0.0
        withheld_rate = withheld_success / withheld_total if withheld_total > 0 else 0.0

        return {
            "injected_success_rate": injected_rate,
            "withheld_success_rate": withheld_rate,
            "delta": injected_rate - withheld_rate,
            "trials": injected_total + withheld_total,
        }

    def detect_contradictions(
        self,
        learnings: list[Learning],
    ) -> list[tuple[Learning, Learning]]:
        """Find pairs of learnings that may contradict each other.

        Two learnings are flagged as contradictory when:
        1. They share the same tool_name
        2. Their trigger_keys overlap >= CONTRADICTION_OVERLAP_THRESHOLD
        3. Their learning text suggests opposite corrections (different advice)

        Returns a list of (learning_a, learning_b) pairs.
        """
        contradictions: list[tuple[Learning, Learning]] = []

        for i in range(len(learnings)):
            for j in range(i + 1, len(learnings)):
                a = learnings[i]
                b = learnings[j]

                # Must be same tool to contradict
                if a.tool_name != b.tool_name:
                    continue

                # Check keyword overlap
                keys_a = set(a.trigger_keys)
                keys_b = set(b.trigger_keys)
                union = keys_a | keys_b
                if not union:
                    continue
                overlap = len(keys_a & keys_b) / len(union)
                if overlap < CONTRADICTION_OVERLAP_THRESHOLD:
                    continue

                # Different learning text = potential contradiction
                if a.learning != b.learning:
                    contradictions.append((a, b))

        return contradictions

    def apply_decay(
        self,
        learnings: list[Learning],
        days_inactive: int = DEFAULT_DECAY_DAYS,
    ) -> list[Learning]:
        """Reduce weight of learnings that haven't been used recently.

        Learnings whose last_used_at is older than `days_inactive` days
        get their weight reduced by DECAY_STEP, down to DECAY_WEIGHT_FLOOR.

        Returns the list of learnings that were decayed (weight reduced).
        """
        now = datetime.now(UTC)
        cutoff = now - timedelta(days=days_inactive)
        decayed: list[Learning] = []

        for learning in learnings:
            if learning.last_used_at < cutoff and learning.weight > DECAY_WEIGHT_FLOOR:
                old_weight = learning.weight
                learning.weight = round(max(learning.weight - DECAY_STEP, DECAY_WEIGHT_FLOOR), 10)
                if learning.weight < old_weight:
                    decayed.append(learning)
                    logger.debug(
                        "Decayed learning id=%s: %.2f -> %.2f",
                        learning.id,
                        old_weight,
                        learning.weight,
                    )

        return decayed
