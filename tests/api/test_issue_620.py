"""Tests for FakeIntentClassifier protocol compliance."""

from __future__ import annotations

from typing import Any, Protocol

from tests.fakes import FakeIntentClassifier


class IntentClassifier(Protocol):
    """Protocol for intent classifiers."""

    async def classify(self, text: str) -> dict[str, Any]: ...


def test_fake_intent_classifier_implements_protocol() -> None:
    """Verify FakeIntentClassifier exists and implements IntentClassifier protocol."""
    classifier = FakeIntentClassifier()
    assert isinstance(classifier, type)
    assert isinstance(classifier(), IntentClassifier)


class TestFakeIntentClassifierHappyPath:
    async def test_classify_intent_returns_default_with_confidence(self) -> None:
        """Test happy path: classify_intent returns default intent with confidence."""
        classifier = FakeIntentClassifier()
        result = await classifier().classify("any text input")

        assert isinstance(result, dict)
        assert "intent" in result
        assert "confidence" in result
        assert isinstance(result["intent"], str)
        assert result["intent"] == "unknown"
        assert isinstance(result["confidence"], float)
        assert 0.0 <= result["confidence"] <= 1.0
