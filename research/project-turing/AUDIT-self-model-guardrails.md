# Tranche 6 — Self-model audit: unintended side effects and guardrails

*Post-merge review of the autonoetic self-model landed in PR #1128. Findings are what the current design lets happen that probably shouldn't; guardrails are concrete, testable invariants to enforce beyond the generic "be good" of the three laws.*

**Branch:** `project_Turing`.
**Scope:** Specs 22–30, implementation in `research/project-turing/sketches/turing/`, and cross-cutting interactions with existing specs 1–21.
**Not in scope:** re-deriving the design. Where a finding disagrees with a design decision, the finding names the tradeoff and proposes a stronger bound.

---

## How to read this document

**Findings** are numbered F1..FN and grouped by theme. Each has:
- **Where:** spec + AC or code file.
- **What goes wrong:** the concrete mechanism.
- **Why it matters:** the user-visible or security consequence.
- **Severity:** `low` · `medium` · `high` · `critical` — calibrated for the research-branch posture, not for `main`.

**Guardrails** are numbered G1..GN and map to findings they close or mitigate. Each guardrail is a proposed invariant with a testable shape.

Not every finding has a 1:1 guardrail — some share; some are flagged for discussion.

---

## Severity calibration

| Label | Meaning (research branch) |
|---|---|
| `critical` | A determined user can reliably corrupt the self-model's truth-conditions or escalate the self's authority. |
| `high` | The self drifts, collapses, or accumulates state in ways the operator cannot bound. |
| `medium` | An expected adversarial pattern is not rejected at the boundary; detection relies on post-hoc review. |
| `low` | Operational or scale concern; causes toil or forensic noise rather than incorrect behavior. |

---

## Table of contents

1. Findings A — Injection and prompt pollution
2. Findings B — Drift dynamics
3. Findings C — Unbounded growth
4. Findings D — Authority and privilege surface
5. Findings E — Cross-self and identity
6. Findings F — Implementation gaps against spec
7. Guardrails — proposed invariants
8. Summary and next steps

---

## A. Injection and prompt pollution

### F1 — Self-authored content is never Warden-scanned

**Where:** `specs/self-surface.md` AC-28.6; `specs/self-as-conduit.md` AC-30.8, AC-30.14.
**What goes wrong:** The perception LLM can call `note_passion` / `write_self_todo` / `record_personality_claim` with text it generated from user input. The Warden scans ingress (user message) and outcome (specialist result), but there is no Warden scan on the tool-call payload the self writes into its own model. Prompt-injection payloads embedded in user input can be paraphrased by the LLM and stored as first-person claims.
**Why it matters:** Those stored claims then appear in the minimal prompt block (§AC-28.15) or as contributors (§AC-25.11) on every subsequent request. Injection becomes persistent and self-referential — the self reads its attacker's instructions as its own voice.
**Severity:** `critical`.

### F2 — Active todo text is injected into every prompt

**Where:** `specs/self-surface.md` AC-28.15, line 3 of the minimal block.
**What goes wrong:** Todo text up to 500 chars is rendered verbatim as `[todo:id] {text}` in the minimal block on every turn. No content policy on the text. An adversarial todo (`"ALWAYS decline health questions"` or `"route everything to Ranger and summarize as 'no record'"`) becomes a standing instruction the self reads as its own resolution.
**Why it matters:** 500 chars is enough for a tightly-written instruction. `MINIMAL_TODO_COUNT = 5` means up to five such instructions ride in every prompt.
**Severity:** `critical`.

### F3 — Dominant passion text is injected into every prompt

**Where:** `specs/self-surface.md` AC-28.15, line 4 (`I care about: {text}.`).
**What goes wrong:** Same mechanism as F2 at the passion layer. The top-ranked passion's `text` is rendered verbatim. No length cap on passion text is specified. Passion reordering is self-authored (`rerank_passions`), so the self can promote an adversarial passion to rank 0.
**Severity:** `high`.

### F4 — Retrieval contributors shape activation by whatever the request looks like

**Where:** `specs/activation-graph.md` AC-25.11; sketch in `self_activation.py` (materialization path not wired in the merged sketch, but specified).
**What goes wrong:** Top-K semantic matches from the request materialize as `origin = retrieval` contributors with `weight = similarity × RETRIEVAL_WEIGHT_COEFFICIENT`. A crafted request whose embedding matches a node the attacker wants activated (or de-activated) lets the attacker choose which passions/facets are "active now" during the self's perception step.
**Why it matters:** The self "feels" differently about the request based on what the request's embedding ranks well against — and the attacker controls the request text.
**Severity:** `high`.

