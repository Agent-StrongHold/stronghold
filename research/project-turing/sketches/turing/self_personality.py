"""HEXACO profile draw and retest math. See specs/personality.md."""

from __future__ import annotations

import random
from collections import defaultdict
from collections.abc import Callable
from datetime import UTC, datetime

from .self_model import (
    ALL_FACETS,
    PersonalityAnswer,
    PersonalityItem,
    PersonalityRevision,
    facet_node_id,
)
from .self_repo import SelfRepo


RETEST_WEIGHT: float = 0.25
RETEST_SAMPLE_SIZE: int = 20
FACET_DIVERSITY_FLOOR: int = 12
BOOTSTRAP_MU: float = 3.0
BOOTSTRAP_SIGMA: float = 0.8


def draw_bootstrap_profile(
    rng: random.Random,
    overrides: dict[str, float] | None = None,
) -> dict[str, float]:
    """Spec 23 §23.2. Truncated normal μ=3, σ=0.8, clamped to [1, 5]."""
    overrides = overrides or {}
    profile: dict[str, float] = {}
    for trait, facet in ALL_FACETS:
        key = facet_node_id(trait, facet)
        mu = overrides.get(key, BOOTSTRAP_MU)
        raw = rng.gauss(mu=mu, sigma=BOOTSTRAP_SIGMA)
        profile[key] = min(5.0, max(1.0, raw))
    return profile


def _rng_weighted_sample(
    rng: random.Random, population: list, weights: list[float], n: int
) -> list:
    """Weighted sampling without replacement (rough but deterministic-under-seed)."""
    assert len(population) == len(weights)
    assert n <= len(population)
    remaining = list(zip(population, weights, strict=True))
    out: list = []
    for _ in range(n):
        total = sum(w for _, w in remaining)
        if total <= 0:
            # Fallback: uniform over what's left.
            picked_idx = rng.randrange(len(remaining))
        else:
            pick = rng.random() * total
            running = 0.0
            picked_idx = len(remaining) - 1
            for i, (_, w) in enumerate(remaining):
                running += w
                if running >= pick:
                    picked_idx = i
                    break
        out.append(remaining[picked_idx][0])
        remaining.pop(picked_idx)
    return out


def sample_retest_items(
    items: list[PersonalityItem],
    last_asked: dict[str, datetime],
    rng: random.Random,
    now: datetime,
    n: int = RETEST_SAMPLE_SIZE,
    facet_diversity_floor: int = FACET_DIVERSITY_FLOOR,
) -> list[PersonalityItem]:
    """Weighted by time-since-last-asked, stratified by facet as a secondary constraint.

    Spec 23 AC-23.12.
    """

    def weight(it: PersonalityItem) -> float:
        t = last_asked.get(it.node_id)
        if t is None:
            return 10_000.0
        days = max(0.001, (now - t).total_seconds() / 86400.0)
        return days

    for _ in range(10):
        weights = [weight(it) for it in items]
        choices = _rng_weighted_sample(rng, items, weights, n)
        if len({c.keyed_facet for c in choices}) >= facet_diversity_floor:
            return choices

    # Fallback: round-robin by facet, oldest-asked first within each.
    by_facet: dict[str, list[PersonalityItem]] = defaultdict(list)
    for it in items:
        by_facet[it.keyed_facet].append(it)
    for facet in by_facet:
        by_facet[facet].sort(
            key=lambda i: last_asked.get(i.node_id, datetime.min.replace(tzinfo=UTC))
        )
    out: list[PersonalityItem] = []
    order = list(by_facet.keys())
    i = 0
    while len(out) < n and any(by_facet.values()):
        bucket = by_facet[order[i % len(order)]]
        if bucket:
            out.append(bucket.pop(0))
        i += 1
    return out


def compute_facet_deltas(
    sampled: list[PersonalityItem],
    raw_answers: list[int],
    current_scores: dict[str, float],
) -> dict[str, tuple[float, float]]:
    """Return `{facet_id: (retest_mean_score, delta_from_current)}` for touched facets.

    Spec 23 AC-23.15, AC-23.16. Reverse scoring uses `6 - raw`.
    """
    if len(sampled) != len(raw_answers):
        raise ValueError("sampled and raw_answers must be same length")
    by_facet: dict[str, list[int]] = defaultdict(list)
    for item, raw in zip(sampled, raw_answers, strict=True):
        scored = (6 - raw) if item.reverse_scored else raw
        by_facet[item.keyed_facet].append(scored)

    out: dict[str, tuple[float, float]] = {}
    for facet, vals in by_facet.items():
        retest_mean = sum(vals) / len(vals)
        current = current_scores.get(facet)
        if current is None:
            raise KeyError(f"no current score for facet {facet}")
        delta = RETEST_WEIGHT * (retest_mean - current)
        out[facet] = (retest_mean, delta)
    return out


AskSelfCallable = Callable[[PersonalityItem], tuple[int, str]]


def apply_retest(
    repo: SelfRepo,
    self_id: str,
    sampled: list[PersonalityItem],
    ask_self: AskSelfCallable,
    now: datetime,
    new_id: Callable[[str], str],
) -> PersonalityRevision:
    """End-to-end retest: ask `ask_self` per item, validate, update scores, persist.

    Spec 23 AC-23.14..AC-23.18. Atomic against invalid answers: raises before
    any score mutation.
    """
    answers: list[tuple[int, str]] = []
    for item in sampled:
        raw, justification = ask_self(item)
        if raw not in (1, 2, 3, 4, 5):
            raise ValueError(f"invalid retest answer for {item.node_id}: {raw}")
        answers.append((raw, justification))

    current: dict[str, float] = {
        f: repo.get_facet_score(self_id, f) for f in {s.keyed_facet for s in sampled}
    }
    deltas = compute_facet_deltas(sampled, [a for a, _ in answers], current)

    revision_id = new_id("rev")
    for facet, (_retest_mean, delta) in deltas.items():
        new_score = current[facet] + delta
        new_score = max(1.0, min(5.0, new_score))
        repo.update_facet_score(self_id, facet, new_score, revised_at=now)

    for item, (raw, justification) in zip(sampled, answers, strict=True):
        repo.insert_answer(
            PersonalityAnswer(
                node_id=new_id("ans"),
                self_id=self_id,
                item_id=item.node_id,
                revision_id=revision_id,
                answer_1_5=raw,
                justification_text=justification[:200],
                asked_at=now,
            )
        )

    return repo.insert_revision(
        PersonalityRevision(
            node_id=new_id("revnode"),
            self_id=self_id,
            revision_id=revision_id,
            ran_at=now,
            sampled_item_ids=[it.node_id for it in sampled],
            deltas_by_facet={facet: delta for facet, (_, delta) in deltas.items()},
        )
    )


def narrative_weight(evidence: str, claim_text: str) -> float:
    """Spec 23 §23.5. Evidence-length heuristic, bounded to [0.1, 0.4]."""
    ev_bonus = min(0.3, len(evidence) / 500.0)
    return min(0.4, 0.1 + ev_bonus)
