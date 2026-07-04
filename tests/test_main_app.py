"""Tests for unified service main.py — uses create_app factory pattern."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi.testclient import TestClient

from agentos_kernel.main import ServiceBootstrap, create_app


def _make_mock_bootstrap() -> ServiceBootstrap:
    """Build a ServiceBootstrap with all components mocked.

    This avoids real connections to Neo4j, SQLite, or the filesystem.
    Each component is a MagicMock/AsyncMock that behaves minimally.
    """
    bs = ServiceBootstrap()

    # Schema provider with a test domain
    bs.schema_provider = MagicMock()
    bs.schema_provider.list_domains.return_value = ["it-asset-mgmt"]
    bs.schema_provider.get_domain.return_value = MagicMock()
    bs.schema_provider.get_schema_definition.return_value = {"domain": "it-asset-mgmt", "classes": []}

    # Available SOPs
    bs.available_sops = [
        {
            "sop_id": "it-onboarding-v1",
            "name": "IT Asset Onboarding",
            "description": "Assign IT equipment to new employees",
            "version": "1.0",
            "steps": 4,
            "file": "src/workflow/sop_examples/it-onboarding.sop.yaml",
        }
    ]

    # Kernel
    bs.kernel = MagicMock()
    bs.kernel.wake_up = AsyncMock(
        return_value=MagicMock(
            text="Hello from test kernel!",
            channel="cli",
            metadata={"session_id": 1, "status": "ok"},
            error=None,
        )
    )

    # SOP engine
    bs.sop_engine = MagicMock()
    bs.sop_engine.create_run = MagicMock(
        return_value=MagicMock(
            run_id="test-run-001",
            sop_id="it-onboarding-v1",
            state=MagicMock(value="COMPLETED"),
        )
    )
    bs.sop_engine.run = AsyncMock(
        return_value=MagicMock(
            run_id="test-run-001",
            sop_id="it-onboarding-v1",
            state=MagicMock(value="COMPLETED"),
        )
    )
    bs.sop_engine.resume = AsyncMock(
        return_value=MagicMock(
            run_id="test-run-001",
            state=MagicMock(value="COMPLETED"),
        )
    )

    # State store
    bs.state_store = MagicMock()
    context_mock = MagicMock(
        run_id="test-run-001",
        sop_id="it-onboarding-v1",
        state=MagicMock(value="SUSPENDED"),
        model_dump_json=lambda: '{"run_id":"test-run-001","sop_id":"it-onboarding-v1","state":"SUSPENDED"}',
    )
    bs.state_store.load_state = MagicMock(return_value=context_mock)

    # Feishu adapter
    bs.feishu = MagicMock()
    bs.feishu.verify_challenge = MagicMock(
        side_effect=lambda body: {"challenge": body.get("challenge")}
        if "challenge" in body
        else None
    )
    bs.feishu.parse_card_callback = MagicMock(
        return_value={
            "run_id": "test-run-001",
            "step_id": "approve_sensitive",
            "decision": "APPROVED",
            "reviewer": "ou_test",
            "reason": "Looks good",
        }
    )
    bs.feishu.parse_event = MagicMock(return_value=None)
    bs.feishu.send_response = AsyncMock()

    # Write gate
    bs.write_gate = MagicMock()

    # Config
    bs.config = MagicMock()

    # Feedback DB
    bs.feedback_db = MagicMock()

    # Policy
    bs.policy = MagicMock()

    # LLM driver (None = use kernel fallback)
    bs.llm_driver = None

    return bs


@pytest.fixture
def mock_bs() -> ServiceBootstrap:
    """Return a pre-built mock bootstrap."""
    return _make_mock_bootstrap()


@pytest.fixture
def client(mock_bs: ServiceBootstrap) -> TestClient:
    """FastAPI TestClient with mocked bootstrap injected via factory."""
    app = create_app(bootstrap=mock_bs)
    with TestClient(app) as c:
        yield c


class TestHealthEndpoint:
    def test_health_returns_ok(self, client: TestClient) -> None:
        response = client.get("/health")
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "ok"
        assert data["service"] == "agent-os"

    def test_health_includes_component_status(self, client: TestClient) -> None:
        response = client.get("/health")
        data = response.json()
        assert data["kernel"] is True
        assert "domains" in data
        assert "sops" in data
        assert data["domains"] == ["it-asset-mgmt"]

    def test_health_degraded_when_no_kernel(self) -> None:
        bs = _make_mock_bootstrap()
        bs.kernel = None
        app = create_app(bootstrap=bs)
        with TestClient(app) as c:
            response = c.get("/health")
            assert response.json()["status"] == "degraded"


class TestApiDomains:
    def test_list_domains(self, client: TestClient) -> None:
        response = client.get("/api/domains")
        assert response.status_code == 200
        data = response.json()
        assert "domains" in data
        assert "it-asset-mgmt" in data["domains"]

    def test_list_domains_empty_when_no_schema(self) -> None:
        bs = _make_mock_bootstrap()
        bs.schema_provider = None
        app = create_app(bootstrap=bs)
        with TestClient(app) as c:
            response = c.get("/api/domains")
            assert response.json() == {"domains": []}


class TestApiSops:
    def test_list_sops(self, client: TestClient) -> None:
        response = client.get("/api/sops")
        assert response.status_code == 200
        data = response.json()
        assert "sops" in data
        assert len(data["sops"]) >= 1

    def test_get_sop_by_id(self, client: TestClient) -> None:
        response = client.get("/api/sops/it-onboarding-v1")
        assert response.status_code == 200
        data = response.json()
        assert data["sop_id"] == "it-onboarding-v1"

    def test_get_sop_by_id_not_found(self, client: TestClient) -> None:
        response = client.get("/api/sops/nonexistent-sop")
        assert response.status_code == 404


class TestFeishuWebhook:
    def test_challenge_verification(self, client: TestClient) -> None:
        """Feishu URL verification: echo back the challenge token."""
        response = client.post(
            "/webhook/feishu",
            json={"challenge": "test-challenge-token", "token": "test"},
        )
        assert response.status_code == 200
        data = response.json()
        assert data.get("challenge") == "test-challenge-token"

    def test_card_callback_approved(self, client: TestClient) -> None:
        """Simulate a Feishu card button click callback (APPROVED)."""
        callback_body = {
            "action": {
                "value": {
                    "run_id": "test-run-001",
                    "action": "APPROVED",
                    "step_id": "approve_sensitive",
                }
            },
            "open_id": "ou_test_user",
        }
        response = client.post("/webhook/feishu", json=callback_body)
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "ok"
        assert data["decision"] == "APPROVED"

    def test_card_callback_rejected(self, client: TestClient) -> None:
        """Simulate a Feishu card button click callback (REJECTED)."""
        # Override the parse to return REJECTED
        bs = client.app.state.bootstrap
        bs.feishu.parse_card_callback = MagicMock(return_value=None)

        callback_body = {
            "action": {
                "value": {
                    "run_id": "test-run-002",
                    "action": "REJECTED",
                    "step_id": "approve_sensitive",
                }
            },
            "open_id": "ou_test_user",
        }

        # Create a fresh app for this test
        fresh_bs = _make_mock_bootstrap()
        fresh_bs.feishu.parse_card_callback = MagicMock(
            return_value={
                "run_id": "test-run-002",
                "step_id": "approve_sensitive",
                "decision": "REJECTED",
                "reviewer": "ou_test",
                "reason": "Not needed",
            }
        )
        fresh_app = create_app(bootstrap=fresh_bs)
        with TestClient(fresh_app) as c:
            response = c.post("/webhook/feishu", json=callback_body)
            assert response.status_code == 200
            data = response.json()
            assert data["status"] == "ok"
            assert data["decision"] == "REJECTED"

    def test_card_callback_nonexistent_run(self, mock_bs: ServiceBootstrap) -> None:
        """Card callback for a run_id that doesn't exist."""
        mock_bs.state_store.load_state = MagicMock(return_value=None)
        app = create_app(bootstrap=mock_bs)
        with TestClient(app) as c:
            response = c.post(
                "/webhook/feishu",
                json={
                    "action": {
                        "value": {
                            "run_id": "ghost-run",
                            "action": "APPROVED",
                        }
                    }
                },
            )
            data = response.json()
            assert data["status"] == "error"
            assert "not found" in data["reason"]

    def test_unknown_event_ignored(self, client: TestClient) -> None:
        """Events that are not challenges, cards, or IM messages are ignored."""
        response = client.post("/webhook/feishu", json={"event": {"type": "unknown"}})
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "ignored"

    def test_im_message_routes_to_kernel(self, mock_bs: ServiceBootstrap) -> None:
        """An IM message event should be parsed and sent through kernel.wake_up()."""
        mock_bs.feishu.parse_event = MagicMock(
            return_value=MagicMock(
                text="show me the schema",
                sender_id="ou_user",
                sender_name="User",
                channel="feishu",
                message_id="msg_001",
                metadata={},
            )
        )
        app = create_app(bootstrap=mock_bs)
        with TestClient(app) as c:
            response = c.post(
                "/webhook/feishu",
                json={
                    "header": {"event_type": "im.message.receive_v1"},
                    "event": {
                        "message": {"content": '{"text":"hello"}', "message_id": "msg_001"},
                        "sender": {"sender_id": {"user_id": "ou_user"}},
                    },
                },
            )
            assert response.status_code == 200
            data = response.json()
            assert data["status"] == "ok"
        mock_bs.kernel.wake_up.assert_awaited_once()

    def test_no_feishu_adapter_returns_503(self) -> None:
        """Without a Feishu adapter, the webhook endpoint returns 503."""
        bs = _make_mock_bootstrap()
        bs.feishu = None
        app = create_app(bootstrap=bs)
        with TestClient(app) as c:
            response = c.post("/webhook/feishu", json={"challenge": "test"})
            assert response.status_code == 503


