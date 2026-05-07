# Spec 15 — RSS thinking pipeline

*Each new feed item is reasoned about, not just queued. Always produces a weak summary; notable items promote into working memory; strong actionable ones commit as AFFIRMATIONs and spawn scheduled action items.*

**Depends on:** [schema.md](./schema.md), [tiers.md](./tiers.md), [write-paths.md](./write-paths.md), [working-memory.md](./working-memory.md), [tool-layer.md](./tool-layer.md), [motivation.md](./motivation.md).
**Depended on by:** —

---

## Current state

`RSSFetcher` polls registered feeds; new items become P7 `rss_item` backlog entries; a dispatch handler (`_think_about_rss_item` in `runtime/main.py`) reasons about them. No spec; not directly tested.

## Target

Four progressive levels of self-engagement with each new feed item, scaled by the LLM's self-reported `interest_score`:

| Level | Trigger | Output |
|---|---|---|
| 1 | Always | Weak `tier=OBSERVATION` summary |
| 2 | `interest_score ≥ NOTABLE` (default 0.4) | + working-memory entry, priority ∝ interest_score |
| 3 | `interest_score ≥ INTERESTING` (default 0.6) | + tier=OPINION with the self's stance |
| 4 | `interest_score ≥ COMMIT` (default 0.8) AND actionable | + AFFIRMATION + scheduled action item at priority `clamp(99 - 95 * interest_score, 4, 99)` |

Each level *includes* the lower levels. A level-4 item produces an OBSERVATION + WM entry + OPINION + AFFIRMATION + P4–P99 action item.

## Acceptance criteria

### Always-write summary (level 1)

- **AC-15.1.** Every dispatched `rss_item` produces exactly one OBSERVATION memory with `source=I_DID`, `tier=OBSERVATION`, `weight=WEIGHT_BOUNDS[OBSERVATION][0]` (the floor), `intent_at_time=f"process-rss-{feed_url}"`, and `context={"feed_url", "link", "title"}`. Test.
- **AC-15.2.** The summary lands even when the LLM call fails (provider error, malformed JSON). Fallback content is the feed item's title. Test with provider that always raises.
- **AC-15.3.** The summary is ≤ 500 characters; longer outputs are truncated. Test.

### Promotion to working memory (level 2)

- **AC-15.4.** When `interest_score ≥ RSS_NOTABLE_THRESHOLD` (default 0.4), the pipeline writes a working-memory entry with content = the LLM's `summary` field and priority = `interest_score`. Test asserts entry presence and priority value.
- **AC-15.5.** WM capacity bounds (per `working-memory.md`) still apply: an over-capacity insert evicts per the existing rules. Test.

### Promotion to OPINION (level 3)

- **AC-15.6.** When `interest_score ≥ RSS_INTERESTING_THRESHOLD` (default 0.6) and the LLM returned a non-empty `opinion`, the pipeline mints an `OPINION` memory with `source=I_DID`, content = `f"about '{title}': {opinion}"`, weight = `WEIGHT_BOUNDS[OPINION][0] + 0.1`, intent = `f"rss-opinion-{feed_url}"`. Test.
- **AC-15.7.** Below threshold, no OPINION is minted. Test.

### Commitment + scheduled action (level 4)

- **AC-15.8.** When `interest_score ≥ RSS_COMMIT_THRESHOLD` (default 0.8), `actionable=true`, and `proposed_action` is non-empty, the pipeline:
  - Mints an AFFIRMATION via `handle_affirmation()` (existing path).
  - Schedules a `rss_action` backlog item at class `clamp(round(99 - 95 * interest_score), 4, 99)`. So `interest_score=1.0 → P4`, `0.9 → P14`, `0.8 → P23`. Test asserts both writes and the priority calculation across several interest_score values.
- **AC-15.9.** The scheduled action item carries the AFFIRMATION's memory_id in payload so when dispatched, the action handler can mark the AFFIRMATION as fulfilled (or supersede it on failure). Test.
- **AC-15.10.** Below the COMMIT threshold or with `actionable=false`, no AFFIRMATION and no action item are produced. Test asserts both negatives.

### LLM contract

