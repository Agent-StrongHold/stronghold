"""Minimal test for Mason phase."""

import pytest
from unittest.mock import AsyncMock, Mock

from stronghold.api.routes.builders import _mason_phase
from stronghold.builders.nested_loop import MasonTestTracker


@pytest.mark.asyncio
async def test_mason_phase_basic():
    """Test that Mason phase can be called."""
    mock_container = Mock()
    mock_agent = AsyncMock()
    mock_agent.handle.return_value = Mock(content="Done", blocked=False)
    mock_container.agents = {"mason": mock_agent}
    mock_tool_dispatcher = AsyncMock()
    mock_tool_dispatcher.execute.return_value = '{"passing": 10, "failing": 0, "coverage": "95%"}'

    test_tracker = MasonTestTracker()

    result = await _mason_phase(
        container=mock_container,
        tool_dispatcher=mock_tool_dispatcher,
        test_tracker=test_tracker,
        run_id="run-1",
        repo="org/repo",
        issue_number=42,
        ws_path="/workspace",
        max_attempts=1,
    )

    print(f"Result: {result}")
    assert result["phase"] == "mason"
