# Spec 16 — Semantic retrieval

*Embedding-based search across durable and stance-bearing memory. The chat dispatcher, RSS thinking, working-memory maintenance, and dream consolidation all use it. I_DID-only by default; score is `cosine_similarity × memory.weight`.*

**Depends on:** [schema.md](./schema.md), [retrieval.md](./retrieval.md), [persistence.md](./persistence.md), [litellm-provider.md](./litellm-provider.md).
**Depended on by:** [chat-surface.md](./chat-surface.md), [rss-thinking.md](./rss-thinking.md), [working-memory.md](./working-memory.md), [dreaming.md](./dreaming.md) (future).

---

## Current state

`runtime/embedding_index.py` (in-memory cosine), `runtime/indexing_repo.py` (write-mirror), `retrieval.py::semantic_retrieve` (top-K) all built. 13 tests. No spec.

## Target

Every I_DID memory write is mirrored into an in-memory embedding index. Any caller can ask `semantic_retrieve(query, top_k, tiers, source_filter, min_similarity)` and get back `[(memory, similarity × weight), ...]` ranked descending. Index rebuilt from repo at startup (no on-disk vector store).

## Acceptance criteria

### Indexing on write

- **AC-16.1.** When `IndexingRepo.insert(memory)` is called and `memory.source == I_DID`, the EmbeddingIndex is updated with `(memory_id, content, meta={self_id, tier, source, intent_at_time})`. Test.
- **AC-16.2.** When `memory.source ∈ {I_WAS_TOLD, I_IMAGINED}`, the index is *not* updated. Test asserts both negative cases.
- **AC-16.3.** Embedding failures (provider error, malformed response) are silent — the insert still lands in the repo, the memory is just not indexed. Logged at WARNING. Test with a failing embed_fn.
- **AC-16.4.** Removing or superseding a memory does NOT remove its embedding from the index. Superseded entries are filtered at retrieval time by checking `memory.superseded_by`. Test asserts a superseded memory does not appear in results.

### Index rebuilding on startup

- **AC-16.5.** `IndexingRepo.rebuild_index_from_repo(self_id)` re-embeds every I_DID memory in the repo (durable + non-durable). Returns the count. Called once at runtime startup so restarts don't need a separate vector store on disk. Test asserts count and presence of arbitrary samples.
- **AC-16.6.** Rebuild is idempotent: calling it twice produces the same index size. Test.

### Search semantics

- **AC-16.7.** `semantic_retrieve(repo, index, self_id, query, top_k=8, tiers=None, source_filter={I_DID}, min_similarity=0.05)` returns at most `top_k` `(memory, score)` pairs. Test.
- **AC-16.8.** Score formula: `cosine_similarity(query, memory) × memory.weight`. Tied scores fall back to creation timestamp (newer first). Test asserts the formula on a deterministic fixture.
- **AC-16.9.** `tiers` filter narrows to only memories whose tier is in the set. None means all tiers. Test.
- **AC-16.10.** `source_filter` defaults to `{I_DID}`. Callers must explicitly opt in to include I_IMAGINED or I_WAS_TOLD. Test asserts default behavior + explicit opt-in.
- **AC-16.11.** `min_similarity` filters out below-threshold results before scoring. Test.
- **AC-16.12.** Memories with `superseded_by IS NOT NULL` are excluded from results. Test.
- **AC-16.13.** Multi-tenant safety: results are filtered to the requesting `self_id` only. (Single-self deployments need not test this; multi-self deployments must.) Test asserts cross-self isolation when two selves exist.

### Performance

- **AC-16.14.** With 10,000 indexed memories, `semantic_retrieve` returns in < 100 ms on reference hardware (research-laptop). Benchmark test.
- **AC-16.15.** `EmbeddingIndex.add` is O(1). `EmbeddingIndex.search` is O(N × D) where D is embedding dimension. Documented; no other big-O claims.

### Embedding model semantics

- **AC-16.16.** The `embed_fn` is provided externally (typically a LiteLLMProvider with role=embedding). The index does not know or care which model produced a vector — it just stores and compares them. If the operator changes the embedding model, all prior vectors become stale; the index should be rebuilt. Test asserts reasonable behavior when the embed_fn is swapped (different vectors, search still returns nearest).
- **AC-16.17.** The embedding pool tracks its own quota usage via the standard FreeTierQuotaTracker pathway; semantic_retrieve calls do not bypass quota accounting. Test.

## Implementation

### 16.1 EmbeddingIndex shape

```python
class EmbeddingIndex:
    _by_id: dict[str, list[float]]
    _meta:  dict[str, dict[str, Any]]
    _lock:  threading.Lock

    def add(memory_id, text, *, meta=None) -> None
    def remove(memory_id) -> None
    def search(query, *, top_k, filter_fn) -> list[(memory_id, similarity, meta)]
    def size() -> int
```

### 16.2 IndexingRepo wrapping

```python
class IndexingRepo:
    def __init__(*, inner: Repo, index: EmbeddingIndex): ...
    def insert(memory) -> str:        # mirror to index for I_DID
    def index_memory(memory) -> None
    def rebuild_index_from_repo(self_id) -> int
    def __getattr__(name) -> Any:     # delegate everything else
```

The `__getattr__` delegation means the rest of the codebase sees an IndexingRepo as a Repo without modification.

### 16.3 Score function

```python
def _cosine(a, b) -> float:
    if not a or not b or len(a) != len(b): return 0.0
    dot = sum(x*y for x,y in zip(a, b, strict=True))
    na, nb = sqrt(sum(x*x for x in a)), sqrt(sum(x*x for x in b))
    return dot / (na * nb) if na and nb else 0.0
```

`semantic_retrieve` then multiplies `cosine` by `memory.weight` for the final score.

### 16.4 Configuration constants

```python
DEFAULT_TOP_K:           int   = 8
DEFAULT_MIN_SIMILARITY:  float = 0.05
```

## Open questions

- **Q16.1.** Per-tier weight scaling beyond the existing `WEIGHT_BOUNDS`. E.g., REGRET retrievals could be amplified during planning. Currently flat. Tunable later.
- **Q16.2.** Embedding storage on disk: rebuild-from-repo at startup is fine for ≤10k memories. At 100k+ this becomes seconds-of-startup. Persisting embeddings to disk (sqlite-vec, lancedb, etc.) is a future concern.
- **Q16.3.** Embedding model versioning: when the embedding model changes, prior vectors are subtly inconsistent (different models produce different geometries). For research, rebuild on startup handles it. For production, a `embedding_model_version` column would let us detect drift.
- **Q16.4.** Index sharing across processes: multi-pod deployments would share the SQLite file but not the in-memory index. Out of scope; single-pod is the autonoetic model.
