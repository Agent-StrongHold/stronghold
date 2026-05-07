# Spec 98 — Cron-driven proactive outbound

*A scheduled Reactor entrypoint that samples ready motivated-todos, gates on mood and quota, and dispatches self-initiated messages via OpenWebUI — closing the gap between "outbound is possible" (spec 55) and "here are quota rules" (spec 54).*

**Depends on:** [proactive-outbound.md](./proactive-outbound.md), [conversation-threads.md](./conversation-threads.md), [motivation-rooted-task-dag.md](./motivation-rooted-task-dag.md), [mood.md](./mood.md), [self-schedules.md](./self-schedules.md), [warden-on-self-writes.md](./warden-on-self-writes.md), [scheduler.md](./scheduler.md).

---

## Current state

Spec 55 defines that the self **can** initiate outbound messages; spec 54 defines **conversation-thread quotas** (1 agent-created thread per user per day); spec 92 defines the motivated-todo DAG. But there's no actual trigger that wakes the self, samples todos, checks quota, and sends. The loop is inert. Hermes-style `periodic_runs` and LocalAGI's `initiate_conversations` pattern are the inspirations.

## Target

A concrete cron entrypoint on the Reactor (spec 20), registered via self-schedules (spec 33), that runs every ~30 min: samples ready motivated-todos (spec 92), gates on `mood.focus > θ` AND per-user daily quota (spec 54), dispatches via OpenWebUI API (spec 55), and writes an AFFIRMATION-linked memory on success / OPINION on failure. Outgoing text is Warden-scanned (spec 36 posture). A global watchdog caps proactive messages at 5/hour across all users to prevent runaway.

## Acceptance criteria

### Scheduling

- **AC-98.1.** Trigger registered via self-schedules (spec 33) at default cadence `PROACTIVE_OUTBOUND_CADENCE = timedelta(minutes=30)`, tunable via config. Test registration.
- **AC-98.2.** Cadence honors the scheduler's **5× dream-time quiet-zone rule** (spec 10) — if the last dream ended < 5× dream-duration ago, skip this tick. Test via a mock clock.
- **AC-98.3.** Timezone-aware: per-user quiet hours are respected. If the target user is in their configured quiet window (default 22:00–08:00 local), skip sending to that user. Test across two timezones.

### Gating

- **AC-98.4.** `mood.focus` threshold (spec 27): default `0.5`; below threshold, the entire tick is skipped with a log line. Test.
- **AC-98.5.** Per-user daily quota check (spec 54) — at most 1 agent-created thread per user per 24h. Query is `SELECT COUNT(*) FROM conversation_threads WHERE initiator='agent' AND user_id=? AND created_at >= ?`. Test at 0 and 1 thread.
- **AC-98.6.** Quota exceeded → **skip that user silently**, no error, log at DEBUG. The tick may still send to other eligible users. Test.
- **AC-98.7.** Global watchdog: at most `PROACTIVE_GLOBAL_HOURLY_CAP = 5` outbound messages across all users per rolling hour. Exceeded → skip and log WARN. Test with a 6th attempt.

### Sampling

- **AC-98.8.** Sample ready motivated-todos (spec 92) where `state = "ready"` AND `next_action_due <= now` AND the todo's root motivation tier is ≥ P30 (below P30 is too low-priority to justify an outbound interrupt). Test priority filter.
- **AC-98.9.** Sampling order: highest motivation-priority first, then oldest `next_action_due`. Ties broken randomly to avoid starvation. Test ordering.
- **AC-98.10.** At most 1 todo dispatched per user per tick, even if multiple are ready. Test user-dedup within a single tick.

### Dispatch

- **AC-98.11.** Outbound text is **Warden-scanned** (spec 36 posture; `warden-on-self-writes.md`) before sending. On `deny` or `escalate`, the message is not sent and the attempt is logged as an OPINION memory with the Warden verdict. Test both verdicts.
- **AC-98.12.** Dispatch uses the OpenWebUI API path defined in spec 55 (`POST /api/chat/completions` with initiator=agent flag). A successful 2xx response writes an AFFIRMATION-linked memory: source `I_DID`, content `f"I reached out about {todo.summary} — message sent"`, linked via contributor edge to the originating motivation node. Test.
- **AC-98.13.** Delivery failure (non-2xx, timeout, connection error) writes an OPINION memory: `f"Tried to reach out about {todo.summary}, the send failed with {reason}"`, source `I_DID`. Test.
- **AC-98.14.** Network timeout default `PROACTIVE_SEND_TIMEOUT_SEC = 10`. Retries: 0. Proactive is non-critical; retries belong to user-initiated flows. Test timeout behavior.

### Safety

- **AC-98.15.** A feature flag `proactive_outbound_enabled: bool` defaults to `False` in production config and `True` only in dev/test configs. Disabled → tick is a no-op that logs DEBUG. Test both states.

### Observability

- **AC-98.16.** Prometheus counters `turing_proactive_outbound_sent_total{self_id, user_id}`, `turing_proactive_outbound_skipped_total{self_id, reason}`, `turing_proactive_outbound_failed_total{self_id, reason}`. Test on every code path.

## Implementation

```python
# reactor/proactive_outbound.py

PROACTIVE_OUTBOUND_CADENCE: timedelta = timedelta(minutes=30)
PROACTIVE_GLOBAL_HOURLY_CAP: int = 5
PROACTIVE_SEND_TIMEOUT_SEC: float = 10.0
MOOD_FOCUS_THRESHOLD: float = 0.5

def tick(repo, clock, warden, openwebui, config) -> TickResult:
    if not config.proactive_outbound_enabled:
        return TickResult(skipped_reason="disabled")
    if _in_quiet_zone(clock, repo):
        return TickResult(skipped_reason="quiet_zone")
    mood = repo.latest_mood()
    if mood.focus < MOOD_FOCUS_THRESHOLD:
        return TickResult(skipped_reason="low_focus")
    if _global_hourly_count(repo, clock.now()) >= PROACTIVE_GLOBAL_HOURLY_CAP:
        return TickResult(skipped_reason="watchdog_cap")

    ready = repo.ready_motivated_todos(min_priority="P30")
    sent = []
    seen_users: set[str] = set()
    for todo in _prioritize(ready):
        if todo.user_id in seen_users:
            continue
        if _user_quota_exceeded(repo, todo.user_id):
            continue
        if _user_in_quiet_hours(clock, todo.user_id):
            continue
        outcome = _dispatch(openwebui, warden, todo, timeout=PROACTIVE_SEND_TIMEOUT_SEC)
        _record_outcome(repo, todo, outcome)
        seen_users.add(todo.user_id)
        sent.append(outcome)
    return TickResult(sent=sent)
```

## Open questions

- **Q98.1.** 30-min cadence may be too frequent for low-traffic selves and too rare for active ones. Adaptive cadence tied to recent motivation-throughput? Deferred.
- **Q98.2.** The mood-focus threshold is a single-dimension gate; a fuller gate might combine valence+arousal+focus. Currently focus only, matching spec 27's emphasis on focus as the "reaching out" dimension.
- **Q98.3.** Global watchdog at 5/hour is cross-user — a single noisy user could starve others. Consider per-user-and-global layered caps once real traffic exists.
- **Q98.4.** Should quiet-hours respect Obsidian-vault-declared calendar events (spec 35 pipeline)? Worth integrating once the newsletter pipeline is stable.
