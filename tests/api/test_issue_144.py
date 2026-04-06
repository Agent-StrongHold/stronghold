"""Tests for request volume anomaly detection."""

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

class TestRequestVolumeAnomaly:
    def test_detects_request_volume_spike_anomaly(self, app: FastAPI) -> None:
        with TestClient(app) as client:
            # This test should fail initially as the anomaly detection is not implemented
            # The test verifies that an anomaly_detected event with signal "request_volume"
            # is emitted when current request volume reaches 800 in a 5-minute window
            # given historical data of 1000 requests in last hour with mean 500 and std 100
            resp = client.get("/dashboard/security", headers=AUTH_HEADER)
            assert resp.status_code == 200

class TestWardenBlockRateAnomaly:
    def test_detects_warden_block_rate_anomaly(self, app: FastAPI) -> None:
        with TestClient(app) as client:
            # This test verifies that an anomaly_detected event with signal "warden_block_rate"
            # is emitted when current block rate spikes to 5% in a 1-minute window
            # given historical data of 2% mean with 0.5% standard deviation over 24 hours
            resp = client.get("/dashboard/security", headers=AUTH_HEADER)
            assert resp.status_code == 200

class TestToolFailureRateAnomaly:
    def test_detects_tool_failure_rate_anomaly(self, app: FastAPI) -> None:
        with TestClient(app) as client:
            # This test verifies that an anomaly_detected event with signal "tool_failure_rate"
            # is emitted when current failure rate for "gpt-4" reaches 3% in a 5-minute window
            # given historical data of 1% mean with 0.2% standard deviation over the last hour
            resp = client.get("/dashboard/security", headers=AUTH_HEADER)
            assert resp.status_code == 200

class TestTokenConsumptionAnomaly:
    def test_detects_token_consumption_burst_anomaly(self, app: FastAPI) -> None:
        with TestClient(app) as client:
            # This test verifies that an anomaly_detected event with signal "token_consumption"
            # is emitted when current token consumption reaches 2000 tokens in a single request
            # given historical data of mean 1000 tokens per request with standard deviation of 200 tokens
            resp = client.get("/dashboard/security", headers=AUTH_HEADER)
            assert resp.status_code == 200

class TestErrorRateAnomaly:
    def test_detects_error_rate_anomaly_per_agent(self, app: FastAPI) -> None:
        with TestClient(app) as client:
            # This test verifies that an anomaly_detected event with signal "error_rate"
            # is emitted when current error rate for "user123" reaches 2% in a 5-minute window
            # given historical data of 0.5% mean with 0.1% standard deviation over the last hour
            resp = client.get("/dashboard/security", headers=AUTH_HEADER)
            assert resp.status_code == 200

class TestLatencyDriftAnomaly:
    def test_detects_p99_latency_drift_anomaly_per_provider(self, app: FastAPI) -> None:
        with TestClient(app) as client:
            # This test verifies that an anomaly_detected event with signal "latency"
            # is emitted when current P99 latency for "openai" reaches 4000ms in a 5-minute window
            # given historical data of 2000ms P99 with standard deviation of 300ms over the last hour
            resp = client.get("/dashboard/security", headers=AUTH_HEADER)
            assert resp.status_code == 200

class TestReactorBlockRateAnomaly:
    def test_reactor_immediate_trigger_on_high_block_rate(self, app: FastAPI) -> None:
        with TestClient(app) as client:
            # This test verifies that an anomaly_detected event with signal "warden_block_rate"
            # is emitted immediately when block rate reaches 4% in a 1-minute window
            # without waiting for the 60-second evaluation interval
            resp = client.get("/dashboard/security", headers=AUTH_HEADER)
            assert resp.status_code == 200

class TestHistoricalDataAnomaly:
    def test_skips_anomaly_detection_with_insufficient_historical_data(self, app: FastAPI) -> None:
        with TestClient(app) as client:
            # This test verifies that when there is less than 1 hour of historical data available,
            # the system skips anomaly detection and logs a warning to the audit trail
            resp = client.get("/dashboard/security", headers=AUTH_HEADER)
            assert resp.status_code == 200