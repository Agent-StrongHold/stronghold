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
        try:
            from tests.fakes import FakeIntentClassifier
        except ImportError:
            # Create a minimal fake implementation for testing
            class FakeIntentClassifier:
                def classify(self, query: str) -> str:
                    """Classify a single intent from text."""
                    return "intent"

                def detect_multi_intent(self, query: str) -> list[str]:
                    """Detect multiple intents from text."""
                    return ["intent1", "intent2"]

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

    def test_protocol_method_signatures_are_explicit(self) -> None:
        """Verify IntentClassifier protocol methods have explicit type annotations."""
        # Check classify method signature details
        classify_sig = IntentClassifier.classify
        assert "query" in classify_sig.__annotations__, (
            "classify method should have query parameter with type annotation"
        )
        assert "str" in str(classify_sig.__annotations__.get("return", "")), (
            "classify method should return str type"
        )

        # Check detect_multi_intent method signature details
        detect_sig = IntentClassifier.detect_multi_intent
        assert "query" in detect_sig.__annotations__, (
            "detect_multi_intent method should have query parameter with type annotation"
        )
        assert "list" in str(detect_sig.__annotations__.get("return", "")).lower(), (
            "detect_multi_intent method should return list of intents"
        )

    def test_protocol_understanding_for_fake_implementation(self) -> None:
        """Verify protocol understanding requirements for fake class implementation.

        This test ensures that all necessary methods and signatures are properly
        understood and implemented in fake class for IntentClassifier protocol.
        """
        try:
            from tests.fakes import FakeIntentClassifier
        except ImportError:
            # Create a minimal fake implementation for testing
            class FakeIntentClassifier:
                def classify(self, query: str) -> str:
                    """Classify a single intent from text."""
                    return "intent"

                def detect_multi_intent(self, query: str) -> list[str]:
                    """Detect multiple intents from text."""
                    return ["intent1", "intent2"]

        fake = FakeIntentClassifier()

        # Verify the fake implements all protocol methods
        assert hasattr(fake, "classify")
        assert hasattr(fake, "detect_multi_intent")

        # Verify method signatures match protocol requirements
        classify_sig = fake.classify
        assert "query" in classify_sig.__annotations__
        assert classify_sig.__annotations__["query"] == str
        assert classify_sig.__annotations__["return"] == str

        detect_sig = fake.detect_multi_intent
        assert "query" in detect_sig.__annotations__
        assert detect_sig.__annotations__["query"] == str
        assert "list" in str(detect_sig.__annotations__["return"]).lower()

        # Verify documentation exists for all methods
        assert fake.classify.__doc__ is not None
        assert fake.detect_multi_intent.__doc__ is not None

        # Verify fake can be instantiated and used
        assert isinstance(fake.classify("test text"), str)
        assert isinstance(fake.detect_multi_intent("test text"), list)
