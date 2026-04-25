# Spec 27 — Mood

*A three-dimensional affective vector that decays toward neutral, is nudged by events, and surfaces in the minimal prompt block. Phase-1 scope: affects tone only.*

**Depends on:** [self-schema.md](./self-schema.md), [tiers.md](./tiers.md).
**Depended on by:** [self-surface.md](./self-surface.md), [self-as-conduit.md](./self-as-conduit.md).

---

## Current state

- Nothing like "how is the self feeling right now" exists. Episodic memory has `affect` per memory (spec 1), but there is no aggregate current state.

## Target

A singleton `Mood` row per `self_id` carrying `(valence, arousal, focus)` that:
- Decays toward neutral `(0, 0.3, 0.5)` on an hourly tick (neutral is slightly positive-arousal and moderately-focused because "idle" is not "collapsed").
- Is nudged by events (surprise deltas on tool calls, affirmations met, regrets minted).
- Surfaces in the minimal prompt block as a one-line descriptor.
- Does NOT affect routing, model choice, or specialist dispatch in Phase 1. Only tone.

## Acceptance criteria

### State

- **AC-27.1.** Exactly one `self_mood` row exists per `self_id` after bootstrap. Bootstrap seeds it to `(valence=0.0, arousal=0.3, focus=0.5)`. A second insert raises (spec 22 AC-22.17). Test.
- **AC-27.2.** `valence ∈ [-1.0, 1.0]`, `arousal ∈ [0.0, 1.0]`, `focus ∈ [0.0, 1.0]`. Out-of-range writes raise. Test on each dimension boundary.
- **AC-27.3.** Every mutation updates `last_tick_at`, `updated_at`. A mutation that doesn't update at least `updated_at` raises. Test.

### Decay

- **AC-27.4.** `tick_mood_decay(self_id, now)` moves each dimension toward its neutral target:
  ```
  new_dim = current + DECAY_RATE × (neutral_dim - current)
  ```
  where `DECAY_RATE = 0.1 per hour` (default). Test with fixed inputs asserts the exact arithmetic.
- **AC-27.5.** Decay runs hourly via a Reactor interval trigger. Missed ticks (downtime longer than the interval) catch up with a **single** compound decay step scaled by the gap:
  ```
  effective_rate = 1 - (1 - DECAY_RATE)^hours_elapsed
  ```
  Asymptotic — no matter how long the gap, state ends at most at neutral. Test simulates 100-hour downtime.
- **AC-27.6.** Decay is purely mathematical — no LLM call, no memory write. `tick_mood_decay` is idempotent within the same tick. Test.
- **AC-27.7.** Decay never crosses neutral (no oscillation). A state at `(0.02, 0.5, 0.5)` decays toward `(0, 0.3, 0.5)`, not past it. Test.

### Event nudges

- **AC-27.8.** `nudge_mood(self_id, dim, delta, reason)` applies `new = clamp(current + delta, range)` on the named dimension. `delta ∈ [-0.5, 0.5]` per single nudge (one event cannot swing mood past half the scale). Values outside raise. Test.
- **AC-27.9.** Every nudge writes an OBSERVATION-tier memory:
  ```
  content = f"[mood nudge] {dim} {current:+.2f} → {new:+.2f} (reason: {reason})"
  intent_at_time = "mood nudge"
  context = {"dim": dim, "delta": delta, "reason": reason}
  ```
  Test.
- **AC-27.10.** Standard event sources and their seed nudges (tunable):
  - Tool call succeeded after expected-fail: `valence +0.1, arousal +0.05`
  - Tool call failed unexpectedly: `valence -0.15, arousal +0.1, focus -0.1`
  - AFFIRMATION minted: `valence +0.1`
  - REGRET minted: `valence -0.2, focus -0.05`
  - Self-todo completed: `valence +0.05, focus +0.05`
  - Warden alert on ingress: `arousal +0.2, focus +0.1`

  Each event-source rule is unit-testable. Test one per row.
- **AC-27.11.** Concurrent nudges on the same `self_id` are serialized by an advisory lock. Final state is the result of applying nudges in the order the lock releases — no lost updates. Test.

### Prompt surface

- **AC-27.12.** The minimal prompt block renders mood as a one-line qualitative descriptor chosen from a lookup table over the `(valence, arousal)` quadrants:

  | | low arousal | high arousal |
  |---|---|---|
  | negative valence | "flat, withdrawn" | "tense, on edge" |
  | neutral valence | "even, steady" | "alert, attentive" |
  | positive valence | "content, easy" | "keen, energized" |

  With `focus` appended as `"; focused"` if `focus > 0.7` or `"; scattered"` if `focus < 0.3`, otherwise omitted.

  Test over 9 representative `(valence, arousal, focus)` tuples.

- **AC-27.13.** The descriptor is the only mood surface in Phase-1. Raw numeric mood values are NOT in the minimal prompt block. They ARE in `recall_self()` output for depth (spec 28). Test.

### Phase-1 scope limits

- **AC-27.14.** Mood does NOT influence model selection, specialist dispatch, or classifier thresholds in Phase-1. Test: swap mood values across an extreme range and assert identical routing outputs on a fixed request.
- **AC-27.15.** Mood DOES influence system-prompt phrasing via the descriptor. Behavioral test: two routings with opposite moods produce prompts that differ in the mood descriptor line but nowhere else.

### Edge cases

- **AC-27.16.** A nudge whose `delta` would push the dimension out of range clamps to the boundary rather than raising. Test at boundary.
- **AC-27.17.** Nudges during the same second as a tick: the tick runs first (decay), then the nudge applies. Test.
- **AC-27.18.** A malformed `dim` (not one of `valence|arousal|focus`) raises immediately. Test.
- **AC-27.19.** The `neutral` target is configurable per deployment. Changing `neutral` mid-run causes the next tick to decay toward the new neutral. Test.

