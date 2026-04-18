# Spec 11 — Tuning: runtime coefficient adjustment via durable memory

*Every coefficient in the motivation system — priority bases, pressure normalization, fit-weighted bonuses, band widths — is runtime-tuned rather than a priori chosen. The tuner observes dispatch outcomes, consults the durable memory's record of REGRETs and ACCOMPLISHMENTs, and proposes coefficient adjustments committed as AFFIRMATIONs.*

**Depends on:** [schema.md](./schema.md), [motivation.md](./motivation.md), [write-paths.md](./write-paths.md).
**Depended on by:** —

---

## Current state

- `main` has no runtime-tuning layer for dispatch coefficients.
- Coefficient values for priority, pressure, fit are not even separated in `main` — there are no dispatch coefficients because there is no dispatcher.

## Target

A `CoefficientTable` object holds every tunable value used by the motivation component. The current table is constructed by applying, in order, every non-superseded AFFIRMATION of tier `coefficient_commitment` to a baseline seed table. A tuner process runs as a P11–P20 RASO candidate on the motivation backlog; when the dispatcher picks it up, it reads recent durable-memory observations and proposes a new AFFIRMATION if observations warrant.

## Acceptance criteria

### Coefficient representation

- **AC-11.1.** `CoefficientTable` exposes every tunable value as a named field with a documented range and seed value. Test asserts field set is complete (no unexposed numeric constants used by motivation).
- **AC-11.2.** Loading the current `CoefficientTable` at startup applies the baseline seed and then applies every non-superseded `coefficient_commitment` AFFIRMATION in order of creation. Integration test over a fixture of AFFIRMATIONs.
- **AC-11.3.** A `CoefficientTable` value outside its documented range causes the AFFIRMATION that produced it to be rejected at load time with an error; the table falls back to the last valid state. Test asserts out-of-range protection.

### Observation feed

- **AC-11.4.** Every dispatch writes an observation record with: `dispatched_item_id`, `class_`, `chosen_model`, `score`, `pressure_vec`, `fit_vec`, `timestamp`, and a placeholder `outcome` field (filled in later when outcome becomes known). Test asserts the record schema and write path.
- **AC-11.5.** Outcome resolution — when the item's work completes or is preempted, the observation's `outcome` field is updated with `completed | preempted | failed | expired`, plus optional affect and surprise deltas. Test asserts outcome propagation.
- **AC-11.6.** Observation writes do NOT go through the durable tier. They live in a separate `dispatch_observation` store (append-only, auto-pruned after `OBSERVATION_RETENTION` default 30 days). Test asserts routing.

### Tuner behavior

- **AC-11.7.** The tuner is a producer that submits a `tuning_candidate` BacklogItem at class P15 periodically (default every `TUNER_CADENCE_MINUTES = 60`). Test asserts periodic submission.
- **AC-11.8.** When dispatched, the tuner reads up to `TUNER_OBSERVATION_WINDOW` (default 10,000) recent dispatch observations and the durable-memory REGRETs and ACCOMPLISHMENTs from the same window. Test.
- **AC-11.9.** The tuner proposes a coefficient adjustment when a statistically significant pattern warrants it (see implementation). Under-threshold patterns produce no proposal — silent, not a no-op write. Test asserts no proposal when observations are ambiguous.
- **AC-11.10.** A proposed adjustment is committed as an AFFIRMATION with `tier = AFFIRMATION`, `source = I_DID`, `content` containing the coefficient name, old value, new value, and supporting evidence summary. Test asserts the commitment schema.
- **AC-11.11.** A new AFFIRMATION that supersedes a prior coefficient commitment sets `supersedes` on the new row and `superseded_by` on the old. The old commitment remains readable. Test asserts the lineage chain.
- **AC-11.12.** An AFFIRMATION out of the tuner is revocable (per [write-paths.md §4.3](./write-paths.md)), consistent with AFFIRMATION's durable-but-revocable contract.

### Convergence guarantees (none)

- **AC-11.13.** The tuner does not claim convergence to an optimum. It claims: "given this observation window, this adjustment is directionally better than the current value by the chosen signal." Tests are about proposal correctness given observation fixtures, not about global optimality.

## Implementation

### 11.1 CoefficientTable

```python
@dataclass
class CoefficientTable:
    # --- Priority bases (seeded from motivation.md PRIORITY_ANCHORS) ---
    priority_anchor_overrides: dict[int, float] = field(default_factory=dict)

    # --- Pressure calibration ---
    pressure_max: float = 5_000.0                   # seed
    pressure_rate_coefficient: float = 1.0          # seed

    # --- Dispatch knobs ---
    action_cadence_ticks: int = 10
    top_x: int = 5
    max_concurrent_dispatches: int = 4
    daydream_fire_floor: float = 10.0

    # --- Scheduler knobs ---
    default_prepare_window_s: int = 600
    daydream_quiet_multiple: int = 5

    # --- Daydreaming knobs ---
    daydream_tokens_per_pass: int = 2_000
    daydream_writes_per_pass: int = 5
    daydream_micro_pass_max_ms: int = 500
    accomplishment_bias: float = 0.5

    # --- Write-path thresholds ---
    regret_surprise_threshold: float = 0.4
    regret_affect_threshold: float = 0.3
    accomplishment_surprise_threshold: float = 0.3
    accomplishment_affect_threshold: float = 0.3

    # --- Tuner knobs ---
    tuner_cadence_minutes: int = 60
    tuner_observation_window: int = 10_000
    observation_retention_days: int = 30

    @classmethod
    def from_affirmations(cls, seeds: "CoefficientTable", commitments: list[EpisodicMemory]) -> "CoefficientTable":
        """Apply coefficient_commitment AFFIRMATIONs in creation order."""
        table = replace(seeds)
        for affirmation in sorted(commitments, key=lambda m: m.created_at):
            if affirmation.superseded_by is not None:
                continue
            update = parse_coefficient_commitment(affirmation.content)
            table = apply_update(table, update)
        return table
```