class TestSopResumeEndpoint:
    def test_resume_approved(self, client: TestClient) -> None:
        response = client.post(
            "/api/sops/test-run-001/resume",
            json={"decision": "APPROVED", "reason": "Approved by test"},
        )
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "ok"
        assert data["decision"] == "APPROVED"

    def test_resume_rejected(self, client: TestClient) -> None:
        response = client.post(
            "/api/sops/test-run-001/resume",
            json={"decision": "REJECTED", "reason": "Not approved"},
        )
        assert response.status_code == 200
        assert response.json()["decision"] == "REJECTED"

    def test_resume_without_decision_fails(self, client: TestClient) -> None:
        response = client.post(
            "/api/sops/test-run-001/resume",
            json={},
        )
        assert response.status_code == 400
        assert "must be APPROVED" in response.json()["detail"]

    def test_resume_invalid_decision_fails(self, client: TestClient) -> None:
        response = client.post(
            "/api/sops/test-run-001/resume",
            json={"decision": "MAYBE"},
        )
        assert response.status_code == 400

    def test_resume_nonexistent_run(self, mock_bs: ServiceBootstrap) -> None:
        mock_bs.state_store.load_state = MagicMock(return_value=None)
        app = create_app(bootstrap=mock_bs)
        with TestClient(app) as c:
            response = c.post(
                "/api/sops/nonexistent-run/resume",
                json={"decision": "APPROVED"},
            )
            assert response.status_code == 404

    def test_resume_unknown_sop_id(self, client: TestClient) -> None:
        """Resume with a context that references an unknown sop_id."""
        bs = client.app.state.bootstrap
        bs.state_store.load_state = MagicMock(
            return_value=MagicMock(
                run_id="run-unknown-sop",
                sop_id="never-heard-of-it",
                state=MagicMock(value="SUSPENDED"),
                model_dump_json=lambda: '{"run_id":"run-unknown-sop","sop_id":"never-heard-of-it"}',
            )
        )
        response = client.post(
            "/api/sops/run-unknown-sop/resume",
            json={"decision": "APPROVED"},
        )
        assert response.status_code == 404
        assert "not found" in response.json()["detail"]

    def test_resume_no_sop_engine(self) -> None:
        """Without a sop_engine, the resume endpoint returns 503."""
        bs = _make_mock_bootstrap()
        bs.sop_engine = None
        app = create_app(bootstrap=bs)
        with TestClient(app) as c:
            response = c.post(
                "/api/sops/test-run-001/resume",
                json={"decision": "APPROVED"},
            )
            assert response.status_code == 503