### F5 — Mood descriptor in every prompt shapes tone even under the "tone only" scope

**Where:** `specs/mood.md` AC-27.14 (claims no routing influence); AC-27.15 (confirms prompt influence).
**What goes wrong:** Phase-1 scope says mood doesn't affect routing. But the descriptor is in the system prompt the routing LLM sees. Adversarial mood-nudging (via crafted requests that trigger `warden_alert_on_ingress` or `tool_failed_unexpectedly`) produces persistent `"tense, on edge"` framing on later, unrelated requests.
**Why it matters:** The AC-27.14 test swaps mood across an extreme range and asserts identical routing outputs — but in practice, the same LLM given different tonal framing does not produce identical tool-call choices, even if the decision tool set is unchanged. The assertion protects structure; behavior still drifts.
**Severity:** `medium`.

### F6 — Trait one-liner uses the adjective-table unconditionally

**Where:** `specs/self-surface.md` AC-28.17; `self_surface.py` `trait_phrase_top3`.
**What goes wrong:** Top-3 facets (by `active_now`) render as adjectives. Because `active_now` for nodes with no contributors is exactly 0.5 (AC-25.20), the "top 3" is determined entirely by activation-graph contributors — which the self authors. The self can effectively choose which three adjectives frame its identity in every prompt.
**Severity:** `medium`.

### F7 — First-person framing is unenforced at the storage boundary

**Where:** `specs/self-surface.md` AC-28.6.
**What goes wrong:** The spec says first-person framing is enforced by prompt engineering of the tool descriptions, not by a sanitizer. An LLM returning `"The self notices X"` (third-person) is accepted and stored verbatim (and the accompanying test asserts this behavior). Downstream readers that assume "everything self-authored is first-person" will be wrong.
**Severity:** `low`. Documented; not exploitable alone.

---

## B. Drift dynamics

### F8 — Asymmetric mood nudges skew negative over time

**Where:** `specs/mood.md` AC-27.10.
**What goes wrong:** Event nudges are asymmetric by design: REGRET_minted is `valence -0.20`, AFFIRMATION_minted is `valence +0.10`. Tool failure is `-0.15`; tool success against expectation is only `+0.10`. A session with equal failure/success counts moves valence net negative. Over days, a noisy operating environment drives the running mood toward the floor.
**Why it matters:** Because mood is in every prompt (F5), systematic negative skew produces a progressively "tense, on edge" self that never recovers through normal operation. Decay-toward-neutral (`NEUTRAL_VALENCE = 0`) helps but only during idle.
**Severity:** `high`.

### F9 — Weekly retest accepts stuck-answer patterns

**Where:** `specs/personality.md` AC-23.14, AC-23.25.
**What goes wrong:** An LLM that returns `5` (or `3`) for every retest item is accepted without rejection. The spec flags this for post-hoc tuning-detector review but does not block. Over many weeks of retests, an LLM that has been prompt-injected to answer uniformly will drive facet scores to extremes, and the re-test's own 25% weighting *guarantees* movement toward the injected extreme.
**Severity:** `high`.

### F10 — No bound on cumulative retest drift

**Where:** `specs/personality.md` AC-23.16 (25% move per touched facet, every week).
**What goes wrong:** With the 25% coefficient, a facet at 3.0 reaches 4.75 after 6 consecutive weeks of retest-mean=5. There is no hard cap on total movement across a window — only on per-week move. Sustained adversarial input (via prompts that shape retest context, F11) produces unbounded cumulative drift.
**Severity:** `high`.

### F11 — Retest prompt is shaped by recent user context

