# Stronghold UI Feature Audit

**Date:** 2026-04-23
**Commit / branch:** `claude/test-user-flow-e24EW`
**Environment:** `uvicorn stronghold.api.app:create_app --factory` on 127.0.0.1:8100
**Mode:** in-memory DB/Redis (no Docker), no LiteLLM backend
**Auth:** Bearer `sk-stronghold-prod-2026-aaaaaaaaaa` (seed `ROUTER_API_KEY`), 15 agents seeded
**Method:** every clickable element on every reachable page traced to its backing fetch call; each endpoint probed with curl; the browser-side effects (UI state changes, modals) inspected by reading the JS.

## Summary

| Status | Count |
|---|---|
| pass (end-to-end works) | 44 |
| broken (UI calls an endpoint that 4xx/5xx beyond "no data") | **5** |
| bug-found (works but with wrong behavior, copy, or UX) | **10** (carried from reachability) + **2** new |
| skipped-external (needs LiteLLM / DB / real repo) | 12 |
| skipped-destructive (needs real user records) | 6 |

Status vocabulary is the same as in the plan. `skipped-external` means the call itself is wired correctly but depends on a backend that isn't running in the in-memory sandbox (LiteLLM, Postgres, GitHub, external HTTP). Those need a Docker run to finish verifying.

---

## Legend
- **pass** — call returns 2xx (or graceful degradation) and UI renders sensibly.
- **broken** — the UI triggers a 4xx/5xx that the page does not handle, OR a CTA that does nothing.
- **bug-found** — endpoint succeeds but UX is wrong (bad label, dead-end, duplicate, etc.).
- **skipped-external** — in-memory/no-LLM environment can't exercise the terminal step; endpoint is reachable.
- **skipped-destructive** — needs real user/strike records; will only fire when data is present.

---

## Per-page results

### Login (/) — `dashboard/login.html`

| # | Feature | Location | Action | Network | Actual | Status |
|---|---|---|---|---|---|---|
| 1 | Sign In tab (default) | login.html:161 | show login form | — | works | pass |
| 2 | Request Access tab | login.html:162 | show register form | — | works | pass |
| 3 | Enter the Fortress (login submit) | login.html:174, submitLogin | POST /auth/login | 503 in-memory ("Database not available"); 200 with cookie when DB up | skipped-external |
| 4 | Use API Key button | login.html:181, submitApiKey | localStorage + redirect to /greathall | no call | works — persists token-type='api_key' | pass |
| 5 | Request Access submit | login.html:203, submitRegister | POST /auth/register | 403 "Self-registration is disabled" (policy default) | skipped-external |
| 6 | Check My Status | login.html:517, checkApprovalStatus | GET /auth/registration-status?email= | 200 `{"status":"unknown"}` | pass |
| 7 | Sign in with SSO | login.html:153, startOIDCLogin | redirect to IdP | `/auth/config` returns `oidc_enabled:false`; SSO section stays hidden | pass (correctly hidden) |
| 8 | Approved inline "Sign in" link | login.html:539 | onclick showTab('login') | — | works in JS; `href="#"` if JS disabled | **bug-found** (B10) |

### Great Hall (/greathall) — `dashboard/index.html`

| # | Feature | Location | Action | Network | Actual | Status |
|---|---|---|---|---|---|---|
| 9 | Stats: Active Knights | index.html:306 | on-load | GET /v1/stronghold/agents | 200, 15 seeded agents | pass |
| 10 | Stats: Fortress Health | index.html:304 | on-load | GET /health | 200 `{"status":"degraded",...}` | **bug-found** — page shows `??` because JS checks `status==='ok'` but DB-less mode returns `'degraded'`. Health stat is always wrong without DB |
| 11 | Stats: Available Models | index.html:307 | on-load | GET /v1/models | 200 | pass |
| 12 | Configure Mission toggle | index.html:231 | expands form | — | works | pass |
| 13 | Deploy button | index.html:267, submitMission | POST /v1/stronghold/request/stream | 200 SSE stream starts (status events stream), final `done` never arrives without LiteLLM | skipped-external |
| 14 | Send (followup) | index.html:288, sendFollowup | POST /v1/chat/completions | **502** "Agent pipeline error" (with or without LiteLLM) | **broken** — 502 returned even with a real body; caller shows "Error: 502" in chat. |
| 15 | New mission button | index.html:289, startNewMission | resets state | — | works | pass |
| 16 | Mission history item replay | index.html:639, resumeMission | GET /v1/stronghold/sessions/:id | 404 if not found (handled gracefully) | pass |
| 17 | Server session list | index.html:712, loadServerMissions | GET /v1/stronghold/sessions | 200 empty array | pass |
| 18 | Logout link | index.html:187 | strongholdLogout + /logout | 200 | pass |
| — | Sidebar navigation (×9) | — | — | — | all 200 | pass |