class TestBootstrap:
    """Tests for ServiceBootstrap.init() with mocked dependencies."""

    @pytest.mark.asyncio
    async def test_init_loads_config(self, tmp_path: Path) -> None:
        """Bootstrap should load config and set up available components."""
        # Use a minimal config file
        config_content = """
kernel:
  name: "ZeroClaw"
  version: "0.1.0"
adapters:
  feishu:
    enabled: false
  cli:
    enabled: true
neo4j:
  uri: "bolt://localhost:7687"
  user: "neo4j"
  password: "test"
mcp:
  server_name: "test"
  port: 9999
  validation:
    nonce_secret: "test-secret"
    nonce_ttl_seconds: 300
autonomy:
  policy_file: "src/policies/policy_config.yaml"
ontology:
  owl_dir: "docker/ontology"
  shacl_dir: "docker/ontology"
  domains:
    - name: "it-asset-mgmt"
      owl_file: "it-asset-mgmt.owl"
      shacl_file: "it-asset-mgmt.shacl.ttl"
observability:
  enabled: false
langfuse:
  enabled: false
"""
        config_path = tmp_path / "test_config.yaml"
        config_path.write_text(config_content)

        bs = ServiceBootstrap()

        # Neo4j will fail to connect, but that's OK — we test graceful degradation
        await bs.init(str(config_path))

        assert bs.config is not None
        assert bs.schema_provider is not None
        assert bs.write_gate is not None
        assert bs.kernel is not None
        # Neo4j may or may not be available — it's optional
        # SOP engine should be initialised
        assert bs.sop_engine is not None
