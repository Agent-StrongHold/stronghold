Quick bug investigation workflow. Trace a symptom through Stronghold's request flow to find the root cause.

Given: $ARGUMENTS (error message, symptom description, or failing test name)

## Process

1. **Classify the symptom**: Determine which layer is likely involved:
   - HTTP/API error → `src/stronghold/api/`
   - Auth failure → `src/stronghold/security/auth/`
   - Classification wrong → `src/stronghold/classifier/`
   - Wrong model selected → `src/stronghold/router/`
   - Warden false positive/negative → `src/stronghold/security/warden/`
   - Memory/learning issue → `src/stronghold/memory/`
   - Agent misbehavior → `src/stronghold/agents/`
   - Config/startup → `src/stronghold/config/`

2. **Trace the request flow**: Follow the path from CLAUDE.md's Request Flow diagram:
   ```
   POST /v1/chat/completions → Auth → Warden → Classifier → Router → Agent → Response
   ```
   Read the relevant source files at each stage.

3. **Search for the error**: Run in parallel:
   - `Grep` for the exact error message in `src/`
   - `Grep` for the error message in `tests/`
   - If it's a test failure: read the test file and the code it tests

4. **Check recent changes**: `git log --oneline -20 -- {relevant_files}` to see if a recent commit introduced the issue.

5. **Identify root cause**: Narrow down to:
   - The specific file and function
   - The condition that triggers the bug
   - Why the existing tests didn't catch it

6. **Produce triage report**:

```
TRIAGE REPORT
─────────────
Symptom:    {what the user reported}
Component:  {which module/layer}
Root cause: {specific function + condition}
File:       {path}:{line_number}
Introduced: {commit hash if identifiable, or "pre-existing"}

Suggested fix:
{1-3 sentences describing the fix approach}

Test to add:
{test function name and what it should assert}
```

7. **If ambiguous**: List the top 2-3 candidate causes ranked by likelihood. Ask the user to provide more context to narrow it down.

Do NOT fix the bug. Diagnose only. The developer decides what to change.
