"""Tool usage tracker: records tool invocations and provides usage-based ranking.

Supports adaptive tool discovery by tracking which tools are used for which
task types, which parameters are actually exercised, and which tool sequences
occur frequently. This data feeds into context building for schema pruning
(removing rarely-used parameters) and priority ordering (most-used tools first).
"""

from __future__ import annotations

import logging
from collections import defaultdict

logger = logging.getLogger("stronghold.tools.usage_tracker")


class ToolUsageTracker:
    """Tracks tool usage patterns for adaptive discovery and schema pruning.

    Thread-safety: This is an in-memory tracker intended for single-process use.
    For multi-process deployments, back this with a shared store (e.g. Redis/PG).
    """

    def __init__(self) -> None:
        # task_type -> tool_name -> invocation count
        self._task_tool_counts: dict[str, dict[str, int]] = defaultdict(
            lambda: defaultdict(int),
        )
        # tool_name -> parameter_name -> usage count
        self._param_counts: dict[str, dict[str, int]] = defaultdict(
            lambda: defaultdict(int),
        )
        # tool_name -> total invocation count (across all task types)
        self._tool_total: dict[str, int] = defaultdict(int)
        # Ordered history of (tool_name,) for chain detection
        self._invocation_history: list[str] = []
        # (tool_a, tool_b) -> sequential pair count
        self._chain_counts: dict[tuple[str, str], int] = defaultdict(int)

    def record_usage(
        self,
        tool_name: str,
        task_type: str,
        parameters_used: list[str],
    ) -> None:
        """Record a single tool invocation.

        Args:
            tool_name: Name of the tool that was invoked.
            task_type: The classified task type for this request.
            parameters_used: List of parameter names that were passed.
        """
        self._task_tool_counts[task_type][tool_name] += 1
        self._tool_total[tool_name] += 1

        for param in parameters_used:
            self._param_counts[tool_name][param] += 1

        # Track sequential chains
        if self._invocation_history:
            prev = self._invocation_history[-1]
            self._chain_counts[(prev, tool_name)] += 1
        self._invocation_history.append(tool_name)

        logger.debug(
            "Recorded usage: tool=%s task=%s params=%s",
            tool_name,
            task_type,
            parameters_used,
        )

    def get_ranked_tools(self, task_type: str) -> list[str]:
        """Return tools sorted by usage frequency for a given task type.

        Args:
            task_type: The task type to rank tools for.

        Returns:
            Tool names sorted descending by invocation count, with ties
            broken alphabetically for deterministic ordering.
        """
        counts = self._task_tool_counts.get(task_type)
        if not counts:
            return []
        return sorted(counts, key=lambda t: (-counts[t], t))

    def get_parameter_usage(self, tool_name: str) -> dict[str, int]:
        """Return parameter usage counts for a tool.

        Args:
            tool_name: The tool to get parameter stats for.

        Returns:
            Dict mapping parameter name to invocation count.
        """
        raw = self._param_counts.get(tool_name)
        if raw is None:
            return {}
        return dict(raw)

    def get_unused_parameters(
        self,
        tool_name: str,
        min_usage_pct: float = 0.05,
    ) -> list[str]:
        """Return parameters used less than min_usage_pct of the time.

        Args:
            tool_name: The tool to check.
            min_usage_pct: Threshold as a fraction (0.05 = 5%). Parameters
                used in fewer than this fraction of total invocations are
                considered unused.

        Returns:
            List of parameter names below the usage threshold.
        """
        total = self._tool_total.get(tool_name, 0)
        if total == 0:
            return []

        raw = self._param_counts.get(tool_name)
        if raw is None:
            return []

        threshold = total * min_usage_pct
        return sorted(param for param, count in raw.items() if count < threshold)

    def get_common_chains(
        self,
        min_count: int = 3,
    ) -> list[tuple[str, str]]:
        """Return frequently sequential tool pairs.

        Args:
            min_count: Minimum number of times a pair must appear
                sequentially to be included.

        Returns:
            List of (tool_a, tool_b) pairs that appeared sequentially
            at least min_count times, sorted by count descending.
        """
        return sorted(
            (pair for pair, count in self._chain_counts.items() if count >= min_count),
            key=lambda p: (-self._chain_counts[p], p),
        )
