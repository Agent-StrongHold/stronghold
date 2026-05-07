# Spec 93 — Passion-seeded desire synthesis

*When a passion stays active for N days with no linked todo, the daydream producer drafts a first-person "what might I want to do?" pass; strong outputs surface as pending todos under operator review.*

**Depends on:** [daydreaming.md](./daydreaming.md), [self-nodes.md](./self-nodes.md), [self-todos.md](./self-todos.md), [operator-review-gate.md](./operator-review-gate.md), [activation-graph.md](./activation-graph.md).
**Depended on by:** [motivation-rooted-task-dag.md](./motivation-rooted-task-dag.md) (synthesized todos enter the DAG).

---

## Current state

Passions (spec 24 self-nodes) carry activation but today never trigger downstream desire generation on their own. Daydreaming (spec 7) runs in I_IMAGINED mode and is memory-only, never producing candidate todos. Operators must manually author todos to link to passions — the self has no channel to say "I notice I keep being drawn here, and I wonder if I want to do X about it."

## Target

Watch each passion's activation. If a passion's `active_now > DESIRE_SYNTHESIS_FLOOR = 0.55` for `DESIRE_CONSEC_DAYS = 5` consecutive days AND has zero linked live todos, trigger a daydream pass asking "what I might want to do about this passion." The output stays I_IMAGINED. If its strength exceeds `DESIRE_STRENGTH_THRESHOLD = 0.7`, surface it as a **pending** todo (operator-review-gate.md, not live). Operator ACK → live todo; operator reject → REGRET linked to the passion. Synthesis rate-limited per passion and per self.

## Acceptance criteria

### Passion-activation watch

- **AC-93.1.** A `passion_active_days` daily aggregate tracks the last 30 days: `day` + `max_activation_that_day` per passion node. Test rollup runs once per UTC day.
- **AC-93.2.** A passion qualifies when the last `DESIRE_CONSEC_DAYS = 5` daily entries all have `max_activation_that_day > DESIRE_SYNTHESIS_FLOOR = 0.55`. Test both boundary cases (4 days = no, 5 days = yes).
- **AC-93.3.** A passion with ANY linked live todo (`status IN ('pending','in_progress')` AND `motivated_by_node_id = this.id`) is excluded. Test.

### Synthesis trigger

- **AC-93.4.** Per-passion rate-limit: at most one synthesis attempt per `DESIRE_SYNTHESIS_PER_PASSION_WINDOW = 7 days`. Test second attempt within window is skipped.
- **AC-93.5.** Global rate-limit per self: `DESIRE_SYNTHESIS_DAILY_CAP = 2` synthesis runs per 24h (regardless of passion). Test.
- **AC-93.6.** Synthesis is dispatched through the daydream producer (spec 7) with a dedicated prompt template `desire_synthesis_v1` and `source = I_IMAGINED`. Test source tag persists on the draft output.

### Output validation

- **AC-93.7.** The producer emits `{title, rationale, strength ∈ [0,1]}`. `strength` is a self-scored number the model returns; Stronghold does not re-score. Test output schema.
- **AC-93.8.** If `strength < DESIRE_STRENGTH_THRESHOLD = 0.7`, the output is **discarded** — no pending todo, no memory write, no forensic trail beyond a single log line. Test with low-strength mock output.
- **AC-93.9.** If `strength >= DESIRE_STRENGTH_THRESHOLD`, write a **pending todo** via operator-review-gate (spec 46 equivalent):
  ```
  status = "pending_review",
  motivated_by_node_id = passion.id,
  source = I_IMAGINED,
  review_required = True,
  parent_todo_id = NULL,
  ```
  Test shape.

### Operator adjudication

