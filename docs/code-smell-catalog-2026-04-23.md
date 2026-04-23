# Stronghold Code-Smell Catalog — 2026-04-23

Scan of `src/stronghold/` (257 files, ~21.8K LOC) plus `tests/` (339 files). Tools used: `ruff`, `mypy --strict`, `bandit -l`, `vulture`, `radon cc/mi`, plus targeted grep passes. Test suite was not executed (Python 3.11 in this environment; project requires 3.12+).

This catalog is diagnostic only. Remediation is deferred — each entry is a pointer, not a ticket.

---

## 0. Top-line counts

| Signal                                   | Count   |
|------------------------------------------|---------|
| `ruff check` findings                    | 0       |
| `mypy --strict` errors                   | 295 (56 files)¹ |
| `bandit -l` findings                     | 27      |
| `vulture` ≥80% confidence findings       | 16      |
| Source modules with no test-import       | 28      |
| `except Exception`-catching blocks       | 96      |
| Lazy imports marked `noqa: PLC0415`      | 158     |
| `typing.Any` annotations                 | 139     |
| TODO/FIXME markers in production code    | 2       |
| `pytest.xfail(strict=False)` tests       | 6       |

¹ Most mypy errors are environment-only (`fastapi`, `httpx`, `jwt`, `argon2` stub lookups) that a real CI venv resolves. The non-stub errors are called out in §2.

---

## 1. Broken / buggy code

### 1.1 Real type error in `conduit.py` (mypy, non-stub)

`src/stronghold/conduit.py:112`

```python
current_tier: str = ...
return replace(intent, tier=current_tier)    # Intent.tier is Literal["P0"..."P5"]
```

`Intent.tier` is `Literal["P0","P1","P2","P3","P4","P5"]` but `current_tier` is typed plain `str`. `dataclasses.replace` accepts any value at runtime, so a typo in `_apply_tenant_policy` (lines 55–60, currently a no-op) or an unexpected agent `priority_tier` would produce an `Intent` with an invalid tier literal that downstream code uses unchecked.

### 1.2 Known security bugs documented as tests

`tests/security/test_security_audit_2026_03_30.py` contains seven **inverted** asserts — the test passes only while the bug is still live. They are *contracts for a fix*, not regressions:

| Line | Bug summary                                                                                          |
|------|------------------------------------------------------------------------------------------------------|
| 160  | Upsert conflict key lacks `org_id` → cross-tenant overwrite possible                                |
| 349  | Empty caller `org_id` returns an org-scoped agent                                                    |
| 392  | `org_id` containing `/` enables prefix-collision access across orgs                                  |
| 441  | Warden scan window gap (bytes 10240..len-2048) lets injections through                               |
| 485  | Warden L3 LLM classifier returns `label="safe"` on exception (fail-open)                             |
| 726  | Code prefix in first 200 chars bypasses full scan                                                    |

These are **known broken behaviors in production code** — the test file calls them "BUG CONFIRMED". Each one needs its fix shipped before the matching assert is flipped.

### 1.3 Unused `type: ignore` in `mcp/deployer.py:35`

Mypy reports `Unused "type: ignore" comment`. The ignore is stacked on a `kubernetes` import which then fails with `import-not-found` — the existing ignore doesn't cover the right error code. Either the ignore comment is stale (fix by removing) or the code assumed a different kubernetes stub package was pinned.

### 1.4 `Any` leaking through `LiteLLMClient`

`src/stronghold/api/litellm_client.py:121,132` — two methods declared as returning `dict[str, Any] | Exception` actually `return <something>` whose type is `Any`, defeating the union. Mypy: `Returning Any from function declared to return "dict[str, Any] | Exception"`.

### 1.5 `Any` leaking through `MCPOAuthStore`

`src/stronghold/mcp/oauth/store.py:21,25,30` — three functions annotated `-> str` / `-> bool` return `Any` from argon2 calls with no cast. These affect OAuth token handling so the missing typing is worth closing.

---

## 2. Dead / stub code

### 2.1 Three agent strategies are single-line docstring stubs

ARCHITECTURE.md documents these as first-class agents, but the implementation is absent:

| File                                                       | LOC | Content                 |
|------------------------------------------------------------|-----|-------------------------|
| `src/stronghold/agents/forge/strategy.py`                  | 1   | `"""Forge agent…"""`    |
| `src/stronghold/agents/warden_at_arms/strategy.py`         | 1   | `"""Warden-at-Arms…"""` |
| `src/stronghold/agents/scribe/strategy.py`                 | 1   | `"""Scribe agent…"""`   |

