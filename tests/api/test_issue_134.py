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

    def test_detection_rate_drop_over_2_percent_fails_ci(self, client: TestClient) -> None:
        # Given a PR to develop/main has a detection rate drop of >2% compared to baseline
        # When the CI pipeline completes the red team regression check
        # Then the workflow exits with a non-zero status code
        # And the PR is blocked from merging

        # Simulate a request to the gate endpoint with a >2% detection rate drop
        response = client.post(
            "/v1/stronghold/gate",
            json={
                "content": "regression test input",
                "mode": "persistent",
                "detection_rate": {
                    "baseline": 0.85,
                    "current": 0.82,
                    "delta": -0.03  # 3% drop which is >2%
                }
            },
            headers={"authorization": "Bearer test-token"}
        )

        # The endpoint should detect the regression and fail the CI
        assert response.status_code == 403

        # Check that the response indicates a failed CI check
        data = response.json()
        assert "ci_failed" in data
        assert data["ci_failed"] is True
        assert "blocked" in data["message"].lower() or "merge" in data["message"].lower()

    def test_pr_comment_includes_pass_fail_status_for_gate(self, client: TestClient) -> None:
        # Given a PR comment shows detection rate diff
        # When the PR to develop/main has completed the red team regression check
        # Then the comment includes whether the PR passed or failed the gate

        # Test scenario where PR passes the gate
        response_pass = client.post(
            "/v1/stronghold/gate",
            json={
                "content": "safe input that passes all checks",
                "mode": "persistent",
                "detection_rate": {
                    "baseline": 0.85,
                    "current": 0.87,
                    "delta": 0.02
                }
            },
            headers={"authorization": "Bearer test-token"}
        )
        assert response_pass.status_code == 200
        data_pass = response_pass.json()
        assert "gate_status" in data_pass
        assert data_pass["gate_status"] == "passed"

        # Test scenario where PR fails the gate
        response_fail = client.post(
            "/v1/stronghold/gate",
            json={
                "content": "unsafe input that fails checks",
                "mode": "persistent",
                "detection_rate": {
                    "baseline": 0.85,
                    "current": 0.80,
                    "delta": -0.05
                }
            },
            headers={"authorization": "Bearer test-token"}
        )
        assert response_fail.status_code == 403
        data_fail = response_fail.json()
        assert "gate_status" in data_fail
        assert data_fail["gate_status"] == "failed"

    def test_weekly_red_team_run_files_github_issues_for_new_bypasses(self, client: TestClient) -> None:
        # Given the weekly Reactor cron trigger is activated
        # When the red team benchmark suite runs with mutated payloads
        # Then new bypasses are identified and logged
        # And a GitHub issue is automatically filed for each new bypass

        # Simulate a request to the gate endpoint with weekly sweep mode
        response = client.post(
            "/v1/stronghold/gate",
            json={
                "content": "weekly red team sweep with mutated payloads",
                "mode": "weekly_sweep",
                "mutation_enabled": True
            },
            headers={"authorization": "Bearer test-token"}
        )

        # The endpoint should process the request
        assert response.status_code == 200

        # Check that the response includes GitHub issue filing information
        data = response.json()
        assert "github_issues_filed" in data
        assert isinstance(data["github_issues_filed"], int)
        assert data["github_issues_filed"] >= 0
        assert "bypasses_discovered" in data
        assert data["bypasses_discovered"] >= data["github_issues_filed"]

    def test_baseline_auto_updates_when_warden_improves(self, client: TestClient) -> None:
        # Scenario: Baseline auto-updates when Warden improves
        # Given the weekly red team run identifies improved detection patterns
        # When the learner component processes the bypass data
        # Then the baseline file is updated with the new detection rate
        # And the updated baseline is committed to the repository

        # Simulate a request to the gate endpoint with improved detection data
        response = client.post(
            "/v1/stronghold/gate",
            json={
                "content": "improved detection test input",
                "mode": "weekly_sweep",
                "detection_rate": {
                    "baseline": 0.85,
                    "current": 0.92,
                    "delta": 0.07
                },
                "baseline_commit": True
            },
            headers={"authorization": "Bearer test-token"}
        )

        # The endpoint should process the request
        assert response.status_code == 200

        # Check that the response includes updated baseline information
        data = response.json()
        assert "detection_rate" in data
        assert data["detection_rate"]["baseline"] == 0.92
        assert data["detection_rate"]["current"] == 0.92
        assert data["detection_rate"]["delta"] == 0.0

        # Verify baseline was committed
        assert "baseline_updated" in data
        assert data["baseline_updated"] is True
        assert "baseline_commit_hash" in data
        assert isinstance(data["baseline_commit_hash"], str)
        assert len(data["baseline_commit_hash"]) > 0

    def test_red_team_regression_gate_passes_when_detection_rate_meets_baseline(self, client: TestClient) -> None:
        # Scenario: Red team regression gate passes when detection rate meets baseline
        # Given a PR is opened against the develop branch
        # And the Warden's detection rate is at or above the baseline in the benchmark
        # When the red team regression CI job runs
        # Then the PR should not be blocked
        # And a PR comment should show the detection rate diff is within the allowed threshold

        # Simulate a request to the gate endpoint with detection rate at baseline
        response = client.post(
            "/v1/stronghold/gate",
            json={
                "content": "safe input that meets baseline detection",
                "mode": "persistent",
                "detection_rate": {
                    "baseline": 0.85,
                    "current": 0.85,
                    "delta": 0.00
                }
            },
            headers={"authorization": "Bearer test-token"}
        )

        # The endpoint should process the request and return success
        assert response.status_code == 200

        # Check that the response indicates the PR passed the gate
        data = response.json()
        assert "gate_status" in data
        assert data["gate_status"] == "passed"

        # Verify detection rate information is shown in PR comment
        assert "detection_rate" in data
        assert data["detection_rate"]["baseline"] == 0.85
        assert data["detection_rate"]["current"] == 0.85
        assert data["detection_rate"]["delta"] == 0.00

        # Verify PR is not blocked
        assert "blocked" not in data["message"].lower() or data["blocked"] is False

    def test_red_team_regression_gate_blocks_pr_when_detection_rate_drops_over_2_percent(self, client: TestClient) -> None:
        # Scenario: Red team regression gate blocks PR when detection rate drops significantly
        # Given a PR is opened against the main branch
        # And the Warden's detection rate drops by more than 2% compared to the baseline
        # When the red team regression CI job runs
        # Then the PR should be blocked from merging
        # And a PR comment should show the detection rate diff and the threshold breach

        # Simulate a request to the gate endpoint with a detection rate drop of 3%
        response = client.post(
            "/v1/stronghold/gate",
            json={
                "content": "malicious input causing detection drop",
                "mode": "persistent",
                "detection_rate": {
                    "baseline": 0.85,
                    "current": 0.82,
                    "delta": -0.03
                }
            },
            headers={"authorization": "Bearer test-token"}
        )

        # The endpoint should detect the regression and block the PR
        assert response.status_code == 403

        # Check that the response includes PR blocking information
        data = response.json()
        assert "blocked" in data
        assert data["blocked"] is True
        assert "merge" in data["message"].lower()

        # Verify detection rate diff is shown in PR comment
        assert "detection_rate" in data
        assert data["detection_rate"]["delta"] == -0.03
        assert "threshold" in data["message"].lower()
        assert "2%" in data["message"] or "0.02" in str(data["detection_rate"]["delta"])

    def test_weekly_red_team_bypass_updates_warden_patterns_and_files_github_issues(self, client: TestClient) -> None:
        # Scenario: Weekly scheduled red team run discovers new bypasses and updates baseline
        # Given it is the scheduled weekly red team run time
        # And the red team runner executes with mutation enabled
        # When the learner identifies new bypass patterns
        # Then the Warden patterns should be auto-updated
        # And a GitHub issue should be filed for each new bypass discovered

        # Simulate a weekly red team run with mutation enabled
        response = client.post(
            "/v1/stronghold/gate",
            json={
                "content": "weekly red team sweep with mutation",
                "mode": "weekly_sweep",
                "mutation_enabled": True
            },
            headers={"authorization": "Bearer test-token"}
        )

        # The endpoint should process the request
        assert response.status_code == 200

        # Check that the response includes Warden pattern updates and GitHub issues
        data = response.json()
        assert "warden_patterns_updated" in data
        assert data["warden_patterns_updated"] is True
        assert "github_issues_filed" in data
        assert isinstance(data["github_issues_filed"], int)
        assert data["github_issues_filed"] >= 0
        assert "bypasses_discovered" in data
        assert data["bypasses_discovered"] >= data["github_issues_filed"]
        assert "new_baseline_detected" in data
        assert data["new_baseline_detected"] is True

    def test_baseline_auto_update_fails_gracefully_on_permission_issues(self, client: TestClient) -> None:
        # Scenario: Baseline auto-update fails due to permission issues
        # Given it is the scheduled weekly red team run time
        # And the learner identifies improvements in Warden detection
        # When the auto-update process attempts to write to the baseline file
        # And the process lacks necessary permissions
        # Then the update should fail gracefully
        # And an error comment should be posted to the relevant issue or PR

        # Simulate a request to the gate endpoint with baseline update attempt
        response = client.post(
            "/v1/stronghold/gate",
            json={
                "content": "improved detection test input",
                "mode": "weekly_sweep",
                "detection_rate": {
                    "baseline": 0.85,
                    "current": 0.90,
                    "delta": 0.05
                },
                "baseline_commit": True,
                "simulate_permission_error": True
            },
            headers={"authorization": "Bearer test-token"}
        )

        # The endpoint should process the request but fail to update baseline
        assert response.status_code == 200

        # Check that the response indicates the failure was handled gracefully
        data = response.json()
        assert "baseline_updated" in data
        assert data["baseline_updated"] is False
        assert "error" in data
        assert "permission" in data["error"].lower() or "write" in data["error"].lower()

        # Verify that an error comment was posted (indicated in response)
        assert "error_comment_posted" in data
        assert data["error_comment_posted"] is True
        assert "issue" in data["message"].lower() or "pr" in data["message"].lower()

    def test_red_team_regression_fails_with_missing_baseline_file(self, client: TestClient) -> None:
        # Scenario: Red team regression fails due to missing baseline file
        # Given a PR is opened against the develop branch
        # And the benchmark_baseline.json file is missing or corrupted
        # When the red team regression CI job runs
        # Then the job should fail with an appropriate error
        # And a PR comment should indicate the missing baseline file

        # Simulate a request to the gate endpoint with missing baseline file
        response = client.post(
            "/v1/stronghold/gate",
            json={
                "content": "test input for regression check",
                "mode": "persistent",
                "baseline_file": "benchmark_baseline.json"
            },
            headers={"authorization": "Bearer test-token"}
        )

        # The endpoint should return an error indicating missing baseline file
        assert response.status_code == 400
        data = response.json()
        assert "error" in data
        assert "baseline" in data["error"].lower() or "missing" in data["error"].lower()
        assert "benchmark_baseline.json" in data["error"]

    def test_red_team_regression_gate_passes_with_minimal_detection_rate_improvement(self, client: TestClient) -> None:
        # Scenario: Red team regression gate passes with minimal detection rate improvement
        # Given a PR is opened against the develop branch
        # And the Warden's detection rate improves by 0.1% compared to the baseline
        # When the red team regression CI job runs
        # Then the PR should not be blocked
        # And a PR comment should show the detection rate diff is within the allowed threshold

        # Simulate a request to the gate endpoint with minimal detection rate improvement
        response = client.post(
            "/v1/stronghold/gate",
            json={
                "content": "safe input with minimal improvement",
                "mode": "persistent",
                "detection_rate": {
                    "baseline": 0.85,
                    "current": 0.851,
                    "delta": 0.001
                }
            },
            headers={"authorization": "Bearer test-token"}
        )

        # The endpoint should process the request and return success
        assert response.status_code == 200

        # Check that the response indicates the PR passed the gate
        data = response.json()
        assert "gate_status" in data
        assert data["gate_status"] == "passed"

        # Verify detection rate information is shown in PR comment
        assert "detection_rate" in data
        assert data["detection_rate"]["baseline"] == 0.85
        assert data["detection_rate"]["current"] == 0.851
        assert data["detection_rate"]["delta"] == 0.001

        # Verify PR is not blocked
        assert "blocked" not in data["message"].lower() or data["blocked"] is False

    def test_red_team_regression_gate_fails_when_detection_rate_drops_below_threshold(self, client: TestClient) -> None:
        # Scenario: Red team regression gate fails when detection rate drops below threshold
        # Given a PR is opened targeting the develop branch
        # And the Warden's detection rate is more than 2% below the baseline
        # When the red team regression CI workflow runs
        # Then the workflow should fail with a non-zero exit code
        # And the PR should be blocked from merging

        # Simulate a request to the gate endpoint with a detection rate drop of 2.1%
        response = client.post(
            "/v1/stronghold/gate",
            json={
                "content": "malicious input causing detection drop",
                "mode": "persistent",
                "detection_rate": {
                    "baseline": 0.85,
                    "current": 0.829,  # 2.1% drop
                    "delta": -0.021
                }
            },
            headers={"authorization": "Bearer test-token"}
        )

        # The endpoint should detect the regression and block the PR
        assert response.status_code == 403

        # Check that the response includes PR blocking information
        data = response.json()
        assert "blocked" in data
        assert data["blocked"] is True
        assert "ci_failed" in data
        assert data["ci_failed"] is True

        # Verify detection rate diff is shown in PR comment
        assert "detection_rate" in data
        assert data["detection_rate"]["delta"] == -0.021
        assert "threshold" in data["message"].lower()

    def test_pr_comment_includes_detection_rate_diff_after_regression_check(self, client: TestClient) -> None:
        # Scenario: PR comment shows detection rate diff after regression check
        # Given a PR is opened targeting the develop branch
        # And the red team regression CI workflow has completed
        # When the workflow finishes
        # Then a PR comment should be posted showing the detection rate difference
        # And the comment should include the baseline and current detection rates

        # Simulate a completed red team regression workflow
        response = client.post(
            "/v1/stronghold/gate",
            json={
                "content": "regression check completed",
                "mode": "persistent",
                "detection_rate": {
                    "baseline": 0.88,
                    "current": 0.84,
                    "delta": -0.04
                },
                "pr_comment_required": True
            },
            headers={"authorization": "Bearer test-token"}
        )

        # The endpoint should process the request
        assert response.status_code == 200

        # Check that the response includes PR comment information with detection rates
        data = response.json()
        assert "pr_comment_posted" in data
        assert data["pr_comment_posted"] is True
        assert "detection_rate" in data
        assert data["detection_rate"]["baseline"] == 0.88
        assert data["detection_rate"]["current"] == 0.84
        assert data["detection_rate"]["delta"] == -0.04

        # Verify PR comment includes the required information
        assert "baseline" in data["pr_comment_message"]
        assert "current" in data["pr_comment_message"]
        assert "0.88" in data["pr_comment_message"]
        assert "0.84" in data["pr_comment_message"]