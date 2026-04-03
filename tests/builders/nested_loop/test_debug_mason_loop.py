"""Debug test for Mason phase loop."""

import pytest
from unittest.mock import AsyncMock, Mock

from stronghold.api.routes.builders import _mason_phase
from stronghold.builders.nested_loop import MasonTestTracker


@pytest.mark.asyncio
async def test_mason_phase_loop_runs():
    """Test that the Mason phase loop actually runs multiple times."""
    mock_container = Mock()
    mock_agent = AsyncMock()
    mock_agent.handle.return_value = Mock(content="Working", blocked=False)
    mock_container.agents = {"mason": mock_agent}
    mock_tool_dispatcher = AsyncMock()
    mock_tool_dispatcher.execute.return_value = "10 passed, 40 failed, 20% coverage"

    test_tracker = MasonTestTracker()
    test_tracker.high_water_mark = 50

    result = await _mason_phase(
        container=mock_container,
        tool_dispatcher=mock_tool_dispatcher,
        test_tracker=test_tracker,
        run_id="run-1",
        repo="org/repo",
        issue_number=42,
        ws_path="/workspace",
        max_attempts=5,
    )

    print(f"Result: {result}")
    print(
        f"Test tracker: hwm={test_tracker.high_water_mark}, counter={test_tracker.stall_counter}, failed={test_tracker.has_failed}"
    )

    assert result["attempts"] == 5