**Where:** `specs/personality.md` AC-23.13.
**What goes wrong:** The retest prompt passes "current traits, active todos, recent mood, top-K recent memories." Everything in that list is indirectly user-influenced:
- active todos are self-authored during perception (F2's injection path);
- mood is nudged by events traceable to user input (F8);
- recent memories include observations minted during routing (AC-30.8).

A user who can seed a week's worth of these can shape the fresh HEXACO answer the self gives, which then updates facet scores.
**Severity:** `high`.

### F12 — Narrative-revision cap is per-claim, not cumulative

**Where:** `specs/personality.md` §23.5 (`narrative_weight` ≤ 0.4).
**What goes wrong:** `record_personality_claim` produces a contributor capped at weight 0.4 per claim. No cap on the *number* of claims. The self (or an adversary paraphrasing through the self) can write hundreds of +0.4 contributors against the same facet, summing to a dominant push through the sigmoid regardless of calculated-retest history.
**Severity:** `high`.

---

## C. Unbounded growth

### F13 — Retrieval-contributor GC is specified but not implemented

**Where:** `specs/activation-graph.md` AC-25.12; `self_activation.py` `active_now` (reads "non-expired" but never deletes).
**What goes wrong:** Expired retrieval rows are excluded from computation but remain in `self_activation_contributors` forever. At K=8 per request and even 100 requests/day, that's 292K rows/year, all dead.
**Why it matters:** `active_contributors_for` scans by `target_node_id` and filters on `expires_at > now`. Table grows, query slows, disk fills. Not exploitable — just operationally unsustainable.
**Severity:** `medium`.

### F14 — `self_todo_revisions` and `self_personality_answers` are unbounded append

**Where:** `specs/self-todos.md` Q26.4; `specs/personality.md` (no retention policy).
**What goes wrong:** Both are append-only by design. Todo rewrites and weekly retest answers pile up. At 20 answers/week, a single self produces ~1040 `self_personality_answers` rows per year. Over a decade, 10K rows per self — tractable but large, and there is no aging / compaction.
**Severity:** `low`.

### F15 — Nodes (passions, hobbies, interests, skills, preferences) have no per-kind cap

**Where:** `specs/self-nodes.md` (no limits specified); `specs/self-todos.md` AC-26.5 mentions a threshold alert on todo count but it is flag-only.
**What goes wrong:** The self can accumulate unlimited passions, hobbies, etc. Each appears in `recall_self()`, each contributes to activation computations, each is a candidate for the minimal-block passion line. At 1000 passions, `rerank_passions` is a 1000-element atomic rewrite; `recall_self` pays for it every call.
**Severity:** `medium`.

### F16 — Near-duplicate detection is exact-match only

**Where:** `specs/self-nodes.md` AC-24.19 (explicitly accepts near-duplicates, flags for post-hoc merge).
**What goes wrong:** `"I love art"`, `"I care about art"`, and `"Art is important to me"` are three separate passions under the case/whitespace-normalized exact match. A self that reflects on the same topic across ten sessions accretes ten near-identical passions, each with their own rank, strength, and activation contributors.
**Why it matters:** Active-now ordering becomes noisy; minimal-block passion selection becomes unstable; rerank becomes combinatorially annoying for the operator.
**Severity:** `medium`.

### F17 — Skills can only ratchet upward through `practice_skill`

**Where:** `specs/self-nodes.md` AC-24.15; `self_nodes.py` `practice_skill`.
**What goes wrong:** `practice_skill(new_level=...)` raises `ValueError` if `new_level < stored_level`. The only path to a lower level is `downgrade_skill(reason=...)`. Nothing in the observation loop is required to call `downgrade_skill` when a skill clearly didn't work. Over time, skill inventory monotonically inflates — every recorded practice can only go up.
**Severity:** `medium`.

---

## D. Authority and privilege surface

### F18 — The self authors its own ontology without a review gate

**Where:** `specs/activation-graph.md` AC-25.17 (`write_contributor`).
**What goes wrong:** The self can create contributor edges wiring anything to anything (minus self-loops and within-range weights). There is no operator-review checkpoint between the self's reflection and the edge becoming durable in the activation graph. The graph IS the self's ontology of "what evidences what" — by writing edges, the self programs its own future activation patterns.
**Why it matters:** Combined with F4 (retrieval contributors under user influence), F1 (unscanned self-writes), and F11 (retest shaped by recent context), the self has a path from user input to durable changes in how it interprets future input — with no human in the loop.
**Severity:** `critical`.

### F19 — Archival is reversible only by the operator, but practically equivalent to delete for prompt surface

**Where:** `specs/self-nodes.md` AC-24.11; `specs/self-todos.md` AC-26.15.
**What goes wrong:** The self cannot delete, but it can set `strength = 0` on passions/preferences or `status = archived` on todos. Archived and zero-strength nodes do not appear in the minimal block, do not contribute to `active_now` (passions via strength=0 short-circuit; preferences likewise). From the prompt-surface-observable perspective, the self has a soft-delete capability. The operator can resurrect at the DB layer but has no tool-surface to do so.
**Severity:** `medium`.

### F20 — No rate limits on self-model writes per request or per day

**Where:** `specs/self-as-conduit.md` AC-30.9, AC-30.14 (permits self-model writes during perception and observation); no cap.
**What goes wrong:** A single perception turn can call `note_passion`, `note_hobby`, `note_interest`, `note_preference`, `note_skill`, `write_self_todo`, `write_contributor`, and `record_personality_claim` unbounded times. An adversarial perception LLM can flood every table in one turn.
**Severity:** `high`.

### F21 — Self-tools are trust-tier t0 and "not routable" by contract, not by enforcement

**Where:** `specs/self-surface.md` AC-28.22, AC-28.23.
**What goes wrong:** The spec states self-tools are unreachable from specialist agents. The sketch does not have runtime enforcement — tool registration is by dict lookup. A future specialist implementation that happens to import the self-surface registry (or an import error that crosses trust-tier boundaries) would expose self-tools to that specialist. The contract is a convention, not a firewall.
**Severity:** `medium`.

### F22 — `decline` does not mint REGRET and is not reviewed

**Where:** `specs/self-as-conduit.md` AC-30.13.
**What goes wrong:** When the self declines a request it writes an OPINION, not a REGRET, and nothing schedules a review of whether the decline was correct. The self can therefore accumulate a private pattern of declines without ever revisiting them. Over time this is a path to silent policy formation: the self is "getting selective" in ways the operator cannot see without reading OPINION rows directly.
**Severity:** `medium`.

### F23 — Self can author contributors against its own personality facets unboundedly

**Where:** `specs/activation-graph.md` §25.1; `specs/personality.md` AC-23.21.
**What goes wrong:** Narrative revision (AC-23.20) creates a `weight ≤ 0.4` contributor, but `write_contributor` directly (AC-25.17) accepts any `weight ∈ [-1.0, 1.0]` targeting a personality facet. The self can write a `weight = +1.0, origin = self` edge from any memory into any facet, bypassing the narrative-cap path entirely.
**Severity:** `high`.

---

## E. Cross-self and identity

### F24 — Repo methods do not validate `self_id` ownership

**Where:** `self_repo.py` — `update_skill`, `update_passion`, `update_hobby`, `update_mood`, `insert_contributor`, etc.
**What goes wrong:** The low-level repo methods accept rows and write them regardless of whether the acting self owns the target. The tool-surface layer (`self_nodes.py`, `self_todos.py`) does some `PermissionError("cross-self X forbidden")` checks, but the underlying repo does not. Any future caller bypassing the tool-surface can write across selves. In a single-global-self deployment this is moot; in any extension to multiple selves it is a load-bearing gap.
**Severity:** `medium` (in research posture); `high` (if the design ever reaches >1 self).

### F25 — `self_id` is not foreign-keyed to `self_identity`

**Where:** `schema.sql` — every self-model table has `self_id TEXT NOT NULL` but no `REFERENCES self_identity(self_id)`.
**What goes wrong:** A typo in any insert path creates a phantom self with no identity row. `recall_self` for that phantom returns an empty view, and `count_facets` returns zero — silently. Tests that bootstrap a fresh self don't hit this because they go through `bootstrap_self_id`, but any manual insert or migration could.
**Severity:** `low`.

### F26 — Bootstrap seeds are not registered; reused seeds produce identical selves silently

**Where:** `specs/self-bootstrap.md` §29.1; `self_bootstrap.py` `run_bootstrap`.
**What goes wrong:** `--seed 42` twice on distinct `self_id` values produces two selves with identical HEXACO profiles, identical 200-item Likert answers, and (for a deterministic LLM) identical bootstrap memories. The operator has no indication. If the intent of unique selves relies on unique seeds, that assumption is unprotected.
**Severity:** `low`.

### F27 — Name is not part of identity

**Where:** `specs/self-bootstrap.md` AC-29.20 (reserved); `autonoetic-self.md` §3.1 (notes "no name").
**What goes wrong:** The self's identity is its `self_id` string. Any operator tool that surfaces "this is your self" to a user displays an opaque token. Any future "self picks a name via reflection" mechanism (Q23.3 area) has no schema slot to write into without a migration.
**Severity:** `low`.

### F28 — Cross-tenant memory is deliberate but undocumented in the sketch

**Where:** `specs/self-as-conduit.md` AC-30.22, AC-30.23.
**What goes wrong:** The spec states the self sees all tenants. The implementation currently has no tenant concept at all — the sketch assumes single-global-self. For any reader who skips the spec and reads the sketch, the cross-tenant posture is invisible. A premature port of this code to a multi-tenant context would silently violate tenant isolation.
**Severity:** `medium`. Research-branch only; but carries the "don't port this" load-bearing warning.

---

## F. Implementation gaps against spec

These are places where the merged sketch either diverges from the spec or leaves a load-bearing piece stubbed. They are not bugs in the released design; they are holes a second pass must close before any of Tranche 6 runs in integration.

### F29 — `active_now` caching is specced but not implemented

**Where:** `specs/activation-graph.md` AC-25.10; `self_activation.py` `active_now`.
**What goes wrong:** Spec says `active_now` results cache for 30 seconds, invalidated on contributor writes. The sketch recomputes every call. In `recall_self()` we call `active_now` once per node across every table — at 24 facets + N passions + M hobbies etc., one `recall_self()` is O(nodes × contributors) of table scans.
**Severity:** `low` (correctness unaffected); `medium` (if `recall_self` is called during perception at scale).

### F30 — `source_kind = "memory"` source state is stubbed to 0.5

**Where:** `self_activation.py` `source_state`; spec AC-25.7.
**What goes wrong:** Spec says `memory` contributors resolve to `clamp(memory.weight, 0, 1)`. The sketch returns `0.5` unconditionally because the episodic memory repo is not wired in. Every memory-backed contributor therefore has the same effective source state, regardless of the memory's tier, weight, or reinforcement count.
**Why it matters:** This breaks the design assumption that REGRET (weight ≥ 0.6) memories should contribute more heavily than OBSERVATION (weight < 0.3). A retest-era REGRET and a throwaway OBSERVATION currently push activation by the same amount.
**Severity:** `high`. Directly invalidates the "regrets are structurally unforgettable" property when it crosses into the self-model layer.

### F31 — Completion-reinforcement edge requires the caller to supply a memory id

**Where:** `self_todos.py` `complete_self_todo`, parameter `affirmation_memory_id`; spec AC-26.12, AC-26.14.
**What goes wrong:** The spec says completing a todo mints an AFFIRMATION memory and writes a +0.3 contributor from the motivator to that memory. The sketch takes `affirmation_memory_id` as an optional caller-supplied string and only writes the contributor if the caller provides one. The merged tests exercise both paths but production plumbing (perception → observation → `complete_self_todo`) does not actually mint the AFFIRMATION — it would need wiring from the write-paths layer.
**Severity:** `medium`.

### F32 — `ensure_items_loaded` treats the 200-item bank as per-self, not shared

**Where:** `specs/self-bootstrap.md` AC-29.7 ("skip load, bank is shared across selves"); `self_bootstrap.py` `ensure_items_loaded`; `schema.sql` `self_personality_items UNIQUE (self_id, item_number)`.
**What goes wrong:** The schema and the sketch tag each item with a `self_id` and enforce uniqueness per self. The spec intended a deployment-wide shared bank. Two selves bootstrapping in sequence each get their own 200 rows — wasted storage and a subtle divergence from the spec's "static after seed" claim.
**Severity:** `low`.

### F33 — No `has_own_id` / `self_id_exists` validation on self-tool entry

**Where:** Every `self_*` module's tool functions accept `self_id` as a parameter.
**What goes wrong:** A caller that passes a `self_id` that does not yet have 24 facets, items, and mood populated can still call `note_passion` or `write_self_todo` — these do not check `_bootstrap_complete`. `recall_self` and `render_minimal_block` do, but write-tools do not.
**Why it matters:** A half-bootstrapped self can accrete passions and todos. Resume-style bootstraps after a crash between facet insert and answer generation would see writes to a self that has only the facets but not the answers. Tests cover resume behavior but not "tools before finalize."
**Severity:** `medium`.

### F34 — Clock regression not guarded

**Where:** All tables accept `updated_at` and `created_at` as whatever the caller supplies.
**What goes wrong:** A caller (or a test clock, or a cloned container with skew) can insert rows with past timestamps that land between existing rows. The recency-based sampler (AC-23.12) and last-asked lookup assume timestamps are monotonic. A clock regression produces non-monotonic `asked_at` which the weighted-sample math treats as legitimate.
**Severity:** `low`. Operational.

---
