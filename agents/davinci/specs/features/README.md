# Da Vinci — Gherkin Feature Files

Behaviour specs for the canvas / document subsystems. One `.feature` per spec
doc in `../`. Each feature lists happy paths, edge cases, and parametric
scenario outlines.

## Convention

- One `Feature:` per file, named after the spec doc (`<spec>.feature`).
- `Background:` for shared setup.
- `@p0` / `@p1` / `@p2` tag per scenario for phasing.
- `@critical` for the must-pass-on-every-change scenarios.
- `@security` for tenant isolation, injection, upload validation.
- `@perf` for performance-bounded scenarios (run gated, not in default suite).

## Naming

Scenarios use the form `<verb> <subject> <qualifier>`. Examples:

- `Adding an effect appends to the stack`
- `Disabling an effect skips it during render`
- `Inpaint with empty mask is a no-op`

## Mapping to tests

Each scenario maps 1:1 to a pytest test under
`tests/tools/test_canvas_<subsystem>.py` named:

```
test_<feature_slug>__<scenario_slug>
```

For example:

```
Feature: Effect stack
  Scenario: Adding an effect appends to the stack
```

becomes:

```python
def test_effect_stack__adding_an_effect_appends_to_the_stack() -> None:
    ...
```

We do NOT use `pytest-bdd` (extra dep, slower import). Gherkin lives as
documentation; test names are the link. The CI lints feature/test parity via a
small test that walks `features/` and checks every scenario has a matching
test (added in the test phase).
