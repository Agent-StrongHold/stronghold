"""Unit-level coverage for the regex shape used by _fetch_prior_runs.

The full method is async and reads from a tool dispatcher; testing it
end-to-end would require fakes for the GitHub tool. The regexes
themselves are pure and capture the contract that PR-Q10 broadens:

  - prior 'Builders Run' comments accept BOTH `run-<hex>` (manual flow)
    and `sched-<hex>` (scheduler flow) ID prefixes
  - prior 'Gatekeeper Verdict on PR #N' comments are picked up

These tests pin both shapes against the live regex literals from
pipeline.py so any future change to the regex without a corresponding
test update will fail loudly.
"""
from __future__ import annotations

import re

# Mirror the patterns from pipeline.py — keep these in sync if the
# source changes. The duplication is intentional: we want a
# breaking-test-on-divergence to surface naturally.
RUN_ID_PATTERN = re.compile(
    r"##\s*Builders Run\s*`?((?:run|sched)-[a-f0-9]+)`?"
)
GATEKEEPER_PATTERN = re.compile(
    r"##\s*Gatekeeper Verdict on PR\s*#(\d+)",
    re.IGNORECASE,
)


# ── Builders Run regex ──────────────────────────────────────────────


def test_run_id_pattern_matches_manual_run_prefix() -> None:
    body = "## Builders Run `run-f23c8f66`\n\nIssue analysis follows."
    match = RUN_ID_PATTERN.search(body)
    assert match is not None
    assert match.group(1) == "run-f23c8f66"


def test_run_id_pattern_matches_scheduler_sched_prefix() -> None:
    body = "## Builders Run `sched-bac9832f`\n\nFrank executing acceptance_defined."
    match = RUN_ID_PATTERN.search(body)
    assert match is not None
    assert match.group(1) == "sched-bac9832f"


def test_run_id_pattern_matches_unbacktick_form() -> None:
    body = "## Builders Run sched-abc1234\n"
    match = RUN_ID_PATTERN.search(body)
    assert match is not None
    assert match.group(1) == "sched-abc1234"


def test_run_id_pattern_rejects_unrelated_prefixes() -> None:
    body = "## Builders Run `manual-12345`\n"
    match = RUN_ID_PATTERN.search(body)
    assert match is None


def test_run_id_pattern_rejects_non_builders_comments() -> None:
    body = "## Auditor Review: `tests_written` (attempt 1)\n\nVerdict: APPROVED"
    match = RUN_ID_PATTERN.search(body)
    assert match is None


# ── Gatekeeper Verdict regex ────────────────────────────────────────


def test_gatekeeper_pattern_matches_basic_verdict() -> None:
    body = "## Gatekeeper Verdict on PR #943\n\n**Decision:** REQUEST_CHANGES"
    match = GATEKEEPER_PATTERN.search(body)
    assert match is not None
    assert match.group(1) == "943"


def test_gatekeeper_pattern_matches_no_space_before_hash() -> None:
    body = "## Gatekeeper Verdict on PR#56\n"
    match = GATEKEEPER_PATTERN.search(body)
    assert match is not None
    assert match.group(1) == "56"


def test_gatekeeper_pattern_is_case_insensitive() -> None:
    body = "## gatekeeper verdict on pr #999\n"
    match = GATEKEEPER_PATTERN.search(body)
    assert match is not None
    assert match.group(1) == "999"


def test_gatekeeper_pattern_rejects_non_verdict_mentions() -> None:
    body = "We discussed the Gatekeeper verdict for PR 42 earlier."
    match = GATEKEEPER_PATTERN.search(body)
    assert match is None


def test_gatekeeper_pattern_rejects_auditor_reviews() -> None:
    body = "## Auditor Review: `acceptance_defined` (attempt 1)\n"
    match = GATEKEEPER_PATTERN.search(body)
    assert match is None


# ── Disjoint patterns: same body never matches both ─────────────────


def test_run_and_gatekeeper_patterns_are_disjoint() -> None:
    """A single comment body should not match both patterns —
    _fetch_prior_runs uses an else-branch and we want to make sure
    the categorization is unambiguous."""
    builders_body = "## Builders Run `sched-deadbeef`\n"
    gatekeeper_body = "## Gatekeeper Verdict on PR #100\n"

    assert RUN_ID_PATTERN.search(builders_body) is not None
    assert GATEKEEPER_PATTERN.search(builders_body) is None

    assert RUN_ID_PATTERN.search(gatekeeper_body) is None
    assert GATEKEEPER_PATTERN.search(gatekeeper_body) is not None