- **AC-15.11.** The reflection prompt asks for a single JSON object on one line matching:
  ```
  {"opinion": "<what you think>",
   "proposed_action": "<what you would want to do, or empty>",
   "interest_score": <0..1>,
   "actionable": <true|false>,
   "summary": "<one-sentence record>"}
  ```
- **AC-15.12.** A reply that's not parseable JSON falls back to: `summary=title`, `interest_score=0.0`, `actionable=false`, `opinion=""`, `proposed_action=""`. The level-1 summary still lands; nothing else fires. Test.
- **AC-15.13.** Numeric `interest_score` outside `[0, 1]` is clamped. Test.

### Polling & throughput

- **AC-15.14.** The `RSSFetcher` polls registered feeds every `RSS_POLL_TICKS` (default 30,000 = ~5 min at 100Hz). Test.
- **AC-15.15.** New items (per the `RSSReader`'s dedup) are inserted as P7 `rss_item` items. Already-seen items are silently dropped. Test.
- **AC-15.16.** A failed feed (network error, bad XML) is logged and skipped; other feeds continue. Test with a mix.

### Per-feed memory accumulation

- **AC-15.17.** When the rss_item handler retrieves semantically related context for the LLM, it includes prior OBSERVATIONs from the same `feed_url` (so the self builds a model of each feed). Test asserts the related-memory section includes feed-scoped retrievals.

## Implementation

### 15.1 Action item priority formula

```python
def _action_priority_class(interest_score: float) -> int:
    interest = max(0.0, min(1.0, interest_score))
    return int(round(99 - 95 * interest))
```

| interest | priority class |
|---|---|
| 1.0 | 4 |
| 0.9 | 14 |
| 0.8 | 23 |
| 0.5 | 51 |
| 0.05 | 95 |

### 15.2 Action handler

```python
def _on_dispatch_rss_action(item: BacklogItem, chosen_pool: str) -> None:
    payload = item.payload
    affirmation_id = payload["affirmation_id"]
    proposed_action = payload["proposed_action"]
    # Identify the right tool from the action text. For chunk N, this is
    # crude string-matching; future detector can do better.
    tool_name = _pick_tool_for_action(proposed_action, tool_registry)
    if tool_name is None:
        # Mint a stance OPINION recording that we couldn't act on it.
        ...
        return
    try:
        tool_registry.invoke(tool_name, ...)
        # Mark the AFFIRMATION as honored (mint an ACCOMPLISHMENT).
    except Exception as exc:
        # Mint stance OPINION (per tool-layer.md failure path).
        ...
```

### 15.3 Configuration constants

```python
RSS_POLL_TICKS:               int = 30_000   # ~5 min at 100Hz
RSS_NOTABLE_THRESHOLD:        float = 0.4
RSS_INTERESTING_THRESHOLD:    float = 0.6
RSS_COMMIT_THRESHOLD:         float = 0.8
RSS_SUMMARY_MAX_LEN:          int = 500
RSS_OPINION_MAX_LEN:          int = 300
RSS_ACTION_MAX_LEN:           int = 300
```

All tunable.

## Open questions

- **Q15.1.** `_pick_tool_for_action` is hand-wavy. A real implementation needs either (a) the LLM in the reflection step picks the tool name from a list, or (b) a separate tool-routing pass before action dispatch. Defer the choice but spec the contract: the action handler must invoke a registered tool or mint a stance-OPINION recording the gap.
- **Q15.2.** Self-tuning of thresholds: when the self repeatedly mints AFFIRMATIONs that turn into REGRETs (over-committing on RSS), the tuner should raise `RSS_COMMIT_THRESHOLD`. Spec'd in tuning; no implementation here.
- **Q15.3.** Per-feed quality weights: some feeds (high-signal blogs) deserve higher trust than others (firehoses). A `feed_weights` map could multiply `interest_score` per source. Out of scope for chunk N; worth adding to feeds config.
- **Q15.4.** Should OBSERVATION pruning rules treat RSS-summary OBSERVATIONs the same as other OBSERVATIONs? Yes by default — they decay with non-reinforcement and get pruned by dreaming phase 5. The intent_at_time tag lets the operator inspect / handle them specially if needed.
