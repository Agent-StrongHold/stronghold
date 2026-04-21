# Tranche 7 — Plan

*Closing the Tranche 6 implementation gaps and landing the Tranche 6 audit's guardrails in dependency order. Five tranches, sequenced so each depends only on earlier ones. All land on `research/project-turing` via PRs targeting `project_Turing`.*

**Prerequisite doc:** [`AUDIT-self-model-guardrails.md`](./AUDIT-self-model-guardrails.md) — findings and guardrail numbering referenced here.

---

## Why this order

Guardrails assume the tools they gate exist. Today's sketch is a library — schema, math, tests — with three load-bearing runtime pieces absent: the self-tool registry (F35), memory mirroring (F38), and scheduled jobs (F37), plus the entire self-as-Conduit pipeline (F39). A guardrail like G1 ("Warden on self-writes") gates tools that have no runtime surface; a guardrail like G6 ("rolling-sum mood cap") assumes mood is decaying on a schedule.

So Tranche 7 starts with foundation closure. Guardrails follow. The Conduit rewrite and operator-oversight design are later tranches because they are the largest surface-area changes and need the earlier work to land first.

| # | Theme | Blocks | Depends on |
|---|---|---|---|
| 7.0 | Foundation closure (critical impl gaps) | F35, F36, F37, F38, F39 (partial), F30, F29, F33 | — |
| 7.1 | Boundary hardening | G1, G2, G5, G17 | 7.0.1, 7.0.2 |
| 7.2 | Drift bounds | G3, G4, G6, G10 | 7.0.1, 7.0.3 |
| 7.3 | Self-as-Conduit runtime | F39 (full), F40 | 7.0 complete |
| 7.4 | Operator oversight | G12, G13, G14, G15, G16, G18 | 7.1, 7.3 |
| 7.5 | Growth and operational | G7, G8, G9, G11 | 7.0.2 |

---

## 7.0 — Foundation closure

Five slices, each a small PR. Ordered by dependency.

### 7.0.1 — Self-tool registry + missing tool impls

**Closes:** F35, F36.
**Ships:** `SelfTool` dataclass + `SELF_TOOL_REGISTRY` + `register_self_tool` in `self_surface.py`; bootstrap-time registration of every tool named in spec 28 AC-28.1; implementations of `write_contributor`, `record_personality_claim`, `retract_contributor_by_counter`.
**Invariants:**
- Every tool registered carries `trust_tier = t0`.
- Tool descriptions start with a first-person clause (AC-28.5) — enforced by a lint in `register_self_tool`.
- `retract_contributor_by_counter(target, source, weight, rationale)` writes a counter-contributor with opposite sign; it does not flip `retracted_by` directly (AC-25.15).
- `record_personality_claim` persists an OPINION memory and a contributor (AC-23.19–22); contributor weight via `narrative_weight()` with the ≤0.4 cap.
**Tests:** one new file `test_self_tool_registry.py` covering registry lookup, description-format enforcement, and each newly-implemented tool's AC.

### 7.0.2 — Memory-mirroring hooks on every self-model write

**Closes:** F38 (critical).
**Ships:** a small `self_memory_bridge.py` module exposing `mirror_observation`, `mirror_affirmation`, `mirror_lesson`, and `mirror_regret` helpers that wrap the existing write-paths (`write_paths.py`) with the first-person `intent_at_time` and `context` keys each spec AC names. Wire every self-model write-site to call the appropriate mirror:
- `note_engagement` / `note_interest_trigger` → OBSERVATION (AC-24.8, AC-24.10).
- `nudge_mood` → OBSERVATION (AC-27.9).
- `complete_self_todo` → AFFIRMATION (AC-26.12).
- `record_personality_claim` → OPINION (AC-23.19).
- `apply_retest` items → OBSERVATION per item (AC-23.17).
- `write_contributor(origin=self)` → OBSERVATION audit row (AC-25.19).
- `finalize` in bootstrap → LESSON (AC-29.17).
**Invariants:**
- Every mirror carries `context.self_id` and, where applicable, `context.request_hash` (forensics — pre-work for G17).
- No write-site writes the self-model row without also writing the mirror, in the same transaction.
**Tests:** extend the existing per-module tests to assert the mirror happens (check `episodic_memory` / `durable_memory` counts before/after each write). Net new: ~30 assertions.

### 7.0.3 — Reactor registration for scheduled jobs

**Closes:** F37.
**Ships:**
- `tick_mood_decay(self_id)` registered in `run_bootstrap.finalize` as an **interval trigger** every `MOOD_DECAY_INTERVAL = 1h`.
- `run_personality_retest(self_id)` registered in `finalize` with `first_fire_at = now + 7d` and interval `7d`; the function body wraps `apply_retest` with sample-selection + LLM-plumbing (keep the LLM ask as an injected `ask_self` callable for testability).
- Reactor can list `self:*` triggers via an inspect command (for operator forensics).
**Invariants:**
- Bootstrap resume preserves existing trigger registrations; double-register is idempotent (named triggers per AC-29.16).
- Downtime catch-up: a missed hourly mood tick produces exactly one decay call on resume (spec 27 AC-27.5).
**Tests:** `test_self_schedules.py` — bootstrap registers two triggers; FakeReactor advanced 24h produces exactly 24 mood-decay calls; advanced 8 days produces one retest call.

### 7.0.4 — Wire `source_kind = "memory"` to real memory weight

**Closes:** F30 (high — required before G12 digest can surface "heaviest self-contributors").
**Ships:** `self_activation.source_state` lookup into the episodic memory repo (`repo.get_memory(source_id).weight`) via a narrow dependency injection in `ActivationContext` (so tests can still stub). Clamp to `[0.0, 1.0]`.
**Invariants:** `source_kind == "memory"` resolves to the stored memory's `weight`, not 0.5. A dangling memory-id falls through to the existing "weight-0 skip" path (AC-25.23).
**Tests:** extend `test_self_activation.py` with three cases: OBSERVATION-weight memory (≈0.2), REGRET-weight memory (≥0.6), dangling memory id. Assert activation differs across the first two.

### 7.0.5 — Guard rails on tool entry + active_now cache + self-id ownership

**Closes:** F29, F33, F24 (partial).
**Ships:**
- `_bootstrap_complete(self_id)` check at the top of every `note_*`, `write_self_todo`, `write_contributor`, `record_personality_claim`. Raises `SelfNotReady`.
- `active_now` 30s cache keyed by `(node_id, ctx.hash)`; invalidate on contributor writes/retractions targeting that node or any of its sources (AC-25.10).
- `acting_self_id` parameter on `SelfRepo.update_*` / `insert_contributor` / `insert_todo_revision`; mismatch raises `CrossSelfAccess`. Tool-surface layer passes `self_id` through.
**Tests:** a pre-finalize `note_passion` raises; cache hit on repeated `active_now`; cross-self repo write raises.
