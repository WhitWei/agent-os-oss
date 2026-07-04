"""L2 集成测试专用 fixtures。

Rule 10.1 边界规范：本文件里构造的所有 kernel/write_gate 都使用 **真实对象**
(SemanticFirewall / CircuitBreaker / BillingFuse / SHACLValidator 均不打桩)，
只在下面两处做受控配置，且都不是"伪造行为"，而是为了让测试在有限时间内确定性触发：

1. BillingFuse 的预算上限：用真实 BillingFuse 类，只是传入一个便于在 2~3 次调用内
   触发的 budget_cap_usd，而不是等待默认值反复调用。
2. 一个"确定会失败"的 SchemaProvider（指向不存在的本体文件目录）：用于验证熔断器
   在主入口路径上真的会在连续失败后拦截，而不是靠 Mock 抛异常来伪造失败。
"""

from __future__ import annotations

import shutil
from pathlib import Path

import pytest

from agentos.kernel.config import DomainConfig
from agentos.governance.schema_provider import SchemaProvider
from agentos.governance.write_gate import WriteGate
from agentos.policies.autonomy_policy import load_policy
from agentos.security.billing_fuse import BillingFuse, BillingFuseConfig
from agentos.kernel.kernel import AgentOSKernel

@pytest.fixture(scope="session")
def neo4j_container(docker_available):
    if not docker_available:
        pytest.skip("Docker daemon 不可用 —— 无法拉起真实 Neo4j 容器做 L2 落库验证")

    from testcontainers.neo4j import Neo4jContainer

    container = Neo4jContainer(image="neo4j:5.26-community", password="l2test12345")
    container.start()
    try:
        yield container
    finally:
        container.stop()


@pytest.fixture
async def neo4j_client(neo4j_container):
    from agentos.governance.neo4j_client import Neo4jClient
    from agentos.kernel.config import Neo4jConfig
    config = Neo4jConfig(
        uri=neo4j_container.get_connection_url(),
        user=neo4j_container.username,
        password=neo4j_container.password,
        database="neo4j",
    )
    client = Neo4jClient(config)
    try:
        healthy = await client.health_check()
        assert healthy, "testcontainers 起的 Neo4j 容器未通过 health_check —— 环境问题,不是被测代码问题"
        yield client
    finally:
        await client.close()


def _docker_available() -> bool:
    """真实探测 Docker daemon 是否可用（不是猜测，是实际连一次）。"""
    if shutil.which("docker") is None:
        return False
    import subprocess

    try:
        result = subprocess.run(
            ["docker", "info"], capture_output=True, timeout=5
        )
        return result.returncode == 0
    except Exception:
        return False


@pytest.fixture(scope="session")
def docker_available() -> bool:
    return _docker_available()


@pytest.fixture
def real_write_gate(app_config) -> WriteGate:
    """指向真实本体文件的 WriteGate（neo4j_client=None — 安全接线测试不需要落库）。"""
    schema_provider = SchemaProvider(
        owl_dir=app_config.ontology.owl_dir,
        shacl_dir=app_config.ontology.shacl_dir,
        domains=app_config.ontology.domains,
    )
    return WriteGate(
        schema_provider=schema_provider,
        neo4j_client=None,
        nonce_secret="l2-integration-test-secret",
        nonce_ttl_seconds=300,
    )


@pytest.fixture
def broken_write_gate(tmp_path: Path) -> WriteGate:
    """指向一个空目录的 WriteGate —— get_domain_schema 对任何域都会真实抛出
    GovernanceError（AgentOSException 子类）。用来在主入口路径上真实制造连续失败，
    而不是靠 Mock 抛异常伪造熔断器触发条件。
    """
    schema_provider = SchemaProvider(
        owl_dir=str(tmp_path),
        shacl_dir=str(tmp_path),
        domains=[
            DomainConfig(
                name="it-asset-mgmt",
                owl_file="does-not-exist.owl",
                shacl_file="does-not-exist.shacl.ttl",
            )
        ],
    )
    return WriteGate(
        schema_provider=schema_provider,
        neo4j_client=None,
        nonce_secret="l2-integration-test-secret",
        nonce_ttl_seconds=300,
    )


@pytest.fixture
def autonomy_policy(app_config):
    return load_policy(app_config.autonomy.policy_file)


@pytest.fixture
def wired_kernel(app_config, real_write_gate, autonomy_policy) -> AgentOSKernel:
    """完整接线的 kernel —— firewall/circuit_breaker/billing_fuse 由 kernel 内部
    自行构造（走真实 __init__ 默认路径），不注入任何 Mock。"""
    return AgentOSKernel(
        config=app_config,
        write_gate=real_write_gate,
        autonomy_policy=autonomy_policy,
    )


@pytest.fixture
def wired_kernel_small_budget(app_config, real_write_gate, autonomy_policy) -> AgentOSKernel:
    """同上，但注入一个真实的、小额度的 BillingFuse，让计费熔断能在 2~3 次调用内
    确定性触发，避免依赖默认 $0.50 预算下"第一条消息就必定触发"这种脆弱断言。"""
    small_budget_fuse = BillingFuse(BillingFuseConfig(budget_cap_usd=0.01))
    return AgentOSKernel(
        config=app_config,
        write_gate=real_write_gate,
        autonomy_policy=autonomy_policy,
        billing_fuse=small_budget_fuse,
    )


@pytest.fixture
def wired_kernel_broken_schema(app_config, broken_write_gate, autonomy_policy) -> AgentOSKernel:
    """schema 查询必定失败的 kernel —— 用于验证熔断器在主入口路径上真实生效。"""
    return AgentOSKernel(
        config=app_config,
        write_gate=broken_write_gate,
        autonomy_policy=autonomy_policy,
    )
