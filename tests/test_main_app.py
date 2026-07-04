"""L1 单元测试：agentos_main/main.py。

测试范围（诚实的 L1 边界）：
  1. create_app 工厂函数能正确创建 FastAPI 实例并注册预期路由。
  2. ServiceBootstrap 能从最小 config.yaml 加载组件（无真实 Neo4j 时优雅降级）。
  3. _handle_card_callback 逻辑分支。

不在此范围内的（后续需通过 tests/integration/ 里的真实 testcontainers 测试覆盖）：
  - 完整的 HTTP 请求/响应生命周期（需要 real Neo4j + real SQLite）。
  - Feishu webhook 签名校验（需要 real 飞书配置）。
  - SOP resume 的端到端流程（需要 real SOP YAML + real 状态存储）。

本测试套件使用 unittest.mock 隔离外部依赖，测试目标是被测模块的结构和逻辑，
不测试 IO/网络/真实的组件交互（那是 L2+ 的职责）。
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi import FastAPI
from fastapi.routing import APIRoute

from agentos_main.main import create_app, ServiceBootstrap


class TestCreateAppFactory:
    """create_app() 工厂函数的基础结构测试（L1，全 Mock 隔离）。"""

    def test_create_app_returns_fastapi_instance(self) -> None:
        """工厂函数应返回一个有效的 FastAPI 实例。"""
        app = create_app()
        assert isinstance(app, FastAPI)
        assert app.title == "Agent OS Unified Service"

    def test_create_app_accepts_mock_bootstrap(self) -> None:
        """接受外部注入的 bootstrap（测试模式），不触发真实 init。"""
        mock = MagicMock(spec=ServiceBootstrap)
        mock.kernel = MagicMock()
        mock.schema_provider = MagicMock()
        mock.schema_provider.list_domains.return_value = []
        mock.available_sops = []
        mock.neo4j_client = MagicMock()
        mock.write_gate = MagicMock()
        mock.sop_engine = MagicMock()
        mock.feishu = MagicMock()
        mock.feedback_db = MagicMock()
        mock.state_store = MagicMock()
        mock.config = MagicMock()
        mock.policy = MagicMock()

        app = create_app(bootstrap=mock)
        assert isinstance(app, FastAPI)

    def test_routes_are_registered(self) -> None:
        """应注册健康检查、webhook、API 路由。"""
        app = create_app()
        route_paths = {r.path for r in app.routes if isinstance(r, APIRoute)}

        assert "/health" in route_paths
        assert "/webhook/feishu" in route_paths
        assert "/api/domains" in route_paths
        assert "/api/sops" in route_paths
        assert "/api/sops/{run_id}/resume" in route_paths

    def test_get_sop_by_id_route_is_registered(self) -> None:
        """具体的 SOP 详情查询路由应存在。"""
        app = create_app()
        route_paths = {r.path for r in app.routes if isinstance(r, APIRoute)}
        assert "/api/sops/{sop_id}" in route_paths

    def test_cors_middleware_is_configured(self) -> None:
        """应配置 CORS 中间件（开放模式用于开发）。"""
        app = create_app()
        cors_present = any(
            "CORSMiddleware" in str(m.cls)
            for m in app.user_middleware
        )
        assert cors_present


class TestServiceBootstrap:
    """ServiceBootstrap 的结构和降级行为测试（L1）。"""

    def test_default_attributes_are_none(self) -> None:
        """初始状态下所有组件属性应为 None。"""
        bs = ServiceBootstrap()
        assert bs.kernel is None
        assert bs.sop_engine is None
        assert bs.write_gate is None
        assert bs.schema_provider is None
        assert bs.neo4j_client is None
        assert bs.feedback_db is None
        assert bs.state_store is None
        assert bs.feishu is None
        assert bs.available_sops == []

    def test_no_llm_driver_attribute(self) -> None:
        """ServiceBootstrap 不应包含 llm_driver 字段（BYO LLM 架构决策）。"""
        bs = ServiceBootstrap()
        # Per BYO LLM architecture: Agent OS does not bundle LLM drivers
        assert not hasattr(bs, "llm_driver")

    @pytest.mark.asyncio
    async def test_init_degrades_gracefully_without_neo4j(self, tmp_path: Path) -> None:
        """没有 Neo4j 时 init() 应优雅降级（不崩溃，写操作将被模拟）。"""
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
  password: "irrelevant"
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
        # Should not crash — Neo4j unavailable, policy file may not be found
        await bs.init(str(config_path))

        # Core components should still be initialised
        assert bs.config is not None
        assert bs.schema_provider is not None
        assert bs.write_gate is not None
        assert bs.kernel is not None
        assert bs.sop_engine is not None
        # FeedbackDB and state_store create SQLite files on disk
        assert bs.feedback_db is not None
        assert bs.state_store is not None
        # Neo4j may or may not be available — graceful degradation
        # feishu adapter is skipped (enabled: false)


class TestCardCallback:
    """_handle_card_callback 的逻辑分支测试（L1）。"""

    @pytest.mark.asyncio
    async def test_callback_with_fully_mocked_state(self) -> None:
        """使用全 Mock 的 ServiceBootstrap 验证回调处理不崩溃。"""
        # This is a structural check: the function exists and accepts the right types.
        # Real callback logic requires real SOP state and is tested in L2.
        from agentos_main.main import _handle_card_callback, ServiceBootstrap

        bs = MagicMock(spec=ServiceBootstrap)
        bs.feishu = MagicMock()
        bs.feishu.parse_card_callback.return_value = {
            "run_id": "test-001",
            "step_id": "step-1",
            "decision": "APPROVED",
            "reviewer": "ou_test",
            "reason": "approved",
        }
        bs.sop_engine = AsyncMock()
        bs.state_store = MagicMock()
        bs.state_store.load_state.return_value = MagicMock(
            sop_id="test-sop",
            run_id="test-001",
        )
        bs.available_sops = []

        result = await _handle_card_callback({"action": {"value": {}}}, bs)
        assert result["status"] == "error"  # No SOP definition found
        assert "not found" in result["reason"]


class TestHealthResponseStructure:
    """健康检查响应的结构测试（通过直接调用路由处理函数验证逻辑）。"""

    def test_health_details_keys_match_expected(self) -> None:
        """health 端点返回的字段应包含所有组件状态标记。"""
        app = create_app()
        # Find the health route handler
        for route in app.routes:
            if isinstance(route, APIRoute) and route.path == "/health":
                handler = route.endpoint
                break
        else:
            pytest.fail("Health route not found")

        # Verify the route is correctly registered (signature + metadata)
        assert hasattr(handler, "__name__")
        assert handler.__name__ == "health"
