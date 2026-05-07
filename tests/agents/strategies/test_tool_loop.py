"""Tests for ToolLoop — shared tool-call processor used by all multi-step strategies."""

from __future__ import annotations

from typing import Any

from stronghold.agents.strategies.tool_loop import ToolLoop
from stronghold.tracing.noop import NoopTrace


def _make_loop(**kwargs: Any) -> ToolLoop:
    defaults: dict[str, Any] = {"tool_executor": None, "trace": NoopTrace()}
    defaults.update(kwargs)
    return ToolLoop(**defaults)


async def _fake_exec(name: str, args: dict[str, Any]) -> str:
    return f"result of {name}"


class TestToolLoopBasicExecution:
    async def test_single_call_appends_to_history_and_messages(self) -> None:
        loop = _make_loop(tool_executor=_fake_exec)
        tc = [{"id": "c1", "function": {"name": "read_file", "arguments": '{"path": "x.py"}'}}]
        msgs: list[dict[str, Any]] = []
        hist: list[dict[str, Any]] = []

        await loop.run_calls(tc, msgs, hist, round_num=0)

        assert len(hist) == 1
        assert hist[0]["tool_name"] == "read_file"
        assert hist[0]["arguments"] == {"path": "x.py"}
        assert "result of read_file" in hist[0]["result"]
        assert hist[0]["round"] == 0
        assert len(msgs) == 1
        assert msgs[0]["role"] == "tool"
        assert msgs[0]["tool_call_id"] == "c1"
        assert "result of read_file" in msgs[0]["content"]

    async def test_multiple_calls_all_recorded(self) -> None:
        loop = _make_loop(tool_executor=_fake_exec)
        tcs = [
            {"id": "c1", "function": {"name": "tool_a", "arguments": "{}"}},
            {"id": "c2", "function": {"name": "tool_b", "arguments": "{}"}},
        ]
        msgs: list[dict[str, Any]] = []
        hist: list[dict[str, Any]] = []

        await loop.run_calls(tcs, msgs, hist, round_num=1)

        assert len(hist) == 2
        assert hist[0]["tool_name"] == "tool_a"
        assert hist[1]["tool_name"] == "tool_b"
        assert all(e["round"] == 1 for e in hist)

    async def test_no_executor_gives_not_available_error(self) -> None:
        loop = _make_loop(tool_executor=None)
        tc = [{"id": "c1", "function": {"name": "missing", "arguments": "{}"}}]
        msgs: list[dict[str, Any]] = []
        hist: list[dict[str, Any]] = []

        await loop.run_calls(tc, msgs, hist, round_num=0)

        assert "not available" in hist[0]["result"]


class TestArgParsing:
    async def test_malformed_json_defaults_to_empty_dict(self) -> None:
        received: list[dict[str, Any]] = []

        async def capturing_exec(name: str, args: dict[str, Any]) -> str:
            received.append(args)
            return "ok"

        loop = _make_loop(tool_executor=capturing_exec)
        tc = [{"id": "c1", "function": {"name": "tool", "arguments": "not-json"}}]
        await loop.run_calls(tc, [], [], round_num=0)

        assert received == [{}]

    async def test_json_bomb_skips_execution_and_records_error(self) -> None:
        executed: list[str] = []

        async def spy_exec(name: str, args: dict[str, Any]) -> str:
            executed.append(name)
            return "ok"

        loop = _make_loop(tool_executor=spy_exec)
        oversized = "x" * 40_000
        tc = [{"id": "c1", "function": {"name": "tool", "arguments": oversized}}]
        hist: list[dict[str, Any]] = []

        await loop.run_calls(tc, [], hist, round_num=0)

        assert executed == []
        assert "Error" in hist[0]["result"]

    async def test_valid_json_args_passed_through(self) -> None:
        received: list[dict[str, Any]] = []

        async def capturing_exec(name: str, args: dict[str, Any]) -> str:
            received.append(args)
            return "ok"

        loop = _make_loop(tool_executor=capturing_exec)
        tc = [{"id": "c1", "function": {"name": "tool", "arguments": '{"key": "value"}'}}]
        await loop.run_calls(tc, [], [], round_num=0)

        assert received == [{"key": "value"}]


class TestResultTruncation:
    async def test_large_result_is_truncated(self) -> None:
        async def fat_exec(name: str, args: dict[str, Any]) -> str:
            return "x" * 20_000

        loop = _make_loop(tool_executor=fat_exec)
        tc = [{"id": "c1", "function": {"name": "tool", "arguments": "{}"}}]
        hist: list[dict[str, Any]] = []

        await loop.run_calls(tc, [], hist, round_num=0)

        assert len(hist[0]["result"]) < 20_000
        assert "truncated" in hist[0]["result"]

    async def test_small_result_is_unchanged(self) -> None:
        async def small_exec(name: str, args: dict[str, Any]) -> str:
            return "small result"

        loop = _make_loop(tool_executor=small_exec)
        tc = [{"id": "c1", "function": {"name": "tool", "arguments": "{}"}}]
        hist: list[dict[str, Any]] = []

        await loop.run_calls(tc, [], hist, round_num=0)

        assert hist[0]["result"] == "small result"


class TestStatusCallback:
    async def test_status_callback_called_with_tool_name(self) -> None:
        statuses: list[str] = []

        async def record_status(msg: str) -> None:
            statuses.append(msg)

        loop = _make_loop(tool_executor=_fake_exec, status_callback=record_status)
        tc = [{"id": "c1", "function": {"name": "my_tool", "arguments": "{}"}}]

        await loop.run_calls(tc, [], [], round_num=0)

        assert any("my_tool" in s for s in statuses)

    async def test_no_status_callback_does_not_raise(self) -> None:
        loop = _make_loop(tool_executor=_fake_exec, status_callback=None)
        tc = [{"id": "c1", "function": {"name": "tool", "arguments": "{}"}}]
        await loop.run_calls(tc, [], [], round_num=0)


class TestOnToolResult:
    async def test_on_tool_result_callback_invoked(self) -> None:
        results: list[tuple[str, str]] = []

        async def on_result(tool_name: str, result_str: str) -> None:
            results.append((tool_name, result_str))

        loop = _make_loop(tool_executor=_fake_exec, on_tool_result=on_result)
        tc = [{"id": "c1", "function": {"name": "read_file", "arguments": "{}"}}]

        await loop.run_calls(tc, [], [], round_num=0)

        assert len(results) == 1
        assert results[0][0] == "read_file"
        assert "result of read_file" in results[0][1]
