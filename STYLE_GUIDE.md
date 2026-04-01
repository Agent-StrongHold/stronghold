# Stronghold Design & Style Guide

**Priorities, in order:** Security > Maintainability > Velocity

Every trade-off resolves in that order. A slower, more secure implementation beats a fast, clever one. A readable implementation beats a compact one. When maintainability and security conflict, security wins.

---

## 1. Secure by Design

### 1.1 Scan uniformly

All security scanning (Warden, PII filter, skill scanner) must use the same normalization pipeline: `sanitize()` then `NFKD`. If the Warden catches a Cyrillic homoglyph but the PII filter doesn't, that's a bug.

**Rule:** Extract normalization into a single function (`normalize_for_scanning`). All scanners call it.

### 1.2 Scan in the base pipeline

Security scanning belongs in the orchestration layer (`Agent.handle()`), not in individual strategies. If a new strategy skips Warden post-scan, every agent using it is unprotected.

**Rule:** `handle()` scans the final response. Strategies scan intermediate results (tool outputs) during their loops. Both are required.

### 1.3 Fail closed

When a security check errors, the result is `inconclusive` or `blocked`, never `safe`. A network timeout on the LLM classifier does not mean the content is safe — it means we don't know.

**Rule:** All security layer catch blocks must return a fail-closed result. Document the fail mode in the docstring.

### 1.4 Name your thresholds

Every security threshold needs a named constant and a comment explaining *why* that value — what corpus it was calibrated against, what FP/TP rates it produces.

```python
# Bad
if density > 0.15:

# Good
# Calibrated on 213-sample adversarial set: 0.15 gives 88% TPR with <1% FPR.
# Values above 0.20 miss multi-encoding attacks; below 0.10 flags normal emails.
INSTRUCTION_DENSITY_THRESHOLD = 0.15
```

### 1.5 org_id on every data access

No store method, no SQL query, no API route may return data without org_id scoping. Empty org_id returns empty results, never all-tenant data. `__system__` is an explicit, audited bypass — not a default.

---

## 2. Naming & Self-Documentation

Code should read like prose. If a reviewer needs a comment to understand what a name means, the name is wrong.

### 2.1 Descriptive names

```python
# Bad
result = await store.get(name)
data = await request.json()
item = items[0]

# Good
agent_record = await agent_store.get(agent_name)
login_request = await request.json()
top_candidate = ranked_models[0]
```

### 2.2 Booleans

Boolean variables and methods use `is_`, `has_`, `should_`, `can_`:

```python
# Bad
admin = auth.has_role("admin")
locked = record.locked_until > now

# Good
is_admin = auth.has_role("admin")
is_locked = record.locked_until > now
```

### 2.3 Avoid vague names

Banned as standalone names: `data`, `result`, `item`, `info`, `stuff`, `tmp`, `val`, `obj`, `resp`. Add a qualifier: `warden_result`, `token_info`, `model_response`.

### 2.4 Module names describe responsibility

Name modules for what they *do*, not how they do it: `detector.py` not `regex_scanner.py`, `store.py` not `dict_backend.py`.

---

## 3. Function & Method Design

### 3.1 Length limits

- **40 lines** soft limit per method. If longer, decompose into named sub-steps.
- **4 parameters** soft limit. Beyond that, group into a config dataclass or named tuple.

### 3.2 Single responsibility

If describing a function requires "and", it should be two functions.

```python
# Bad: "classify intent AND check quota AND select model"
async def route_request(self, messages, ...) -> dict:  # 540 lines

# Good: pipeline of named steps
async def route_request(self, messages, ...) -> ChatResponse:
    intent = await self._classify(messages)
    quota = await self._check_quota(intent)
    model = await self._select_model(intent, quota)
    return await self._dispatch(intent, model, messages)
```

### 3.3 Early return over deep nesting

```python
# Bad
if auth:
    if auth.has_role("admin"):
        if org_id:
            # 4 levels deep
            ...

# Good
if not auth:
    raise HTTPException(401)
if not auth.has_role("admin"):
    raise HTTPException(403)
if not org_id:
    raise HTTPException(400)
# flat
...
```

### 3.4 No cross-cutting concerns inline

Tracing, logging, and metrics are cross-cutting. Use context managers or decorators, not `if trace: ... else: <same thing>` forks that double the line count.

```python
# Bad (doubles every pipeline step)
if trace:
    with trace.span("classify") as s:
        intent = await self._classify(messages)
        s.set_output(intent)
else:
    intent = await self._classify(messages)

# Good
with maybe_span(trace, "classify") as s:
    intent = await self._classify(messages)
    s.set_output(intent)
```

---

## 4. Type Discipline

### 4.1 No `dict[str, Any]` at boundaries

Every API boundary (function signatures, return types, inter-layer data) uses typed dataclasses or Pydantic models. `dict[str, Any]` is acceptable only inside a function for transient local data.

```python
# Bad
async def route_request(self, messages: list[dict[str, Any]]) -> dict[str, Any]:

# Good
async def route_request(self, messages: list[ChatMessage]) -> ChatCompletionResponse:
```

### 4.2 Every dependency has a protocol

If a constructor takes a collaborator, that collaborator has a protocol in `src/stronghold/protocols/` and a fake in `tests/fakes.py`. No `strategy: Any`, `sentinel: Any`, `coin_ledger: Any`.

### 4.3 No `Any`-typed fields on the Container

If you know the type, declare it. Use `TYPE_CHECKING` imports to avoid circular dependencies.

### 4.4 Return types on all public methods

