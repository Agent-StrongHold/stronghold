"""Auditor agent — PR review engine."""

from stronghold.agents.auditor.checks import (
    check_architecture_update,
    check_bundled_changes,
    check_hardcoded_secrets,
    check_missing_tests,
    check_mock_usage,
    check_private_field_access,
    check_production_code_in_test_pr,
    check_protocol_compliance,
    check_test_imports_exist,
    check_type_annotations,
)

# Registry of review checks the Auditor runs against every PR. This list
# is the canonical wire-in point — anything added to `checks.py` must
# also appear here or it is dead code. Ordering is not significant;
# checks are independent and idempotent.
ALL_CHECKS = (
    check_mock_usage,
    check_architecture_update,
    check_protocol_compliance,
    check_production_code_in_test_pr,
    check_type_annotations,
    check_hardcoded_secrets,
    check_missing_tests,
    check_private_field_access,
    check_bundled_changes,
    check_test_imports_exist,
)

__all__ = [
    "ALL_CHECKS",
    "check_architecture_update",
    "check_bundled_changes",
    "check_hardcoded_secrets",
    "check_missing_tests",
    "check_mock_usage",
    "check_private_field_access",
    "check_production_code_in_test_pr",
    "check_protocol_compliance",
    "check_test_imports_exist",
    "check_type_annotations",
]
