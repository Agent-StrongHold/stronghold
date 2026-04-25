# Spec 96 — Tool-gated self-disclosure

*Split `recall_self()` into typed subcalls the self invokes on demand — the minimal prompt block stays tight, and the self pays token cost only for the subsurface a given decision actually needs.*

**Depends on:** [self-surface.md](./self-surface.md), [self-write-budgets.md](./self-write-budgets.md), [self-write-preconditions.md](./self-write-preconditions.md), [self-tool-registry.md](./self-tool-registry.md), [forensic-tagging.md](./forensic-tagging.md).

---

## Current state

`recall_self()` returns a monolithic self-surface blob (spec 6) used by the minimal prompt block (spec 28). Every request pays the full token cost regardless of which subsurface matters — a routing decision and a regret-writing decision get the same payload. Acontext-style progressive disclosure (its `get_skill` pattern) isn't wired for self-state.

## Target

Expose `recall_self` as a **namespace of typed subcalls** registered in the self-tool registry: `passions()`, `regrets(since=)`, `affirmations()`, `recent_surprises(top_k=5)`, `activation_snapshot()`, `personality()`. Minimal prompt block remains 4-line identity + mood + todos + passion (spec 28). The self reaches deeper by calling a subsurface tool, which returns a bounded slice, forensic-tagged, cached for 30 s, and capped per-request so deep-dive doesn't explode token spend.

## Acceptance criteria

### Subcall registration

- **AC-96.1.** Six subcalls registered in the self-tool registry (spec self-tool-registry.md) under namespace `recall_self.*`: `passions`, `regrets`, `affirmations`, `recent_surprises`, `activation_snapshot`, `personality`. Test each is discoverable via the registry.
- **AC-96.2.** Each subcall has a declared **per-call token estimate** (constant in code: passions=120, regrets=300, affirmations=250, recent_surprises=400, activation_snapshot=600, personality=180). Test estimates are exposed as registry metadata.
- **AC-96.3.** Each subcall returns a typed dataclass (not a free-form dict). Test schemas match dataclass definitions.

### Per-request budget

- **AC-96.4.** Per-request cap: at most **3 subcalls** of `recall_self.*` per incoming request. 4th call raises `SelfDisclosureBudgetExceeded`. Test with a fake driver issuing 4 calls.
- **AC-96.5.** Budget is request-scoped (keyed by `request_id`), not session-scoped — a new request resets the counter. Test.
- **AC-96.6.** Budget extends the broader per-request self-write budget (spec 95) but is tracked separately (reads vs writes). Test that a request hitting the write cap can still make subcalls and vice versa.

### Read semantics

- **AC-96.7.** `recall_self.*` output is **NOT written back as memory** — it's a read of existing state. Test that invoking `recent_surprises()` produces zero new OBSERVATIONs.
- **AC-96.8.** Subcalls are **forensic-tagged** with `perception_tool_call_id` (spec forensic-tagging.md) so later audit can reconstruct "what the self saw when it decided X." Test tags are stamped on every return.

### Caching

- **AC-96.9.** Each subcall result cached with 30 s TTL, keyed by `(self_id, subcall_name, args_hash)`. Test cache hit returns within 5 ms; test TTL expiry triggers recompute.
- **AC-96.10.** Cache key **must not include time-travel params** (spec 90 as_of / point-in-time) — time-travel always bypasses cache. Test that `recall_self.regrets(since=..., as_of=...)` skips the cache layer entirely.
- **AC-96.11.** Cache is invalidated on any self-write that touches the relevant tier (e.g., new REGRET invalidates `regrets()` and `activation_snapshot()` entries). Test via spec 25 hook.

### Preconditions

- **AC-96.12.** All subcalls require `bootstrap_complete = True` (spec self-write-preconditions.md). Before bootstrap, calls raise `BootstrapIncomplete`. Test.
- **AC-96.13.** `activation_snapshot()` additionally requires `activation_graph.ready = True` — if the graph is still warming, return a stub `{status: "warming", retry_after_s: 30}` instead of raising. Test.

### Malformed args

- **AC-96.14.** Malformed args raise `ValueError` with the offending field (e.g., `recall_self.regrets(since="banana")` → "since must be datetime or None"). Test each subcall's arg validation.
- **AC-96.15.** `top_k` on `recent_surprises` is clamped to `[1, 20]`; out-of-range values clamp silently (don't raise) and log a warning. Test clamp boundaries.

### Observability

- **AC-96.16.** Prometheus counter `turing_recall_self_subcalls_total{self_id, subcall}` and histogram `turing_recall_self_subcall_tokens_estimate{subcall}`. Test metrics emit on every call.

## Implementation

```python
# self/disclosure.py

RECALL_SELF_BUDGET_PER_REQUEST: int = 3
RECALL_SELF_CACHE_TTL_SEC: int = 30

@dataclass(frozen=True)
class SubcallMeta:
    name: str
    token_estimate: int
    returns: type

_SUBCALLS: dict[str, SubcallMeta] = {
    "passions":            SubcallMeta("passions",            120, PassionsSnapshot),
    "regrets":             SubcallMeta("regrets",             300, RegretsSnapshot),
    "affirmations":        SubcallMeta("affirmations",        250, AffirmationsSnapshot),
    "recent_surprises":    SubcallMeta("recent_surprises",    400, SurprisesSnapshot),
    "activation_snapshot": SubcallMeta("activation_snapshot", 600, ActivationSnapshot),
    "personality":         SubcallMeta("personality",         180, HexacoSnapshot),
}

def recall_self_subcall(
    name: str,
    *,
    self_id: str,
    request_id: str,
    args: dict,
    perception_tool_call_id: str,
) -> Any:
    _check_bootstrap(self_id)
    _check_budget(request_id)  # raises SelfDisclosureBudgetExceeded at >3

    if name not in _SUBCALLS:
        raise ValueError(f"unknown recall_self subcall: {name}")

    as_of = args.get("as_of")
    cache_key = (self_id, name, _stable_hash(args)) if as_of is None else None

    if cache_key and (hit := _cache_get(cache_key)):
        return _tag(hit, perception_tool_call_id)

    result = _dispatch(name, self_id=self_id, args=args)
    if cache_key:
        _cache_put(cache_key, result, ttl=RECALL_SELF_CACHE_TTL_SEC)
    _increment_budget(request_id)
    return _tag(result, perception_tool_call_id)
```

## Open questions

- **Q96.1.** Token estimates are hand-set constants — should we measure real token counts in CI and fail the build if they drift > 25%? Probably yes once estimates stabilize; deferred.
- **Q96.2.** Budget of 3 may be too tight for complex multi-step reasoning. Consider an override for `plan_execute` strategy (spec 4) allowing 5. Tune once we have trace data.
- **Q96.3.** Should `personality()` ever return partial HEXACO if a trait hasn't been inferred yet? Current: always returns all 6 facets with `null` for un-inferred. Revisit if prompt noise matters.
- **Q96.4.** `activation_snapshot()` at 600 tokens is the heaviest — we may want a `compact=True` variant that trims to top-K active nodes only. Deferred to spec 95 tuning.
