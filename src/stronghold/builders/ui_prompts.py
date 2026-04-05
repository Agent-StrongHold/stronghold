"""Prompt templates for the UI Builders pipeline (Piper + Glazier).

Parallel to prompts.py (Frank + Mason) but specialized for dashboard
HTML/CSS/JS issues. Uses the same {{double_brace}} variable convention.
"""

from __future__ import annotations

# -- Piper prompts -----------------------------------------------------------

PIPER_ANALYZE_UI = """\
Analyze this UI issue for the Stronghold dashboard.

Issue #{{issue_number}}: {{issue_title}}

{{issue_content}}

Target file content:
{{source_context}}

## Your Task

1. **Classify the rendering model** for each affected element:
   - STATIC: Element exists in HTML markup
   - JS-RENDERED: Element is built by JavaScript (createElement, innerHTML)
   - CSS-ONLY: Change is purely CSS (classes, transitions)
   - HYBRID: HTML exists but JS modifies it

2. **Identify affected code sections**: Which lines or functions need changes?

3. **List requirements**: What specifically needs to change?

Output ONLY a JSON object:
{"rendering_model": "static|js_rendered|css_only|hybrid",
 "affected_elements": [{"element": "...", "model": "...", "location": "..."}],
 "requirements": ["..."],
 "approach": "..."}
"""

PIPER_UI_ACCEPTANCE_CRITERIA = """\
Write acceptance criteria for this UI issue.

Issue #{{issue_number}}: {{issue_title}}

Rendering model: {{rendering_model}}
Requirements:
{{requirements}}

{{feedback_block}}

## CRITICAL CONSTRAINT: No Browser Available

All criteria will be tested by READING THE FILE with Python. There is NO
browser, NO DOM rendering, NO click simulation.

Write criteria that are statically verifiable:

For STATIC elements:
  - GOOD: "HTML file contains the class scroll-smooth on the html element"
  - BAD: "Page scrolls smoothly when clicking nav links"

For JS-RENDERED elements:
  - GOOD: "JavaScript code that builds cards sets .title on description element"
  - BAD: "Tooltip appears when hovering over truncated description"

For CSS changes:
  - GOOD: "File contains CSS transition property for width changes"
  - BAD: "Progress bar animates from 0% to actual value"

Rules:
- Each scenario MUST be verifiable by reading the file
- Minimum 3 scenarios
- Cover the fix, accessibility (aria attributes), and a negative case

Output ONLY Gherkin scenarios. No commentary.
Start directly with 'Scenario:'
"""

# -- Glazier prompts ---------------------------------------------------------

GLAZIER_WRITE_UI_TEST = """\
Write a pytest test file for this UI acceptance criterion:

{{criterion}}

Target file: {{file_path}}
Rendering model: {{rendering_model}}

Source context:
{{source_context}}

{{feedback_block}}

CRITICAL RULES:
- Read the HTML file with `Path("{{file_path}}").read_text()`
- For STATIC elements: check for strings in the HTML markup
- For JS-RENDERED elements: check for patterns in the JavaScript code
  (e.g., `.title =`, `.classList.add(`, `.setAttribute(`)
- For CSS: check for class names or CSS properties in style blocks
- NEVER import FastAPI, TestClient, or httpx -- this is an HTML file test
- NEVER check for static HTML attributes on JS-rendered elements
- Include `from pathlib import Path` and define `DASHBOARD_DIR`

Output ONLY Python pytest code. No explanation.
"""

GLAZIER_APPEND_UI_TEST = """\
Add ONE new test function to this existing test file.

New criterion to test:
{{criterion}}

Rendering model: {{rendering_model}}

Existing test file:
```python
{{existing_code}}
```

{{feedback_block}}

CRITICAL RULES:
- Return the COMPLETE file with the new test APPENDED
- Do NOT modify existing test functions
- Do NOT duplicate imports
- Match the test approach used in existing tests (HTML check vs JS check)

Output ONLY the complete Python file. No explanation.
"""

