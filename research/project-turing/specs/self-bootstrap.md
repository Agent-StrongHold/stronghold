# Spec 29 — Self-bootstrap

*The one-shot procedure that mints a self: random HEXACO profile, 200 Likert answers with justifications, 24 facet rows, neutral mood, everything else empty. Idempotent per `self_id`. Ships as `stronghold bootstrap-self`.*

**Depends on:** [self-schema.md](./self-schema.md), [personality.md](./personality.md), [self-nodes.md](./self-nodes.md), [mood.md](./mood.md), [persistence.md](./persistence.md).
**Depended on by:** [self-surface.md](./self-surface.md), [self-as-conduit.md](./self-as-conduit.md).

---

## Current state

- `self_id` minting (spec 8) exists but is not populated with a self-model. A bootstrap self has an `agent_id` and nothing else.

## Target

A CLI-triggered procedure that takes a fresh `self_id` to a state where `recall_self()` succeeds: the 24 HEXACO facets populated, the 200-item HEXACO bank loaded (once per deployment, shared across selves), 200 answer rows minted, mood neutral, all other node kinds empty. Running bootstrap twice for the same `self_id` raises.

## Acceptance criteria

### Invocation

- **AC-29.1.** `stronghold bootstrap-self --self-id <ID>` is registered as a CLI entry point. `--self-id` is required. An absent value raises with a clear usage message. Test via invoking the CLI under a subprocess-harness or its `main()` function directly.
- **AC-29.2.** Optional flags:
  - `--seed <INT>`: RNG seed for deterministic HEXACO draw (default: random).
  - `--llm-model <NAME>`: override the LLM pool used for the 200 Likert answer generations (default: cheapest available).
  - `--dry-run`: run the full procedure without writing. Report what would be written.
  - `--resume`: continue a partially-bootstrapped self from its last checkpoint (see AC-29.12).

  Test each flag's effect.
- **AC-29.3.** The CLI exits with code 0 on success, 1 on validation failure (already bootstrapped, invalid self_id shape), 2 on runtime failure (LLM error, DB error). Test each exit code.

### Pre-flight validation

- **AC-29.4.** Before any writes, the bootstrap checks: `self_id` exists in the identity table (spec 8); `self_id` has zero rows in `self_personality_facets`; zero rows in `self_personality_answers`; no `self_mood` row. Any pre-existing state raises `AlreadyBootstrapped`. Test.
- **AC-29.5.** Pre-flight checks are bundled into a single read transaction. Test.

### HEXACO-200 bank load (once per deployment)

- **AC-29.6.** If `self_personality_items` has zero rows at bootstrap start, the bank is loaded from `research/project-turing/config/hexaco_200.yaml`. If the file is absent, raise `HexacoBankMissing`. If the file loads 199 or 201 rows, raise `HexacoBankInvalid`. Test.
- **AC-29.7.** If the bank already has 200 rows, skip load (bank is shared across selves). Test.
- **AC-29.8.** The bank YAML schema is a list of `{item_number, prompt_text, keyed_facet, reverse_scored}`. Unknown keys raise at parse time. Test against a malformed fixture.

### Facet draw

- **AC-29.9.** Draw 24 facet scores per `draw_bootstrap_profile` (spec 23 §23.2). Write 24 `PersonalityFacet` rows in a single transaction. Abort if any constraint fails (e.g., duplicate `(trait, facet_id)`). Test for atomicity: a rigged failure on the 20th row leaves zero facet rows.
- **AC-29.10.** When `--seed` is provided, the 24 scores are reproducible across runs. Test asserts identical output for identical seeds.

### 200-item Likert generation

- **AC-29.11.** For each of 200 items, invoke the configured LLM with a prompt that includes the full 24-facet profile and the item's `prompt_text`. Require the LLM to return `{"answer": int in {1..5}, "justification": str of length ≤ 200}`. Retry up to 3 times per item on parse or range failure. On 4th failure, abort the whole bootstrap. Test with a flaky fake LLM.
- **AC-29.12.** After each successful item answer, write the `PersonalityAnswer` row AND the mirrored OBSERVATION memory, AND record a `bootstrap_progress` row keyed to `self_id` with the last completed item number. Test asserts the progress row updates monotonically.
- **AC-29.13.** On `--resume`, the bootstrap reads `bootstrap_progress` and continues from the next uncompleted item. Tests: a run aborted at item 87, then resumed, produces 200 total answers. Test with simulated mid-run crash.
- **AC-29.14.** The 200 answers are NOT generated in parallel by default — they are serial to respect LLM rate limits on a single pool. A `--concurrency <N>` flag allows up to N=4 parallel answer calls. Test serial mode and N=4 mode produce identical answer counts.