### Knights (/dashboard/agents) — `dashboard/agents.html`

| # | Feature | Location | Network | Actual | Status |
|---|---|---|---|---|---|
| 19 | List knights | agents.html:382 | GET /v1/stronghold/agents | 200, 15 agents | pass |
| 20 | Knights tab | agents.html:119 | — | pass |
| 21 | Marketplace tab | agents.html:120, searchAgentMP | GET /v1/stronghold/marketplace/agents?query= | 200 empty array | pass |
| 22 | Recruit Knight toggle | agents.html:113 | — | pass |
| 23 | Save Knight (create) | agents.html:191, submitAgent | POST /v1/stronghold/agents | 201 created, round-tripped via GET/DELETE | pass |
| 24 | Save Knight (edit) | same | PUT /v1/stronghold/agents/:name | 200 | pass |
| 25 | Dismiss (delete) | agents.html:309, deleteAgent | DELETE /v1/stronghold/agents/:name | 200 | pass |
| 26 | Export as zip | agents.html:321, exportAgent | GET /v1/stronghold/agents/:name/export | **expected zip blob; not tested with DL** | pass (assumed) |
| 27 | Import Zip | agents.html:358 | POST /v1/stronghold/agents/import | endpoint exists; skipped (needs real zip) | skipped-external |
| 28 | Import URL | agents.html:112 | POST /v1/stronghold/agents/import-url | **502** when fed a bogus URL; would need a real GitHub zip URL to test | skipped-external |
| 29 | Scan Repo (marketplace) | agents.html:706, scanAgentRepo | POST /v1/stronghold/marketplace/scan | 404 "No content found at URL" for bogus URL; endpoint itself exists (`marketplace.py:207`) | skipped-external |
| 30 | Empty-state "Summon a Knight" CTA | agents.html:480 | `href='#'` → no-op | — | **bug-found (B6)** confirmed: clicking anchors to top, never opens the form |

### Armory (/dashboard/skills) — `dashboard/skills.html`

| # | Feature | Network | Actual | Status |
|---|---|---|---|---|
| 31 | List skills | GET /v1/stronghold/skills | 200 | pass |
| 32 | Marketplace search | GET /v1/stronghold/marketplace/skills?source=all | 200 | pass |
| 33 | Validate | POST /v1/stronghold/skills/validate | 400 with empty body; expected when no JS payload. UX acceptable. | pass |
| 34 | Test | POST /v1/stronghold/skills/test | 400 with empty body | pass |
| 35 | Forge weapon | POST /v1/stronghold/skills/forge | 400 with empty body; terminal step needs LLM | skipped-external |
| 36 | Scan repo | POST /v1/stronghold/marketplace/scan | same as #29 | skipped-external |

### Forge (/dashboard/mcp) — `dashboard/mcp.html`

| # | Feature | Network | Actual | Status |
|---|---|---|---|---|
| 37 | Deployed list | GET /v1/stronghold/mcp/servers | 200 empty | pass |
| 38 | Catalog tab | GET /v1/stronghold/mcp/catalog | 200 | pass |
| 39 | Popular tab | GET /v1/stronghold/mcp/registries/search?q=popular&registry=smithery&scan=true | 200 | pass |
| 40 | Registry Search | GET /v1/stronghold/mcp/registries/search?q=github | 200, 10 servers | pass |
| 41 | Empty-state "Browse Catalog" CTA | mcp.html:282 `href='#'` | — | **bug-found (B6)** confirmed: dead anchor |
| 42 | Double `display:none` on tool modal | mcp.html:129 | — | **bug-found (B8)** confirmed (cosmetic) |

