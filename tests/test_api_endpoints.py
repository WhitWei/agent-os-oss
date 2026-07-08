import pytest
from fastapi.testclient import TestClient
from unittest.mock import Mock, AsyncMock
from datetime import datetime

from agentos.main.main import create_app

@pytest.fixture
def mock_bootstrap():
    b = Mock()
    b.shutdown = AsyncMock()
    # Mock Kernel
    b.kernel = Mock()
    b.kernel._billing_fuse = Mock()
    b.kernel._billing_fuse.cumulative_spend.return_value = 1.25

    # Mock FeedbackDB
    b.feedback_db = Mock()
    b.feedback_db.count_by_decision.return_value = 5
    
    mock_record = Mock()
    mock_record.id = 1
    mock_record.trace_id = "test-trace"
    mock_record.reviewer = "user_1"
    mock_record.decision = "REJECTED"
    mock_record.reason = "test reason"
    mock_record.original_agent_output = "{}"
    mock_record.timestamp = datetime.now().isoformat()
    
    b.feedback_db.list_all.return_value = [mock_record]

    # Mock StateStore
    b.state_store = Mock()
    b.state_store.count_by_state.return_value = 10
    
    mock_run = {
        "run_id": "test-run",
        "sop_id": "test-sop",
        "state": "COMPLETED",
        "updated_at": "2023-01-01T00:00:00"
    }
    b.state_store.list_runs.return_value = [mock_run]

    return b

@pytest.fixture
def test_client(mock_bootstrap):
    app = create_app(bootstrap=mock_bootstrap)
    with TestClient(app) as client:
        yield client

def test_metrics_overview(test_client):
    response = test_client.get("/api/v1/metrics/overview")
    assert response.status_code == 200
    data = response.json()
    assert data["total_spend_usd"] == 1.25
    assert data["total_intercepts"] == 5
    assert data["successful_workflows"] == 10

def test_workflows_runs(test_client):
    response = test_client.get("/api/v1/workflows/runs?limit=10&offset=5")
    assert response.status_code == 200
    data = response.json()
    assert data["limit"] == 10
    assert data["offset"] == 5
    assert len(data["runs"]) == 1
    assert data["runs"][0]["run_id"] == "test-run"

def test_governance_audits(test_client):
    response = test_client.get("/api/v1/governance/audits")
    assert response.status_code == 200
    data = response.json()
    assert len(data["audits"]) == 1
    assert data["audits"][0]["trace_id"] == "test-trace"
    assert data["audits"][0]["decision"] == "REJECTED"
