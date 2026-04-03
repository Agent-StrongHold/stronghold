# Builders 2.0 Changeover

## Goal

Replace the current in-process Frank/Mason flow with a separate, versioned delivery runtime that takes a GitHub issue to a mergeable PR, while Stronghold core stays up and remains the control plane.

## Why Change

Current state:

- Frank/Mason logic is embedded in the main app
- workflow state is mixed with execution logic
- upgrades require touching the main codebase/runtime
- long-running delivery work is not isolated from normal agents

Target state:

- Stronghold core owns orchestration, state, gates, UI, and GitHub reporting
- Builders runtime owns delivery execution for `frank`, `mason`, and `auditor`
- generic GitAgent-style agents stay on a separate generic runtime
- builders can be versioned, deployed, and rolled back independently

## Top-Level Architecture

Services:

- `stronghold-core`
- `builders-runtime`
- `generic-agent-runtime`
- `workspace-service`
- `github-service`
- `artifact-store`
- `event-bus`

Separation:

- `stronghold-core` never imports builders code
- `builders-runtime` is its own deployable unit
- workers are stateless
- workflow state lives in Stronghold core

## Runtime Responsibilities

`stronghold-core`

- create and track builder runs
- choose stage/role
- evaluate gates
- retry, fail, block, or advance
- update UI and GitHub
- store artifacts and event history

`builders-runtime`

- execute stage work for `frank`, `mason`, or `auditor`
- load prompts/tools by role and stage
- read/write workspace through services
- return artifacts, logs, and claims
- hold no durable workflow state

`generic-agent-runtime`

- run normal prompt/tool GitAgent-style agents
- separate sandbox and release cycle from builders

## Why Frank, Mason, and Auditor Share One Runtime

Shared:

- Docker image
- server
- clients
- contracts
- artifact format
- tracing/logging

Different:

- prompts
- stage handlers
- tool allowlist
- output artifacts
- execution style

This keeps delivery logic together without making the roles indistinguishable.

## Control Flow

1. User or webhook creates builder run in `stronghold-core`
2. Core prepares workspace
3. Core sends typed stage task to `builders-runtime`
4. Runtime selects `frank`, `mason`, or `auditor`
5. Runtime returns artifacts and claims
6. Core evaluates gates
7. Core advances, retries, blocks, or fails
8. Core posts progress to UI and GitHub
9. Core opens/updates PR when all gates pass

## Contracts

Core request to builders:

- `run_id`
- `stage`
- `role`
- `repo`
- `issue_number`
- `branch`
- `workspace_ref`
- `artifact_refs`
- `prompt_version`
- `runtime_version`
- `context`

Builders response:

- `run_id`
- `stage`
- `role`
- `status`
- `summary`
- `artifact_refs`
- `claims`
- `logs`
- `metrics`

Supporting contracts:

- `ArtifactRef`
- `StageEvent`
- `WorkerStatus`
- `GateResult`

## State Model

Owned by `stronghold-core`:

- run id
- repo / issue / branch / PR
- current stage
- current role
- current status
- attempt counts
- workspace ref
- artifact refs
- gate results
- issue comment ids
- UI status
- timestamps
- builder runtime version
- prompt version

Rule:

- if `builders-runtime` restarts, no run state is lost

## Workflow Families

Builders contains more than one workflow family.

### Issue-To-PR Workflow

Roles:

- `frank`
- `mason`

Trigger:

- GitHub issue assignment or explicit builder-run creation

Purpose:

- turn an issue into a mergeable PR

### PR-Audit Workflow

Role:

- `auditor`

Trigger:

- PR opened
- PR updated
- explicit audit request

Purpose:

- review a PR against coding practices, risk signals, and delivery expectations
- approve, block, or send work back for rework

### Learning Workflow

Roles:

- `auditor`
- learning extraction components
- future `frank` and `mason` runs

Trigger:

- structured audit findings
- explicit review outcomes

Purpose:

- convert review findings into durable learning artifacts
- feed those learnings into future Builders runs
- measure whether violations trend downward over time

