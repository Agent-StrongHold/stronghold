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

    def test_method_documentation(self) -> None:
        """Verify IntentClassifier protocol methods are properly documented."""
        # Check classify method documentation
        classify_doc = IntentClassifier.classify.__doc__
        assert classify_doc is not None, "classify method must be documented"
        assert "classify" in classify_doc.lower(), "classify method doc should mention its purpose"
        assert "intent" in classify_doc.lower(), "classify method doc should mention intent"

        # Check detect_multi_intent method documentation
        detect_doc = IntentClassifier.detect_multi_intent.__doc__
        assert detect_doc is not None, "detect_multi_intent method must be documented"
        assert (
            "detect_multi_intent" in detect_doc.lower() or "multi intent" in detect_doc.lower()
        ), "detect_multi_intent method doc should mention its purpose"