### Finalization

- **AC-29.15.** After all 200 answers are persisted, insert the singleton `self_mood` row at `(valence=0.0, arousal=0.3, focus=0.5, last_tick_at=now())`. Test.
- **AC-29.16.** Register the weekly retest Reactor trigger with `first_fire_at = now() + timedelta(days=7)`. Test by inspecting the Reactor's trigger list.
- **AC-29.17.** Write a LESSON-tier episodic memory marking the completion: `content = "I was bootstrapped on {date} with seed {seed}. I have no passions, hobbies, skills, or preferences yet."`, `source = I_DID`, `intent_at_time = "self bootstrap complete"`. Test.
- **AC-29.18.** Delete the `bootstrap_progress` row for this `self_id`. Test.
- **AC-29.19.** A final verification pass asserts: exactly 24 facet rows; exactly 200 answer rows; exactly 1 mood row; zero passion/hobby/interest/preference/skill rows; zero todo rows; trigger registered. If any assertion fails, log an error but do NOT roll back (the partial state is more useful for forensics than a clean slate). Test the verification pass in both success and induced-failure modes.

### Name and operator overrides

- **AC-29.20.** The self has no name post-bootstrap. `recall_self()` returns `self_id` as the identity string. The operator can later set a name via `stronghold self name <NAME>` (out of scope for this spec; reserved).
- **AC-29.21.** An operator can supply per-facet mean overrides via `--facet-bias <trait.facet>=<mean>` flags. Each override replaces the default `μ=3.0` with the given mean for the truncated-normal draw. Test.

### Edge cases

- **AC-29.22.** A bootstrap interrupted by SIGTERM between items 87 and 88: `bootstrap_progress` is at 87; on resume, item 88 is the next call. Test by sending SIGTERM to a subprocess mid-run.
- **AC-29.23.** A bootstrap where the LLM returns answers that are all 3 (indifferent) still completes — no semantic check on answer distribution at bootstrap time. The tuning detector will flag the pattern post-hoc. Test.
- **AC-29.24.** A bootstrap where the LLM returns a malformed JSON on the 200th item retries three times then aborts. The 199 successful answers are preserved. On resume, only item 200 is re-asked. Test.
- **AC-29.25.** Concurrent `stronghold bootstrap-self --self-id X` invocations: the second acquires the advisory lock on `self:X:bootstrap` and blocks. If the first completes successfully, the second sees `AlreadyBootstrapped` and exits 1. If the first fails mid-way, the second acquires the lock and continues as `--resume`. Test with two subprocesses.
- **AC-29.26.** `--dry-run` performs facet draw and one LLM-answer-generation as a canary (to validate connectivity), then reports and exits. No DB writes occur. Test.

## Implementation

### 29.1 CLI shape

```python
# stronghold/cli/bootstrap_self.py
@click.command()
@click.option("--self-id", required=True, type=str)
@click.option("--seed", type=int, default=None)
@click.option("--llm-model", type=str, default=None)
@click.option("--dry-run", is_flag=True, default=False)
@click.option("--resume", is_flag=True, default=False)
@click.option("--concurrency", type=int, default=1)
@click.option("--facet-bias", multiple=True,
              help="e.g. openness.inquisitiveness=4.0")
def bootstrap_self(self_id, seed, llm_model, dry_run, resume, concurrency, facet_bias):
    overrides = _parse_biases(facet_bias)
    try:
        run_bootstrap(
            self_id=self_id, seed=seed, llm_model=llm_model,
            dry_run=dry_run, resume=resume,
            concurrency=concurrency, facet_biases=overrides,
        )
    except AlreadyBootstrapped as e:
        click.echo(f"already bootstrapped: {e}", err=True)
        sys.exit(1)
    except BootstrapValidationError as e:
        click.echo(f"validation failure: {e}", err=True)
        sys.exit(1)
    except BootstrapRuntimeError as e:
        click.echo(f"runtime failure: {e}", err=True)
        sys.exit(2)
```

