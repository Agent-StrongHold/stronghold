# Spec 5 — WISDOM write path

*WISDOM writes now land via the dreaming consolidation process. This spec retains the constraints the write path must satisfy; the how is in [dreaming.md](./dreaming.md).*

**Status:** ACTIVE (was DEFERRED; superseded by the arrival of [dreaming.md](./dreaming.md)).

**Depends on:** [schema.md](./schema.md), [tiers.md](./tiers.md), [durability-invariants.md](./durability-invariants.md), [dreaming.md](./dreaming.md).
**Depended on by:** —

---

## Why a dedicated spec

WISDOM is the tier whose durability is most expensive to wrong and most expensive to correct. Weight floor 0.9, immutable, survives across versions. Writing WISDOM inline during a request — i.e., letting the LLM's in-the-moment pattern claim become structurally unforgettable — is incompatible with the reliability WISDOM demands.

The write path is **consolidation via dreaming**: a scheduled, phase-gated process that walks durable memories, identifies invariant patterns, and proposes WISDOM candidates through a review gate. See [dreaming.md](./dreaming.md) for the full process. This spec owns the invariants the write path must enforce regardless of who's invoking it.

## Acceptance criteria

- **AC-5.1.** `durable_memory` insert with `tier == wisdom` is permitted *only* when every WISDOM-specific invariant below is satisfied. Violating any one raises a repository-level error. Negative tests per invariant.
- **AC-5.2.** Retrieval that filters for `tier == wisdom` returns an empty set cleanly when no entries exist, and returns matches when they do. Test covers both.
- **AC-5.3.** All durable-memory invariants from [durability-invariants.md](./durability-invariants.md) continue to apply — floors, non-deletion, append-only, migration fidelity.

## Invariants (enforced at repository / schema layer)

1. **Consolidation-origin only.** Every WISDOM memory has a non-null `origin_episode_id` pointing at an OBSERVATION session marker whose content starts with `dream session `. Enforced by the repository (validates the reference at INSERT).
2. **I_DID provenance.** `source = i_did` required. Content is distilled from I_DID inputs; the *act* of dreaming is an I_DID action by the Conduit.
3. **Traceable lineage.** `context.supersedes_via_lineage` is a non-empty list of memory_ids referencing real durable memories in `{regret, accomplishment, lesson, affirmation}`. Rejected at repo if missing or any referenced memory doesn't exist.
4. **No superseding existing WISDOM.** `supersedes` on a WISDOM entry may not point at another WISDOM entry. New WISDOM extends; it does not overwrite.
5. **Bounded minting rate per session.** `DREAM_MAX_WISDOM_CANDIDATES` (default 3) enforced in the Dreamer; the tier cannot be flooded from a single session.
6. **Review-gate gated.** A WISDOM entry cannot be committed without passing the Dreamer's phase 6 self-consistency check. See [dreaming.md](./dreaming.md) for the gate's behavior.

## Open questions

- **Q5.1.** The Dreamer's review gate is automatic in research mode. `main` port would need operator review. Moving to operator review changes the UX but not the repo invariants listed above.
- **Q5.2.** `origin_episode_id` referential integrity: enforced at INSERT in the research sketch, but there's no SQLite foreign-key-style guarantee (it's a loose lookup). Tightening would require a DB-level check or, more likely, a background verifier. Not blocking.
