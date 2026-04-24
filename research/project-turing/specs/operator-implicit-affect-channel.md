# Spec 111 — Operator implicit-affect channel

*Extends `stronghold self coach` so coaching content also passes through a lightweight affect-extraction stage. Detected tone — frustrated, warm, urgent, neutral — becomes a small mood nudge in addition to the I_WAS_TOLD memory. The self feels how the operator is teaching it, not just what's said. Confidence-gated to avoid misreading.*

**Depends on:** [operator-coaching-channel.md](./operator-coaching-channel.md), [mood.md](./mood.md), [warden-on-self-writes.md](./warden-on-self-writes.md), [litellm-provider.md](./litellm-provider.md).

---

## Current state

The operator coaching channel (spec 66) accepts `stronghold self coach "<content>"` and writes an I_WAS_TOLD memory, signed by the operator key. Warden-on-self-writes (spec 36) already Warden-scans the content. Mood (spec 27) models valence/arousal/focus with hourly decay and event nudges — but nothing today nudges mood from coaching tone. The result: an operator saying "do X" and an operator snapping "DO X" land identically on the self's memory. Tone is lost.

## Target

Insert a new affect-extraction stage between the Warden scan and the I_WAS_TOLD write. The stage is cheap-to-expensive (design principle #1): regex pattern-match first, then an LLM call only if patterns are inconclusive (spec 19 cheap-LLM). Output is one of four categories with a confidence score. Above threshold (0.6), the matched category issues a small mood nudge. Below threshold, or when the operator passes `--neutral`, no nudge is issued. The extraction result is stored as metadata alongside the I_WAS_TOLD memory.

## Acceptance criteria

### Pipeline position

- **AC-111.1.** Affect extraction runs strictly after Warden scan pass and strictly before memory write. If Warden blocks, extraction is skipped. Test.
- **AC-111.2.** On `--neutral` flag, extraction is fully bypassed and no affect metadata is stored. Test.
- **AC-111.3.** On smoke mode (`STRONGHOLD_MODE=smoke`), extraction is disabled and mood is never nudged from coaching. Test via smoke-mode fixture.

### Categories & nudges

- **AC-111.4.** Four categories with these mood deltas:
  - `frustrated`: valence −0.2
  - `warm`: valence +0.2
  - `urgent`: arousal +0.2, focus +0.1
  - `neutral`: no delta
  Test each category produces its delta on a crafted input.
- **AC-111.5.** Max one nudge per coaching message, regardless of extractor output shape. Test that an extractor returning multi-category output still emits exactly one nudge (highest-confidence category wins).

### Cheap-to-expensive extractor

- **AC-111.6.** Pattern stage: regex list per category (e.g. frustrated patterns like `\b(seriously|again|really\?|wtf)\b`, warm patterns like `\b(thanks|nice work|well done|good job)\b`, urgent patterns like `\b(asap|now|immediately|urgent)\b`). Test pattern-stage returns a category when at least one pattern matches for exactly one category.
- **AC-111.7.** If patterns match ≥2 categories or 0 categories, fall through to the LLM stage. Test both branches.
- **AC-111.8.** LLM stage uses a cheap provider (spec 19), temperature 0, returns `{category, confidence}`. Prompt is a fixed classification prompt loaded from `prompts/affect_extractor.md`. Test response parsing handles valid and malformed outputs.
- **AC-111.9.** LLM stage timeout default 5s. On timeout, category is `neutral` with confidence 0 — effectively "no nudge." Test with a fake LLM that delays past timeout.

### Confidence gate & metadata

- **AC-111.10.** Confidence threshold default 0.6 (configurable via `TURING_AFFECT_CONFIDENCE_MIN`). Below threshold → no nudge, but metadata still stored as `{category, confidence, stage, below_threshold: true}`. Test.
- **AC-111.11.** Pattern-stage results always carry confidence 1.0 (deterministic match); they pass the threshold gate by construction. Test.
- **AC-111.12.** Affect metadata attached to the I_WAS_TOLD memory under `context.affect = {category, confidence, stage}`. Test round-trip via memory read.

### Observability

- **AC-111.13.** Prometheus counter `turing_coaching_affect_total{self_id, category, stage}` with stage ∈ {pattern, llm, timeout, bypass}. Test counts increment.
- **AC-111.14.** Prometheus counter `turing_coaching_affect_below_threshold_total{self_id, category}`. Test.

### Edge cases

- **AC-111.15.** Empty coaching content (`""`) never reaches extractor (Warden or upstream validation rejects). Test.
- **AC-111.16.** Extractor error (exception) → category `neutral`, confidence 0, stage `error`, metadata stores the error class name but not the stack trace. The memory write proceeds. Test.
- **AC-111.17.** Very long coaching content (>4KB) — extractor truncates to first 2KB for LLM stage (pattern stage runs on the full text). Test truncation is applied and noted in metadata.
- **AC-111.18.** Concurrent coaching calls — each extraction is independent; mood nudges are applied via the standard mood-event bus (spec 27) and serialized there. Test two concurrent warm nudges both apply.

## Implementation

```python
# coaching/affect_extractor.py

AFFECT_CONFIDENCE_MIN: float = 0.6
AFFECT_LLM_TIMEOUT_SEC: float = 5.0
AFFECT_MAX_LLM_INPUT: int = 2048

MOOD_DELTAS: dict[str, dict[str, float]] = {
    "frustrated": {"valence": -0.2},
    "warm": {"valence": +0.2},
    "urgent": {"arousal": +0.2, "focus": +0.1},
    "neutral": {},
}


async def extract(content: str, llm: LLMClient) -> AffectResult:
    hits = _pattern_scan(content)
    if len(hits) == 1:
        return AffectResult(category=hits[0], confidence=1.0, stage="pattern")
    try:
        out = await asyncio.wait_for(
            llm.classify_affect(content[:AFFECT_MAX_LLM_INPUT]),
            timeout=AFFECT_LLM_TIMEOUT_SEC,
        )
        return AffectResult(category=out.category, confidence=out.confidence, stage="llm")
    except asyncio.TimeoutError:
        return AffectResult(category="neutral", confidence=0.0, stage="timeout")
    except Exception as exc:
        return AffectResult(category="neutral", confidence=0.0, stage="error", error=type(exc).__name__)


def apply_nudge(mood_bus, result: AffectResult, self_id: str) -> bool:
    if result.category == "neutral" or result.confidence < AFFECT_CONFIDENCE_MIN:
        return False
    mood_bus.emit_nudge(self_id=self_id, deltas=MOOD_DELTAS[result.category], source="coaching")
    return True
```

## Open questions

- **Q111.1.** Four categories is a deliberate minimum. More (sad, proud, worried…) adds prompt surface and test load without clear gain. Revisit after real operator data.
- **Q111.2.** Valence delta magnitudes (±0.2) are modest. An operator can still flood mood with repeated coaching, but mood's hourly decay (spec 27) bounds it. We do not rate-limit affect nudges separately today; spec 27's decay is the governor.
- **Q111.3.** Pattern lists will be ad-hoc initially. Consider a small curated pattern file per language/locale if we ever go multilingual.
- **Q111.4.** Should the self's own self-authored writes (not operator coaching) pass through a similar affect-extraction? Out of scope here — spec 36 handles Warden on self-writes and that's enough for now. The asymmetry is intentional: operator affect is a signal; self-affect is just self-talk.
