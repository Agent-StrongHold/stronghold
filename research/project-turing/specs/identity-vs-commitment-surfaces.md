# Spec 95 — Identity-vs-commitment read surfaces

*Two derived, operator-facing read surfaces — `identity.md` and `commitments.md` — regenerated on every WISDOM change or passion rerank. Replaces ad-hoc identity queries with a stable, consistent pair of documents.*

**Depends on:** [wisdom-write-path.md](./wisdom-write-path.md), [journal.md](./journal.md), [self-nodes.md](./self-nodes.md), [self-todos.md](./self-todos.md), [self-bootstrap.md](./self-bootstrap.md).
**Depended on by:** (none yet — external operator UIs may consume these surfaces).

---

## Current state

Operators today query the self's identity by ad-hoc HEXACO reads or by running retrieval against WISDOM memories. There is no canonical "what does this self stand for right now?" document, and nothing consistent across versions (self-bootstrap.md guarantees `self_id` stability but no identity-surface stability). Committments (active AFFIRMATIONs + top todos) similarly require manual aggregation.

## Target

Formalize two read-only, derived documents:
- **`identity.md`** — top-3 HEXACO traits, dominant passions (≥P50 activation over the last 14 days), hobbies. Max 1.5KB.
- **`commitments.md`** — top-5 weight AFFIRMATIONs + top-ranked live todos (post-DAG filter from spec 92). Max 1KB.

Both are **regenerated** (not stored) whenever WISDOM tier changes OR any passion's 14-day rolling rank changes. A short OBSERVATION memory is written each rebuild. Files cleared on self-archive. Surfaces exposed via CLI (`stronghold self identity`, `stronghold self commitments`) and HTTP (`GET /v1/self/{self_id}/identity`, `.../commitments`).

## Acceptance criteria

### Regeneration triggers

- **AC-95.1.** Regenerate both files on any WISDOM insert or update (hooked via wisdom-write-path.md post-commit). Test both triggers fire.
- **AC-95.2.** Regenerate on any change to the passion rank order over the last 14 days. A daily rollup computes rank; if top-K (`IDENTITY_PASSION_TOPK = 5`) differs from the prior day, rebuild. Test with a synthetic rank flip.
- **AC-95.3.** Regeneration debounced at `IDENTITY_REBUILD_DEBOUNCE_SEC = 10` — multiple triggers within the window coalesce into one rebuild. Test rapid-fire triggers yield one rebuild.

### Content generation

- **AC-95.4.** `identity.md` sections (in order): `## Traits` (top-3 HEXACO facets above mean), `## Passions` (top-5 by 14-day mean activation), `## Hobbies` (all with activation > 0.3 over 14 days). Test section presence.
- **AC-95.5.** `commitments.md` sections (in order): `## Affirmations` (top-5 by weight, durable tier), `## Active Commitments` (top-10 live todos from spec 92 ready-set, ordered by motivator activation). Test.
- **AC-95.6.** Both documents are **read-only** — no CLI or HTTP surface accepts PUT/POST/edits. Attempts return 405. Test.

### Size caps

- **AC-95.7.** `identity.md` hard cap `IDENTITY_MAX_BYTES = 1536`. If content exceeds, drop lowest-priority section entries until it fits (Hobbies first, then Passions tail, then Traits tail). Test with a self that would overflow.
- **AC-95.8.** `commitments.md` hard cap `COMMITMENTS_MAX_BYTES = 1024`. Same drop-order: Active Commitments tail first, then Affirmations tail. Test.

### Provenance + diff logging

- **AC-95.9.** Every rebuild writes an OBSERVATION memory `content = "Rebuilt identity.md + commitments.md"` with `context = {identity_hash, commitments_hash, triggers}`. Test OBSERVATION exists post-rebuild.
- **AC-95.10.** Rebuild logs a diff against the previous version: `{added: [lines], removed: [lines]}` to structured logs. Test diff correctness on a known before/after.
- **AC-95.11.** No-op rebuild (content hash unchanged) still writes the OBSERVATION but with `context.noop = True`; no diff logged. Test.

### Self-archive behavior

- **AC-95.12.** On self-archive (self-bootstrap.md), both files are cleared (set to empty-string or deleted per storage convention) and a final OBSERVATION with `content = "Identity and commitment surfaces cleared on archive"` is written. Test archive path.
- **AC-95.13.** Reading an archived self's surfaces returns 410 Gone on HTTP, empty content on CLI. Test.

### Surfaces

- **AC-95.14.** CLI: `stronghold self identity` and `stronghold self commitments` print the current file content to stdout with a trailing newline. Exit 0 on success, 1 on unknown self_id, 2 on archived self. Test.
- **AC-95.15.** HTTP: `GET /v1/self/{self_id}/identity` returns `text/markdown` with `ETag = identity_hash` and `Cache-Control: no-store`. Test headers and status.
- **AC-95.16.** Both surfaces are unauthenticated by default but gate-able via operator policy (operator-review-gate.md). Test default and gated paths.

## Implementation

```python
# surfaces/identity.py

IDENTITY_MAX_BYTES: int = 1536
COMMITMENTS_MAX_BYTES: int = 1024
IDENTITY_PASSION_TOPK: int = 5
IDENTITY_REBUILD_DEBOUNCE_SEC: int = 10


@dataclass(frozen=True)
class IdentitySurface:
    identity_md: str
    commitments_md: str
    identity_hash: str
    commitments_hash: str
    built_at: datetime


def build(repo, self_id: str, now: datetime) -> IdentitySurface:
    traits = repo.hexaco_top(self_id, k=3)
    passions = repo.passion_rank_14d(self_id, k=IDENTITY_PASSION_TOPK)
    hobbies = repo.hobby_activation_14d(self_id, floor=0.3)
    affs = repo.top_affirmations(self_id, k=5, durable_only=True)
    todos = repo.ready_todos(self_id, limit=10)  # from spec 92
    identity = _render_identity(traits, passions, hobbies, cap=IDENTITY_MAX_BYTES)
    commitments = _render_commitments(affs, todos, cap=COMMITMENTS_MAX_BYTES)
    return IdentitySurface(
        identity_md=identity, commitments_md=commitments,
        identity_hash=_hash(identity), commitments_hash=_hash(commitments),
        built_at=now,
    )


def on_trigger(repo, self_id: str, trigger: str, now: datetime) -> None:
    _debounce(self_id, trigger, window=IDENTITY_REBUILD_DEBOUNCE_SEC)
    if _within_debounce(self_id, now):
        return
    current = build(repo, self_id, now)
    prior = repo.last_identity_surface(self_id)
    is_noop = prior and prior.identity_hash == current.identity_hash and \
              prior.commitments_hash == current.commitments_hash
    repo.store_surface(self_id, current)
    repo.write_observation(self_id, content="Rebuilt identity.md + commitments.md",
                           context={"identity_hash": current.identity_hash,
                                    "commitments_hash": current.commitments_hash,
                                    "triggers": [trigger], "noop": is_noop})
    if not is_noop:
        _log_diff(prior, current)
```

## Open questions

- **Q95.1.** Should the surfaces include the raw HEXACO score vector, or just named top-3 traits? Leaning named-only to avoid leaking score noise to operators.
- **Q95.2.** Caching: the files are derived, but serving them through HTTP at scale might want a short TTL cache. Defer to deployment spec.
- **Q95.3.** Are these surfaces subject to memory-mirroring? No — they're derived documents, not memories. The OBSERVATION write is the audit trail.
- **Q95.4.** Should the identity surface include REGRETs summary ("what I'm working on")? Out of scope for v1 — belongs in a future `aspiration.md` surface.
