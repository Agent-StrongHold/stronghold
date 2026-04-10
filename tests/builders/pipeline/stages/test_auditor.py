"""Unit tests for the extracted auditor verdict parser."""

from __future__ import annotations

from stronghold.builders.pipeline.stages.auditor import parse_verdict


class TestParseVerdict:
    def test_approved_uppercase(self) -> None:
        assert parse_verdict("APPROVED\nLooks good") is True

    def test_verdict_approved_colon(self) -> None:
        assert parse_verdict("VERDICT: APPROVED") is True

    def test_verdict_approved_no_space(self) -> None:
        assert parse_verdict("VERDICT:APPROVED") is True

    def test_changes_requested(self) -> None:
        assert parse_verdict("CHANGES_REQUESTED\nFix this") is False

    def test_verdict_changes_colon(self) -> None:
        assert parse_verdict("VERDICT: CHANGES_REQUESTED") is False

    def test_no_verdict_defaults_to_approved(self) -> None:
        assert parse_verdict("Everything looks fine to me.") is True

    def test_empty_response(self) -> None:
        assert parse_verdict("") is True

    def test_markdown_header(self) -> None:
        assert parse_verdict("# APPROVED\n\nAll good") is True

    def test_changes_requested_mid_line_ignored(self) -> None:
        """Only the first keyword on a stripped line matters."""
        assert parse_verdict("some text CHANGES_REQUESTED later") is True  # doesn't startswith
