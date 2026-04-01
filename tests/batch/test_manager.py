"""Tests for batch task manager: submit, get, list, update, cancel."""

from __future__ import annotations

import pytest

from stronghold.batch.manager import BatchTask, InMemoryBatchManager


@pytest.fixture
def manager() -> InMemoryBatchManager:
    return InMemoryBatchManager()


class TestSubmit:
    async def test_submit_assigns_id(self, manager: InMemoryBatchManager) -> None:
        task = BatchTask(user_id="u1", org_id="org1", messages=[{"role": "user", "content": "hi"}])
        result = await manager.submit(task)
        assert result.id.startswith("batch-")
        assert len(result.id) > 6

    async def test_submit_sets_status_to_submitted(self, manager: InMemoryBatchManager) -> None:
        task = BatchTask(user_id="u1", org_id="org1", messages=[{"role": "user", "content": "hi"}])
        result = await manager.submit(task)
        assert result.status == "submitted"

    async def test_submit_sets_created_at(self, manager: InMemoryBatchManager) -> None:
        task = BatchTask(user_id="u1", org_id="org1", messages=[{"role": "user", "content": "hi"}])
        result = await manager.submit(task)
        assert result.created_at > 0

    async def test_submit_preserves_custom_id(self, manager: InMemoryBatchManager) -> None:
        task = BatchTask(
            id="custom-id", user_id="u1", org_id="org1", messages=[{"role": "user", "content": "x"}]
        )
        result = await manager.submit(task)
        assert result.id == "custom-id"


class TestGet:
    async def test_get_returns_task_for_correct_org(self, manager: InMemoryBatchManager) -> None:
        task = BatchTask(user_id="u1", org_id="org1", messages=[{"role": "user", "content": "hi"}])
        submitted = await manager.submit(task)
        result = await manager.get(submitted.id, org_id="org1")
        assert result is not None
        assert result.id == submitted.id

    async def test_get_returns_none_for_wrong_org(self, manager: InMemoryBatchManager) -> None:
        task = BatchTask(user_id="u1", org_id="org1", messages=[{"role": "user", "content": "hi"}])
        submitted = await manager.submit(task)
        result = await manager.get(submitted.id, org_id="org2")
        assert result is None

    async def test_get_returns_none_for_nonexistent(self, manager: InMemoryBatchManager) -> None:
        result = await manager.get("nonexistent", org_id="org1")
        assert result is None


class TestListForUser:
    async def test_filters_by_user_and_org(self, manager: InMemoryBatchManager) -> None:
        await manager.submit(
            BatchTask(user_id="u1", org_id="org1", messages=[{"role": "user", "content": "a"}])
        )
        await manager.submit(
            BatchTask(user_id="u2", org_id="org1", messages=[{"role": "user", "content": "b"}])
        )
        await manager.submit(
            BatchTask(user_id="u1", org_id="org2", messages=[{"role": "user", "content": "c"}])
        )

        tasks = await manager.list_for_user(user_id="u1", org_id="org1")
        assert len(tasks) == 1
        assert tasks[0].user_id == "u1"
        assert tasks[0].org_id == "org1"

    async def test_respects_limit(self, manager: InMemoryBatchManager) -> None:
        for i in range(5):
            await manager.submit(
                BatchTask(
                    user_id="u1",
                    org_id="org1",
                    messages=[{"role": "user", "content": f"task {i}"}],
                )
            )
        tasks = await manager.list_for_user(user_id="u1", org_id="org1", limit=3)
        assert len(tasks) == 3

    async def test_returns_empty_for_no_match(self, manager: InMemoryBatchManager) -> None:
        tasks = await manager.list_for_user(user_id="nobody", org_id="org1")
        assert tasks == []


class TestUpdateStatus:
    async def test_updates_status_and_progress(self, manager: InMemoryBatchManager) -> None:
        task = BatchTask(user_id="u1", org_id="org1", messages=[{"role": "user", "content": "hi"}])
        submitted = await manager.submit(task)

        ok = await manager.update_status(submitted.id, status="working", progress="50%")
        assert ok is True

        updated = await manager.get(submitted.id, org_id="org1")
        assert updated is not None
        assert updated.status == "working"
        assert updated.progress == "50%"
        assert updated.started_at > 0

    async def test_updates_with_result(self, manager: InMemoryBatchManager) -> None:
        task = BatchTask(user_id="u1", org_id="org1", messages=[{"role": "user", "content": "hi"}])
        submitted = await manager.submit(task)

        result_data = {"answer": "done"}
        ok = await manager.update_status(
            submitted.id, status="completed", result=result_data
        )
        assert ok is True

        updated = await manager.get(submitted.id, org_id="org1")
        assert updated is not None
        assert updated.status == "completed"
        assert updated.result == {"answer": "done"}
        assert updated.completed_at > 0

    async def test_updates_with_error(self, manager: InMemoryBatchManager) -> None:
        task = BatchTask(user_id="u1", org_id="org1", messages=[{"role": "user", "content": "hi"}])
        submitted = await manager.submit(task)

        ok = await manager.update_status(
            submitted.id, status="failed", error="something broke"
        )
        assert ok is True

        updated = await manager.get(submitted.id, org_id="org1")
        assert updated is not None
        assert updated.status == "failed"
        assert updated.error == "something broke"

    async def test_returns_false_for_nonexistent(self, manager: InMemoryBatchManager) -> None:
        ok = await manager.update_status("nope", status="working")
        assert ok is False


class TestCancel:
    async def test_cancel_submitted_task(self, manager: InMemoryBatchManager) -> None:
        task = BatchTask(user_id="u1", org_id="org1", messages=[{"role": "user", "content": "hi"}])
        submitted = await manager.submit(task)

        ok = await manager.cancel(submitted.id, org_id="org1")
        assert ok is True

        updated = await manager.get(submitted.id, org_id="org1")
        assert updated is not None
        assert updated.status == "cancelled"

    async def test_cancel_working_task(self, manager: InMemoryBatchManager) -> None:
        task = BatchTask(user_id="u1", org_id="org1", messages=[{"role": "user", "content": "hi"}])
        submitted = await manager.submit(task)
        await manager.update_status(submitted.id, status="working")

        ok = await manager.cancel(submitted.id, org_id="org1")
        assert ok is True

    async def test_cancel_fails_for_completed_task(self, manager: InMemoryBatchManager) -> None:
        task = BatchTask(user_id="u1", org_id="org1", messages=[{"role": "user", "content": "hi"}])
        submitted = await manager.submit(task)
        await manager.update_status(submitted.id, status="completed")

        ok = await manager.cancel(submitted.id, org_id="org1")
        assert ok is False

    async def test_cancel_fails_for_wrong_org(self, manager: InMemoryBatchManager) -> None:
        task = BatchTask(user_id="u1", org_id="org1", messages=[{"role": "user", "content": "hi"}])
        submitted = await manager.submit(task)

        ok = await manager.cancel(submitted.id, org_id="wrong-org")
        assert ok is False

    async def test_cancel_fails_for_nonexistent(self, manager: InMemoryBatchManager) -> None:
        ok = await manager.cancel("nope", org_id="org1")
        assert ok is False