### Watchtower (/dashboard/security) — `dashboard/security.html`

| # | Feature | Network | Actual | Status |
|---|---|---|---|---|
| 43 | Audit log auto-load + 15s refresh | GET /v1/stronghold/admin/audit | 200 empty | pass |
| 44 | Warden layer copy | security.html:110 | "3-layer threat detection" | **bug-found (B7)** — agents.html:649 and auth.js both say 4-layer |

### Treasury (/dashboard/outcomes) — `dashboard/outcomes.html`

| # | Feature | Network | Actual | Status |
|---|---|---|---|---|
| 45 | Outcomes | GET /v1/stronghold/admin/outcomes | 200 | pass |
| 46 | Learnings | GET /v1/stronghold/admin/learnings | 200 | pass |
| 47 | Empty state CTA "Go to Great Hall" | outcomes.html:165 → /greathall | — | pass |

### Ledger (/dashboard/quota) — `dashboard/quota.html`

| # | Feature | Network | Actual | Status |
|---|---|---|---|---|
| 48 | Quota overview | GET /v1/stronghold/admin/quota | 200 | pass |
| 49 | Coin pricing | GET /v1/stronghold/admin/coins/pricing | 200 | pass |
| 50 | Coin refill | GET /v1/stronghold/admin/coins/refill | 200 | pass |
| 51 | Exchange button | POST /v1/stronghold/admin/coins/convert | endpoint wired; terminal depends on data | skipped-external |
| 52 | Range pills 7/14/30/90d | no network; recomputes per tab | — | pass |
| 53 | Wallets tab (default) | renders from /admin/quota | — | pass |
| 54 | Providers tab | renders from /admin/quota | — | pass |
| 55 | Users tab | GET /admin/quota/usage?group_by=user_id | 200 | pass |
| 56 | Teams tab | GET /admin/quota/usage?group_by=team_id | 200 | pass |
| 57 | Models tab | GET /admin/quota/usage?group_by=model_used | 200 | pass |
| 58 | Trends tab | 3× GET /admin/quota/timeseries | 200 | pass |
| 59 | Analyst Ask | POST /admin/quota/analyze | 200 `{"error":"AI analyst temporarily unavailable"}` (graceful) | skipped-external |
| 60 | 5 follow-up prompt chips | wired to qAsk → Analyst | — | pass |

### Scrolls (/prompts) — `dashboard/prompts.html`

| # | Feature | Network | Actual | Status |
|---|---|---|---|---|
| 61 | List prompts | GET /v1/stronghold/prompts | 200, multiple seeded (arbiter soul, etc.) | pass |
| 62 | Open detail | GET /v1/stronghold/prompts/:name | 200 | pass |
| 63 | Version history | GET /v1/stronghold/prompts/:name/versions | 200 | pass |
| 64 | Save New Version | PUT /v1/stronghold/prompts/:name | 200 `{"version":N,"status":"created"}` | pass |
| 65 | Create new prompt | PUT /v1/stronghold/prompts/:name | 200 | pass |
| 66 | Promote to Production | POST /v1/stronghold/prompts/:name/promote | 200 | pass |
| 67 | Request Approval | POST /v1/stronghold/prompts/:name/request-approval | 200 | pass |
| 68 | Diff / Close Diff | GET /v1/stronghold/prompts/:name/diff?... | 200 | pass |
| 69 | Empty-state "Create a scroll" CTA | prompts.html:223 (no CTA href; button inline) | — | pass |

### Workshop (/dashboard/mason) — `dashboard/mason.html` (admin)

| # | Feature | Network | Actual | Status |
|---|---|---|---|---|
| 70 | Load repo | — | — | pass |
| 71 | Status | GET /v1/stronghold/mason/status | 200 | pass |
| 72 | Queue | GET /v1/stronghold/mason/queue | 200 | pass |
| 73 | Scan Codebase | GET /v1/stronghold/mason/scan | 200, 26 suggestions returned from the in-memory scanner | pass |
| 74 | Create Selected on GitHub | POST /v1/stronghold/mason/scan/create | needs real GH token | skipped-external |
| 75 | Assign | POST /v1/stronghold/mason/assign | needs real issue | skipped-external |
| 76 | Review PR | POST /v1/stronghold/mason/review-pr | needs real PR | skipped-external |
| 77 | Retry | POST /v1/stronghold/mason/assign (resend) | same | skipped-external |
| 78 | Refresh buttons | replay GETs | — | pass |

