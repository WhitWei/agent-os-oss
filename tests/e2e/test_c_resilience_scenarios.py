"""L3 业务场景组 C —— 韧性与恢复(真实重启 / 真实下游故障模拟)。

这两个场景都不 Mock 故障——C1 真的构造一个指向同一个 sqlite 文件的全新
WorkflowStateStore 实例来模拟进程重启；C2 真的把 WriteGate 接到一个连不通
的 Neo4j 地址上，而不是靠抛异常的 Mock 来"假装" Neo4j 挂了。
"""

from __future__ import annotations

import pytest

from agentos.database.feedback_db import FeedbackDB
from agentos.governance.neo4j_client import Neo4jClient
from agentos.governance.schema_provider import SchemaProvider
from agentos.governance.write_gate import WriteGate
from agentos.database.state_store import WorkflowStateStore
from tests.e2e.business_data import assignment_ttl, count_resource_nodes, onboarding_data
from agentos.workflow.sop_engine import SOPEngine
from agentos.workflow.sop_schema import SOPRunState
from agentos.kernel.config import Neo4jConfig

pytestmark = pytest.mark.integration


class TestC1_ProcessRestartResumesApprovalFromDisk:
    """C1: SOP 挂起等待审批期间，模拟服务进程重启(state_store 从磁盘重新
    加载，而不是复用内存里的旧对象)，验证审批依然能被正确恢复并继续执行。

    这是 WorkflowStateStore 存在的全部意义 —— 如果只在内存对象上验证
    resume()，这条能力实际上从未被真正测试过。
    """

    async def test_suspended_approval_survives_simulated_restart(
        self,
        schema_provider,
        write_gate,
        feedback_db,
        state_store_path,
        state_store,
        sop_definition,
        neo4j_client,
    ):
        # ── "重启前" 的进程：发起流程并挂起 ──
        engine_before_restart = SOPEngine(
            schema_provider=schema_provider,
            write_gate=write_gate,
            feedback_db=feedback_db,
            state_store=state_store,
        )

        report, nonce = write_gate.verify_shacl_compliance(
            "it-asset-mgmt", assignment_ttl("c1-assign-001")
        )
        assert report.is_valid

        data = onboarding_data(
            employee_id="EMP-C1-001",
            employee_name="周涛",
            asset_id="c1-asset-001",
            serial_number="MBP-C1-SN-001",
            model="MacBook Pro 16 M4",
            sensitivity="HIGH",
            assignment_id="c1-assign-001",
            nonce=nonce,
        )
        ctx = engine_before_restart.create_run(sop_definition, data)
        ctx = await engine_before_restart.run(sop_definition, ctx)
        assert ctx.state == SOPRunState.SUSPENDED
        run_id = ctx.run_id

        # ── 模拟进程重启:不复用上面的 state_store 对象，
        #    而是针对同一个 sqlite 文件路径构造一个全新实例 ──
        state_store_after_restart = WorkflowStateStore(str(state_store_path))
        engine_after_restart = SOPEngine(
            schema_provider=schema_provider,
            write_gate=write_gate,
            feedback_db=feedback_db,
            state_store=state_store_after_restart,
        )

        loaded_ctx = state_store_after_restart.load_state(run_id)
        assert loaded_ctx is not None, "重启后无法从磁盘恢复挂起的运行上下文"
        assert loaded_ctx.state == SOPRunState.SUSPENDED
        assert loaded_ctx.suspended_step_id == "approve_sensitive_asset"

        # ── "重启后" 的进程收到审批回调，继续执行 ──
        resumed_ctx = await engine_after_restart.resume(
            sop_definition, loaded_ctx, decision="APPROVED",
            reason="重启后补批", approver_id="ou_manager_c1",
        )

        assert resumed_ctx.state == SOPRunState.COMPLETED, (
            "重启恢复后的流程应当能正常跑完 —— 若这里失败，"
            "请对照测试报告里已记录的 SOPEngine 治理写入 await 缺失问题，"
            "而不是当作新的重启恢复缺陷。"
        )

        record = feedback_db.get_by_trace_id(run_id)
        assert record is not None
        assert record.decision == "APPROVED"
        assert record.reviewer == "ou_manager_c1"

        # ── 关键:不能只看 ctx.state 说了什么，必须独立读回数据库 ──
        # ctx.state == COMPLETED 这件事本身，在已知的 await 缺失 bug 下，
        # 无论数据有没有真的写进去都会成立 —— 所以"重启恢复是否真的完成了
        # 业务交易"这个问题，唯一可信的答案只能来自数据库本身。
        assert await count_resource_nodes(
            neo4j_client, "http://agent-os.local/data/assignment/c1-assign-001"
        ) == 1, (
            "重启恢复后 ctx.state 报告 COMPLETED，但 Neo4j 里查不到对应记录 —— "
            "与 A1 场景是同一个根因(SOPEngine 治理写入协程未被 await)，"
            "不是重启恢复机制本身的缺陷。"
        )


class TestC2_Neo4jOutageDuringWriteFailsHonestly:
    """C2: 治理写入阶段 Neo4j 真实不可达，验证系统诚实地把流程标记为
    FAILED，而不是崩溃、挂起，或者更糟——报告一个从未真正发生的"成功"。
    """

    async def test_neo4j_outage_during_governed_write_yields_failed_state(
        self, schema_provider, feedback_db, state_store, sop_definition
    ):
        # 故意指向一个不可达端口，模拟 Neo4j 下线/网络分区
        broken_config = Neo4jConfig(
            uri="bolt://127.0.0.1:1", user="neo4j", password="unreachable",
            database="neo4j",
        )
        broken_neo4j_client = Neo4jClient(broken_config)
        broken_write_gate = WriteGate(
            schema_provider=schema_provider,
            neo4j_client=broken_neo4j_client,
            nonce_secret="e2e-c2-secret",
            nonce_ttl_seconds=300,
        )

        try:
            report, nonce = broken_write_gate.verify_shacl_compliance(
                "it-asset-mgmt", assignment_ttl("c2-assign-001")
            )
            assert report.is_valid  # SHACL 校验不碰 Neo4j，应该照常通过

            engine = SOPEngine(
                schema_provider=schema_provider,
                write_gate=broken_write_gate,
                feedback_db=feedback_db,
                state_store=state_store,
            )
            data = onboarding_data(
                employee_id="EMP-C2-001",
                employee_name="吴敏",
                asset_id="c2-asset-001",
                serial_number="MBP-C2-SN-001",
                model="MacBook Pro 16 M4",
                sensitivity="HIGH",
                assignment_id="c2-assign-001",
                nonce=nonce,
            )
            ctx = engine.create_run(sop_definition, data)
            ctx = await engine.run(sop_definition, ctx)
            assert ctx.state == SOPRunState.SUSPENDED

            ctx = await engine.resume(
                sop_definition, ctx, decision="APPROVED",
                reason="批准，但下游 Neo4j 已下线", approver_id="ou_manager_c2",
            )

            assert ctx.state == SOPRunState.FAILED, (
                "Neo4j 不可达时,治理写入必须诚实地把流程标记为 FAILED。"
                "如果这里断言失败且 ctx.state 是 COMPLETED，说明写入步骤"
                "根本没有真正尝试连接 Neo4j —— 这正是测试报告里那个"
                "'协程从未被 await'问题的最极端后果:连数据库下线都测不出来。"
            )
            assert len(ctx.errors) >= 1
        finally:
            await broken_neo4j_client.close()
