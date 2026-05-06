# Epic 15: Emissary MCP Gateway Plane

## Summary

Spec-compliant MCP surface for Stronghold: a tool catalog (scope-aware
approvals), credential issuer (Keyward — short-lived audience-bound JWTs),
composite tool orchestrator (Composer), in-process gateway dispatcher
(Emissary), HTTP listener (RFC 9728 PRM + RFC 8707 audience binding +
OAuth 2.1), outbound MCP client, admin API, YAML startup loader, and
Postgres write-through persistence. The plane gates every outbound LLM
tools[] declaration through Sentinel against the principal's catalog at
USER/TEAM/ORG/PLATFORM scope.

## Why Now

Stronghold previously had no MCP gateway. Tools were dispatched via the
legacy `tool_dispatcher` with org-level RBAC; there was no fingerprint
identity, no scope-walked approvals, no audience-bound credential
issuance, no MCP-spec-compliant external surface, and no defense
against tool-poisoning or rug-pull at the LLM-edge. This epic delivers
the gateway plane that closes those gaps. Most of the plane shipped on
`claude/setup-learning-repo-Q7Fo0` (PR #1206 + 8 follow-ups,
2026-04-28 → 2026-05-05); pending stories round it out.

## Depends On

- Phase 3 (Security Layer — Warden + Sentinel) — verdicts feed Emissary's
  Warden→Keyward revocation coupling
- Phase 5 (Data Layer + Auth) — `AuthContext` is the principal type;
  asyncpg pool drives persistence
- Phase 7 (Tools) — `MCPRegistry` and `MCPDeployer` predate this epic and
  the LOCAL_HOST invoker integrates with them
- ADR-K8S-018 (per-user credential vault) — Keyward issues from secrets
  the vault holds (in spirit; full vault wiring is a follow-up)
- ADR-K8S-020 (MCP server gateway orchestrator) — same architectural
  concern; this epic is its concrete realisation
- ADR-K8S-024 (MCP transport / auth / discovery) — implementation target
  for the HTTP binding and outbound client

## Blocks

- Promotion API (Story 15.6) — needs the catalog data model from 15.1
- Agent-side Emissary integration (Story 15.7) — needs auth-context
  propagation across agents → strategies → LLM client; depends on
  every prior story landing first

## Ship Gate

An admin POSTs a tool to `/v1/stronghold/admin/mcp/tools`, the tool
appears in a fresh principal's `tools/list` via the HTTP binding, the
principal calls it with a Keyward-issued audience-bound JWT, the
backend dispatch hits a registered REMOTE_PROXY, the tool result passes
the Warden scan, and the catalog approval survives a process restart
because Postgres rehydrates it. All five steps end-to-end without a
behaviour change to legacy `tool_dispatcher` traffic.

## Roles Affected

| Role | Impact |
|------|--------|
| Platform operator | Drops `mcp_tools.yaml` for startup-seeded tools; uses admin API for runtime changes |
| Org admin | Approves/revokes tools at org scope via admin API |
| Agent author | (Pending Story 15.7) Eventually routes tool calls through Emissary instead of legacy dispatcher |
| Security auditor | Reviews Sentinel `ToolDeclarationValidator` decisions in audit log; verifies Keyward token TTLs and audience binding |
| External MCP client | Connects to Stronghold's MCP HTTP endpoint via OAuth 2.1; sees only tools approved for its principal |

## Stories

| # | Story | Status |
|---|-------|--------|
| 15.1 | ToolCatalog scope-aware approvals + ToolFingerprinter | ✅ landed |
| 15.2 | Sentinel ToolDeclarationValidator | ✅ landed |
| 15.3 | Keyward credential issuer | ✅ landed |
| 15.4 | Composer composite tool orchestrator (sequential) | ✅ landed |
| 15.5 | Emissary in-process gateway + HTTP binding + outbound MCPClient | ✅ landed |
| 15.6 | Admin API + YAML startup loader | ✅ landed |
| 15.7 | Postgres write-through persistence (catalog, registrations, revocations, composites) | ✅ landed |
| 15.8 | Redis persistence for high-write state (sessions, idempotency, issued tokens, PRM cache) | ⏳ pending |
| 15.9 | Agent-side Emissary integration (legacy `tool_dispatcher` → Emissary) | ⏳ pending |
| 15.10 | Promotion workflow API (USER → TEAM → ORG → PLATFORM with cumulative consent + cascade revocation) | ⏳ pending |
| 15.11 | Hardening — Keyward signing-key rotation, K8sDeployer adapter, streamable HTTP, Composer parallel groups, periodic revocation purge, YAML composite loader | ⏳ pending |
| 15.12 | BDD scaffolding + real-DB integration tests for `pg_mcp.py` | ⏳ pending |

## Evidence References

- [MCP-2025-11-25-AUTH] — MCP authorization spec; mandates OAuth 2.1 +
  PKCE + RFC 8707 resource indicators + RFC 9728 PRM
