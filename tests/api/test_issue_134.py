"""Tests for gate_endpoint.py - red team regression workflow."""

from __future__ import annotations

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from stronghold.api.app import create_app
from stronghold.api.routes.gate_endpoint import router as gate_router

class TestRedTeamRegressionWorkflow:
    @pytest.fixture
    def app(self) -> FastAPI:
        app = create_app()
        app.include_router(gate_router)
        return app

    @pytest.fixture
    def client(self, app: FastAPI) -> TestClient:
        return TestClient(app)

    def test_red_team_regression_workflow(self, client: TestClient) -> None:
        # Given a PR is opened targeting the develop branch
        # When the CI pipeline executes the red team regression workflow
        # Then the red team benchmark suite runs against the Warden

        # Simulate a request to the gate endpoint
        response = client.post(
            "/v1/stronghold/gate",
            json={
                "content": "test input that might trigger security issues",
                "mode": "persistent"
            },
            headers={"authorization": "Bearer test-token"}
        )

        # The endpoint should process the request without raising exceptions
        assert response.status_code in (200, 400, 401, 403)

    def test_detection_rate_regression_blocks_pr_merge(self, client: TestClient) -> None:
        # Given a PR to the main branch with a detection rate drop of 3% from baseline
        # When the CI pipeline evaluates the red team results
        # Then the pipeline fails and blocks the PR merge

        # Simulate a request to the gate endpoint with a known malicious input
        response = client.post(
            "/v1/stronghold/gate",
            json={
                "content": "malicious payload that should be detected",
                "mode": "persistent"
            },
            headers={"authorization": "Bearer test-token"}
        )

        # The endpoint should detect the security issue and return a failure status
        assert response.status_code == 403

    def test_pr_comment_shows_detection_rate_diff(self, client: TestClient) -> None:
        # Given a PR to the develop branch with a detection rate change
        # When the CI pipeline completes the red team regression
        # Then a PR comment is posted showing the detection rate difference from baseline

        # Simulate a request to the gate endpoint with detection rate data
        response = client.post(
            "/v1/stronghold/gate",
            json={
                "content": "regression test input",
                "mode": "persistent",
                "detection_rate": {
                    "baseline": 0.85,
                    "current": 0.82,
                    "delta": -0.03
                }
            },
            headers={"authorization": "Bearer test-token"}
        )

        # The endpoint should process the request and return success
        assert response.status_code == 200

        # Check that the response includes detection rate information
        data = response.json()
        assert "detection_rate" in data
        assert data["detection_rate"]["baseline"] == 0.85
        assert data["detection_rate"]["current"] == 0.82
        assert data["detection_rate"]["delta"] == -0.03

    def test_weekly_red_team_sweep_logs_new_bypasses(self, client: TestClient) -> None:
        # Given it is the scheduled weekly red team run time
        # When the Reactor triggers the weekly red team sweep
        # Then new bypasses are discovered and logged

        # Simulate a request to the gate endpoint with weekly sweep mode
        response = client.post(
            "/v1/stronghold/gate",
            json={
                "content": "weekly red team sweep input",
                "mode": "weekly_sweep"
            },
            headers={"authorization": "Bearer test-token"}
        )

        # The endpoint should process the request
        assert response.status_code == 200

        # Check that the response includes bypass discovery information
        data = response.json()
        assert "bypasses_discovered" in data
        assert isinstance(data["bypasses_discovered"], int)
        assert data["bypasses_discovered"] >= 0

    def test_baseline_auto_updated_when_warden_improves(self, client: TestClient) -> None:
        # Given the weekly red team run detects improved detection rates
        # When the learner identifies Warden pattern improvements
        # Then the baseline is automatically updated with the new values

        # Simulate a request to the gate endpoint with improved detection data
        response = client.post(
            "/v1/stronghold/gate",
            json={
                "content": "improved detection test input",
                "mode": "weekly_sweep",
                "detection_rate": {
                    "baseline": 0.85,
                    "current": 0.90,
                    "delta": 0.05
                }
            },
            headers={"authorization": "Bearer test-token"}
        )

        # The endpoint should process the request
        assert response.status_code == 200

        # Check that the response includes updated baseline information
        data = response.json()
        assert "detection_rate" in data
        assert data["detection_rate"]["baseline"] == 0.90
        assert data["detection_rate"]["current"] == 0.90
        assert data["detection_rate"]["delta"] == 0.0

    def test_red_team_fails_on_missing_baseline_file(self, client: TestClient) -> None:
        # Given a PR to the main branch
        # When the CI pipeline attempts to run red team regression
        # Then the pipeline fails with an error indicating missing baseline file

        # Simulate a request to the gate endpoint with missing baseline file scenario
        response = client.post(
            "/v1/stronghold/gate",
            json={
                "content": "test input for missing baseline",
                "mode": "persistent",
                "baseline_file": "missing_baseline.json"
            },
            headers={"authorization": "Bearer test-token"}
        )

        # The endpoint should return an error indicating missing baseline file
        assert response.status_code == 400
        data = response.json()
        assert "error" in data
        assert "baseline" in data["error"].lower() or "missing" in data["error"].lower()

    def test_critical_security_regression_fails_pipeline(self, client: TestClient) -> None:
        # Given a PR to the develop branch with a detection rate drop of 5%
        # When the CI pipeline evaluates the red team results
        # Then the pipeline fails and posts a critical alert in the PR comment

        # Simulate a request to the gate endpoint with a critical regression scenario
        response = client.post(
            "/v1/stronghold/gate",
            json={
                "content": "critical security regression test",
                "mode": "persistent",
                "detection_rate": {
                    "baseline": 0.95,
                    "current": 0.90,
                    "delta": -0.05
                }
            },
            headers={"authorization": "Bearer test-token"}
        )

        # The endpoint should detect the critical regression and return a failure status
        assert response.status_code == 403

        # Check that the response includes critical alert information
        data = response.json()
        assert "critical_alert" in data
        assert data["critical_alert"] is True
        assert "detection rate drop" in data["message"].lower()

    def test_red_team_benchmark_suite_executes_on_target_branches(self, client: TestClient) -> None:
        # Given a PR is opened targeting the develop or main branch
        # When the CI pipeline executes the red team regression workflow
        # Then the red team benchmark suite runs against the Warden
        # And the detection rate is compared against the baseline

        # Simulate a request to the gate endpoint with target branch information
        response = client.post(
            "/v1/stronghold/gate",
            json={
                "content": "benchmark test input",
                "mode": "persistent",
                "target_branch": "develop",
                "benchmark_suite": True
            },
            headers={"authorization": "Bearer test-token"}
        )

        # The endpoint should process the request and return benchmark results
        assert response.status_code == 200

        # Check that the response includes benchmark execution information
        data = response.json()
        assert "benchmark_executed" in data
        assert data["benchmark_executed"] is True
        assert "detection_rate" in data
        assert "baseline_comparison" in data
        assert "warden_evaluation" in data