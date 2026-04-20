# Spec 13 — Journal: progressive multi-resolution narrative

*The self's life as it happens, distilled into nested time horizons. Operator-readable, never operator-written. Models human memory consolidation: today is sharp, yesterday is short, last week is summary, last month is theme, "recent history" is identity-adjacent narrative.*

**Depends on:** [schema.md](./schema.md), [persistence.md](./persistence.md).
**Depended on by:** [chat-surface.md](./chat-surface.md) (the chat HTTP `GET /thoughts` endpoint reads from it).

---

## Current state

- `runtime/journal.py` writes a single growing `narrative.md` plus a rewritten `identity.md`.
- No rotation. After a year of uptime, narrative.md is megabytes.
- No summarization. Every event is full-detail forever.

## Target

A multi-resolution journal directory:

```
<journal_dir>/
├── identity.md              — current WISDOM, rewritten on change
├── today.md                 — live append; full detail
├── yesterday.md             — yesterday distilled; replaced each day
├── this-week.md             — last 7 days; replaced each week
├── this-month.md            — last 30 days; replaced each month
├── recent-history.md        — longer-term narrative; replaced each month
└── archive/
    ├── days/<YYYY-MM-DD>.md     — preserved raw daily logs
    ├── weeks/<YYYY-WW>.md       — preserved week summaries
    └── months/<YYYY-MM>.md      — preserved month summaries
```

The "rolling" files (today/yesterday/this-week/this-month/recent-history) are the operator's normal reading surface. The `archive/` tree is the historical record — never deleted, used to regenerate any rollup if needed.

## Acceptance criteria

### File layout & content

- **AC-13.1.** On first start, `journal_dir/today.md` is created with a header (`# Today — <YYYY-MM-DD>`) and an empty body. Test asserts file exists and has the header.
- **AC-13.2.** Significant durable-memory events (REGRET / ACCOMPLISHMENT / AFFIRMATION / WISDOM / LESSON) become entries in `today.md` within `JOURNAL_POLL_TICKS` of the write. Format: `## <ISO timestamp> — <kind>\n\n<content>\n\n_<meta>_`. Each entry includes the user tag (if the underlying memory carried one). Test asserts the format and tag inclusion.
- **AC-13.3.** Dream session markers (final markers, not placeholders) appear in `today.md` with kind `dream session`. Test.
- **AC-13.4.** `identity.md` is rewritten whenever the set of non-superseded WISDOM memory_ids changes. The file lists every current WISDOM with its `intent_at_time`, lineage size, and creation timestamp. Test asserts re-write on WISDOM addition.
- **AC-13.5.** When the runtime starts and `today.md` exists, new entries append to the existing file. Restart-safe. Test.

### Daily rollup (today → yesterday)

- **AC-13.6.** A daily rollup runs at `DAILY_ROLLUP_TIME_LOCAL` (default 23:55 local). It:
  1. Reads `today.md`.
  2. Asks the chat-role provider to produce a 1–3 paragraph summary.
  3. Writes the summary to `yesterday.md` (replaces).
  4. Copies the original `today.md` to `archive/days/<YYYY-MM-DD>.md`.
  5. Truncates `today.md` to a fresh date header for the new day.
  6. Mints a `tier=OBSERVATION, source=I_DID` marker memory recording the rollup.
- **AC-13.7.** A rollup that crashes mid-run leaves `today.md` intact (no data loss). Test with induced LLM failure.

### Weekly rollup

- **AC-13.8.** Sunday evening at `WEEKLY_ROLLUP_TIME_LOCAL` (default 23:00), the last 7 days of `archive/days/*.md` are concatenated and summarized into `this-week.md` (replaces). Original is preserved in `archive/weeks/<YYYY-WW>.md`. Test.

### Monthly rollup

- **AC-13.9.** End-of-month at `MONTHLY_ROLLUP_TIME_LOCAL` (default 23:30 on the last day), the last 30 days are summarized into `this-month.md`. Original preserved in `archive/months/<YYYY-MM>.md`. Test.

### Recent-history rollup

- **AC-13.10.** When a new monthly summary lands, the existing `recent-history.md` plus the new monthly summary are summarized together, replacing `recent-history.md`. This is the long-horizon distillation; runs less often, costs more tokens per run. Test asserts trigger on month rollover.