`Artificer` is real (248 LOC). Anything that tries to `create_agents(...)` for Forge/Scribe/Warden-at-Arms and reach a strategy will crash or silently fall back — see §2.2.

### 2.2 `factory.py` swallows `ImportError` on every strategy registration

`src/stronghold/agents/factory.py:196–228` wraps each `register_strategy(...)` in `try/except ImportError: pass`. If any strategy module has a bug that manifests as `ImportError` (typo, circular import, missing dep), the registration silently no-ops. `create_agents()` then builds an agent whose strategy is `None`, and the failure only surfaces at `agent.handle()` with a confusing `NoneType` error — nowhere near the real cause. Either let `ImportError` propagate or log with the module name at WARNING.

### 2.3 Orphaned diagnostic artifact

`src/stronghold/agents/strategies/builders_learning.py:116–126` builds a "diagnostic artifact" dict into `_` so ruff F841 stays quiet, with the comment `TODO: wire to orchestrator`. The dict is constructed every call, logged only as a constant string `"Frank diagnostic produced"`, then discarded. Either wire it or delete the dead construction.

### 2.4 Vulture ≥80%-confidence dead items (16)

Mostly unused exception-unpack tuples (`exc_tb`), unused dataclass args surfaced as "unused variable", and a handful of assign-and-forget locals:

- `src/stronghold/agents/auditor/checks.py:320` — `commit_count` (100%)
- `src/stronghold/protocols/agent_pod.py:60,88,89,91,109,110` — unused positional fields
- `src/stronghold/protocols/data.py:30`, `memory.py:83`, `mcp.py:70`, `secrets.py:56,79`
- `src/stronghold/tracing/{noop,phoenix_backend}.py` — `exc_tb` unused in `__aexit__`
- `src/stronghold/tools/decorator.py:22` — `required_permissions` assigned, never read

These are near-certainly real (protocol arg placeholders, `exc_tb` idiom). The auditor `commit_count` at line 320 is worth a second look — it's the only 100%-confident one that sits in branching logic.

(Vulture at 60% confidence emits 467 findings — dominated by FastAPI route handlers reached via decorators, which the tool misses. Noise.)

### 2.5 Module stubs in `config/` and `tracing/`

`config/defaults.py`, `config/env.py`, `tracing/prompts.py`, `tracing/trace.py`, `tracing/arize.py` have zero test imports (§3). They may still be referenced by production code, but nothing locks down their shape — they're "written once, never re-entered".

---

## 3. Untested modules

Detected by grepping `tests/` for `from <module>` / `import <module>` — **28 source modules have zero test references.** Grouped by subsystem:

| Subsystem   | Modules                                                                                                    |
|-------------|------------------------------------------------------------------------------------------------------------|
| persistence | `pg_audit`, `pg_outcomes`, `pg_sessions`                                                                   |
| tracing     | `prompts`, `trace`, `arize`                                                                                |
| config      | `defaults`, `env`                                                                                          |
| protocols   | `spec`, `llm`                                                                                              |
| security    | `warden/patterns`                                                                                          |
| api         | `routes/conductor`, `middleware/tracing`, `middleware/auth`                                                |
| builders    | `runtime`, `orchestrator`, `services`                                                                      |
| agents      | `streaming`, `cache`, `importer`, `identity`, `registry`, `exporter`, `forge/strategy`, `warden_at_arms/strategy`, `scribe/strategy` |
| memory      | `scopes`                                                                                                   |
| tools       | `legacy`                                                                                                   |

Persistence `pg_*` is intentionally excluded from coverage in `pyproject.toml` (needs a live Postgres), so those three are expected. The agent-strategy stubs (§2.1) being untested is tautological — there's no code there. The rest are real gaps: `middleware/auth`, `middleware/tracing`, `warden/patterns`, and `memory/scopes` back hot-path security and request-pipeline behavior with no direct unit coverage.

### 3.1 Existing `xfail(strict=False)` tests (6)

These advertise coverage without enforcing it:

- `tests/api/test_agents_routes.py:203`
- `tests/integration/test_structured_request.py:26`
- `tests/integration/test_full_pipeline_e2e.py:171`
- `tests/integration/test_coverage_api.py:260, 418, 457`

`docs/test-quality-remediation-plan.md` (already in repo) lists each with an "unskip" action item. Reference, don't duplicate.

---

## 4. Code smells

### 4.1 God method: `Conduit.route_request`

