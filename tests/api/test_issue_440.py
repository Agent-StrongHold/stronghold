"""Tests for unused imports in agents.py."""

from __future__ import annotations

import pytest
from fastapi import FastAPI

from stronghold.api.routes import agents
from tests.fakes import make_test_container

AUTH_HEADER = {"Authorization": "Bearer sk-test"}


@pytest.fixture
def app() -> FastAPI:
    """Create a FastAPI app with test container."""
    app = FastAPI()
    app.include_router(agents.router)  # Mount router WITHOUT prefix
    container = make_test_container()  # All 12+ required fields handled
    app.state.container = container
    return app


class TestAgentsRouteUnusedImports:
    def test_ruff_check_passes(self, app: FastAPI) -> None:
        """Verify no unused imports in agents.py."""
        # This test will fail initially (TDD) until unused imports are removed
        # Run ruff check on the file
        import subprocess  # noqa: PLC0415

        result = subprocess.run(
            ["ruff", "check", "src/stronghold/api/routes/agents.py"],
            capture_output=True,
            text=True,
        )
        assert result.returncode == 0, (
            f"ruff check failed with output:\n{result.stdout}\n{result.stderr}"
        )
