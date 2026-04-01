"""Tests for A2A container runtime: dispatch, health_check, callback tokens."""

from __future__ import annotations

import pytest

from stronghold.agents.container_runtime import (
    A2ATask,
    ContainerNotAvailableError,
    ContainerRuntime,
    ContainerStrategy,
)


class TestContainerStrategy:
    def test_defaults(self) -> None:
        cs = ContainerStrategy(image="stronghold/ranger:latest", command=["python", "-m", "agent"])
        assert cs.image == "stronghold/ranger:latest"
        assert cs.command == ["python", "-m", "agent"]
        assert cs.timeout == 300
        assert cs.resource_limits == {"cpu": "500m", "memory": "512Mi"}

    def test_custom_resource_limits(self) -> None:
        cs = ContainerStrategy(
            image="stronghold/artificer:latest",
            command=["python", "-m", "agent"],
            timeout=600,
            resource_limits={"cpu": "2000m", "memory": "4Gi"},
        )
        assert cs.timeout == 600
        assert cs.resource_limits["cpu"] == "2000m"
        assert cs.resource_limits["memory"] == "4Gi"

    def test_frozen(self) -> None:
        cs = ContainerStrategy(image="img:1", command=["run"])
        with pytest.raises(AttributeError):
            cs.image = "img:2"  # type: ignore[misc]


class TestA2ATask:
    def test_construction(self) -> None:
        task = A2ATask(
            task_id="t-001",
            agent_name="ranger",
            messages=[{"role": "user", "content": "search logs"}],
            callback_url="https://stronghold.local/callback",
            token_budget=4096,
        )
        assert task.task_id == "t-001"
        assert task.agent_name == "ranger"
        assert len(task.messages) == 1
        assert task.callback_url == "https://stronghold.local/callback"
        assert task.token_budget == 4096

    def test_defaults(self) -> None:
        task = A2ATask(task_id="t-002", agent_name="scribe")
        assert task.messages == []
        assert task.callback_url == ""
        assert task.token_budget == 0

    def test_frozen(self) -> None:
        task = A2ATask(task_id="t-003", agent_name="forge")
        with pytest.raises(AttributeError):
            task.agent_name = "ranger"  # type: ignore[misc]


class TestContainerRuntime:
    async def test_dispatch_returns_result(self) -> None:
        runtime = ContainerRuntime()
        task = A2ATask(
            task_id="t-100",
            agent_name="ranger",
            messages=[{"role": "user", "content": "find file"}],
            callback_url="https://stronghold.local/cb",
            token_budget=2048,
        )
        strategy = ContainerStrategy(image="stronghold/ranger:latest", command=["python", "run.py"])
        result = await runtime.dispatch(task, strategy)
        assert result["task_id"] == "t-100"
        assert result["status"] == "completed"
        assert result["agent_name"] == "ranger"
        assert "container_id" in result
        assert "callback_token" in result

    async def test_dispatch_stores_container(self) -> None:
        runtime = ContainerRuntime()
        task = A2ATask(task_id="t-101", agent_name="scribe", token_budget=1024)
        strategy = ContainerStrategy(image="stronghold/scribe:latest", command=["python", "run.py"])
        result = await runtime.dispatch(task, strategy)
        container_id = result["container_id"]
        is_healthy = await runtime.health_check(container_id)
        assert is_healthy is True

    async def test_health_check_unknown_container(self) -> None:
        runtime = ContainerRuntime()
        is_healthy = await runtime.health_check("nonexistent-container-id")
        assert is_healthy is False

    async def test_dispatch_respects_timeout(self) -> None:
        runtime = ContainerRuntime()
        task = A2ATask(task_id="t-102", agent_name="artificer", token_budget=8192)
        strategy = ContainerStrategy(
            image="stronghold/artificer:latest",
            command=["python", "run.py"],
            timeout=60,
        )
        result = await runtime.dispatch(task, strategy)
        assert result["timeout"] == 60

    async def test_dispatch_multiple_tasks(self) -> None:
        runtime = ContainerRuntime()
        strategy = ContainerStrategy(image="stronghold/ranger:latest", command=["run"])
        ids = []
        for i in range(5):
            task = A2ATask(task_id=f"t-{200 + i}", agent_name="ranger", token_budget=1024)
            result = await runtime.dispatch(task, strategy)
            ids.append(result["container_id"])
        # All container IDs should be unique
        assert len(set(ids)) == 5

    async def test_callback_token_unique_per_task(self) -> None:
        runtime = ContainerRuntime()
        strategy = ContainerStrategy(image="img:1", command=["run"])
        task1 = A2ATask(task_id="t-300", agent_name="ranger", token_budget=1024)
        task2 = A2ATask(task_id="t-301", agent_name="ranger", token_budget=1024)
        r1 = await runtime.dispatch(task1, strategy)
        r2 = await runtime.dispatch(task2, strategy)
        assert r1["callback_token"] != r2["callback_token"]

    async def test_dispatch_unavailable_raises(self) -> None:
        runtime = ContainerRuntime(available=False)
        task = A2ATask(task_id="t-400", agent_name="ranger", token_budget=1024)
        strategy = ContainerStrategy(image="img:1", command=["run"])
        with pytest.raises(ContainerNotAvailableError):
            await runtime.dispatch(task, strategy)

    async def test_container_not_available_error_inherits(self) -> None:
        from stronghold.types.errors import StrongholdError

        err = ContainerNotAvailableError("runtime down")
        assert isinstance(err, StrongholdError)
        assert err.code == "CONTAINER_NOT_AVAILABLE"
        assert "runtime down" in str(err)

    async def test_dispatch_includes_resource_limits(self) -> None:
        runtime = ContainerRuntime()
        task = A2ATask(task_id="t-500", agent_name="artificer", token_budget=4096)
        strategy = ContainerStrategy(
            image="stronghold/artificer:latest",
            command=["python", "run.py"],
            resource_limits={"cpu": "4000m", "memory": "8Gi"},
        )
        result = await runtime.dispatch(task, strategy)
        assert result["resource_limits"] == {"cpu": "4000m", "memory": "8Gi"}

    async def test_dispatch_includes_image_and_command(self) -> None:
        runtime = ContainerRuntime()
        task = A2ATask(task_id="t-600", agent_name="forge", token_budget=2048)
        strategy = ContainerStrategy(
            image="stronghold/forge:v2",
            command=["python", "-m", "forge", "--safe"],
        )
        result = await runtime.dispatch(task, strategy)
        assert result["image"] == "stronghold/forge:v2"
        assert result["command"] == ["python", "-m", "forge", "--safe"]

    async def test_dispatch_includes_token_budget(self) -> None:
        runtime = ContainerRuntime()
        task = A2ATask(task_id="t-700", agent_name="scribe", token_budget=16384)
        strategy = ContainerStrategy(image="img:1", command=["run"])
        result = await runtime.dispatch(task, strategy)
        assert result["token_budget"] == 16384
