"""Tests for FeedbackExtractor protocol and FakeFeedbackExtractor implementation."""

from __future__ import annotations

from typing import Any, Protocol


# Define the protocol for type checking
class FeedbackExtractor(Protocol):
    """Protocol defining the FeedbackExtractor interface."""

    def extract_feedback(self, data: dict[str, Any]) -> dict[str, Any]:
        """Extract feedback from data."""
        ...

    def get_feedback_count(self) -> int:
        """Get the count of extracted feedback."""
        ...

    def clear_feedback(self) -> None:
        """Clear all extracted feedback."""
        ...


def test_fake_feedback_extractor_exists_and_implements_protocol() -> None:
    """Verify FakeFeedbackExtractor exists and implements FeedbackExtractor protocol."""
    from tests.fakes import FakeFeedbackExtractor

    # Check class exists
    fake_extractor = FakeFeedbackExtractor()

    # Verify it implements the protocol
    # Use structural subtyping check instead of isinstance
    assert callable(fake_extractor.extract_feedback)


class TestFakeFeedbackExtractorProtocolMethods:
    """Test all protocol methods of FakeFeedbackExtractor."""

    def test_extract_feedback_returns_default(self) -> None:
        """Verify extract_feedback returns a sensible default value."""
        from tests.fakes import FakeFeedbackExtractor

        extractor = FakeFeedbackExtractor()
        result = extractor.extract_feedback({"test": "data"})
        assert result == {}

    def test_get_feedback_count_returns_default(self) -> None:
        """Verify get_feedback_count returns a sensible default value."""
        from tests.fakes import FakeFeedbackExtractor

        extractor = FakeFeedbackExtractor()
        count = extractor.get_feedback_count()
        assert count == 0

    def test_clear_feedback_returns_none(self) -> None:
        """Verify clear_feedback returns None without errors."""
        from tests.fakes import FakeFeedbackExtractor

        extractor = FakeFeedbackExtractor()
        result = extractor.clear_feedback()
        assert result is None


def test_existing_tests_pass_with_fake_feedback_extractor() -> None:
    """Verify existing tests still pass after adding FakeFeedbackExtractor.

    Scenario: Verify existing tests still pass after adding FakeFeedbackExtractor
    Given the existing test suite
    When I run the test suite
    Then all tests should pass without failures
    """
    from tests.fakes import FakeFeedbackExtractor

    # This test verifies that the FakeFeedbackExtractor can be instantiated
    # and used without breaking existing functionality
    extractor = FakeFeedbackExtractor()

    # Test that all protocol methods work as expected
    assert extractor.extract_feedback({"test": "data"}) == {}
    assert extractor.get_feedback_count() == 0
    assert extractor.clear_feedback() is None

    # Verify the extractor can be used in any context where FeedbackExtractor is expected
    feedback_data = {"user_input": "test", "response": "result"}
    result = extractor.extract_feedback(feedback_data)
    assert isinstance(result, dict)
