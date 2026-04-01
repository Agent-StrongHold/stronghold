"""Tests for dynamic intent creation on agent import.

IntentRegistry.register_intent() and remove_intent() enable runtime
registration of new task_type -> agent_name mappings with associated keywords.
The keyword scoring table is updated at runtime so the classifier picks up
dynamically registered intents without a restart.
"""

from __future__ import annotations

import pytest

from stronghold.agents.intents import IntentRegistry
from stronghold.classifier.keyword import STRONG_INDICATORS, score_keywords

# -- Fixtures ----------------------------------------------------------------


@pytest.fixture
def registry() -> IntentRegistry:
    """Fresh IntentRegistry with default routing table."""
    return IntentRegistry()


@pytest.fixture
def empty_registry() -> IntentRegistry:
    """IntentRegistry with an empty routing table."""
    return IntentRegistry(routing_table={})


# -- register_intent ---------------------------------------------------------


class TestRegisterIntent:
    """register_intent adds a new task_type -> agent mapping."""

    def test_register_new_intent(self, empty_registry: IntentRegistry) -> None:
        """A brand-new intent is added to the routing table."""
        empty_registry.register_intent("translation", "polyglot", ["translate", "language"])
        assert empty_registry.get_agent_for_intent("translation") == "polyglot"

    def test_register_returns_true_for_new(self, empty_registry: IntentRegistry) -> None:
        """register_intent returns True when creating a new intent."""
        result = empty_registry.register_intent("translation", "polyglot", ["translate"])
        assert result is True

    def test_register_overwrites_existing_agent(self, registry: IntentRegistry) -> None:
        """Registering an existing task_type updates the agent name."""
        registry.register_intent("code", "new-coder", ["code"])
        assert registry.get_agent_for_intent("code") == "new-coder"

    def test_register_returns_false_for_overwrite(self, registry: IntentRegistry) -> None:
        """register_intent returns False when overwriting an existing intent."""
        result = registry.register_intent("code", "new-coder", ["code"])
        assert result is False

    def test_registered_intent_routes_to_agent(self, empty_registry: IntentRegistry) -> None:
        """After registration, get_agent_for_intent returns the correct agent."""
        empty_registry.register_intent("data_analysis", "analyst", ["csv", "dataframe", "pandas"])
        assert empty_registry.get_agent_for_intent("data_analysis") == "analyst"

    def test_register_populates_keywords(self, empty_registry: IntentRegistry) -> None:
        """Keywords are stored and retrievable for a registered intent."""
        empty_registry.register_intent("translation", "polyglot", ["translate", "language"])
        keywords = empty_registry.get_keywords("translation")
        assert keywords == ["translate", "language"]

    def test_register_with_empty_keywords(self, empty_registry: IntentRegistry) -> None:
        """Registering with empty keywords list is allowed."""
        empty_registry.register_intent("translation", "polyglot", [])
        assert empty_registry.get_agent_for_intent("translation") == "polyglot"
        assert empty_registry.get_keywords("translation") == []


# -- remove_intent -----------------------------------------------------------


class TestRemoveIntent:
    """remove_intent tears down a dynamic intent registration."""

    def test_remove_intent(self, empty_registry: IntentRegistry) -> None:
        """Removing a registered intent makes it resolve to None."""
        empty_registry.register_intent("translation", "polyglot", ["translate"])
        empty_registry.remove_intent("translation")
        assert empty_registry.get_agent_for_intent("translation") is None

    def test_remove_cleans_up_keywords(self, empty_registry: IntentRegistry) -> None:
        """Removing an intent also removes its keywords."""
        empty_registry.register_intent("translation", "polyglot", ["translate"])
        empty_registry.remove_intent("translation")
        assert empty_registry.get_keywords("translation") == []

    def test_remove_nonexistent_returns_false(self, empty_registry: IntentRegistry) -> None:
        """Removing an intent that doesn't exist returns False."""
        result = empty_registry.remove_intent("nonexistent")
        assert result is False

    def test_remove_existing_returns_true(self, empty_registry: IntentRegistry) -> None:
        """Removing an existing intent returns True."""
        empty_registry.register_intent("translation", "polyglot", ["translate"])
        result = empty_registry.remove_intent("translation")
        assert result is True


