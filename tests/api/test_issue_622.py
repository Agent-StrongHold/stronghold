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
        assert "multiple intents" in detect_doc.lower(), (
            "detect_multi_intent method doc should mention its purpose"
        )

    def test_fake_implementation_matches_protocol(self) -> None:
        """Verify fake IntentClassifier implementation matches protocol requirements."""
        from tests.fakes import FakeIntentClassifier

        fake = FakeIntentClassifier()

        # Verify all protocol methods are implemented
        assert hasattr(fake, "classify")
        assert hasattr(fake, "detect_multi_intent")
        assert callable(fake.classify)
        assert callable(fake.detect_multi_intent)

        # Verify method signatures match protocol
        assert fake.classify.__annotations__.get("return") is not None
        assert fake.detect_multi_intent.__annotations__.get("return") is not None

        # Verify fake has proper documentation
        assert fake.classify.__doc__ is not None
        assert fake.detect_multi_intent.__doc__ is not None