- **AC-93.10.** `stronghold self ack-desire <pending_id> [--edit-title TITLE]` marks the todo `status = "pending"` (live), changes `source` to `I_WAS_TOLD` (operator endorsed), and mirrors an OBSERVATION. Test.
- **AC-93.11.** `stronghold self reject-desire <pending_id> --reason TEXT` deletes the pending todo AND mints a REGRET linked to the passion with `content = "Synthesized desire '{title}' rejected: {reason}"`; the REGRET adds a `weight = -0.05` inhibitory contributor to the passion's activation (origin="rule"). Test both effects.
- **AC-93.12.** A pending todo unacknowledged for `DESIRE_PENDING_TTL = 30 days` auto-expires to rejected with `reason = "auto-expired"`; mints a standard REGRET but **without** the inhibitory contributor (auto-expiry is not a judgment). Test.

### Watchdog

- **AC-93.13.** If synthesis produces `DESIRE_RUNAWAY_CAP = 5` accepted-to-pending todos across the whole self within a rolling 14 days, the synthesizer is disabled for 7 days and an operator alert is raised. Test by driving 6 synthesis successes.
- **AC-93.14.** Disabling is reversible via `stronghold self resume-desire-synthesis`. Test.

### Forensic tagging

- **AC-93.15.** Every synthesis write (pending todo + any REGRET) carries `request_hash` + `perception_tool_call_id` per spec 39. Test.
- **AC-93.16.** Prometheus: `turing_desire_synthesis_triggered_total`, `turing_desire_synthesis_pending_total`, `turing_desire_synthesis_rejected_total`, `turing_desire_synthesis_disabled` (gauge). Test.

## Implementation

```python
# synthesis/desire.py

DESIRE_SYNTHESIS_FLOOR: float = 0.55
DESIRE_CONSEC_DAYS: int = 5
DESIRE_STRENGTH_THRESHOLD: float = 0.7
DESIRE_SYNTHESIS_PER_PASSION_WINDOW: timedelta = timedelta(days=7)
DESIRE_SYNTHESIS_DAILY_CAP: int = 2
DESIRE_PENDING_TTL: timedelta = timedelta(days=30)
DESIRE_RUNAWAY_CAP: int = 5


def qualifying_passions(repo, self_id: str, now: datetime) -> list[SelfNode]:
    out = []
    for p in repo.passions(self_id):
        if repo.has_live_todo_for(p.id):
            continue
        days = repo.passion_active_days(p.id, limit=DESIRE_CONSEC_DAYS)
        if len(days) < DESIRE_CONSEC_DAYS:
            continue
        if all(d.max_activation > DESIRE_SYNTHESIS_FLOOR for d in days):
            out.append(p)
    return out


async def synthesize(repo, daydreamer, self_id: str, now: datetime) -> int:
    if repo.synth_disabled(self_id, now):
        return 0
    if repo.synth_count_today(self_id, now) >= DESIRE_SYNTHESIS_DAILY_CAP:
        return 0
    made = 0
    for passion in qualifying_passions(repo, self_id, now):
        if repo.last_synth_for_passion(passion.id) > now - DESIRE_SYNTHESIS_PER_PASSION_WINDOW:
            continue
        draft = await daydreamer.produce(template="desire_synthesis_v1", seed=passion)
        if draft.strength < DESIRE_STRENGTH_THRESHOLD:
            continue
        repo.insert_pending_todo(
            self_id=self_id, title=draft.title, rationale=draft.rationale,
            motivated_by_node_id=passion.id, source="I_IMAGINED",
            status="pending_review",
        )
        made += 1
    _watchdog(repo, self_id, now)
    return made
```

## Open questions

- **Q93.1.** Is `strength` self-reported by the model trustworthy? Calibration pass in Phase 5; consider replacing with a separate scorer.
- **Q93.2.** The `5 consecutive days` rule is conservative — a strong one-day spike gets ignored. Alternative: "5 of last 7". Revisit after telemetry.
- **Q93.3.** Should the inhibitory contributor on reject decay? For now it's permanent; decay policy belongs in activation-graph decay.
- **Q93.4.** Interaction with spec 92 DAG: synthesized pending todos never have a `parent_todo_id` — they're always epic-roots. Document in self-todos.md.
