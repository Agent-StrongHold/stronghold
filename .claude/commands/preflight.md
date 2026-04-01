Run the full Stronghold CI-equivalent check suite locally. This is the "did I break anything?" command.

## Process

Run ALL of these checks in parallel using Bash tools:

1. **Ruff lint**: `cd /vmpool/github/stronghold && ruff check src/stronghold/ 2>&1`
2. **Ruff format**: `cd /vmpool/github/stronghold && ruff format --check src/stronghold/ 2>&1`
3. **Mypy**: `cd /vmpool/github/stronghold && mypy src/stronghold/ --strict 2>&1`
4. **Bandit**: `cd /vmpool/github/stronghold && bandit -r src/stronghold/ -ll -q 2>&1`
5. **Pytest (critical)**: `cd /vmpool/github/stronghold && pytest tests/ -x -q -m critical 2>&1`

After all 5 complete, produce a single dashboard:

```
PREFLIGHT RESULTS
─────────────────
Ruff lint:    PASS / FAIL (N issues)
Ruff format:  PASS / FAIL (N files)
Mypy:         PASS / FAIL (N errors)
Bandit:       PASS / FAIL (N issues)
Tests:        PASS / FAIL (N passed, M failed)
─────────────────
VERDICT: READY TO COMMIT / BLOCKING ISSUES
```

If any check fails:
- Show the first 10 lines of errors for each failing check
- Suggest the specific fix command (e.g., `ruff format src/stronghold/` for format issues)

If all pass and the user asked for a full run, also run:
`cd /vmpool/github/stronghold && pytest tests/ -x -q -m "not perf and not e2e" 2>&1`

Do NOT auto-fix anything. Report only. The developer decides what to fix.