Both workflows share the same Builders platform, contracts, services, and runtime image.

## Learning Model

The old single-agent assumption is no longer sufficient.

Builders is now a co-agent delivery system, so learning targets must be more specific than only `agent_id="mason"`.

Learning targets should support:

- `mason`
- `frank`
- `builders_workflow`

Examples:

- implementation-pattern failures teach `mason`
- acceptance-criteria or test-design failures teach `frank`
- handoff or stage-boundary failures teach `builders_workflow`

The original RLHF-style design remains useful as behavior:

- structured audit findings become durable learnings
- future runs retrieve relevant learnings
- violation trends are measured over time

But the architecture changes:

- audit findings become artifacts first
- Stronghold core or a learning pipeline decides where the learning should be stored
- future Builders runs receive learnings as context through contracts, not hidden in-process state

## Artifact Boundary

Artifacts are the handoff layer between stages and between Frank/Mason:

- issue snapshot
- analysis
- acceptance criteria
- test plan
- test files
- implementation summary
- audit report
- learning artifact
- validation report
- CI report
- coverage report
- PR summary
- failure report

Rule:

- workers communicate through artifacts, not freeform in-memory conversation

## Service Boundaries

`workspace-service`

- create isolated workspace per run
- manage branch/worktree
- cleanup/archive

`github-service`

- fetch issue/PR metadata
- post/update issue comments
- open/update PRs
- attach checks/status where needed

`artifact-store`

- persist artifacts by run/stage/version
- expose refs, metadata, retention policy

`event-bus`

- emit run/stage lifecycle events for UI and automation

## Sandbox Model

Generic runtime:

- prompt/tool-based agents
- low-stakes or standard agent work

Builders runtime:

- delivery-specific sandbox
- repo modification
- tests, lint, typecheck, coverage
- GitHub side effects through services only

Important rule:

- builders do not call raw infra directly when avoidable
- they go through platform services for control and auditability

## Versioning

Independently version:

- `stronghold-core`
- `builders-runtime`
- prompts
- gate rules
- contracts

This allows:

- hot-swapping builders
- rolling back builders without restarting core
- A/B testing builder runtime versions

## Repo Strategy

Use a monorepo now.

Structure:

- `apps/stronghold`
- `apps/builders-runtime`
- `apps/generic-agent-runtime`
- `packages/contracts`
- `services/workspace-service`
- `services/github-service`
- `services/artifact-store`

Rule:

- treat them as microservices in deployment
- keep them in one repo until contracts and ownership stabilize

## Stages

Stages exist, but architecture comes first.
For the changeover, the only architectural requirement is:

- every stage is a persisted unit of work
- every stage has typed inputs/outputs
- stage advancement is decided by core, not runtime

This applies to both:

- issue-to-PR stages
- PR-audit stages

## Gates

Same rule:

- deterministic gates live in core or dedicated gate services
- workers may make claims
- workers do not self-certify completion

## Migration Plan

Phase 1:

- add contracts package
- add builders runtime skeleton
- add builder run model in core
- move Frank/Mason behind contracts without changing behavior much

Phase 2:

- extract workflow state from current Mason strategy into core
- make builders runtime stateless
- move progress reporting into core

Phase 3:

- route real runs through `builders-runtime`
- keep old path as fallback

Phase 4:

- add runtime version pinning and rollout controls
- support canary / A-B runs

Phase 5:

- remove old embedded Frank/Mason pipeline from main runtime

## Success Criteria

- Stronghold core remains up while builders are upgraded
- Frank/Mason can be versioned independently
- runs survive builder runtime restarts
- all progress is visible in UI and GitHub
- artifacts and gate decisions are durable
- builder failures do not destabilize generic agents

## Design Rules

- core owns truth
- runtime executes
- artifacts are the handoff boundary
- state is external
- builders are isolated from generic agents
- builders are versioned independently from core

## Next Document

The next useful document after this one is the concrete repo refactor map:

- what folders move
- what modules are retired
- what APIs get added first
