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
