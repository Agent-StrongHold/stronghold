"""LLM output extraction utilities for the Builders pipeline.

Parse structured content (Python code, JSON, Gherkin) from LLM text responses.
All functions are pure — no I/O, no side effects.

Retry-aware: each extractor returns a result or raises ExtractionError with
a diagnostic message suitable for feeding back to the LLM.
"""

from __future__ import annotations

import json
import re


class ExtractionError(ValueError):
    """Raised when LLM output cannot be parsed into the expected format.

    The message is designed to be fed back to the LLM as correction context.
    """


def extract_python_code(text: str) -> str:
    """Extract Python code from LLM response, stripping markdown fences.

    Tries in order:
    1. ```python ... ``` fenced block
    2. ``` ... ``` generic fenced block
    3. Heuristic: lines that look like Python

    Raises ExtractionError if no valid Python found.
    """
    # Try ```python block
    match = re.search(r"```python\s*\n(.*?)```", text, re.DOTALL)
    if match:
        code = match.group(1).strip()
        if code:
            return code

    # Try generic ``` block
    match = re.search(r"```\s*\n(.*?)```", text, re.DOTALL)
    if match:
        code = match.group(1).strip()
        if code and _looks_like_python(code):
            return code

    # Heuristic: find contiguous lines that look like Python
    lines = text.strip().splitlines()
    code_lines: list[str] = []
    in_code = False
    for line in lines:
        stripped = line.strip()
        if not in_code:
            if stripped.startswith(("import ", "from ", "def ", "class ", "@", "#!")):
                in_code = True
                code_lines.append(line)
        else:
            code_lines.append(line)

    if code_lines:
        code = "\n".join(code_lines).strip()
        if _looks_like_python(code):
            return code

    raise ExtractionError(
        "Could not extract Python code from your response. "
        "Wrap your code in ```python ... ``` fences. "
        "Output ONLY code — no prose, no explanation."
    )


def extract_json(text: str) -> dict:
    """Extract JSON object from LLM response.

    Tries in order:
    1. ```json ... ``` fenced block
    2. First { ... } block in text
    3. Raw text as JSON

    Raises ExtractionError with the parse error for LLM feedback.
    """
    candidates: list[str] = []

    # Try ```json block
    match = re.search(r"```json\s*\n(.*?)```", text, re.DOTALL)
    if match:
        candidates.append(match.group(1).strip())

    # Try generic ``` block
    match = re.search(r"```\s*\n(.*?)```", text, re.DOTALL)
    if match:
        candidates.append(match.group(1).strip())

    # Try first { ... } block (greedy for nested)
    match = re.search(r"\{.*\}", text, re.DOTALL)
    if match:
        candidates.append(match.group(0))

    # Raw text
    candidates.append(text.strip())

    last_error = ""
    for candidate in candidates:
        try:
            result = json.loads(candidate)
            if isinstance(result, dict):
                return result
            last_error = f"Parsed JSON but got {type(result).__name__}, expected object"
        except json.JSONDecodeError as e:
            last_error = str(e)

    raise ExtractionError(
        f"Could not extract valid JSON from your response. Parse error: {last_error}. "
        "Wrap your JSON in ```json ... ``` fences. "
        "Output ONLY the JSON object — no prose before or after."
    )


def extract_gherkin_scenarios(text: str) -> list[str]:
    """Extract Gherkin Scenario blocks from LLM response.

    Returns list of individual scenario strings, each starting with 'Scenario:'.
    Raises ExtractionError if fewer than 1 valid scenario found.
    """
    # Strip markdown fences
    clean = re.sub(r"```(?:gherkin)?\s*\n?", "", text)
    clean = re.sub(r"```", "", clean)

    # Split on 'Scenario:' keeping the delimiter
    parts = re.split(r"(?=Scenario:)", clean)
    scenarios: list[str] = []
    for part in parts:
        stripped = part.strip()
        if stripped.startswith("Scenario:") and _has_given_when_then(stripped):
            scenarios.append(stripped)

    if not scenarios:
        raise ExtractionError(
            "Could not extract valid Gherkin scenarios from your response. "
            "Each scenario must start with 'Scenario:' and contain Given, When, and Then steps. "
            "Output ONLY Gherkin — no prose, no explanation."
        )

    return scenarios


def sanitize_filename(text: str) -> str:
    """Turn arbitrary text into a safe filename component."""
    clean = re.sub(r"[^a-z0-9]+", "_", text[:40].lower())
    return clean.strip("_") or "unnamed"


def _looks_like_python(code: str) -> bool:
    """Quick heuristic: does this text look like Python code?"""
    indicators = ("import ", "from ", "def ", "class ", "async def ", "assert ", "return ")
    return any(line.strip().startswith(indicators) for line in code.splitlines())


def _has_given_when_then(scenario: str) -> bool:
    """Check that a Gherkin scenario has all three step types."""
    lower = scenario.lower()
    return "given" in lower and "when" in lower and "then" in lower