### 29.2 Top-level flow

```python
def run_bootstrap(*, self_id, seed, llm_model, dry_run, resume,
                  concurrency, facet_biases):
    with repo.advisory_lock(f"self:{self_id}:bootstrap"):
        if not resume:
            _preflight_validate(self_id)

        _ensure_bank_loaded()

        if dry_run:
            _dry_run_canary(self_id, seed, llm_model, facet_biases)
            return

        if resume:
            progress = repo.get_bootstrap_progress(self_id)
            if progress is None:
                raise BootstrapValidationError("nothing to resume")
        else:
            progress = repo.start_bootstrap_progress(self_id, seed=seed)
            _draw_and_persist_facets(self_id, seed, facet_biases)

        _generate_likert_answers(
            self_id=self_id,
            progress=progress,
            llm_model=llm_model,
            concurrency=concurrency,
        )

        _finalize(self_id, seed=seed)
```

### 29.3 Resume resilience

Each successful item write is one atomic `BEGIN; INSERT answer; INSERT memory; UPDATE progress; COMMIT;` transaction. Crash between items → at most one item's worth of partial work, and the progress row guarantees `--resume` picks up exactly where the crash occurred.

### 29.4 Finalize

```python
def _finalize(self_id, seed):
    now = datetime.now(UTC)
    repo.insert_mood(Mood(
        self_id=self_id,
        valence=0.0, arousal=0.3, focus=0.5,
        last_tick_at=now,
    ))
    reactor.register_interval_trigger(
        name=f"retest:{self_id}",
        interval=timedelta(days=7),
        first_fire_at=now + timedelta(days=7),
        handler=lambda: run_personality_retest(self_id, now=datetime.now(UTC)),
    )
    memories.write_lesson(
        self_id=self_id,
        content=(
            f"I was bootstrapped on {now.date().isoformat()} with seed {seed}. "
            "I have no passions, hobbies, skills, or preferences yet."
        ),
        source=SourceKind.I_DID,
        intent_at_time="self bootstrap complete",
    )
    repo.delete_bootstrap_progress(self_id)
    _verify_final_state(self_id)
```

### 29.5 Verify

```python
def _verify_final_state(self_id):
    problems = []
    if repo.count_facets(self_id) != 24:
        problems.append("facet count")
    if repo.count_answers(self_id) != 200:
        problems.append("answer count")
    if not repo.has_mood(self_id):
        problems.append("missing mood")
    for kind in ("passion", "hobby", "interest", "preference", "skill", "todo"):
        if repo.count(kind, self_id) != 0:
            problems.append(f"non-empty {kind}")
    if not reactor.has_trigger(f"retest:{self_id}"):
        problems.append("retest trigger not registered")
    if problems:
        log.error("bootstrap final-state problems: %s", problems)
```

Logs the problems but does not roll back. Operator decides whether to reset via a separate `stronghold self reset` (not specced here).

## Open questions

- **Q29.1.** HEXACO-200 bank file path is hardcoded to `research/project-turing/config/hexaco_200.yaml`. An alternative is a `--bank-file` flag. Keeping hardcoded for the research branch.
- **Q29.2.** Licensing of the HEXACO-200 item text. The HEXACO-PI-R is available for non-commercial research use under the author's license (Lee & Ashton). The research branch treats this as acceptable for its research status; commercial deployments would need to address licensing separately.
- **Q29.3.** `--concurrency > 1` violates "serial by default for rate limits." The cap at 4 is a seed; actual safe parallelism depends on the LLM pool's RPM.
- **Q29.4.** `_dry_run_canary` makes one real LLM call. An alternative is to skip the LLM call entirely and only validate the schema / connectivity. The canary call catches prompt/format issues the schema alone doesn't.
- **Q29.5.** No operator review gate after bootstrap. The self enters service immediately with a random personality. A `--approval-required` flag that pauses after the LESSON memory is written and waits for an operator ACK would be a mild safety valve. Deferred.