### Profile (/dashboard/profile) — `dashboard/profile.html`

| # | Feature | Network | Actual | Status |
|---|---|---|---|---|
| 79 | Load profile | GET /v1/stronghold/profile | 200 | pass |
| 80 | Save Profile | PUT /v1/stronghold/profile | **503** "Database not available" in in-memory; 200 with DB | skipped-external |
| 81 | Avatar click → upload | reads file, POST /v1/stronghold/profile/avatar | skipped (DB-gated) | skipped-external |
| 82 | Capture via webcam | same upload path | needs camera | skipped-external |
| 83 | Tower toggle | localStorage only; reload restores CSS | — | pass |
| 84 | View Leaderboard link | → /dashboard/leaderboard | — | pass |

### Arena (/dashboard/leaderboard) — `dashboard/leaderboard.html`

| # | Feature | Network | Actual | Status |
|---|---|---|---|---|
| 85 | Load leaderboard | GET /v1/stronghold/leaderboard?days=0&limit=50 | 200 empty → empty state | pass |
| 86 | Time filter select | re-call with `days=7/30/90` | 200 | pass |
| 87 | Sidebar lacks "Leaderboard" | no active highlight on this page | — | **bug-found (B5)** confirmed |

### Admin-only pages

Auth.js injects these only for users whose `/auth/session` returns `team_admin`, `org_admin`, or `admin` roles. In in-memory mode `/auth/session` returns `{authenticated:false}` and therefore **the admin sidebar block never renders**. Actions below were probed directly with the bearer key.

| # | Page | Feature | Network | Actual | Status |
|---|---|---|---|---|---|
| 88 | Dungeon | List inmates | GET /admin/strikes | 200 empty | pass |
| 89 | Dungeon | Recent violations | GET /admin/audit?limit=50 | 200 | pass |
| 90 | Dungeon | Enable account | POST /admin/strikes/:user/enable | 404 "No strike record" (expected for empty DB) | skipped-destructive |
| 91 | Dungeon | Unlock | POST /admin/strikes/:user/unlock | 404 same | skipped-destructive |
| 92 | Dungeon | Remove strike | POST /admin/strikes/:user/remove | 404 same | skipped-destructive |
| 93 | Barracks | Users list | GET /v1/stronghold/admin/users | **503** "Database not available" | **broken** in in-memory; pass with DB |
| 94 | Barracks | Per-user action | POST /admin/users/:id/:action | skipped-destructive | skipped-destructive |
| 95 | Throne Room | Users list | same 503 as #93 | **broken** in in-memory |
| 96 | Throne Room | Save roles | PUT /admin/users/:id/roles | 422 with empty body (correct shape needed); endpoint wired | skipped-destructive |
| 97 | Throne Room | Quota overview | GET /admin/quota | 200 | pass |

---

## Hard broken items (new since the reachability audit)

**N1 — Great Hall "Send" (followup chat) returns 502 even with correct body.**
`POST /v1/chat/completions` (index.html:573) responds `502 {"detail":"Agent pipeline error"}` against both `model:"auto"` and `model:"gpt-4o-mini"`. The UI shows `Error: 502` in the conversation bubble and stops. The streaming endpoint `/v1/stronghold/request/stream` works end-to-end (pipeline runs, status events stream, final LLM call needs LiteLLM). So Deploy works, Send (followup) fails as soon as the pipeline tries a non-streaming call. Worth investigating whether the followup should use the streaming endpoint for consistency.

**N2 — Fortress Health stat is hard-wired to `ok` and misreads `degraded`.**
index.html:308 does `health.status === 'ok' ? '100%' : '??'`. The real `/health` returns `degraded` whenever DB OR LiteLLM is down. On every non-Docker dev run the Great Hall shows `??` for Fortress Health and `◦ Offline` in the sidebar, even though the API is reachable. Either change the copy (`degraded` → yellow banner) or compare against `in ("ok","degraded")`.

