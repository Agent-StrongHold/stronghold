"""Thompson sampling for prompt A/B testing.

Uses Beta-Bernoulli conjugate model: each variant tracks successes (alpha)
and failures (beta). Selection draws from Beta(alpha, beta) per variant
and picks the highest sample — this naturally balances exploration vs
exploitation.
"""

from __future__ import annotations

import random
from dataclasses import dataclass


@dataclass
class VariantDistribution:
    """Beta distribution parameters for a single prompt variant.

    alpha = successes + 1 (prior), beta = failures + 1 (prior).
    """

    variant_id: str
    alpha: float = 1.0
    beta: float = 1.0


class ThompsonSelector:
    """Selects prompt variants using Thompson sampling.

    Each variant maintains a Beta distribution. On ``select``, we draw
    a sample from each variant's distribution and return the variant
    with the highest draw. On ``record_outcome``, we update the
    corresponding alpha (success) or beta (failure) parameter.
    """

    def __init__(self) -> None:
        self._distributions: dict[str, VariantDistribution] = {}

    def _get_or_create(self, variant_id: str) -> VariantDistribution:
        """Return the distribution for *variant_id*, creating if needed."""
        if variant_id not in self._distributions:
            self._distributions[variant_id] = VariantDistribution(variant_id=variant_id)
        return self._distributions[variant_id]

    def select(self, variants: list[str]) -> str:
        """Sample from Beta(alpha, beta) per variant; return the highest.

        Raises ``ValueError`` if *variants* is empty.
        """
        if not variants:
            msg = "variants must not be empty"
            raise ValueError(msg)

        best_variant = variants[0]
        best_sample = -1.0

        for vid in variants:
            dist = self._get_or_create(vid)
            sample = random.betavariate(dist.alpha, dist.beta)
            if sample > best_sample:
                best_sample = sample
                best_variant = vid

        return best_variant

    def record_outcome(self, variant_id: str, *, success: bool) -> None:
        """Update alpha (on success) or beta (on failure) for *variant_id*."""
        dist = self._get_or_create(variant_id)
        if success:
            dist.alpha += 1.0
        else:
            dist.beta += 1.0

    def get_stats(self, variant_id: str) -> dict[str, float]:
        """Return ``{alpha, beta, mean, trials}`` for *variant_id*.

        Unknown variants return the uninformative prior (alpha=1, beta=1).
        """
        dist = self._get_or_create(variant_id)
        mean = dist.alpha / (dist.alpha + dist.beta)
        # trials = (alpha - 1) + (beta - 1), since prior starts at 1/1
        trials = (dist.alpha - 1.0) + (dist.beta - 1.0)
        return {
            "alpha": dist.alpha,
            "beta": dist.beta,
            "mean": mean,
            "trials": trials,
        }

    def should_auto_promote(
        self,
        variant_id: str,
        min_trials: int = 100,
        min_advantage: float = 0.05,
    ) -> bool:
        """Return ``True`` if *variant_id* is clearly better than baseline (0.5).

        Requires at least *min_trials* observations and a mean at least
        *min_advantage* above the 0.5 baseline.
        """
        stats = self.get_stats(variant_id)
        if stats["trials"] < min_trials:
            return False
        return stats["mean"] > 0.5 + min_advantage

    def should_auto_disable(
        self,
        variant_id: str,
        min_trials: int = 100,
        max_disadvantage: float = -0.05,
    ) -> bool:
        """Return ``True`` if *variant_id* is clearly worse than baseline (0.5).

        Requires at least *min_trials* observations and a mean below
        ``0.5 + max_disadvantage`` (where *max_disadvantage* is negative).
        """
        stats = self.get_stats(variant_id)
        if stats["trials"] < min_trials:
            return False
        return stats["mean"] < 0.5 + max_disadvantage