GLAZIER_IMPLEMENT_UI = """\
These UI tests are failing:

```python
{{test_code}}
```

Test output:
```
{{pytest_output}}
```

Current file `{{file_path}}`:
```html
{{source_code}}
```

Rendering model: {{rendering_model}}
Issue: {{issue_content}}

{{feedback_block}}

## Implementation Rules

For STATIC fixes: modify the HTML markup directly.
For JS-RENDERED fixes: modify the `<script>` block that builds the element.
  Find the createElement/innerHTML section and add the fix THERE.
For CSS fixes: add to the `<style>` block or add Tailwind classes.

- Do NOT add HTML attributes that JavaScript will overwrite at runtime
- Use const/let in JavaScript, never var
- Prefer Tailwind classes over custom CSS
- Add aria attributes for accessibility

Output ONLY the complete updated HTML file. No explanation.
"""

# -- Auditor stage context for UI pipeline -----------------------------------

AUDITOR_STAGE_UI_ANALYZED = """\
purpose: Understand the UI problem and classify the rendering model
scope: Rendering model classification, affected elements, requirements
out_of_scope: Implementation details, test code
checklist:
- Rendering model is classified (static, js_rendered, css_only, or hybrid)
- At least one affected element identified with its model
- Requirements are listed and match the issue
rejection_format: State WHICH item failed and what is missing
"""

AUDITOR_STAGE_UI_CRITERIA = """\
purpose: Define statically verifiable acceptance criteria
scope: Gherkin scenarios that can be tested by reading the file
out_of_scope: >
  Criteria requiring browser execution, DOM rendering, or visual
  inspection. These are HTML files tested with Python file reads.
checklist:
- At least 3 Gherkin scenarios present
- Each scenario is verifiable by reading the file (no browser needed)
- Criteria match the rendering model (JS checks for JS-rendered elements)
- At least one accessibility criterion (aria attributes)
rejection_format: State WHICH scenario requires a browser and suggest a static alternative
"""

AUDITOR_STAGE_UI_TESTS = """\
purpose: Create pytest tests that verify HTML/JS/CSS changes by reading the file
scope: Test file exists, compiles, tests match rendering model
out_of_scope: >
  Whether tests PASS (TDD -- they should fail initially).
  Only SyntaxError and ImportError are real problems.
  Do NOT reject for AssertionError.
checklist:
- Test file created
- Pytest ran without SyntaxError or ImportError
- Tests read the HTML file (not using TestClient or FastAPI)
- Tests check the correct layer (JS source for JS-rendered, HTML for static)
rejection_format: State WHICH test checks the wrong layer and why
"""

AUDITOR_STAGE_UI_IMPLEMENTED = """\
purpose: Verify the UI fix was applied to the correct layer
scope: File modified, changes in correct location (markup vs script block)
out_of_scope: >
  Visual appearance, browser rendering, CSS animation timing.
  Pytest test failures -- TDD stage handles that.
checklist:
- Target HTML file was modified
- Changes are in the correct layer (script block for JS-rendered, markup for static)
- No var usage in JavaScript (must use const/let)
rejection_format: State WHERE the change was made and WHERE it should be
"""

AUDITOR_STAGE_UI_VERIFIED = """\
purpose: Final check -- confirm commits and file validity
scope: Git log, file structure, accessibility
out_of_scope: >
  Re-reviewing implementation decisions. Test pass/fail counts.
  Do NOT reject because some tests fail.
checklist:
- Git log shows at least one commit
- HTML file still has valid structure (html, head, body tags)
- Pytest output is present (was invoked)
rejection_format: State WHICH check failed, quoting evidence
"""

# -- Registry ----------------------------------------------------------------

UI_PROMPT_DEFAULTS: dict[str, str] = {
    # Piper
    "builders.piper.analyze_ui": PIPER_ANALYZE_UI,
    "builders.piper.ui_acceptance_criteria": PIPER_UI_ACCEPTANCE_CRITERIA,
    # Glazier
    "builders.glazier.write_ui_test": GLAZIER_WRITE_UI_TEST,
    "builders.glazier.append_ui_test": GLAZIER_APPEND_UI_TEST,
    "builders.glazier.implement_ui": GLAZIER_IMPLEMENT_UI,
    # Auditor (UI stages)
    "builders.auditor.stage.ui_analyzed": AUDITOR_STAGE_UI_ANALYZED,
    "builders.auditor.stage.ui_criteria_defined": AUDITOR_STAGE_UI_CRITERIA,
    "builders.auditor.stage.ui_tests_written": AUDITOR_STAGE_UI_TESTS,
    "builders.auditor.stage.ui_implemented": AUDITOR_STAGE_UI_IMPLEMENTED,
    "builders.auditor.stage.ui_verified": AUDITOR_STAGE_UI_VERIFIED,
}
