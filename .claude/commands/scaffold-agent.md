Generate a complete new agent definition for Stronghold.

Given: $ARGUMENTS (agent name and brief description, e.g., "herald — voice and notification specialist")

## Pre-checks

1. **Parse input**: Extract agent name (lowercase, hyphenated) and description.
2. **Guard check**: Verify the agent is described in ARCHITECTURE.md. If not, stop and tell the user to run `/guard {name}` first and update ARCHITECTURE.md.
3. **Collision check**: Verify the agent name doesn't already exist in `agents/` or `src/stronghold/agents/`.

## Generate files

### 1. Agent definition: `agents/{name}/agent.yaml`

Use the Artificer agent as a template (`agents/artificer/agent.yaml`). Adapt:
- `name`, `description` from user input
- `reasoning.strategy`: ask the user or infer (direct for simple, react for tool-using, plan_execute for multi-step, delegate for triage)
- `tools`: infer from the agent's role
- `trust_tier`: default to t2 unless the agent needs elevated access
- `memory.scope`: default to agent
- `rules`: include at least the 3 core rules (tests, architecture, no secrets)

### 2. System prompt: `agents/{name}/SOUL.md`

Write a focused system prompt (10-15 lines max) covering:
- Who the agent is (one sentence)
- Its process (numbered steps)
- Key constraints

### 3. Test stubs: `tests/agents/test_{name_underscored}.py`

Generate test stubs with `pytest.skip("Not implemented yet")` for:
- `test_{name}_identity_loads` — agent.yaml parses correctly
- `test_{name}_handles_happy_path` — basic request → response
- `test_{name}_warden_scans_output` — output passes Warden
- `test_{name}_respects_boundaries` — rejects out-of-scope requests

Use fixtures from `tests/conftest.py` and fakes from `tests/fakes.py`.

### 4. Intent registration stub

Show the user what to add to the intent registry (classifier config or task_types in `config/example.yaml`):
- New task_type entry with keywords
- Mapping to the new agent name

## After generation

- List all created files
- Remind: "Run `/preflight` to verify nothing broke"
- Remind: "Implement the test stubs before writing agent logic (TDD)"