## Implementation

### 27.1 Constants

```python
NEUTRAL_VALENCE:  float = 0.0
NEUTRAL_AROUSAL:  float = 0.3
NEUTRAL_FOCUS:    float = 0.5
DECAY_RATE:       float = 0.1     # per hour
NUDGE_MAX:        float = 0.5
```

### 27.2 Decay math

```python
def decay_step(current: float, neutral: float, hours: float) -> float:
    effective = 1.0 - (1.0 - DECAY_RATE) ** hours
    return current + effective * (neutral - current)


def tick_mood_decay(repo: SelfRepo, self_id: str, now: datetime) -> Mood:
    with repo.advisory_lock(f"mood:{self_id}"):
        m = repo.get_mood(self_id)
        hours = max(0.0, (now - m.last_tick_at).total_seconds() / 3600.0)
        if hours <= 0:
            return m
        m.valence = decay_step(m.valence, NEUTRAL_VALENCE, hours)
        m.arousal = decay_step(m.arousal, NEUTRAL_AROUSAL, hours)
        m.focus   = decay_step(m.focus,   NEUTRAL_FOCUS,   hours)
        m.last_tick_at = now
        m.updated_at   = now
        repo.update_mood(m)
        return m
```

### 27.3 Nudge with clamp

```python
DIM_RANGES: dict[str, tuple[float, float]] = {
    "valence": (-1.0, 1.0),
    "arousal": ( 0.0, 1.0),
    "focus":   ( 0.0, 1.0),
}


def nudge_mood(repo: SelfRepo, self_id: str, dim: str,
               delta: float, reason: str) -> Mood:
    if dim not in DIM_RANGES:
        raise ValueError(f"unknown mood dim: {dim}")
    if abs(delta) > NUDGE_MAX:
        raise ValueError(f"nudge delta {delta} exceeds NUDGE_MAX {NUDGE_MAX}")
    low, high = DIM_RANGES[dim]
    with repo.advisory_lock(f"mood:{self_id}"):
        m = repo.get_mood(self_id)
        current = getattr(m, dim)
        new = max(low, min(high, current + delta))
        setattr(m, dim, new)
        m.updated_at = datetime.now(UTC)
        repo.update_mood(m)
        memories.write_observation(
            self_id=self_id,
            content=f"[mood nudge] {dim} {current:+.2f} → {new:+.2f} (reason: {reason})",
            intent_at_time="mood nudge",
            context={"dim": dim, "delta": delta, "reason": reason},
        )
        return m
```

### 27.4 Descriptor table

```python
def mood_descriptor(m: Mood) -> str:
    if m.valence < -0.15:
        v = "negative"
    elif m.valence > 0.15:
        v = "positive"
    else:
        v = "neutral"

    a = "high" if m.arousal > 0.6 else "low"

    core = {
        ("negative", "low"):  "flat, withdrawn",
        ("negative", "high"): "tense, on edge",
        ("neutral",  "low"):  "even, steady",
        ("neutral",  "high"): "alert, attentive",
        ("positive", "low"):  "content, easy",
        ("positive", "high"): "keen, energized",
    }[(v, a)]

    if m.focus > 0.7:
        return f"{core}; focused"
    if m.focus < 0.3:
        return f"{core}; scattered"
    return core
```

### 27.5 Standard event dispatch

```python
EVENT_NUDGES: dict[str, list[tuple[str, float]]] = {
    "tool_succeeded_against_expectation": [("valence", +0.10), ("arousal", +0.05)],
    "tool_failed_unexpectedly":           [("valence", -0.15), ("arousal", +0.10), ("focus", -0.10)],
    "affirmation_minted":                 [("valence", +0.10)],
    "regret_minted":                      [("valence", -0.20), ("focus", -0.05)],
    "todo_completed":                     [("valence", +0.05), ("focus", +0.05)],
    "warden_alert_on_ingress":            [("arousal", +0.20), ("focus", +0.10)],
}


def apply_event_nudge(repo: SelfRepo, self_id: str, event: str, reason: str) -> None:
    for dim, delta in EVENT_NUDGES.get(event, []):
        nudge_mood(repo, self_id, dim, delta, reason=f"{event}: {reason}")
```

## Open questions

- **Q27.1.** Neutral `(0, 0.3, 0.5)` is a guess. "Slightly positive arousal, moderately focused" matches a resting agent waiting for the next request. An operator running a support-focused deployment might prefer `arousal=0.5` (more eager). Configurable.
- **Q27.2.** `DECAY_RATE = 0.1/hour` means ~10% of distance-to-neutral per hour. Over a 24h idle period, a dimension at `+0.8` decays to roughly `+0.2`. Empirically check whether that feels right on the live branch.
- **Q27.3.** `NUDGE_MAX = 0.5` prevents any single event from flipping the sign of valence. A sequence of nudges can — a string of regrets pushes valence negative quickly. Intentional: the self can accumulate a mood, it just can't be whiplashed by one event.
- **Q27.4.** Phase-2 (backlog): mood affects decisions. Example couplings worth exploring: low `focus` → favor specialists with tighter scope; high `arousal` → prefer faster models; negative `valence` + high `arousal` → raise Warden sensitivity threshold by default. All deferred; not in this spec.
- **Q27.5.** The descriptor table is 6 labels × 3 focus modifiers = 18 phrases. A more graduated phrasing is plausible (polar-coordinate descriptor based on the full 3-vector). The 6-cell table is deliberately coarse to avoid overclaiming resolution.
- **Q27.6.** Mood is singleton per `self_id`. On a per-conversation basis, a "session mood" sub-state could better capture "how do I feel about *this* interaction." Deferred; the global mood is enough for Phase-1.
