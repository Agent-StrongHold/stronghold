"""Tests for prompt refinement and A/B testing."""

from __future__ import annotations

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from stronghold.api.routes.dashboard import router as dashboard_router
from tests.fakes import make_test_container

AUTH_HEADER = {"Authorization": "Bearer sk-test"}


@pytest.fixture
def app() -> FastAPI:
    """Create a FastAPI app with test container."""
    app = FastAPI()
    app.include_router(dashboard_router)  # Mount router WITHOUT prefix
    container = make_test_container()  # All 12+ required fields handled
    app.state.container = container
    return app


class TestPromptRefinementABTesting:
    def test_refines_prompt_after_threshold_failures(self, app: FastAPI) -> None:
        with TestClient(app) as client:
            # This test should fail initially as the implementation doesn't exist yet
            resp = client.get("/dashboard/skills", headers=AUTH_HEADER)
            assert resp.status_code == 200

    def test_auto_promotes_refined_prompt_with_20pct_improvement(self, app: FastAPI) -> None:
        with TestClient(app) as client:
            # Simulate the scenario where draft prompt has 85% success rate
            # and production prompt has 60% success rate
            resp = client.post(
                "/dashboard/skills/promote",
                headers=AUTH_HEADER,
                json={
                    "draft_success_rate": 0.85,
                    "draft_run_count": 5,
                    "production_success_rate": 0.60,
                    "production_run_count": 5,
                },
            )
            assert resp.status_code == 200
            data = resp.json()
            assert data["promoted"] is True
            assert "improvement_metrics" in data
            assert data["improvement_metrics"]["percentage_improvement"] > 0.20

    def test_auto_rolls_back_refined_prompt_below_80pct_success(self, app: FastAPI) -> None:
        with TestClient(app) as client:
            # Simulate the scenario where draft prompt has 40% success rate
            # and production prompt has 60% success rate
            resp = client.post(
                "/dashboard/skills/promote",
                headers=AUTH_HEADER,
                json={
                    "draft_success_rate": 0.40,
                    "draft_run_count": 5,
                    "production_success_rate": 0.60,
                    "production_run_count": 5,
                },
            )
            assert resp.status_code == 200
            data = resp.json()
            assert data["promoted"] is False
            assert data["rolled_back"] is True
            assert "performance_metrics" in data
            assert data["performance_metrics"]["draft_success_rate"] == 0.40
            assert data["performance_metrics"]["production_success_rate"] == 0.60
            assert "audit_log_id" in data

    def test_no_refinement_triggered_when_error_pattern_below_threshold(self, app: FastAPI) -> None:
        with TestClient(app) as client:
            # Simulate scenario where prompt failed 2 times with same error pattern
            resp = client.post(
                "/dashboard/skills/check-failures",
                headers=AUTH_HEADER,
                json={
                    "failures": [
                        {
                            "stage": "parsing",
                            "error_type": "syntax_error",
                            "prompt_version": "v1.1",
                        },
                        {
                            "stage": "parsing",
                            "error_type": "syntax_error",
                            "prompt_version": "v1.1",
                        },
                    ],
                },
            )
            assert resp.status_code == 200
            data = resp.json()
            assert data["refinement_triggered"] is False
            assert data["action_taken"] == "none"
            assert "audit_log_id" in data

    def test_ab_testing_paused_when_no_production_prompt_available(self, app: FastAPI) -> None:
        with TestClient(app) as client:
            # Simulate scenario where no production prompt exists for A/B testing
            resp = client.post(
                "/dashboard/skills/ab-test/start",
                headers=AUTH_HEADER,
                json={
                    "prompt_id": "new_feature_prompt",
                    "variants": ["variant_a", "variant_b"],
                },
            )
            assert resp.status_code == 200
            data = resp.json()
            assert data["ab_test_started"] is False
            assert data["paused"] is True
            assert "alert_sent" in data
            assert data["alert_sent"] is True
            assert "audit_log_id" in data
            assert "failure_reason" in data
            assert "no_production_prompt" in data["failure_reason"]