`src/stronghold/conduit.py:186–735` — a single async method of **~550 lines** with radon cyclomatic complexity **99 (F grade)**. It covers classification, ambiguity handling, session stickiness, intent routing, warden scans, agent dispatch, tracing, learning extraction, and response assembly. This is the docstring-named "ONLY way requests reach an LLM" — which is also why the blast radius of any edit here is high.

### 4.2 Other radon hotspots (C / D / E / F grade)

| Grade | Location                                                     |
|-------|--------------------------------------------------------------|
| F(99) | `conduit.py:186` `Conduit.route_request`                     |
| E(33) | `skills/fixer.py:13` `fix_content`                           |
| D(29) | `config/loader.py:62` `load_config`                          |
| D(28) | `api/routes/admin.py:1307` `analyze_quota`                   |
| D(27) | `api/routes/admin.py:736` `get_quota`                        |
| C(20) | `conduit.py:134` class body; `memory/episodic/store.py:9` `_matches_scope`; `router/filter.py:14` `filter_candidates` |
| C(18) | `container.py:216` `create_container`; `api/routes/chat.py:25` `chat_completions`; `api/routes/mcp.py:153` `deploy_server` |

### 4.3 File-size outliers

- `src/stronghold/api/routes/admin.py` — **1,598 lines**, maintainability index C (the only C-rated MI in the tree). Covers learnings admin, user admin, quota, coins, strikes, appeals, coin pricing — at least seven distinct responsibilities in one file.
- `src/stronghold/skills/connectors.py` — 736 lines.
- `src/stronghold/conduit.py` — 766 lines, one class.

### 4.4 Broad `except Exception` with silent pass

96 `except Exception` blocks across the source tree. Bandit flags eight `B110 try/except/pass`:

| File:line                                                 | What gets swallowed                                    |
|-----------------------------------------------------------|--------------------------------------------------------|
| `agents/factory.py:330`                                   | Strategy registration (see §2.2)                       |
| `agents/strategies/tool_http.py:58`                       | Any failure during `list_tools()` → returns `[]`       |
| `api/routes/profile.py:100`                               | Token breakdown lookup → user sees 0 XP with no error  |
| `mcp/deployer.py:270,275`                                 | K8s `delete_namespaced_deployment/service` failures    |
| `memory/learnings/embeddings.py:178`                      | Embedding failure → silently skips that learning       |
| `security/auth_demo_cookie.py:62`                         | Cookie parse error → request falls through as unauth   |
| `triggers.py:317`                                         | GitHub webhook body parse                              |

Plus one `B112 try/except/continue` at `tools/workspace.py:211`.

Individually most are arguable. Together they describe a "when in doubt, swallow it" culture that makes production failures hard to diagnose. A standard like "log at WARNING, re-raise unless the docstring names the exception" would help.

### 4.5 Module-level mutable singletons

`global` writes at module scope — these make ordering/lifetime bugs hard to test:

- `cache/redis_pool.py:34,50` — `_pool`
- `persistence/__init__.py:16,30` — `_pool`
- `models/engine.py:29,76` — `_engine`, `_engine_url`
- `mcp/oauth/endpoints.py:41` — `_store`
- `skills/connectors.py:644` — `_claude_cache`, `_claude_cache_ts`
- `log_config.py:75` — `_CONFIGURED`

The protocol-driven DI container is the stated pattern; these are the leaks. `mcp/oauth/endpoints.py` holding a module-level `_store` is the most surprising one given OAuth is security-critical.

### 4.6 Lazy imports everywhere

**158** imports tagged `# noqa: PLC0415`. `src/stronghold/container.py` alone has 34. Some are legitimate (breaking circulars between `container.py` and `conduit.py`, optional `redis`/`kubernetes` deps), but this density is a signal that the import graph has too many cross-subsystem edges. Worth an audit targeting `container.py` and `api/routes/*` first.

### 4.7 `Any` density

139 `: Any` / `-> Any` annotations. Hot spots: `conduit.py` (`messages: list[dict[str, Any]]`, `auth: Any`, `agent: Any` — the public API of the router), `container.py`, `agents/base.py`. `conduit.py:186` typing `auth: Any` and then checking `isinstance(auth, AuthContext)` inside the function is a runtime-type-narrowing smell — the static type should just be `AuthContext`.

### 4.8 Bandit — low severity but worth triaging

