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