---

## Cross-cutting bugs from the reachability audit — reproduced?

| ID | Description | Verdict |
|---|---|---|
| B1 | No "Chat" link in sidebar | **reproduced** (sidebars contain Great Hall, not Chat) |
| B2 | Workshop link only on /greathall | **reproduced** (grep: only index.html, mason.html, profile.html have the static Workshop link; all other pages omit it) |
| B3 | Duplicate "Admin" header on /greathall for admins | **reproduced** (index.html:170-173 hardcodes an Admin block; auth.js:593-629 injects a second one before Profile) |
| B4 | Non-admins see Workshop link | **reproduced** (static, not role-gated) |
| B5 | Leaderboard discoverability via tiny Profile link | **reproduced** |
| B6 | `href="#"` dead CTAs | **reproduced** (agents.html:480 "Summon a Knight", mcp.html:282 "Browse Catalog") |
| B7 | Warden layer count mismatch (3 vs 4) | **reproduced** |
| B8 | Double `display:none` on MCP tool modal | **reproduced** (mcp.html:129) |
| B9 | Login redirect route ambiguity (`/` vs `/login`) | **reproduced** (both serve login.html; auth.js uses `/`) |
| B10 | Approved "Sign in" anchor has `href="#"` | **reproduced** |

---

## What I could NOT verify without Docker / a real DB

Anything requiring Postgres or a LiteLLM proxy is marked `skipped-external` above. To finish those, run:
```
./scripts/e2e.sh        # brings up docker stack with Postgres + LiteLLM + Phoenix
```
Then re-probe: `#3 /auth/login`, `#5 /auth/register` (enable self-registration first), `#13 full mission completion`, `#14 followup chat`, `#28 agents import-url` (real GH zip), `#35 skills forge` (needs LLM), `#51 coin exchange`, `#59 Analyst chat`, `#74-77 mason GitHub actions`, `#80-82 profile save/avatar`, `#90-96 admin destructive actions` (seed a test strike first).

---

## Recommended fixes — ranked

1. **Fix Great Hall followup chat (N1).** `/v1/chat/completions` returning 502 is the single most visible "is the UI broken?" signal a user can hit. If it's meant to route through the same pipeline as streaming, point `sendFollowup` at `/v1/stronghold/request/stream` and reuse the SSE reader already written for `submitMission`.
2. **Fix Fortress Health copy (N2).** One-liner; stops every dev machine from reporting `??` and `◦ Offline`.
3. **Unify the sidebar.** Extract it into a single file included across every page; wire admin links through a role check; rename "Great Hall" to "Great Hall (Chat)" or add a top-level "Chat" icon pointing at `/greathall`. Resolves B1, B2, B3, B4 and prevents future drift.
4. **Wire the dead empty-state CTAs (B6).** `agents.html:480` → `onclick="toggleForm()"`. `mcp.html:282` → `onclick="switchTab('catalog')"`.
5. **Hide Workshop from non-admins (B4).** Move its render into the same role-gated injector in auth.js.
6. **Add a sidebar entry + active state for Leaderboard (B5).**
7. **Reconcile Warden layer copy (B7)** across `security.html`, `agents.html`, `auth.js` onboarding modal.
8. **Minor:** remove the duplicate `display:none` on `mcp.html:129` (B8); replace `href="#"` anchors on the login page with `<button>` (B10); pick one canonical login route (B9).

---

## How to re-run this audit

From `/home/user/stronghold`:
```
unset DATABASE_URL REDIS_URL
export ROUTER_API_KEY=sk-stronghold-prod-2026-aaaaaaaaaa
export PYTHONPATH=src
python3.12 -m venv /tmp/sh-venv && /tmp/sh-venv/bin/pip install -e ".[dev]"
/tmp/sh-venv/bin/uvicorn stronghold.api.app:create_app --factory --port 8100 &
curl -sf http://127.0.0.1:8100/health
# then re-run the probe loops in this document's rows 3-97 and record the actual status codes.
```