### Bounds & failure semantics

- **AC-13.11.** Each rollup has a token budget cap (`ROLLUP_MAX_TOKENS`, default 4000). An over-budget rollup writes a truncation note in the summary file and continues. Test.
- **AC-13.12.** A rollup that fails to reach the LLM falls back to a deterministic "first paragraph + bullet list of headings" summary so the file always has *some* content. Test with a provider that always raises.
- **AC-13.13.** Rollups are idempotent over the same source: re-running today's daily rollup with the same `today.md` produces the same `yesterday.md` modulo timestamps. Test with a pinned LLM.

## Implementation

### 13.1 Directory structure

```python
class Journal:
    def __init__(self, *, repo, self_id, journal_dir: Path, llm: Provider | None,
                 daily_time=time(23, 55), weekly_time=time(23, 0),
                 monthly_time=time(23, 30)):
        ...
```

`llm` is the provider used for summarization (chat-role pool from the runtime's pool registry). When None, all rollups use the deterministic fallback summarizer (AC-13.12).

### 13.2 Append loop

The existing `on_tick` polling pattern stays — every `JOURNAL_POLL_TICKS`:

1. Fetch new memory events since `_last_seen`.
2. Append each to `today.md`.
3. Rewrite `identity.md` if WISDOM set changed.
4. Check rollup triggers (see 13.3).

### 13.3 Rollup triggers

A separate per-tick check that runs in `on_tick`:

```python
def _check_rollups(self, now: datetime) -> None:
    if self._crossed_into(now, self._next_daily_at):
        self._run_daily_rollup(now)
        self._next_daily_at = self._next_daily_window(now)
    if now.weekday() == 6 and self._crossed_into(now, self._next_weekly_at):
        ...
```

`_crossed_into` returns true if `last_check_at < target_time <= now`. Idempotent across multiple ticks within the same second.

### 13.4 LLM-driven summarization

```python
ROLLUP_PROMPTS = {
    "daily": (
        "You are summarizing a single day's activity from your own journal.\n"
        "Read the entries below and produce a 1-3 paragraph first-person\n"
        "summary capturing: what happened, what you learned, what you'd\n"
        "want to remember tomorrow. Be honest and concise.\n\n"
    ),
    "weekly": "You are summarizing a week from your own daily summaries...",
    "monthly": "You are summarizing a month from your own weekly summaries...",
    "recent_history": (
        "You are updating your longer-term narrative. The current narrative\n"
        "and a new monthly summary are below. Produce a new narrative that\n"
        "preserves the through-lines, drops what's no longer relevant.\n\n"
    ),
}
```

### 13.5 Configuration constants

```python
JOURNAL_POLL_TICKS:           int  = 200       # ~2s at 100Hz
DAILY_ROLLUP_TIME_LOCAL:      time = time(23, 55)
WEEKLY_ROLLUP_TIME_LOCAL:     time = time(23, 0)     # Sunday
MONTHLY_ROLLUP_TIME_LOCAL:    time = time(23, 30)    # last day of month
ROLLUP_MAX_TOKENS:            int  = 4_000
ROLLUP_LLM_TIMEOUT_S:         int  = 60
```

All runtime-tunable via the CoefficientTuner pathway.

## Open questions

- **Q13.1.** Cadences are operator-local-time, not UTC. Implication: a deployment that crosses time zones (very rare for this kind of project) would see weird rollup timing. Default to local; let operators set TZ via env.
- **Q13.2.** "Recent history" rollup uses recent-history + new monthly to produce new recent-history. After 5 years there's a lot of compression in a single file. Should there be N-year archives of recent-history.md too? Probably yes.
- **Q13.3.** The daily summary is LLM-generated. Tokens cost. For very high-traffic deployments, a single day's rollup could exceed `ROLLUP_MAX_TOKENS` easily. The truncation strategy is simple (drop later events); a better strategy would chunk-and-summarize iteratively. Deferred.
- **Q13.4.** Per-user journals: with the multi-user shared-self model, all users contribute to one journal. Should there also be per-user threads (`journal/users/<user_tag>/...`)? Open.
- **Q13.5.** The deterministic fallback summarizer is "first paragraph + list of `## ` headings." Crude. Operators may want something better (e.g., template-based). Tunable via subclass or callback.
