"""Tests for stronghold.worker_main module (worker entry point)."""

from __future__ import annotations

import sys
from unittest.mock import AsyncMock, patch

import pytest


def test_worker_main_module_imports() -> None:
    """The worker_main module should be importable without side effects."""
    import stronghold.worker_main
    assert hasattr(stronghold.worker_main, "main")
    assert hasattr(stronghold.worker_main, "logger")


async def test_main_starts_and_runs_worker() -> None:
    """main() loads config, creates worker, and starts run_loop."""
    from stronghold import worker_main

    with patch("stronghold.worker_main.load_config") as mock_load, \
         patch("stronghold.worker_main.LiteLLMClient") as mock_llm, \
         patch("stronghold.worker_main.InMemoryTaskQueue") as mock_queue, \
         patch("stronghold.worker_main.AgentWorker") as mock_worker_cls:

        mock_config = type("Config", (), {"litellm_url": "http://x", "litellm_key": "k"})()
        mock_load.return_value = mock_config
        mock_worker_instance = mock_worker_cls.return_value
        mock_worker_instance.run_loop = AsyncMock()

        await worker_main.main()

        mock_load.assert_called_once()
        mock_llm.assert_called_once_with(base_url="http://x", api_key="k")
        mock_queue.assert_called_once()
        mock_worker_cls.assert_called_once()
        mock_worker_instance.run_loop.assert_awaited_once()
