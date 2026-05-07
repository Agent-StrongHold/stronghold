# Detectors

*Producers that watch state and propose candidates for the motivation backlog. Each detector is small, single-purpose, and runs as part of the per-tick event loop. They do not execute work themselves; they just propose.*

**Parent specs:** [`../motivation.md`](../motivation.md), [`../schema.md`](../schema.md), [`../durability-invariants.md`](../durability-invariants.md).

---

## The pattern

A detector is a cheap observer with a narrow job:

1. Per tick, inspect a slice of state (durable memory, tool-call traces, recent outcomes, config).
2. If a specific condition holds, build a `BacklogItem` describing the proactive work that should happen.
3. Submit it to the motivation backlog at the appropriate class (typically P11–P20 for RASO-class work).
4. Do not execute. Do not dispatch. Do not touch models.

When the motivation dispatcher later picks the candidate, a separate execution path does the actual work. The detector has already moved on.

## Contract

```python
class Detector(Protocol):
    name: str

    def on_tick(self, state: PipelineState, motivation: Motivation) -> None:
        """Called per tick. Insert 0 or more candidates into motivation."""
        ...
```

Constraints:

- `on_tick` is subject to the Reactor's 1 ms blocking-gate contract. Expensive scanning must be deferred to the dispatched execution step, not done in the detector itself.
- A detector must be idempotent about candidate submission: if it would propose the same candidate twice (same `item_id` semantics), it must not re-insert. Duplicates bloat the backlog.
- Detectors are stateless relative to prior ticks unless they cache cheap summaries. Any meaningful state goes to durable memory.
- A detector cannot write durable memory directly. All its outputs are candidates for the motivation backlog; durable writes happen (if ever) during the candidate's dispatched execution.

## Candidate-submission template

```python
def build_candidate(detector_name: str, class_: int, payload: Any, fit: dict[str, float]) -> BacklogItem:
    return BacklogItem(
        item_id=new_item_id(),
        class_=class_,
        kind=f"raso_{detector_name}",
        payload=payload,
        fit=fit,
        readiness=readiness_raso,
        cost_estimate_tokens=payload.estimated_cost,
    )
```

## Planned detectors

Only one is specced in this tranche. Others are listed as intended future detectors; their specs will land alongside their implementations.

| Detector | Class | What it detects | Status |
|---|---|---|---|
| [`contradiction.md`](./contradiction.md) | P14 | Two durable memories whose content points at each other as contradictory and whose resolution is available from subsequent outcomes. | Specced (this tranche) |
| `learning_extraction.md` | P12 | Recent tool-call traces showing a fail→succeed correction pattern. | Planned |
| `affirmation_candidacy.md` | P13 | A pattern of repeated ACCOMPLISHMENTs that warrants a forward commitment. | Planned |
| `prospection.md` | P16 | A request class that recurs often enough that pre-simulating a stance is worth it. | Planned |
| `coefficient_tuner.md` | P15 | The runtime-tuning job (see [`../tuning.md`](../tuning.md)). Currently specced inside `tuning.md`; may migrate here. | Specced |

Classes are seed values, tunable per the normal coefficient-tuning path.

## Why detectors are cheap

Detectors do not perform the proactive work; they only propose it. This keeps the per-tick event loop inside its budget and gives the motivation component a single place to weigh every candidate together. If a detector's scanning logic would be expensive, it must either:

- Run its expensive scan *inside* the dispatched execution of a prior candidate (using the detected state as the proposal payload, not the scan logic itself), or
- Maintain a cheap incremental index that is updated on each new durable memory write.

## Open questions

- **Q-D.1.** Detector registration: static list at startup vs dynamic registration via operator command? Leaning static for research; dynamic is a main-port concern.
- **Q-D.2.** A detector misfiring (submitting many low-quality candidates) pollutes the backlog and costs dispatcher CPU. Detectors probably need a per-detector budget (candidates per hour) with the overflow dropped. Add to `CoefficientTable`?
- **Q-D.3.** A detector proposing the same candidate repeatedly due to persistent condition (contradiction exists until resolved): the dedup must be content-hash based, not just `item_id`-based. Naming explicitly so implementations get this right.
