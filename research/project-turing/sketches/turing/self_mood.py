"""Mood tick + nudges. See specs/mood.md."""

from __future__ import annotations

from datetime import UTC, datetime

from .self_model import Mood
from .self_repo import SelfRepo


NEUTRAL_VALENCE: float = 0.0
NEUTRAL_AROUSAL: float = 0.3
NEUTRAL_FOCUS: float = 0.5
DECAY_RATE: float = 0.1          # per hour
NUDGE_MAX: float = 0.5


DIM_RANGES: dict[str, tuple[float, float]] = {
    "valence": (-1.0, 1.0),
    "arousal": (0.0, 1.0),
    "focus": (0.0, 1.0),
}

NEUTRAL_BY_DIM: dict[str, float] = {
    "valence": NEUTRAL_VALENCE,
    "arousal": NEUTRAL_AROUSAL,
    "focus": NEUTRAL_FOCUS,
}


EVENT_NUDGES: dict[str, list[tuple[str, float]]] = {
    "tool_succeeded_against_expectation": [("valence", +0.10), ("arousal", +0.05)],
    "tool_failed_unexpectedly": [("valence", -0.15), ("arousal", +0.10), ("focus", -0.10)],
    "affirmation_minted": [("valence", +0.10)],
    "regret_minted": [("valence", -0.20), ("focus", -0.05)],
    "todo_completed": [("valence", +0.05), ("focus", +0.05)],
    "warden_alert_on_ingress": [("arousal", +0.20), ("focus", +0.10)],
}


def decay_step(current: float, neutral: float, hours: float) -> float:
    """Compound decay of `hours` single-hour ticks.

    One hour of decay: `new = current + DECAY_RATE * (neutral - current)`.
    N hours: `new = current + (1 - (1 - DECAY_RATE)^N) * (neutral - current)`.
    The asymptote is `neutral`; we never cross it.
    """
    if hours <= 0:
        return current
    effective = 1.0 - (1.0 - DECAY_RATE) ** hours
    return current + effective * (neutral - current)


def tick_mood_decay(repo: SelfRepo, self_id: str, now: datetime) -> Mood:
    m = repo.get_mood(self_id)
    hours = max(0.0, (now - m.last_tick_at).total_seconds() / 3600.0)
    if hours <= 0:
        return m
    m.valence = decay_step(m.valence, NEUTRAL_VALENCE, hours)
    m.arousal = decay_step(m.arousal, NEUTRAL_AROUSAL, hours)
    m.focus = decay_step(m.focus, NEUTRAL_FOCUS, hours)
    m.last_tick_at = now
    repo.update_mood(m)
    return m


def nudge_mood(
    repo: SelfRepo,
    self_id: str,
    dim: str,
    delta: float,
    reason: str,
) -> Mood:
    if dim not in DIM_RANGES:
        raise ValueError(f"unknown mood dim: {dim}")
    if abs(delta) > NUDGE_MAX:
        raise ValueError(f"nudge delta {delta} exceeds NUDGE_MAX {NUDGE_MAX}")
    low, high = DIM_RANGES[dim]
    m = repo.get_mood(self_id)
    current = getattr(m, dim)
    new = max(low, min(high, current + delta))
    setattr(m, dim, new)
    repo.update_mood(m)
    return m


def apply_event_nudge(
    repo: SelfRepo, self_id: str, event: str, reason: str
) -> Mood | None:
    """Apply the nudge tuple registered under `event`. Unknown events no-op."""
    last: Mood | None = None
    for dim, delta in EVENT_NUDGES.get(event, []):
        last = nudge_mood(repo, self_id, dim, delta, reason=f"{event}: {reason}")
    return last


def mood_descriptor(m: Mood) -> str:
    """Spec 27 AC-27.12: qualitative one-liner from (valence, arousal, focus)."""
    if m.valence < -0.15:
        v = "negative"
    elif m.valence > 0.15:
        v = "positive"
    else:
        v = "neutral"
    a = "high" if m.arousal > 0.6 else "low"
    core = {
        ("negative", "low"): "flat, withdrawn",
        ("negative", "high"): "tense, on edge",
        ("neutral", "low"): "even, steady",
        ("neutral", "high"): "alert, attentive",
        ("positive", "low"): "content, easy",
        ("positive", "high"): "keen, energized",
    }[(v, a)]
    if m.focus > 0.7:
        return f"{core}; focused"
    if m.focus < 0.3:
        return f"{core}; scattered"
    return core
