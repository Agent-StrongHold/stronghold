# Spec 100 — Session-close digest pipeline

*On session close, a sandboxed Python reflector computes `{expected, observed, cause}` and extracts worked / failed / preference buckets; results feed the detector backlog at P30. Replaces ambient "somehow learn from session" with a structured, dedupable close-ritual.*

**Depends on:** [detectors/README.md](./detectors/README.md), [conversation-threads.md](./conversation-threads.md), [memory-mirroring.md](./memory-mirroring.md), [warden-on-self-writes.md](./warden-on-self-writes.md), [forensic-tagging.md](./forensic-tagging.md), [self-write-budgets.md](./self-write-budgets.md).

---

## Current state

Sessions end (timeout or explicit end) and the only artifact is trace history + memory-mirror (spec 32). There's no structured "what happened here" distillation — lessons drift into LESSON-tier only via ad-hoc learning-extraction (spec 63), which operates on routing pairs, not full-session context. Acontext's task-close distillation and ACE's sandboxed reflector are the references.

## Target

One digest per closed session. A sandboxed Python reflector reads the session's trace history and returns `{expected, observed, cause}` plus three buckets: `worked: list[str]`, `failed: list[str]`, `preferences: list[str]`. Each bucket emits one OBSERVATION (source `I_DID`, forensic-tagged) and a detector-backlog entry at P30. Sandbox has CPU/memory/timeout caps; reflector failure doesn't block session close.

## Acceptance criteria

### Trigger

- **AC-100.1.** Digest fires on session close: either (a) explicit end via API, or (b) idle timeout (`SESSION_IDLE_TIMEOUT_SEC`, default 1800s) elapsed since last turn. Test both triggers.
- **AC-100.2.** Exactly one digest per session — idempotency enforced by `request_hash = hash(session_id)` dedup in the digest table. A second close attempt logs DEBUG and no-ops. Test.

### Sandbox

- **AC-100.3.** Reflector runs in a Python subprocess with `resource.setrlimit` applied: `RLIMIT_CPU = 20s`, `RLIMIT_AS = 256 MB`. Test that an infinite-loop reflector is killed by CPU limit.
- **AC-100.4.** Wall-clock timeout `REFLECTOR_TIMEOUT_SEC = 30` (greater than RLIMIT_CPU to catch fork/import overhead). On timeout, subprocess is SIGKILL'd. Test.
- **AC-100.5.** Sandbox has no network access (egress blocked via a deny-all loopback-only `requests` session fixture and blocked `socket.create_connection`). Test that attempted HTTPS calls raise.
- **AC-100.6.** Sandbox stdin feeds the trace history as JSON; stdout is the digest JSON. Any non-JSON stdout is treated as failure. Test with a reflector that prints garbage.

### Digest schema

- **AC-100.7.** Digest return schema (validated via `pydantic` or dataclass-json):
  ```python
  @dataclass
  class SessionDigest:
      expected: str          # ≤ 280 chars
      observed: str          # ≤ 280 chars
      cause: str             # ≤ 280 chars
      worked: list[str]      # each ≤ 200 chars, len(list) ≤ 10
      failed: list[str]      # each ≤ 200 chars, len(list) ≤ 10
      preferences: list[str] # each ≤ 200 chars, len(list) ≤ 10
  ```
  Test each length cap.
- **AC-100.8.** Out-of-schema digest (missing field, over-length string, over-length list) is rejected; no memories written. Test with fixtures.

### Memory writes

- **AC-100.9.** Valid digest writes **one OBSERVATION per bucket item** (worked/failed/preferences), source `I_DID`, content = the bucket string, forensic-tagged with `perception_tool_call_id = "session_close_digest:{digest_id}"`. Test count of writes equals `len(worked)+len(failed)+len(preferences)`.
- **AC-100.10.** Writes carry `origin = "session_close"` for sector filtering (spec 99 reflective sector doesn't include this — consider future sector extension). Test origin is stamped.
- **AC-100.11.** Warden-scanned per spec 36 posture; a `deny` or `escalate` verdict on any bucket item skips that item and logs an OPINION noting the verdict. Other bucket items proceed. Test.

### Detector backlog

- **AC-100.12.** One detector-backlog entry per digest at priority `P30`, carrying `digest_id` for traceability. Backlog entry body is `{expected, observed, cause}` only (not the full buckets — buckets are already materialized as memories). Test.

### Failure tolerance

- **AC-100.13.** A failed reflector (timeout, non-zero exit, invalid JSON, validation error) **does not block session close**. An OPINION memory records the failure: `"session close digest failed: <reason>"`. Test each failure mode.
- **AC-100.14.** Reflector failure increments `turing_session_digest_failed_total{reason}`. Test metric on each failure path.

### Budget integration

- **AC-100.15.** Digest writes count as **1 node add** toward the per-request write budget (spec 95), not one per bucket item — the digest is treated as a batch. Over-budget defers the detector-backlog entry only; memories still write (core-pipeline operation). Test budget accounting.

### Digest table

- **AC-100.16.** Digests persisted in `session_digests(id, session_id UNIQUE, created_at, expected, observed, cause, worked jsonb, failed jsonb, preferences jsonb, status)` where status ∈ `{"ok","failed","warden_partial"}`. Test schema.

## Implementation

```python
# reflector/session_close.py

REFLECTOR_TIMEOUT_SEC: int = 30
SESSION_IDLE_TIMEOUT_SEC: int = 1800

def on_session_close(repo, warden, session_id: str) -> DigestOutcome:
    if repo.digest_exists(session_id):
        return DigestOutcome(skipped="duplicate")

    trace = repo.session_trace(session_id)
    try:
        raw = _run_sandboxed(
            script=REFLECTOR_SCRIPT,
            stdin=json.dumps({"trace": trace}).encode(),
            cpu=20, mem_mb=256, timeout=REFLECTOR_TIMEOUT_SEC,
        )
        digest = SessionDigest(**json.loads(raw))
    except (TimeoutError, ValueError, json.JSONDecodeError) as e:
        repo.write_opinion(f"session close digest failed: {e}")
        repo.record_digest(session_id, status="failed")
        return DigestOutcome(failed=str(e))

    digest_id = repo.insert_digest(session_id, digest, status="ok")
    for item in digest.worked + digest.failed + digest.preferences:
        verdict = warden.scan(item)
        if verdict.denied:
            repo.write_opinion(f"session close digest item denied: {verdict.rationale}")
            continue
        repo.write_observation(
            content=item, source="I_DID", origin="session_close",
            perception_tool_call_id=f"session_close_digest:{digest_id}",
        )
    repo.enqueue_detector_backlog(digest_id, priority="P30")
    return DigestOutcome(digest_id=digest_id)
```

## Open questions

- **Q100.1.** Should the reflector be deterministic (pure-Python summarization) or LLM-backed? Current assumption: deterministic first, LLM-variant gated behind a feature flag once deterministic baseline is proven. Deferred.
- **Q100.2.** `SESSION_IDLE_TIMEOUT_SEC = 1800` may be too short for long multi-day threads (spec 54 conversation-threads). Consider per-thread-type overrides.
- **Q100.3.** The digest P30 backlog entry duplicates some signal with spec 63's learning-extraction (routing regrets). Coalesce via detector-dedup or leave as parallel paths? Keep parallel for now; revisit if redundancy hurts.
- **Q100.4.** Buckets are flat strings; a future richer schema could attach references to specific turns. Defer until we see reflector output quality.
