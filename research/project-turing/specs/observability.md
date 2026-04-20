# Spec 21 — Observability: metrics, inspect CLI, smoke

*Three operator-facing windows into the running system. Prometheus metrics for live monitoring, inspect CLI for ad-hoc queries, smoke mode for deploy-readiness gates.*

**Depends on:** all other runtime specs.
**Depended on by:** —

---

## Current state

`runtime/metrics.py` (Prometheus HTTP endpoint), `runtime/inspect.py` (CLI subcommands), `runtime/smoke.py` (acceptance check). 13 tests; metrics has no docs, inspect has no formal contract, smoke threshold is in code only. No spec.

## Target

A versioned, stable-named set of Prometheus metrics; an inspect CLI with a documented set of read-only subcommands; a smoke mode whose pass/fail criteria are explicit.

## Acceptance criteria

### Prometheus metrics endpoint

- **AC-21.1.** `GET /metrics` returns Prometheus text exposition format (Content-Type: `text/plain; version=0.0.4`). Test asserts headers + body parses as valid Prometheus.
- **AC-21.2.** `GET /<anything-else>` returns 404. Test.
- **AC-21.3.** The endpoint binds on `metrics_bind` (default `127.0.0.1`, container default `0.0.0.0`), port `metrics_port`. Test asserts bind address.

### Metric set (v1 contract — name changes bump suffix)

- **AC-21.4.** `turing_tick_count` (counter) — monotonic tick counter from RealReactor. Test.
- **AC-21.5.** `turing_drift_ms_p99` (gauge) — p99 of recent per-tick drift. Test.
- **AC-21.6.** `turing_pressure{pool="<name>"}` (gauge) — per-pool pressure scalar feeding motivation. Test asserts one label per registered pool.
- **AC-21.7.** `turing_quota_headroom{pool="<name>"}` (gauge) — tokens remaining in the current free-tier window per pool. Test.
- **AC-21.8.** `turing_durable_memories_total{tier="<regret|accomplishment|affirmation|wisdom>"}` (gauge) — row count in `durable_memory` per tier. Refreshed every 10 ticks (cheap). Test.
- **AC-21.9.** `turing_dispatch_total{kind="<item.kind>", pool="<chosen_pool>"}` (counter) — dispatch count by item kind × chosen pool. Incremented at dispatch time. Test.
- **AC-21.10.** Metric names ARE a stable contract within v1. Renames bump the metric set version (suffix) and require dashboard updates. Documented.

### Inspect CLI

- **AC-21.11.** `python -m turing.runtime.inspect --db <path> <subcommand>` is the entry shape. Test asserts argparse contract.
- **AC-21.12.** `summarize` — counts by tier × source for `episodic_memory` and `durable_memory`; current `self_id`; recent REGRETs / ACCOMPLISHMENTs; recent coefficient AFFIRMATIONs. Test asserts the major sections appear.
- **AC-21.13.** `dispatch-log [--limit N]` — recent OBSERVATION/I_DID markers (includes daydream session markers, dream session markers, migration markers, RSS summaries). Test.
- **AC-21.14.** `daydream-sessions [--limit N]` — recent daydream session markers each followed by the I_IMAGINED outputs they produced (linked via `origin_episode_id`). Test.
- **AC-21.15.** `lineage <memory_id>` — walks both directions (`supersedes` backward, `superseded_by` forward); returns nonzero exit code if the memory_id is unknown. Test asserts both happy and unknown paths.
- **AC-21.16.** `pressure --metrics-url <url>` — scrapes the running metrics endpoint and prints `turing_pressure{pool=...}` lines only. Test with a fake metrics server.
- **AC-21.17.** `working-memory` — prints current self-managed working-memory entries with priority and timestamps. Read-only. No `--clear` or `--set` subcommand exists. Test asserts the absence of mutating flags.
- **AC-21.18.** `--json` flag on any subcommand emits machine-parseable JSON instead of plain text. Test on `summarize`.
- **AC-21.19.** Every subcommand exits 0 on success, 1 on operational failure (DB missing, network unreachable for `pressure`, etc.). Test.

### Smoke mode

- **AC-21.20.** `python -m turing.runtime.main --smoke-test` runs a fixed-duration check with the FakeProvider against a temp SQLite + temp journal + temp Obsidian vault, then verifies a checklist and exits 0/1. Test.
- **AC-21.21.** Smoke success criteria (any failure → exit 1):
  - Runtime exited cleanly (rc=0).
  - `journal/narrative.md` exists.
  - `journal/identity.md` exists.
  - At least one Obsidian note file was written (under the temp vault).
  - `durable_memory` has ≥ 1 row at end.
  - `/metrics` endpoint responded with `turing_tick_count`.
- **AC-21.22.** Smoke prints success/failure to stdout in human-readable form. Failure prints a bulleted list of which checks failed. Test asserts both outputs.
- **AC-21.23.** Smoke uses a free port for the metrics endpoint to avoid collisions in CI.

## Implementation

### 21.1 MetricsCollector

Mutable, thread-safe store. `update(name=value)` for scalars; `set_labeled(name, labels, value)` for labeled; `inc_labeled(name, labels)` for counters. `render()` produces Prometheus text.

The runtime registers a per-tick handler that refreshes the collector from authoritative sources (reactor status, quota tracker, repo counts).

### 21.2 Inspect CLI subcommand registration

```python
parser = argparse.ArgumentParser(prog="turing-inspect")
parser.add_argument("--db", required=True)
parser.add_argument("--json", action="store_true")
sub = parser.add_subparsers(dest="command", required=True)
sub.add_parser("summarize").set_defaults(func=cmd_summarize)
sub.add_parser("dispatch-log").set_defaults(func=cmd_dispatch_log)
# ...
```

### 21.3 Smoke check loop

```python
def run_smoke():
    failures = []
    with tempfile.TemporaryDirectory() as tmp:
        # Probe metrics from a side thread.
        # Run the runtime for SMOKE_DURATION_SECONDS.
        # Verify each criterion, append to failures.
    if failures:
        print("smoke FAILED:", failures)
        return 1
    print("smoke OK: ...")
    return 0
```

### 21.4 Configuration constants

```python
SMOKE_DURATION_SECONDS:  int = 12
SMOKE_TICK_RATE:         int = 100
METRICS_REFRESH_TICKS:   int = 10        # how often to re-pull DB counts
```

## Open questions

- **Q21.1.** Histograms / distributions: the v1 metric set is gauges + counters only. No histograms (drift_p99 is a single gauge, not a full histogram). Operators with Prometheus skill can compute distributions from raw scrapes; if histograms become important, they bump the metric set version.
- **Q21.2.** Inspect over a remote DB: the CLI assumes local SQLite. K8s users `kubectl exec` into the pod or copy the DB out. Documented; no remote inspect protocol planned.
- **Q21.3.** Smoke criteria are checklist-style. A future tightened smoke could check WISDOM count, contradiction-detector latency, etc. Easy to extend; left minimal for now.
- **Q21.4.** Metric cardinality: `turing_dispatch_total{kind, pool}` could explode if `kind` proliferates (one new kind per detector). Currently bounded; revisit if cardinality becomes a problem.
