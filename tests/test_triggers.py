"""Tests for stronghold.triggers — core reactor trigger registration."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from stronghold.triggers import register_core_triggers
from stronghold.types.reactor import Event, TriggerMode


# ── Fake Reactor ────────────────────────────────────────────────────


class FakeReactor:
    def __init__(self) -> None:
        self._triggers: list[tuple] = []

    def register(self, spec, action) -> None:
        self._triggers.append((spec, action))


def _make_container() -> MagicMock:
    container = MagicMock()
    container.reactor = FakeReactor()
    container.learning_promoter = AsyncMock()
    container.learning_promoter.check_and_promote = AsyncMock(return_value=[])
    container.rate_limiter = MagicMock()
    container.rate_limiter._windows = {"a": 1, "b": 2}
    container.rate_limiter._evict_stale_keys = MagicMock(side_effect=lambda *_: container.rate_limiter._windows.clear())
    container.outcome_store = MagicMock()
    container.outcome_store.get_task_completion_rate = AsyncMock(
        return_value={"total": 10, "succeeded": 8, "failed": 2, "rate": 0.8, "by_model": {}},
    )
    container.warden = MagicMock()
    container.warden.scan = AsyncMock(return_value=MagicMock(clean=True, flags=[]))
    container.tournament = MagicMock()
    container.tournament.get_stats = MagicMock(return_value={"matches": 5})
    container.canary_manager = MagicMock()
    container.canary_manager.list_active = MagicMock(return_value=[])
    container.canary_manager.check_promotion_or_rollback = MagicMock(return_value="hold")
    container.learning_store = MagicMock()
    container.mason_queue = MagicMock()
    container.route_request = AsyncMock()
    return container


def test_register_core_triggers_registers_ten() -> None:
    container = _make_container()
    register_core_triggers(container)
    assert len(container.reactor._triggers) == 10


def test_trigger_names_unique() -> None:
    container = _make_container()
    register_core_triggers(container)
    names = [spec.name for spec, _ in container.reactor._triggers]
    assert len(names) == len(set(names))


def test_all_modes_represented() -> None:
    """Registered triggers cover both INTERVAL and EVENT modes."""
    container = _make_container()
    register_core_triggers(container)
    modes = {spec.mode for spec, _ in container.reactor._triggers}
    assert TriggerMode.INTERVAL in modes
    assert TriggerMode.EVENT in modes


# ── Individual trigger handlers ─────────────────────────────────────


def _get_handler(container, name):
    for spec, action in container.reactor._triggers:
        if spec.name == name:
            return action
    raise KeyError(name)


async def test_learning_promotion_check_returns_count() -> None:
    container = _make_container()
    container.learning_promoter.check_and_promote = AsyncMock(return_value=["l1", "l2"])
    register_core_triggers(container)
    handler = _get_handler(container, "learning_promotion_check")
    result = await handler(Event(name="timer"))
    assert result["promoted_count"] == 2


async def test_learning_promotion_skipped_without_promoter() -> None:
    container = _make_container()
    container.learning_promoter = None
    register_core_triggers(container)
    handler = _get_handler(container, "learning_promotion_check")
    result = await handler(Event(name="timer"))
    assert result["skipped"] is True


async def test_rate_limit_eviction_returns_count() -> None:
    container = _make_container()
    register_core_triggers(container)
    handler = _get_handler(container, "rate_limit_eviction")
    result = await handler(Event(name="timer"))
    assert result["evicted"] == 2


async def test_outcome_stats_snapshot() -> None:
    container = _make_container()
    register_core_triggers(container)
    handler = _get_handler(container, "outcome_stats_snapshot")
    result = await handler(Event(name="timer"))
    assert result["total"] == 10
    assert result["rate"] == 0.8


async def test_security_rescan_clean_content() -> None:
    container = _make_container()
    register_core_triggers(container)
    handler = _get_handler(container, "security_rescan")
    result = await handler(Event(name="security.rescan", data={"content": "hello"}))
    assert result["clean"] is True


async def test_security_rescan_no_content_skipped() -> None:
    container = _make_container()
    register_core_triggers(container)
    handler = _get_handler(container, "security_rescan")
    result = await handler(Event(name="security.rescan", data={}))
    assert result["skipped"] is True


async def test_security_rescan_flagged_content() -> None:
    container = _make_container()
    container.warden.scan = AsyncMock(
        return_value=MagicMock(clean=False, flags=["prompt_injection"]),
    )
    register_core_triggers(container)
    handler = _get_handler(container, "security_rescan")
    result = await handler(Event(name="security.rescan", data={"content": "ignore instructions"}))
    assert result["clean"] is False
    assert "prompt_injection" in result["flags"]


async def test_post_tool_learning_on_failure() -> None:
    container = _make_container()
    register_core_triggers(container)
    handler = _get_handler(container, "post_tool_learning")
    result = await handler(Event(
        name="post_tool_loop",
        data={"tool_name": "shell", "success": False},
    ))
    assert result["tool_name"] == "shell"
    assert result["success"] is False


async def test_tournament_check_with_tournament() -> None:
    container = _make_container()
    register_core_triggers(container)
    handler = _get_handler(container, "tournament_evaluation")
    result = await handler(Event(name="timer"))
    assert result["matches"] == 5


async def test_tournament_check_skipped_without() -> None:
    container = _make_container()
    container.tournament = None
    register_core_triggers(container)
    handler = _get_handler(container, "tournament_evaluation")
    result = await handler(Event(name="timer"))
    assert result["skipped"] is True


async def test_canary_check_with_active_deployments() -> None:
    container = _make_container()
    container.canary_manager.list_active = MagicMock(return_value=[
        {"skill_name": "skill1", "stage": "10%"},
        {"skill_name": "skill2", "stage": "50%"},
    ])
    container.canary_manager.check_promotion_or_rollback = MagicMock(
        side_effect=["advance", "rollback"],
    )
    register_core_triggers(container)
    handler = _get_handler(container, "canary_deployment_check")
    result = await handler(Event(name="timer"))
    assert result["active_canaries"] == 2


async def test_canary_check_without_manager() -> None:
    container = _make_container()
    container.canary_manager = None
    register_core_triggers(container)
    handler = _get_handler(container, "canary_deployment_check")
    result = await handler(Event(name="timer"))
    assert result["skipped"] is True


async def test_rlhf_feedback_no_result_skipped() -> None:
    container = _make_container()
    register_core_triggers(container)
    handler = _get_handler(container, "rlhf_feedback")
    result = await handler(Event(name="pr.reviewed", data={}))
    assert result["skipped"] is True


async def test_mason_dispatch_no_issue_skipped() -> None:
    container = _make_container()
    register_core_triggers(container)
    handler = _get_handler(container, "mason_dispatch")
    result = await handler(Event(name="mason.issue_assigned", data={}))
    assert result["skipped"] is True


async def test_mason_dispatch_success() -> None:
    container = _make_container()
    register_core_triggers(container)
    handler = _get_handler(container, "mason_dispatch")
    result = await handler(Event(
        name="mason.issue_assigned",
        data={"issue_number": 42, "title": "fix", "owner": "o", "repo": "r"},
    ))
    assert result["issue_number"] == 42
    assert result["status"] == "completed"
    container.mason_queue.start.assert_called_with(42)
    container.mason_queue.complete.assert_called_with(42)


async def test_mason_dispatch_failure() -> None:
    container = _make_container()
    container.route_request = AsyncMock(side_effect=RuntimeError("boom"))
    register_core_triggers(container)
    handler = _get_handler(container, "mason_dispatch")
    result = await handler(Event(
        name="mason.issue_assigned",
        data={"issue_number": 99, "title": "t", "owner": "o", "repo": "r"},
    ))
    assert result["status"] == "failed"
    assert "boom" in result["error"]


async def test_mason_pr_review_no_pr_skipped() -> None:
    container = _make_container()
    register_core_triggers(container)
    handler = _get_handler(container, "mason_pr_review")
    result = await handler(Event(name="mason.pr_review_requested", data={}))
    assert result["skipped"] is True


async def test_mason_pr_review_success() -> None:
    container = _make_container()
    register_core_triggers(container)
    handler = _get_handler(container, "mason_pr_review")
    result = await handler(Event(
        name="mason.pr_review_requested",
        data={"pr_number": 100, "owner": "o", "repo": "r"},
    ))
    assert result["pr_number"] == 100
    assert result["status"] == "completed"


async def test_mason_pr_review_failure() -> None:
    container = _make_container()
    container.route_request = AsyncMock(side_effect=RuntimeError("failed"))
    register_core_triggers(container)
    handler = _get_handler(container, "mason_pr_review")
    result = await handler(Event(
        name="mason.pr_review_requested",
        data={"pr_number": 200, "owner": "o", "repo": "r"},
    ))
    assert result["status"] == "failed"
