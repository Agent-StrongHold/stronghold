# Spec 19 — LiteLLM provider

*A single LiteLLM proxy fronts every model the operator wants Project Turing to use. One virtual key, one base URL, many pools (each pool = a model + its free-tier window). Pools have roles (chat or embedding); the runtime picks the right pool for each task.*

**Depends on:** [persistence.md](./persistence.md) (for quota tracker integration).
**Depended on by:** [chat-surface.md](./chat-surface.md), [semantic-retrieval.md](./semantic-retrieval.md), [rss-thinking.md](./rss-thinking.md), [working-memory.md](./working-memory.md), [dreaming.md](./dreaming.md).

---

## Current state

`runtime/providers/base.py` (Protocol + EmbeddingProvider Protocol + FreeTierWindow + exception types), `runtime/providers/litellm.py` (HTTP client), `runtime/providers/fake.py` (offline test provider), `runtime/pools.py` (PoolConfig + role + load_pools). Tests for litellm (10) + pools (5). No spec.

## Target

A clean Provider abstraction that:
1. Exposes the same `complete()` + `embed()` + `quota_window()` interface across LiteLLM and the FakeProvider.
2. Treats each pool as an independent quota window so pressure-based scheduling works correctly.
3. Supports both chat and embedding roles in one provider class (multiple instances, one per pool).
4. Gracefully handles 429 / 5xx / network errors with documented retry semantics.

## Acceptance criteria

### Protocol

- **AC-19.1.** Every Provider implements:
  ```python
  name: str
  def complete(prompt: str, *, max_tokens: int = 512) -> str
  def embed(text: str) -> list[float]
  def quota_window() -> FreeTierWindow | None
  def close() -> None
  ```
  Test asserts both LiteLLMProvider and FakeProvider expose all five.
- **AC-19.2.** `complete()` may raise `RateLimited` (on 429), `ProviderUnavailable` (on persistent 5xx or network errors). All other exceptions are programmer errors. Test asserts both exception paths.
- **AC-19.3.** `embed()` may raise the same exception types as `complete()`. Test.

### Pools

- **AC-19.4.** `PoolConfig` carries `pool_name` (unique identifier within a deployment), `model` (LiteLLM model identifier like `gemini/gemini-2.0-flash-exp`), `window_kind` ∈ `{rpm, daily, monthly, rolling_hours}`, `window_duration_seconds`, `tokens_allowed`, `quality_weight ∈ (0, 10]`, `role ∈ {chat, embedding}`. Test asserts validation for each field.
- **AC-19.5.** `load_pools(yaml_path)` parses a `{pools: [...]}` YAML; missing top-level `pools` key raises `ValueError`. Test.
- **AC-19.6.** Two pools may share a `model` but never a `pool_name`. Test.
- **AC-19.7.** `role` defaults to `"chat"` when not specified in YAML. Test.

### LiteLLM client

- **AC-19.8.** `LiteLLMProvider.__init__(*, pool_config, base_url, virtual_key, client=None)` rejects empty `virtual_key` or `base_url` with `ValueError`. Test.
- **AC-19.9.** `complete()` POSTs to `<base_url>/chat/completions` with body `{model, messages: [{role: "user", content: prompt}], max_tokens, temperature: 0.8}` and `Authorization: Bearer <virtual_key>`. Test asserts request shape via respx.
- **AC-19.10.** `embed()` POSTs to `<base_url>/embeddings` with body `{model, input: text}`. Test asserts request shape.
- **AC-19.11.** Token accounting prefers `response.usage.total_tokens` when present; falls back to `(len(prompt) + len(reply)) // 4` char estimate. Test asserts both paths.
- **AC-19.12.** 429 response → `RateLimited`. Test.
- **AC-19.13.** 5xx response → one retry. If retry also fails, `ProviderUnavailable`. Test asserts retry-once + raise-on-double-fail.
- **AC-19.14.** Network errors (`httpx.RequestError`) → `ProviderUnavailable`. Test.
- **AC-19.15.** Empty embedding response → `ProviderUnavailable`. Test.

### Quota tracking

- **AC-19.16.** `quota_window()` returns the current `FreeTierWindow(provider, window_kind, window_started_at, window_duration, tokens_allowed, tokens_used)`. Test asserts shape.
- **AC-19.17.** When `now - window_started_at >= window_duration`, the window is rolled forward (window_started_at = now, tokens_used = 0). Test asserts rollover.
- **AC-19.18.** `tokens_used` is incremented by every `complete()` and `embed()` call. Test asserts increments after each.

### FakeProvider

- **AC-19.19.** `complete()` returns canned replies cycling through a configured list. Test.
- **AC-19.20.** `embed()` returns a deterministic 64-dim vector derived from the SHA-256 of the input. Same input → same vector; different inputs → different vectors. Test.
- **AC-19.21.** `fail_every` and `unavailable_every` constructor parameters trigger `RateLimited` / `ProviderUnavailable` deterministically. Test asserts both.
- **AC-19.22.** Configurable `latency_s` simulates slow calls. Test asserts approximate latency.

### Closing

- **AC-19.23.** `close()` releases the underlying httpx.Client. Idempotent. Test asserts no error when called twice.

## Implementation

### 19.1 Provider hierarchy

```
Provider (Protocol)
├── LiteLLMProvider     — real HTTP client; one instance per pool
└── FakeProvider        — offline test stub; one instance per pool name
```

### 19.2 Pool selection

The runtime instantiates one Provider per pool. The `pool_roles` map (built by `_pool_roles(cfg)`) tells the runtime which pool to pick for which task:

```python
chat_provider = pick(role="chat", maximize=quality_weight)
embedding_provider = pick(role="embedding") or None
```

If no `role=embedding` pool is registered, semantic retrieval is disabled gracefully.

### 19.3 Configuration constants

```python
DEFAULT_BASE_URL_GEMINI:    str = "(operator-provided)"
DEFAULT_REQUEST_TIMEOUT_S:  float = 30.0
DEFAULT_TEMPERATURE:        float = 0.8
```

## Open questions

- **Q19.1.** Per-task-type embedding pools: maybe chat retrieval wants high-quality embeddings, RSS thinking is fine with cheap ones. Currently one embedding pool serves everyone. Could add `role=embedding-chat` vs `role=embedding-rss` if the operator wants. Defer.
- **Q19.2.** Configurable retry policy beyond "1 retry on 5xx." Real production wants exponential backoff, jitter, max attempts. The research box's behavior is fine for now; the spec leaves room for `RetryPolicy` injection.
- **Q19.3.** Streaming completions: `complete_streaming(prompt) -> Iterator[str]`. Required for `chat-surface.md`'s streaming. Add as a separate method on the Protocol; FakeProvider yields tokens one at a time from its canned reply.
- **Q19.4.** Token accounting is per-pool. If a single LiteLLM model is used by two pools (different windows), they each track separately — meaning the operator's choice of pool granularity directly determines accounting accuracy. Documented.