# -- Duplicate keywords merge ------------------------------------------------


class TestDuplicateKeywordsMerge:
    """When re-registering an intent, keywords are replaced, not appended."""

    def test_reregister_replaces_keywords(self, empty_registry: IntentRegistry) -> None:
        """Re-registering an intent fully replaces its keyword list."""
        empty_registry.register_intent("code", "coder-v1", ["python", "javascript"])
        empty_registry.register_intent("code", "coder-v2", ["rust", "go"])
        keywords = empty_registry.get_keywords("code")
        assert keywords == ["rust", "go"]

    def test_keywords_across_intents_are_independent(self, empty_registry: IntentRegistry) -> None:
        """Keywords from one intent don't bleed into another."""
        empty_registry.register_intent("code", "coder", ["python", "javascript"])
        empty_registry.register_intent("data", "analyst", ["pandas", "sql"])
        assert empty_registry.get_keywords("code") == ["python", "javascript"]
        assert empty_registry.get_keywords("data") == ["pandas", "sql"]


# -- Classifier picks up dynamic keywords ------------------------------------


class TestClassifierIntegration:
    """score_keywords sees dynamically registered intents via task_type config."""

    def test_classifier_picks_up_dynamic_keywords(self, empty_registry: IntentRegistry) -> None:
        """Dynamic keywords score when passed as TaskTypeConfig to score_keywords."""
        empty_registry.register_intent("translation", "polyglot", ["translate", "language"])
        # Build task_types from registry
        task_types = empty_registry.as_task_type_configs()
        scores = score_keywords("please translate this text", task_types)
        assert "translation" in scores
        assert scores["translation"] > 0

    def test_removed_intent_absent_from_task_configs(self, empty_registry: IntentRegistry) -> None:
        """After removing an intent, it is absent from as_task_type_configs()."""
        empty_registry.register_intent("translation", "polyglot", ["translate"])
        empty_registry.remove_intent("translation")
        task_types = empty_registry.as_task_type_configs()
        assert "translation" not in task_types

    def test_keyword_table_updated_at_runtime(self, empty_registry: IntentRegistry) -> None:
        """Registering new intents immediately affects keyword scoring."""
        # Before registration -- no score
        task_types_before = empty_registry.as_task_type_configs()
        scores_before = score_keywords("deploy the kubernetes cluster", task_types_before)
        assert "devops" not in scores_before

        # Register intent
        empty_registry.register_intent("devops", "infra-bot", ["deploy", "kubernetes", "cluster"])

        # After registration -- scores appear
        task_types_after = empty_registry.as_task_type_configs()
        scores_after = score_keywords("deploy the kubernetes cluster", task_types_after)
        assert "devops" in scores_after
        assert scores_after["devops"] >= 2.0  # at least 2 keyword matches

    def test_strong_indicators_registered(self, empty_registry: IntentRegistry) -> None:
        """register_intent with strong_indicators populates STRONG_INDICATORS."""
        empty_registry.register_intent(
            "translation",
            "polyglot",
            ["translate", "language"],
            strong_indicators=["translate this document", "convert to english"],
        )
        assert "translation" in STRONG_INDICATORS
        assert "translate this document" in STRONG_INDICATORS["translation"]

        # Clean up global state
        empty_registry.remove_intent("translation")
        assert "translation" not in STRONG_INDICATORS

    def test_strong_indicators_boost_score(self, empty_registry: IntentRegistry) -> None:
        """Strong indicators give +3.0 per match, boosting classification."""
        empty_registry.register_intent(
            "translation",
            "polyglot",
            ["translate"],
            strong_indicators=["translate this document"],
        )
        task_types = empty_registry.as_task_type_configs()
        scores = score_keywords("translate this document", task_types)
        # Should get +3.0 from strong indicator + 1.0 from keyword "translate"
        assert scores.get("translation", 0) >= 4.0

        # Clean up global state
        empty_registry.remove_intent("translation")
