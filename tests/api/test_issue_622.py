"""Tests for IntentClassifier protocol."""

from __future__ import annotations

from inspect import iscoroutinefunction, signature
from typing import Protocol

from stronghold.protocols.classifier import IntentClassifier


class TestIntentClassifierProtocol:
    def test_protocol_methods_match_expected_signatures(self) -> None:
        # Check that IntentClassifier is a Protocol
        assert isinstance(IntentClassifier, type) and issubclass(IntentClassifier, Protocol)

        # Check for required methods
        assert hasattr(IntentClassifier, "classify")
        assert hasattr(IntentClassifier, "detect_multi_intent")

        # Check classify method signature
        classify_sig = signature(IntentClassifier.classify)
        classify_params = list(classify_sig.parameters.keys())
        assert "self" in classify_params
        assert "messages" in classify_params
        assert "task_types" in classify_params
        assert "explicit_priority" in classify_params
        assert classify_sig.return_annotation == IntentClassifier.__annotations__.get("classify")

        # Check detect_multi_intent method signature
        detect_sig = signature(IntentClassifier.detect_multi_intent)
        detect_params = list(detect_sig.parameters.keys())
        assert "self" in detect_params
        assert "user_text" in detect_params
        assert "task_types" in detect_params
        assert detect_sig.return_annotation == IntentClassifier.__annotations__.get(
            "detect_multi_intent"
        )

        # Check that classify is async
        assert iscoroutinefunction(IntentClassifier.classify)
