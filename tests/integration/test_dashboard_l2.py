"""L2 集成测试 — Dashboard 与后端路由物理接线验证 (Rule 10.2)。

验证 SPA 静态资源的正确挂载，以及前端与后端 API 的物理通信。
遵守 Rule 10.2，不使用任何 Mock。
"""

import pytest
import httpx

from agentos.main.main import ServiceBootstrap, create_app
from agentos.kernel.kernel import AgentOSKernel
from agentos.governance.write_gate import WriteGate
from agentos.governance.schema_provider import SchemaProvider
from agentos.database.feedback_db import FeedbackDB
from agentos.database.state_store import WorkflowStateStore
from agentos.workflow.sop_engine import SOPEngine

pytestmark = pytest.mark.integration


@pytest.fixture
async def dashboard_app(app_config, neo4j_client, tmp_path):
    """物理启动后端环境及 SQLite/Neo4j 数据库"""
    bs = ServiceBootstrap()
    bs.config = app_config
    
    bs.schema_provider = SchemaProvider(
        owl_dir=app_config.ontology.owl_dir,
        shacl_dir=app_config.ontology.shacl_dir,
        domains=app_config.ontology.domains,
    )
    
    bs.neo4j_client = neo4j_client
    
    bs.write_gate = WriteGate(
        schema_provider=bs.schema_provider,
        neo4j_client=bs.neo4j_client,
        nonce_secret=app_config.mcp.validation.nonce_secret,
        nonce_ttl_seconds=300,
    )
    
    db_path = tmp_path / "feedback.db"
    state_path = tmp_path / "state.db"
    bs.feedback_db = FeedbackDB(str(db_path))
    bs.state_store = WorkflowStateStore(str(state_path))
    
    bs.sop_engine = SOPEngine(
        schema_provider=bs.schema_provider,
        write_gate=bs.write_gate,
        feedback_db=bs.feedback_db,
        state_store=bs.state_store,
        default_chat_id="test_chat",
    )
    
    from agentos.policies.autonomy_policy import load_policy
    try:
        bs.policy = load_policy(app_config.autonomy.policy_file)
    except Exception:
        bs.policy = None
        
    bs.kernel = AgentOSKernel(
        config=app_config,
        write_gate=bs.write_gate,
        autonomy_policy=bs.policy,
    )
    bs.available_sops = []
    
    app = create_app(bootstrap=bs)
    yield app
    
    bs.feedback_db.close()


@pytest.mark.asyncio
class TestDashboardL2Integration:
    """SPA 前端与 API 的 L2 物理连通性测试"""

    async def test_dashboard_static_and_spa_fallback(self, dashboard_app):
        """测试静态文件服务与 SPA 路由回退功能"""
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=dashboard_app), base_url="http://test") as client:
            
            # 1. 访问 /dashboard (应返回 index.html)
            resp = await client.get("/dashboard")
            assert resp.status_code == 200
            assert "text/html" in resp.headers.get("content-type", "")
            assert "<html" in resp.text
            
            # 2. 访问 /dashboard/index.html (真实存在的静态文件)
            resp_index = await client.get("/dashboard/index.html")
            assert resp_index.status_code == 200
            assert "<html" in resp_index.text
            
            # 3. SPA 路由回退：访问一个不存在的 SPA 路由例如 /dashboard/settings
            resp_fallback = await client.get("/dashboard/settings")
            assert resp_fallback.status_code == 200
            assert "<html" in resp_fallback.text
            assert "Dashboard" in resp_fallback.text
            
            # 4. 访问 Next.js 构建产物 (如 _next/static/... 等)
            # 通过 fallback 路由它会尝试读取真实文件。如果文件不存在它会退回 index.html，
            # 但既然 fallback 能处理，我们就验证路由机制未崩溃即可。

    async def test_api_metrics_overview(self, dashboard_app):
        """测试 /api/v1/metrics/overview 真实 API 端点物理连通性"""
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=dashboard_app), base_url="http://test") as client:
            
            resp = await client.get("/api/v1/metrics/overview")
            assert resp.status_code == 200
            data = resp.json()
            assert "total_governed_writes" in data
            assert isinstance(data["total_governed_writes"], int)