- [RFC-8707] — OAuth 2.0 Resource Indicators; audience binding
- [RFC-9728] — OAuth 2.0 Protected Resource Metadata
- [OWASP-MCP-TOP-10] — tool poisoning (MCP01), rug-pull (MCP02), exposed
  credentials (MCP04), confused deputy (MCP07), context injection (MCP10)
- [OWASP-AGENTIC-TOP-10-2026] — ASI01 goal hijack, ASI02 tool misuse,
  ASI03 identity & privilege abuse, ASI04 supply chain
- [DUAL-LLM-PATTERN] — separation pattern (output-scanning sub-agent
  isolating tool output from main agent) adapted into the Warden
  output-scan + composite-runtime indirection
- [REFERENCE-MCP-GATEWAY] — public two-plane (data + control) reference
  architecture inspired the structure; we rejected its open-by-default
  reads in favour of explicit allowlist semantics

## Files Touched

### New Files

- `src/stronghold/security/tool_fingerprint.py` — canonical sha256 over (name, description, input_schema)
- `src/stronghold/security/tool_catalog.py` — `InMemoryToolCatalog` with scope walk + write-through hooks
- `src/stronghold/security/keyward.py` — `Keyward`, `KeywardConfig`
- `src/stronghold/security/sentinel/tool_declarations.py` — `ToolDeclarationValidator`
- `src/stronghold/protocols/security.py` — `ToolCatalog`, `CredentialIssuer`, `Composer`, `CompositeRuntime`, `MCPGateway`, `TokenValidator`
- `src/stronghold/mcp/composer.py` — `Composer` with on_error policies
- `src/stronghold/mcp/emissary.py` — `Emissary`, `BackendRegistration`, target-kind dispatch, sessions, idempotency cache
- `src/stronghold/mcp/http_binding.py` — Starlette ASGI; PRM at well-known + sub-path
- `src/stronghold/mcp/client.py` — outbound `MCPClient` with PRM discovery + audience-binding refusal
- `src/stronghold/mcp/invokers.py` — `make_remote_invoker`, `make_local_host_invoker`
- `src/stronghold/mcp/registration_loader.py` — YAML → catalog approval + Emissary backend
- `src/stronghold/api/routes/mcp_admin.py` — `/v1/stronghold/admin/mcp/tools` list/get/approve/revoke
- `src/stronghold/persistence/pg_mcp.py` — `PgCatalogPersistence`, `PgRegistrationPersistence`, `PgRevocationPersistence`, `PgCompositePersistence` + `hydrate_emissary_plane`
- `migrations/012_mcp_emissary_plane.sql` — schema for the four tables

### Modified Files

- `src/stronghold/types/security.py` — add `Scope`, `ToolFingerprint`, `CatalogEntry`, `IssuedToken`, `TokenRequest`/`Result`/`Status`, `RevocationCriteria`, `Session*`, `ToolCallRequest`/`Result`, `ToolDescriptor`, `TargetKind`, `CompositeStep`/`Definition`, `IncomingToken`, token-validation error hierarchy, `MCPServerNotRunningError`. Additive `revoke` field on `WardenVerdict`.
- `src/stronghold/types/config.py` — add `mcp_tools_file`
- `src/stronghold/container.py` — wire 6 fields, build persisters, hydrate-from-Postgres, build invokers
- `src/stronghold/api/routes/chat.py` — inbound `tools[]` validator hook
- `src/stronghold/api/app.py` — mount `mcp_admin_router`
- `src/stronghold/conduit.py` — small Tier cast for mypy strict (PR-side fix)
- `.vulture_whitelist.py` — protocol-stub parameters

## Incremental Rollout Plan

- **Feature flag**: none — every component is opt-in by construction.
  Without `db_pool` configured, persistence is a no-op (in-memory only,
  legacy behaviour). Without `mcp_tools_file` set, no startup-seeded
  catalog. Without an admin POST or YAML entry, the gateway accepts no
  traffic. The legacy `tool_dispatcher` path is unmodified, so existing
  agents continue to work.
- **Canary cohort**: internal dev org; admin POSTs a single REMOTE_PROXY
  tool, exercises it via the HTTP binding, restarts the process to
  verify Postgres rehydration.
- **Rollback plan**: drop the four migration tables and unset
  `mcp_tools_file`. Container construction skips persistence wiring; the
  in-memory components are preserved as-is. Drop the
  `mcp_admin_router` mount in `app.py` if a rollback also needs to
  withdraw the runtime admin surface.

## Open Questions

- OQ-EMI-01: Should Keyward use a dedicated signing key (rotated via
  vault) instead of reusing `jwt_secret`? Tracked in Story 15.11.
- OQ-EMI-02: Is the agent-side integration a `Conduit`-level concern or
  a strategy-level concern? Auth-context propagation will likely go
  through `ToolRuntime` either way; the call site is the choice.
- OQ-EMI-03: Should the K8sDeployer adapter live alongside the existing
  deployer (composition) or replace its surface (adoption)? Composition
  preserves backwards compat for the existing pod lifecycle path.
- OQ-EMI-04: When the Promotion API ships, does cascade revocation
  cross the SYSTEM (`__system__`) boundary? Default plan: yes (a
  revoke at PLATFORM removes from every narrower scope), confirm with
  security review.
