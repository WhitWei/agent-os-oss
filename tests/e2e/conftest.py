"""L3 端到端业务场景测试 fixtures。

组合根(composition root)与 scripts/run_uat.py 保持一致 —— 这是当前仓库里
唯一存在的、把 SchemaProvider + WriteGate + Neo4jClient + SOPEngine +
FeedbackDB + WorkflowStateStore 串成一条完整业务链路的方式(因为没有
main.py/FastAPI app 把它们接成一个常驻服务)。
"""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest

from database.feedback_db import FeedbackDB
from database.state_store import WorkflowStateStore
from governance.neo4j_client import Neo4jClient
from governance.schema_provider import SchemaProvider
from governance.write_gate import WriteGate
from policies.autonomy_policy import load_policy
from workflow.sop_engine import SOPEngine
from agentos_kernel.config import Neo4jConfig
from agentos_kernel.kernel import AgentOSKernel


def _docker_available() -> bool:
    if shutil.which("docker") is None:
        return False
    try:
        result = subprocess.run(["docker", "info"], capture_output=True, timeout=5)
        return result.returncode == 0
    except Exception:
        return False


@pytest.fixture(scope="session")
def docker_available() -> bool:
    return _docker_available()


@pytest.fixture(scope="session")
def e2e_neo4j_container(docker_available):
    """整个 E2E 会话共用一个真实 Neo4j 容器(启动成本较高,场景之间用唯一 ID
    区分数据,不需要每个场景单独起一个容器)。"""
    if not docker_available:
        pytest.skip("Docker daemon 不可用 —— 无法进行真实环境业务场景验证")

    from testcontainers.neo4j import Neo4jContainer

    container = Neo4jContainer(image="neo4j:5.26-community", password="e2e-test-12345")
    container.start()
    try:
        yield container
    finally:
        container.stop()


@pytest.fixture
async def neo4j_client(e2e_neo4j_container) -> Neo4jClient:
    config = Neo4jConfig(
        uri=e2e_neo4j_container.get_connection_url(),
        user=e2e_neo4j_container.username,
        password=e2e_neo4j_container.password,
        database="neo4j",
    )
    client = Neo4jClient(config)
    try:
        assert await client.health_check(), "E2E Neo4j 容器未通过 health_check"
        yield client
    finally:
        await client.close()


@pytest.fixture
def schema_provider(app_config) -> SchemaProvider:
    return SchemaProvider(
        owl_dir=app_config.ontology.owl_dir,
        shacl_dir=app_config.ontology.shacl_dir,
        domains=app_config.ontology.domains,
    )


@pytest.fixture
def write_gate(schema_provider, neo4j_client) -> WriteGate:
    """真实写模式的 WriteGate —— 每个测试独立实例,避免 nonce 存储跨场景互相污染。"""
    return WriteGate(
        schema_provider=schema_provider,
        neo4j_client=neo4j_client,
        nonce_secret="e2e-business-scenario-secret",
        nonce_ttl_seconds=300,
    )


@pytest.fixture
def autonomy_policy(app_config):
    return load_policy(app_config.autonomy.policy_file)


@pytest.fixture
def feedback_db(tmp_path: Path) -> FeedbackDB:
    db = FeedbackDB(str(tmp_path / "e2e_feedback.db"))
    try:
        yield db
    finally:
        db.close()


@pytest.fixture
def state_store_path(tmp_path: Path) -> Path:
    """返回路径而不是实例 —— C1(进程重启恢复)场景需要针对同一个文件重新
    构造全新的 WorkflowStateStore 实例来模拟"重启后从磁盘恢复"。"""
    return tmp_path / "e2e_state.db"


@pytest.fixture
def state_store(state_store_path: Path) -> WorkflowStateStore:
    return WorkflowStateStore(str(state_store_path))


@pytest.fixture
def sop_definition(project_root: Path):
    sop_path = project_root / "src" / "workflow" / "sop_examples" / "it-onboarding.sop.yaml"
    return SOPEngine.load_sop(sop_path)


@pytest.fixture
def sop_engine(schema_provider, write_gate, feedback_db, state_store) -> SOPEngine:
    return SOPEngine(
        schema_provider=schema_provider,
        write_gate=write_gate,
        feedback_db=feedback_db,
        state_store=state_store,
    )


@pytest.fixture
def wired_kernel(app_config, write_gate, autonomy_policy) -> AgentOSKernel:
    """完整接线的 kernel(真实防火墙/熔断器/计费熔断),用于 B 组"安全红线嵌入
    业务叙事"场景 —— 验证聊天入口的安全钩子与 SOPEngine 的业务写入路径。"""
    return AgentOSKernel(
        config=app_config,
        write_gate=write_gate,
        autonomy_policy=autonomy_policy,
    )