### 11.2 Observation schema

A new memory kind, distinct from `EpisodicMemory` because it has a short retention horizon and is not autonoetic:

```python
@dataclass(frozen=True)
class DispatchObservation:
    observation_id: str
    self_id: str
    dispatched_item_id: str
    item_class: int
    item_kind: str
    chosen_model: str
    score: float
    pressure_vec_snapshot: dict[str, float]
    fit_vec_snapshot: dict[str, float]
    decided_at: datetime
    outcome: str = "pending"              # pending | completed | preempted | failed | expired
    outcome_resolved_at: datetime | None = None
    outcome_affect: float | None = None
    outcome_surprise_delta: float | None = None
    outcome_notes: str = ""
```

Stored in `dispatch_observation` table (separate from durable memory), auto-pruned at `observation_retention_days`.

### 11.3 Tuner

```python
class CoefficientTuner:
    """A P15 RASO producer that proposes coefficient AFFIRMATIONs."""

    def on_tick(self, motivation: Motivation) -> None:
        if self._cadence_elapsed():
            motivation.insert(self._build_candidate())

    def _build_candidate(self) -> BacklogItem:
        return BacklogItem(
            item_id=new_item_id(),
            class_=15,
            kind="tuning_candidate",
            payload=TuningPayload(self_id=self.self_id),
            fit=self._tuner_fit(),
            readiness=readiness_raso,
            cost_estimate_tokens=5_000,
        )

    # --- On dispatch ---
    def execute(self) -> list[CoefficientUpdate]:
        observations = self._load_recent_observations(TUNER_OBSERVATION_WINDOW)
        memory = self._load_recent_durable(observations_window_equivalent)
        proposals = []
        proposals.extend(self._analyze_deadline_hits(observations, memory))
        proposals.extend(self._analyze_pool_utilization(observations))
        proposals.extend(self._analyze_cross_band_outcomes(observations, memory))
        proposals.extend(self._analyze_daydream_fire_rate(observations, memory))
        return [p for p in proposals if p.is_significant()]

    def commit(self, proposal: CoefficientUpdate) -> None:
        """Write an AFFIRMATION superseding any prior commitment on the same coefficient."""
        prior = self._find_prior_commitment(proposal.coefficient_name)
        affirmation = build_affirmation_memory(
            self_id=self.self_id,
            content=proposal.to_content_string(),
            supersedes=prior.memory_id if prior else None,
        )
        self._repo.insert(affirmation)
        if prior is not None:
            self._repo.set_superseded_by(prior.memory_id, affirmation.memory_id)
```

### 11.4 Signals the tuner uses

Not exhaustive; a seed set. Each signal maps to specific coefficients.

- **Deadline hit rate on P0.** Repeated misses → raise `priority_anchor_overrides[0]`, widen the P0 band, raise `default_prepare_window_s`.
- **Pool utilization at reset.** A pool consistently leaving headroom unused → raise `pressure_rate_coefficient` for that pool's class. Consistently hitting zero headroom with rejected work → lower it.
- **Cross-band reordering outcomes.** If cross-band reorderings preceded REGRETs more often than ACCOMPLISHMENTs, raise `pressure_max` cap (make cross-band reordering harder). Opposite → lower it.
- **Daydream fire rate.** Too many daydream fires without resulting I_IMAGINED-that-later-matches-real-event → raise `daydream_fire_floor`. Too few fires with consistent free-tier waste → lower it.

### 11.5 Significance test

A proposal is significant when:

- The signal's sample size exceeds `MIN_OBSERVATIONS_FOR_PROPOSAL` (default 50).
- The effect's magnitude in the signal's own units exceeds `MIN_EFFECT` (default 2 standard deviations from baseline, or a coefficient-specific threshold).
- The proposed new value is inside the coefficient's documented range.

Under-threshold → no AFFIRMATION minted. Silence is the default; the Conduit commits only when evidence is clear.

## Open questions

- **Q11.1.** **Coefficients as AFFIRMATIONs vs. dedicated `Coefficient` durable type.** Current spec uses AFFIRMATION for simplicity and lineage. Downside: AFFIRMATION gets loaded with operational state that isn't really "commitment to a value" in the autonoetic sense. Alternative: a dedicated `Coefficient` durable type with its own tier, parallel to AFFIRMATION but semantically distinct. Deferred as-is; worth revisiting once the tuner runs against real data.
- **Q11.2.** Signals in 11.4 are heuristic. A principled version would treat this as an online optimization problem (bandit, gradient-free optimizer). For the research push, heuristic signals are enough to produce durable records; the signal selection itself is future research.
- **Q11.3.** The tuner is P15 but has no way to express "I am more urgent this hour because observations are piling up." Dynamic priority on tuning candidates based on the size of the observation-to-commitment gap? Or is the fixed P15 fine? Leaving fixed for now.
- **Q11.4.** `OBSERVATION_RETENTION = 30 days` is a guess. The tuner's observation window (`TUNER_OBSERVATION_WINDOW = 10,000 events`) may hit memory pressure before 30 days under high load, or be sparse after 30 days under low load. Retention might need to be event-count-based rather than time-based.
- **Q11.5.** A failed or out-of-range AFFIRMATION (AC-11.3) falls back to the last valid state. But the failed AFFIRMATION sits in the durable store as a ghost. Does it need a `validity_status` field, or is "rejected at load" enough?