| ID    | Count | Notes                                                                                          |
|-------|-------|------------------------------------------------------------------------------------------------|
| B101  | 2     | `assert` in production code (`events.py:100`, `memory/learnings/promoter.py:73`) — stripped under `python -O` |
| B105  | 6     | String literals like `"Bearer"`, `"refresh"` flagged as "possible hardcoded password" — false positives, but they mark real hot-path auth strings that could use an enum |
| B106  | 2     | Same idiom in `mcp/oauth/store.py:133,154` — false positive                                    |
| B107  | 1     | Default arg `token: str = ""` in `tools/github.py:191` — works with `os.environ.get(...)` fallback, still fragile |
| B110  | 8     | Swallowed exceptions (see §4.4)                                                                |
| B112  | 1     | `try/except/continue` in `tools/workspace.py:211`                                              |
| B311  | 2     | Non-cryptographic RNG for jitter (`events.py:204`) and canary routing (`skills/canary.py:116`) — low risk, but canary routing should at least be seeded deterministically per (skill, org_id) to avoid replay asymmetry |
| B404  | 1     | `subprocess` import in `tools/workspace.py:20`                                                 |
| B603  | 1     | `subprocess` call at `tools/workspace.py:220` — untrusted-input risk if `cmd` ever takes user text |
| B608  | 3     | SQL string-building in `persistence/pg_outcomes.py:114,173` and `api/routes/profile.py:175`. The persistence ones interpolate a trusted `group_by` literal from a whitelist; `profile.py` builds `UPDATE ... SET f=$n` from a hardcoded field tuple — both safe today but the pattern is fragile. |

No high-severity bandit findings.

### 4.9 Pre-existing test-quality backlog

`docs/test-quality-remediation-plan.md` has already cataloged 331 weak/bad tests:

- 118 trivial-type tests (`isinstance`/`hasattr` right after assignment)
- 65 status-only (`status_code == 200` with no body assert)
- 54 over-mock (mock determines outcome)
- 34 no-assert smoke tests
- 32 tautologies (setup equals outcome)
- 26 planned deletions across 10 files

Top offenders: `tests/test_types.py` (30), `tests/security/test_security_audit_2026_03_30.py` (20), `tests/mcp/test_registries_coverage.py` (18), `tests/api/test_admin_routes.py` (18). Defer to that plan — no need to re-audit here.

### 4.10 Coverage-padding test files

Four files at the `tests/` root whose names advertise the purpose rather than the subject:

| File                                       | LOC   |
|--------------------------------------------|-------|
| `tests/test_coverage_final.py`             | 1,630 |
| `tests/test_coverage_misc.py`              |   935 |
| `tests/test_new_modules.py`                |   717 |
| `tests/test_new_modules_2.py`              | 1,039 |

Total 4,321 LOC. Useful as a staging ground but they hide behavior under geography — a change to `skills/forge.py` has no obvious reason to hunt `test_coverage_final.py`. Worth redistributing to `tests/<subsystem>/`.

---

## 5. Production TODOs

Only two survive in `src/`:

- `src/stronghold/api/routes/admin.py:1244` — `update_coin_settings` needs superadmin gating once trust tiers are wired (§4.3 of the existing admin hotspot).
- `src/stronghold/agents/strategies/builders_learning.py:116` — orphan diagnostic artifact (§2.3).

---

## 6. Red-team / injection bait

`.easter.egg.hi` at the repo root is a prompt-injection honeypot (a file addressed to scanning LLMs with instructions). Not executed, not imported — leaving it alone is the right move. Worth flagging so reviewers know it's intentional.

---

## Suggested priority order for remediation

1. **Flip the seven `BUG CONFIRMED` security tests** (§1.2). These are active vulnerabilities with fixes pre-written as test contracts.
2. **Fix the `Intent.tier` type leak** (§1.1) and the two `Any`-return regressions (§1.4, §1.5).
3. **Un-swallow `ImportError` in `factory.py`** (§2.2) — silent agent-strategy failures will bite hard in production.
4. **Decompose `Conduit.route_request`** (§4.1) and split `api/routes/admin.py` (§4.3) before they accrete more logic.
5. **Close the 28 untested modules** (§3) prioritizing `middleware/auth`, `middleware/tracing`, `warden/patterns`, `memory/scopes`.
6. **Execute the existing test-quality plan** (§4.9) — the work is scoped; this catalog just confirms it's still needed.
7. **Implement or delete the Forge / Scribe / Warden-at-Arms stubs** (§2.1). If they're near-term on the roadmap, promote to skeletons with failing tests; otherwise drop them so the architecture doc stops overselling.
