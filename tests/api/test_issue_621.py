"""Tests for FeedbackExtractor protocol and FakeFeedbackExtractor implementation."""

from __future__ import annotations

from typing import Any, Protocol


# Define the protocol for type checking
class FeedbackExtractor(Protocol):
    """Protocol defining the FeedbackExtractor interface."""

    def extract_feedback(self, data: dict[str, Any]) -> dict[str, Any]:
        """Extract feedback from data."""
        ...


def test_fake_feedback_extractor_exists_and_implements_protocol() -> None:
    """Verify FakeFeedbackExtractor exists and implements FeedbackExtractor protocol."""
    from tests.fakes import FakeFeedbackExtractor

    # Check class exists
    fake_extractor = FakeFeedbackExtractor()

    # Verify it implements the protocol
    # Use structural subtyping check instead of isinstance
    assert callable(fake_extractor.extract_feedback)
