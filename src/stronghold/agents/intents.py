"""Intent registry: routing table mapping task_type -> agent_name.

Supports dynamic registration at runtime so agents imported with new
capabilities can create intents and update the keyword scoring table
without a restart.
"""

from __future__ import annotations

from stronghold.classifier.keyword import STRONG_INDICATORS
from stronghold.types.config import TaskTypeConfig


class IntentRegistry:
    """Maps task types to agent names with runtime keyword tracking."""

    def __init__(self, routing_table: dict[str, str] | None = None) -> None:
        self._table: dict[str, str] = dict(
            routing_table
            if routing_table is not None
            else {
                "code": "artificer",
                "automation": "warden-at-arms",
                "search": "ranger",
                "creative": "scribe",
                "reasoning": "artificer",
            }
        )
        self._keywords: dict[str, list[str]] = {}

    def get_agent_for_intent(self, task_type: str) -> str | None:
        """Return the agent name for a task type, or None for default handling."""
        return self._table.get(task_type)

    def register_intent(
        self,
        task_type: str,
        agent_name: str,
        keywords: list[str],
        *,
        strong_indicators: list[str] | None = None,
    ) -> bool:
        """Register a task_type -> agent_name mapping with associated keywords.

        Returns True if the intent is new, False if it overwrites an existing one.
        """
        is_new = task_type not in self._table
        self._table[task_type] = agent_name
        self._keywords[task_type] = list(keywords)

        if strong_indicators is not None:
            STRONG_INDICATORS[task_type] = list(strong_indicators)

        return is_new

    def remove_intent(self, task_type: str) -> bool:
        """Remove a task_type mapping and its keywords.

        Returns True if the intent existed and was removed, False otherwise.
        """
        existed = task_type in self._table
        self._table.pop(task_type, None)
        self._keywords.pop(task_type, None)
        STRONG_INDICATORS.pop(task_type, None)
        return existed

    def get_keywords(self, task_type: str) -> list[str]:
        """Return the keywords registered for a task type, or empty list."""
        return list(self._keywords.get(task_type, []))

    def as_task_type_configs(self) -> dict[str, TaskTypeConfig]:
        """Export registered intents as TaskTypeConfig dicts for the classifier."""
        configs: dict[str, TaskTypeConfig] = {}
        for task_type in self._table:
            keywords = self._keywords.get(task_type, [])
            configs[task_type] = TaskTypeConfig(keywords=keywords)
        return configs
