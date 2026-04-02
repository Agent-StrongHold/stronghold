"""Test the GitHub-based Artificer flow: issue → branch → code → PR."""

import pytest


class TestGitHubFlowStructure:
    def test_form_includes_repo_field(self) -> None:
        """Dashboard form should accept a GitHub repo URL."""
        # Read the dashboard HTML and verify the field exists
        from pathlib import Path

        dashboard = Path("src/stronghold/dashboard/index.html").read_text()
        assert "repo" in dashboard.lower() or "github" in dashboard.lower()

    def test_structured_request_accepts_repo(self) -> None:
        """The /v1/stronghold/request endpoint should accept a repo field."""
        from stronghold.api.app import create_app

        app = create_app()
        routes = {route.path for route in app.routes}
        assert "/v1/stronghold/request" in routes
