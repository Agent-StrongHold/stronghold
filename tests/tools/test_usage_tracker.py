"""Tests for tool usage tracker: usage-based ranking and schema pruning."""

from stronghold.tools.usage_tracker import ToolUsageTracker


class TestRecordUsage:
    def test_record_single_usage(self) -> None:
        tracker = ToolUsageTracker()
        tracker.record_usage("web_search", "search", ["query"])
        stats = tracker.get_parameter_usage("web_search")
        assert stats == {"query": 1}

    def test_record_multiple_usages_same_tool(self) -> None:
        tracker = ToolUsageTracker()
        tracker.record_usage("web_search", "search", ["query"])
        tracker.record_usage("web_search", "search", ["query", "max_results"])
        stats = tracker.get_parameter_usage("web_search")
        assert stats == {"query": 2, "max_results": 1}

    def test_record_usage_different_task_types(self) -> None:
        tracker = ToolUsageTracker()
        tracker.record_usage("shell", "code", ["command"])
        tracker.record_usage("shell", "automation", ["command"])
        # Tool should appear in rankings for both task types
        assert "shell" in tracker.get_ranked_tools("code")
        assert "shell" in tracker.get_ranked_tools("automation")


class TestGetRankedTools:
    def test_ranked_by_frequency(self) -> None:
        tracker = ToolUsageTracker()
        tracker.record_usage("web_search", "search", ["query"])
        tracker.record_usage("file_read", "search", ["path"])
        tracker.record_usage("web_search", "search", ["query"])
        tracker.record_usage("web_search", "search", ["query"])
        ranked = tracker.get_ranked_tools("search")
        assert ranked == ["web_search", "file_read"]

    def test_empty_task_type_returns_empty(self) -> None:
        tracker = ToolUsageTracker()
        assert tracker.get_ranked_tools("nonexistent") == []

    def test_ranked_tools_only_returns_tools_for_task_type(self) -> None:
        tracker = ToolUsageTracker()
        tracker.record_usage("web_search", "search", ["query"])
        tracker.record_usage("shell", "code", ["command"])
        ranked = tracker.get_ranked_tools("search")
        assert ranked == ["web_search"]
        assert "shell" not in ranked

    def test_tie_breaking_is_stable(self) -> None:
        tracker = ToolUsageTracker()
        tracker.record_usage("alpha", "code", ["x"])
        tracker.record_usage("beta", "code", ["y"])
        ranked = tracker.get_ranked_tools("code")
        assert len(ranked) == 2
        # Both have count 1, order should be deterministic (alphabetical)
        assert ranked == ["alpha", "beta"]


class TestGetParameterUsage:
    def test_unknown_tool_returns_empty(self) -> None:
        tracker = ToolUsageTracker()
        assert tracker.get_parameter_usage("nonexistent") == {}

    def test_accumulates_across_task_types(self) -> None:
        tracker = ToolUsageTracker()
        tracker.record_usage("shell", "code", ["command", "timeout"])
        tracker.record_usage("shell", "automation", ["command"])
        stats = tracker.get_parameter_usage("shell")
        assert stats == {"command": 2, "timeout": 1}


class TestGetUnusedParameters:
    def test_identifies_rarely_used_params(self) -> None:
        tracker = ToolUsageTracker()
        # Use "query" 20 times, "max_results" once — 1/21 ≈ 4.8% < 5%
        for _ in range(20):
            tracker.record_usage("web_search", "search", ["query"])
        tracker.record_usage("web_search", "search", ["query", "max_results"])
        unused = tracker.get_unused_parameters("web_search")
        assert "max_results" in unused
        assert "query" not in unused

    def test_no_unused_when_all_frequent(self) -> None:
        tracker = ToolUsageTracker()
        for _ in range(10):
            tracker.record_usage("shell", "code", ["command", "timeout"])
        unused = tracker.get_unused_parameters("shell")
        assert unused == []

    def test_unknown_tool_returns_empty(self) -> None:
        tracker = ToolUsageTracker()
        assert tracker.get_unused_parameters("nonexistent") == []

    def test_custom_min_usage_pct(self) -> None:
        tracker = ToolUsageTracker()
        # 10 usages of "query", 1 usage of "filter" — 1/11 ≈ 9.1%
        for _ in range(10):
            tracker.record_usage("search", "code", ["query"])
        tracker.record_usage("search", "code", ["query", "filter"])
        # Default 5% threshold: filter is NOT unused (9.1% > 5%)
        assert "filter" not in tracker.get_unused_parameters("search")
        # Raise threshold to 10%: filter IS unused (9.1% < 10%)
        assert "filter" in tracker.get_unused_parameters("search", min_usage_pct=0.10)


class TestGetCommonChains:
    def test_detects_sequential_pairs(self) -> None:
        tracker = ToolUsageTracker()
        # Record a chain: web_search -> file_write, 3 times
        for _ in range(3):
            tracker.record_usage("web_search", "search", ["query"])
            tracker.record_usage("file_write", "search", ["path", "content"])
        chains = tracker.get_common_chains(min_count=3)
        assert ("web_search", "file_write") in chains

    def test_below_threshold_excluded(self) -> None:
        tracker = ToolUsageTracker()
        # Only 2 occurrences — below default threshold of 3
        for _ in range(2):
            tracker.record_usage("web_search", "search", ["query"])
            tracker.record_usage("file_write", "search", ["path"])
        chains = tracker.get_common_chains(min_count=3)
        assert ("web_search", "file_write") not in chains

    def test_chains_across_task_types(self) -> None:
        tracker = ToolUsageTracker()
        # Same sequential pair across different task types should still count
        for _ in range(2):
            tracker.record_usage("shell", "code", ["command"])
            tracker.record_usage("file_read", "code", ["path"])
        tracker.record_usage("shell", "automation", ["command"])
        tracker.record_usage("file_read", "automation", ["path"])
        chains = tracker.get_common_chains(min_count=3)
        assert ("shell", "file_read") in chains

    def test_no_chains_returns_empty(self) -> None:
        tracker = ToolUsageTracker()
        tracker.record_usage("solo_tool", "code", ["x"])
        assert tracker.get_common_chains() == []

    def test_interleaved_tools_dont_false_chain(self) -> None:
        tracker = ToolUsageTracker()
        # A -> B -> A -> B only produces (A, B) and (B, A), each twice
        tracker.record_usage("alpha", "code", ["x"])
        tracker.record_usage("beta", "code", ["y"])
        tracker.record_usage("alpha", "code", ["x"])
        tracker.record_usage("beta", "code", ["y"])
        # Neither pair reaches 3
        chains = tracker.get_common_chains(min_count=3)
        assert chains == []
