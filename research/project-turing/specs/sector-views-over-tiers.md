# Spec 99 — Sector views over tiers

*Five retrieval sectors — emotional, procedural, reflective, semantic, episodic — defined as pure query views over the existing 8-tier memory schema. No new tables, no migration, orthogonal composition.*

**Depends on:** [retrieval.md](./retrieval.md), [schema.md](./schema.md), [semantic-retrieval.md](./semantic-retrieval.md).

---

## Current state

Retrieval (spec 16) filters primarily by tier and semantic similarity. OpenMemory's 5-sector model (emotional / procedural / reflective / semantic / episodic) offers a useful orthogonal axis — "show me what I've emotionally processed about X" — but tiers alone can't express it. REGRET + AFFIRMATION + high-|affect| OBSERVATIONs together form the emotional sector; we don't expose that as a first-class query.

## Target

Add a `sector` parameter to `retrieve(...)` that filters rows by a **pure predicate** over existing columns (tier, source, affect, origin, stance_owner). No new tables, no migration. Sectors are orthogonal — a memory can match multiple — and composable with existing filters (since, limit, user scope). Invalid sector raises; `sector=None` is a no-op.

## Acceptance criteria

### Sector predicates (exact)

- **AC-99.1.** `emotional`: `tier IN ('REGRET','ACCOMPLISHMENT') OR ABS(affect) > 0.5`. Test with mixed fixtures.
- **AC-99.2.** `procedural`: `tier = 'LESSON' AND context->>'outcome' = 'tool_success'`. Test that a non-tool-success LESSON is excluded.
- **AC-99.3.** `reflective`: `origin IN ('dream','daydream')` (per spec 12/7). Test.
- **AC-99.4.** `semantic`: `tier = 'OBSERVATION' AND stance_owner IS NULL`. Test that an OBSERVATION with a non-null `stance_owner` is excluded (it's opinion-tinted).
- **AC-99.5.** `episodic`: `source = 'I_DID'`. Test that `I_WAS_TOLD` and `I_IMAGINED` rows are excluded.

### Composition

- **AC-99.6.** Sector composes with `since=`, `limit=`, `user_scope=`, and semantic `query=` filters using AND. Test a query like `retrieve(sector="emotional", since=7d, query="meeting with X", limit=20)`.
- **AC-99.7.** Sectors are **orthogonal** — a memory matching `emotional` can also match `episodic`. Test that a REGRET with `source=I_DID` appears under both sector filters independently.
- **AC-99.8.** Sector + tier filter both allowed; they AND together. A caller requesting `sector="emotional", tier="REGRET"` gets REGRETs only (REGRETs ∩ emotional = REGRETs). Test the intersection narrows appropriately.

### Validation

- **AC-99.9.** `sector` accepts exactly the five strings: `"emotional"`, `"procedural"`, `"reflective"`, `"semantic"`, `"episodic"`. Any other value raises `ValueError("unknown sector: <value>")`. Test with `"skills"`, `"random"`, `""`, `123`.
- **AC-99.10.** `sector=None` (default) produces no sector predicate — equivalent to current behavior. Test.
- **AC-99.11.** Sector is case-sensitive lower-case only; `"Emotional"` raises. Test.

### No-migration guarantee

- **AC-99.12.** Sector predicates reference only columns that already exist in the schema (tier, source, affect, origin, stance_owner, context jsonb). A schema-introspection test confirms no new column references. Test by diff'ing the predicate's column set against `information_schema.columns`.
- **AC-99.13.** No new index is required for correctness (existing indexes on tier and source suffice). A performance note is added to retrieval.md recommending a partial index if sector filters dominate traffic; not mandated. Test that queries complete within existing latency SLOs on a 10k-row fixture.

### Observability

- **AC-99.14.** Prometheus counter `turing_retrieve_by_sector_total{self_id, sector}` increments on every sectored query. Test.
- **AC-99.15.** Histogram `turing_retrieve_by_sector_hits{sector}` records result counts; operators can spot dead sectors (always-zero hits) via dashboard. Test.

### Documentation

- **AC-99.16.** `specs/retrieval.md` appends a "Sectors" subsection listing the five names, their predicates, and a usage example. Test by reading the file contains the subsection header.

## Implementation

```python
# retrieval/sectors.py

SECTORS: dict[str, str] = {
    "emotional":  "(tier IN ('REGRET','ACCOMPLISHMENT') OR ABS(affect) > 0.5)",
    "procedural": "(tier = 'LESSON' AND context ->> 'outcome' = 'tool_success')",
    "reflective": "(origin IN ('dream','daydream'))",
    "semantic":   "(tier = 'OBSERVATION' AND stance_owner IS NULL)",
    "episodic":   "(source = 'I_DID')",
}


def sector_predicate(sector: str | None) -> str | None:
    if sector is None:
        return None
    if sector not in SECTORS:
        raise ValueError(f"unknown sector: {sector!r}")
    return SECTORS[sector]


# Integrates into retrieve() like:
def retrieve(
    *, self_id: str, sector: str | None = None,
    since: datetime | None = None, limit: int = 20, query: str | None = None,
    tier: MemoryTier | None = None,
) -> list[Memory]:
    clauses = [f"self_id = :self_id"]
    if (pred := sector_predicate(sector)) is not None:
        clauses.append(pred)
    if tier is not None:
        clauses.append("tier = :tier")
    # ... existing since/query/limit composition unchanged
```

## Open questions

- **Q99.1.** Should `reflective` include REGRETs authored by dream-origin or only the intermediate dream-origin observations? Current predicate uses `origin`, not `tier`, so dream-origin REGRETs match. Acceptable for v1.
- **Q99.2.** Affect threshold `|affect| > 0.5` for emotional is hand-picked; tune once we have affect distribution data.
- **Q99.3.** An `affective_but_not_episodic` intersection (purely imagined emotional content) isn't a first-class sector — callers compose `sector="emotional"` with `source != "I_DID"` themselves. Fine for v1.
- **Q99.4.** Sectors are currently retrieval-only; we could also expose them in `recall_self.*` (spec 96) as a sixth subcall. Deferred until sector traffic is measured.
