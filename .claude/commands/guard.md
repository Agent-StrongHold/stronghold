Architecture compliance check. Enforces Stronghold's "No Code Without Architecture" build rule.

Given: $ARGUMENTS (a module path, feature name, or description of what's being built)

## Process

1. **Read ARCHITECTURE.md**: `Read /vmpool/github/stronghold/ARCHITECTURE.md`

2. **Search for the module/feature**: Check if the given argument appears in ARCHITECTURE.md. Search for:
   - The module name (e.g., "quota", "sentinel", "memory")
   - The feature concept (e.g., "rate limiting", "skill marketplace")
   - Related section headings

3. **Check source tree**: If implementing a new file, check if it already exists:
   - `Glob` for `src/stronghold/**/{name}*`
   - `Glob` for `tests/**/{name}*`

4. **Produce verdict**:

If found in ARCHITECTURE.md:
```
GUARD: CLEARED
Module: {name}
Architecture section: §{section_number} — {section_title}
Existing files: {list or "none yet"}
Test files: {list or "none yet — create these first (TDD)"}
```

If NOT found:
```
GUARD: BLOCKED
Module: {name}
Status: Not documented in ARCHITECTURE.md

You must add this module to ARCHITECTURE.md before writing code.
Suggested section: §{best_fit_section}
Required fields: purpose, API surface, security boundaries, data flow
```

5. **Check related protocols**: If the feature needs a new protocol, check if it exists in `src/stronghold/protocols/`. If not, remind about the "Every Protocol Needs a Noop/Fake" rule and suggest running `/scaffold-protocol`.

6. **Check test coverage plan**: Remind about TDD — test stubs must exist before implementation begins.