Every `def` and `async def` that isn't prefixed with `_` has a return type annotation.

---

## 5. DRY & Extraction

### 5.1 Three strikes, extract

If a pattern appears 3+ times, extract it into a shared function or base class method.

Current violations to fix:
- Auth/CSRF helpers copy-pasted across 6 route files
- User text extraction duplicated in 5 files
- Error detection heuristic repeated in 6 places
- `_PATTERN_TIMEOUT_S` defined in 3 warden modules

### 5.2 Config coercion happens once

Dict-to-dataclass conversion happens at config load time, not on every request. If `StrongholdConfig.providers` is `dict[str, ProviderConfig]`, the coercion lives in `config/loader.py`, not in `conduit.route_request()`.

### 5.3 No mutation through private attributes

Never assign to another object's `_private` attribute. If you need to change its state, add a public method.

```python
# Bad
self._c.llm._fallback_models = fallback_models

# Good
self._c.llm.set_fallback_models(fallback_models)
```

---

## 6. Layer Boundaries

### 6.1 Routes are thin controllers

A route handler does: authenticate, parse input, call a service/store, format response. No SQL. No business logic. No multi-step orchestration.

```python
# Bad (route handler with inline SQL)
async def update_user_roles(user_id: int, request: Request):
    async with pool.acquire() as conn:
        await conn.execute("UPDATE users SET roles = $1 WHERE id = $2", ...)

# Good
async def update_user_roles(user_id: int, request: Request):
    await user_service.update_roles(user_id, roles, org_id=auth.org_id)
```

### 6.2 SQL lives in persistence

All SQL strings belong in `src/stronghold/persistence/pg_*.py`. Route handlers never call `conn.execute()` directly.

### 6.3 DI wiring lives in the container

No `if warden is None: warden = Warden()` inside business classes. If a dependency is optional, make it `Optional[Protocol]` and handle the None case. Never silently construct a degraded default.

### 6.4 Types cross all layers

Dataclasses in `src/stronghold/types/` are the shared vocabulary. Every layer imports them. No layer defines its own ad-hoc dicts for structured data.

---

## 7. Error Handling

### 7.1 Catch specific types

```python
# Bad
except (ValueError, RuntimeError, TimeoutError, OSError):

# Good
except StrongholdError:  # project's own hierarchy
    ...
except httpx.TimeoutException:  # specific external error
    ...
```

### 7.2 No swallowed exceptions

Every `except` block must either log, re-raise, or return a meaningful result. `except Exception: pass` is never acceptable.

### 7.3 Security exceptions fail closed

```python
# Bad — security check fails open
except Exception:
    return {"label": "safe"}

# Good — security check fails closed
except Exception:
    logger.warning("scan failed", exc_info=True)
    return {"label": "inconclusive", "error": "scan_failed"}
```

---

## 8. Constants & Configuration

### 8.1 Named constants for all thresholds

No magic numbers in logic. Extract to a module-level constant with an explanatory name.

```python
# Bad
if len(content) > 102400:
    content = content[:102400]

# Good
_MAX_SCAN_BYTES = 100 * 1024  # Bounds worst-case scan time to ~10s
if len(content) > _MAX_SCAN_BYTES:
    content = content[:_MAX_SCAN_BYTES]
```

### 8.2 Hardcoded limits are configurable or justified

If a limit exists (10,000 learnings, 200 results, 50KB body), it either comes from config or has a comment explaining why that specific value was chosen.

### 8.3 Shared constants live in one place

If multiple modules need the same constant (e.g., pattern timeout), it lives in a shared constants module, not duplicated in each file.

---

## 9. Testing Expectations

### 9.1 Integration tests, not mocks

Import and instantiate real classes. Only mock external HTTP calls. Use the fakes in `tests/fakes.py`.

### 9.2 Every security fix gets a regression test

When fixing a vulnerability, write a test that would fail if the fix is reverted. The test asserts the *fixed* behavior.

### 9.3 Tests mirror source structure

`tests/security/` tests `src/stronghold/security/`. `tests/api/` tests `src/stronghold/api/`.

---

## 10. Anti-Pattern Catalog

Real examples from this codebase. Each is a refactoring target.

| Anti-Pattern | Location | What's Wrong |
|---|---|---|
| God method | `conduit.py:route_request` (540 lines) | 12+ concerns in one method |
| God method | `agents/base.py:handle` (345 lines) | Pipeline + tracing + error handling + recording |
| God function | `container.py:create_container` (240 lines) | 14 responsibility blocks |
| Dict soup | `conduit.py` throughout | `dict[str, Any]` for messages, responses, metadata |
| Copy-paste auth | `_check_csrf` in 6 route files | Same 10-line function duplicated |
| Copy-paste extraction | User text extraction in 5 files | Different multimodal handling in each |
| Missing protocol | `agents/base.py` `strategy: Any` | No `ReasoningStrategy` protocol exists |
| Inline SQL | `admin.py` (20+ SQL strings) | Route handlers execute SQL directly |
| Private mutation | `conduit.py:552` `llm._fallback_models = ...` | Breaks encapsulation, race condition |
| Silent default | `gate.py` `warden=None` fallback | Constructs degraded Warden without logging |
| Inconsistent scanning | `PlanExecuteStrategy` | No Warden post-scan or PII filter |
| Dead code | `app.py` `_dashboard_candidates` | Defined but never used |
| Magic threshold | `heuristics.py` `0.15` | No calibration documentation |
| Duplicated constant | `_PATTERN_TIMEOUT_S` in 3 files | Same value defined independently |
