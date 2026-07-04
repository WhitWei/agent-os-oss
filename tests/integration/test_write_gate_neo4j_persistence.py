"""L2 集成测试 — governed write 是否真的把数据落到 Neo4j。

对应 Rule 10.2:"涉及数据落库时,必须使用真实的容器/图数据库进行真实写入,并从
数据库中读取并断言该实体确实存在……绝对禁止因环境配置繁琐而使用 Dummy 字典
伪造成功"。

这里用 testcontainers 拉起一个真实、一次性的 Neo4j 容器,完整走一遍
schema → SHACL 校验 → nonce → execute_governed_write 三段式,然后用一条独立的
Cypher 查询把数据读回来验证 —— 不信任 execute_governed_write() 自己返回的
"status": "success",只信任数据库里查得到的东西。
"""

from __future__ import annotations

import pytest

from agentos.governance.neo4j_client import Neo4jClient
from agentos.governance.schema_provider import SchemaProvider
from agentos.governance.write_gate import WriteGate
from agentos.kernel.config import Neo4jConfig
from agentos.kernel.exceptions import SHACLValidationError

pytestmark = pytest.mark.integration




@pytest.fixture
def write_gate_with_real_neo4j(app_config, neo4j_client) -> WriteGate:
    schema_provider = SchemaProvider(
        owl_dir=app_config.ontology.owl_dir,
        shacl_dir=app_config.ontology.shacl_dir,
        domains=app_config.ontology.domains,
    )
    return WriteGate(
        schema_provider=schema_provider,
        neo4j_client=neo4j_client,
        nonce_secret="l2-neo4j-persistence-secret",
        nonce_ttl_seconds=300,
    )


class TestGovernedWritePersistsToRealNeo4j:
    async def test_valid_write_is_actually_readable_back_from_neo4j(
        self, write_gate_with_real_neo4j, neo4j_client, sample_valid_ttl
    ):
        """完整三段式 + 独立读回校验。这是本文件里唯一"信任"的断言方式:
        不看 execute_governed_write() 的返回值字典,只看数据库里能不能查到。
        """
        # Stage 1
        schema = write_gate_with_real_neo4j.get_domain_schema("it-asset-mgmt")
        assert schema["domain"] == "it-asset-mgmt"

        # Stage 2
        report, nonce = write_gate_with_real_neo4j.verify_shacl_compliance(
            "it-asset-mgmt", sample_valid_ttl
        )
        assert report.is_valid
        assert nonce is not None

        # Stage 3 —— 真实 await 写入,不是"看起来成功"
        result = await write_gate_with_real_neo4j.execute_governed_write(
            "it-asset-mgmt", sample_valid_ttl, validation_nonce=nonce
        )
        assert result["status"] == "success"

        # ── 独立读回校验:不信任上面 result 的返回值,直接查数据库 ──
        rows = await neo4j_client.execute_read(
            "MATCH (a:Resource {uri: $uri})-[:SERIALNUMBER]->(b:Resource) "
            "RETURN b.uri AS serial",
            {"uri": "http://agent-os.local/data/asset/mbp-001"},
        )
        assert len(rows) == 1, (
            "governed write 声称成功,但从 Neo4j 里查不到对应的资产节点 —— "
            "这正是之前那个'返回成功但从未真正写入'的 bug 的回归测试。"
        )
        assert rows[0]["serial"] == "MBP2024-X7K9"

    async def test_invalid_data_never_reaches_neo4j(
        self, write_gate_with_real_neo4j, neo4j_client, sample_invalid_ttl
    ):
        """反向对照:SHACL 校验失败的数据,不应该有任何途径写入数据库 —— 即便
        跳过 nonce 检查直接尝试(用一个伪造 nonce 验证会被拒绝),数据库里也绝不能
        出现这条记录。这是"治理闸门是否真的挡在数据库前面"的落库层面证据。"""
        report, nonce = write_gate_with_real_neo4j.verify_shacl_compliance(
            "it-asset-mgmt", sample_invalid_ttl
        )
        assert not report.is_valid
        assert nonce is None

        with pytest.raises(Exception):
            await write_gate_with_real_neo4j.execute_governed_write(
                "it-asset-mgmt", sample_invalid_ttl, validation_nonce="fake-nonce-attempt"
            )

        rows = await neo4j_client.execute_read(
            "MATCH (a:Resource {uri: $uri}) RETURN a",
            {"uri": "http://agent-os.local/data/asset/laptop-bad"},
        )
        assert len(rows) == 0, "SHACL 校验失败的数据不应该出现在数据库里"
