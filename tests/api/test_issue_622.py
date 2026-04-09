"""Tests for IntentClassifier protocol."""

from __future__ import annotations

from stronghold.protocols.classifier import IntentClassifier


class TestIntentClassifierProtocol:
    def test_has_required_methods(self) -> None:
        """Verify IntentClassifier protocol has all required methods with correct signatures."""
        assert hasattr(IntentClassifier, "classify")
        assert hasattr(IntentClassifier, "detect_multi_intent")

        # Check classify method signature
        classify_method = IntentClassifier.classify
        assert callable(classify_method)

        # Check detect_multi_intent method signature
        detect_method = IntentClassifier.detect_multi_intent
        assert callable(detect_method)
