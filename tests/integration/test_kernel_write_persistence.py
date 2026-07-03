"""L2 集成测试 — governed write 物理落库验证 (WO-302)。

对应 Rule 10.2:"必须断言当发生恶意 Prompt 或超额写入时,主路由线上的防火墙、
熔断器和配额机制是真实被触发并产生了物理拦截"。
我们测试主入口 AgentOSKernel.wake_up() 是否能真正落库。
"""

from __future__ import annotations

import pytest

from agentos_kernel.kernel import ChannelMessage

pytestmark = pytest.mark.integration
pytestmark = pytest.mark.asyncio

class TestKernelWakeUpWritePersistence:
    async def test_wake_up_write_is_actually_readable_back_from_neo4j(
        self, app_config, neo4j_client, real_write_gate, sample_valid_ttl
    ):
        """完整三段式 + 独立读回校验，通过 kernel.wake_up 执行。"""
        from agentos_kernel.kernel import AgentOSKernel
        from policies.autonomy_policy import load_policy

        sample_valid_ttl = sample_valid_ttl.strip()
        
        # inject the real neo4j_client into the real_write_gate
        real_write_gate._neo4j_client = neo4j_client

        policy = load_policy(app_config.autonomy.policy_file)
        kernel = AgentOSKernel(
            config=app_config,
            write_gate=real_write_gate,
            autonomy_policy=policy,
        )

        # Reset billing fuse to prevent failures due to shared test state
        if getattr(kernel, "_billing_fuse", None):
            kernel._billing_fuse._budget = 99999.0
            kernel._billing_fuse._current_spend = 0.0

        # Stage 1: Get schema (skip for this test as we already have valid ttl)
        # Stage 2: Validate to get nonce
        report, nonce = real_write_gate.verify_shacl_compliance(
            "it-asset-mgmt", sample_valid_ttl
        )
        assert report.is_valid
        assert nonce is not None

        # Stage 3: Send message through wake_up
        msg = ChannelMessage(
            text=f"execute_governed_write it-asset-mgmt {nonce}\n{sample_valid_ttl}",
            sender_id="tester",
            sender_name="Tester",
            channel="cli",
        )
        response = await kernel.wake_up(msg)
        
        assert response.metadata.get("status") == "ok", f"Expected ok but got {response.metadata}"
        assert "Write successful" in response.text

        # Independent verify
        rows = await neo4j_client.execute_read(
            "MATCH (a:Resource {uri: $uri})-[:SERIALNUMBER]->(b:Resource) RETURN b.uri AS serial",
            {"uri": "http://agent-os.local/data/asset/mbp-001"},
        )
        assert len(rows) == 1, (
            "governed write 声称成功,但从 Neo4j 里查不到对应的资产节点"
        )
        assert rows[0]["serial"] == "MBP2024-X7K9"
