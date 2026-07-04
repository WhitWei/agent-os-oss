"""L3 业务场景组 D —— 并发多用户隔离 与 子系统架构隔离。

D1 验证"业务层"隔离:两个员工的入职流程并发发起，互不串数据。
D2 验证"架构层"隔离:kernel 的聊天安全钩子与 SOPEngine 的业务执行链路
是两个完全独立的子系统 —— 这不是假设，是本仓库当前的真实接线状态
(全仓库搜索确认 AgentOSKernel 从未调用过 SOPEngine)，用测试把这个事实
钉下来，防止未来有人在不知情的情况下把两者错误地当成"一套安全模型"。
"""

from __future__ import annotations

import asyncio
from pathlib import Path

import pytest

from agentos.database.feedback_db import FeedbackDB
from agentos.governance.schema_provider import SchemaProvider
from agentos.governance.write_gate import WriteGate
from tests.e2e.business_data import assignment_ttl, count_resource_nodes, onboarding_data
from agentos.workflow.sop_engine import SOPEngine
from agentos.workflow.sop_schema import SOPRunState
from agentos.kernel.config import DomainConfig
from agentos.kernel.exceptions import CircuitBreakerOpenError
from agentos.kernel.kernel import ChannelMessage, AgentOSKernel

pytestmark = pytest.mark.integration


class TestD1_ConcurrentEmployeeOnboardingIsolation:
    """D1: 两名员工的入职申请并发发起、并发审批，验证 run_id、
    FeedbackDB 记录、ctx.data 之间完全不串扰。"""

    async def test_two_concurrent_onboardings_do_not_cross_contaminate(
        self, sop_engine, sop_definition, write_gate, feedback_db, neo4j_client
    ):
        report_x, nonce_x = write_gate.verify_shacl_compliance(
            "it-asset-mgmt", assignment_ttl("d1-assign-x")
        )
        report_y, nonce_y = write_gate.verify_shacl_compliance(
            "it-asset-mgmt", assignment_ttl("d1-assign-y")
        )
        assert report_x.is_valid and report_y.is_valid

        data_x = onboarding_data(
            employee_id="EMP-D1-X", employee_name="员工X",
            asset_id="d1-asset-x", serial_number="SN-D1-X",
            model="MacBook Pro 16 M4", sensitivity="HIGH",
            assignment_id="d1-assign-x", nonce=nonce_x,
        )
        data_y = onboarding_data(
            employee_id="EMP-D1-Y", employee_name="员工Y",
            asset_id="d1-asset-y", serial_number="SN-D1-Y",
            model="Dell Latitude 5440", sensitivity="CRITICAL",
            assignment_id="d1-assign-y", nonce=nonce_y,
        )

        ctx_x = sop_engine.create_run(sop_definition, data_x)
        ctx_y = sop_engine.create_run(sop_definition, data_y)

        # 真正并发执行,给 sqlite state_store / feedback_db 的并发访问路径加压
        ctx_x, ctx_y = await asyncio.gather(
            sop_engine.run(sop_definition, ctx_x),
            sop_engine.run(sop_definition, ctx_y),
        )

        assert ctx_x.run_id != ctx_y.run_id
        assert ctx_x.state == SOPRunState.SUSPENDED
        assert ctx_y.state == SOPRunState.SUSPENDED

        # 并发恢复:X 批准，Y 驳回
        ctx_x, ctx_y = await asyncio.gather(
            sop_engine.resume(
                sop_definition, ctx_x, decision="APPROVED",
                reason="X 批准", approver_id="ou_manager_x",
            ),
            sop_engine.resume(
                sop_definition, ctx_y, decision="REJECTED",
                reason="Y 驳回", approver_id="ou_manager_y",
            ),
        )

        assert ctx_y.state == SOPRunState.REJECTED

        record_x = feedback_db.get_by_trace_id(ctx_x.run_id)
        record_y = feedback_db.get_by_trace_id(ctx_y.run_id)
        assert record_x is not None and record_x.decision == "APPROVED"
        assert record_x.reviewer == "ou_manager_x"
        assert record_y is not None and record_y.decision == "REJECTED"
        assert record_y.reviewer == "ou_manager_y"
        # 交叉校验:两条记录不能互相串位
        assert record_x.trace_id != record_y.trace_id

        # Y 被驳回，不应有任何写入痕迹(这条断言不依赖已知的写入 bug)
        assert await count_resource_nodes(
            neo4j_client, "http://agent-os.local/data/assignment/d1-assign-y"
        ) == 0


class TestD2_KernelSecurityHooksAreIsolatedFromSopEngine:
    """D2: 让 kernel 的熔断器因反复失败真实跳闸，验证这不会影响一个完全
    独立发起的合法 SOPEngine 业务流程 —— 因为两者是两个不同的组合根，
    kernel 的熔断器实例从未被 SOPEngine 引用过。"""

    async def test_tripped_kernel_circuit_breaker_does_not_block_sop_engine(
        self, app_config, tmp_path: Path, autonomy_policy,
        sop_engine, sop_definition, write_gate,
    ):
        # 构造一个"必定失败"的 kernel:指向不存在的本体文件目录
        broken_schema_provider = SchemaProvider(
            owl_dir=str(tmp_path), shacl_dir=str(tmp_path),
            domains=[
                DomainConfig(
                    name="it-asset-mgmt",
                    owl_file="missing.owl",
                    shacl_file="missing.shacl.ttl",
                )
            ],
        )
        broken_write_gate = WriteGate(
            schema_provider=broken_schema_provider,
            neo4j_client=None,
            nonce_secret="e2e-d2-secret",
        )
        broken_kernel = AgentOSKernel(
            config=app_config, write_gate=broken_write_gate,
            autonomy_policy=autonomy_policy,
        )

        failing_msg = ChannelMessage(
            text="Show me the schema for it-asset-mgmt",
            sender_id="user", sender_name="Dave", channel="cli",
        )
        for _ in range(3):
            resp = await broken_kernel.wake_up(failing_msg)
            assert resp.metadata["status"] == "error"

        tripped = await broken_kernel.wake_up(failing_msg)
        assert tripped.metadata["status"] == "tripped", (
            "前置条件不满足:kernel 熔断器应该已经因连续 3 次真实失败而跳闸"
        )

        # ── 与上面完全独立的一个 SOPEngine 实例(不同的 write_gate/schema_provider)──
        report, nonce = write_gate.verify_shacl_compliance(
            "it-asset-mgmt", assignment_ttl("d2-assign-001")
        )
        assert report.is_valid

        data = onboarding_data(
            employee_id="EMP-D2-001", employee_name="郑爽",
            asset_id="d2-asset-001", serial_number="SN-D2-001",
            model="MacBook Pro 16 M4", sensitivity="HIGH",
            assignment_id="d2-assign-001", nonce=nonce,
        )
        ctx = sop_engine.create_run(sop_definition, data)
        ctx = await sop_engine.run(sop_definition, ctx)

        # 只需证明 SOPEngine 完全正常地跑到了挂起点，
        # 完全没有受到上面那个已跳闸的 kernel 熔断器影响。
        assert ctx.state == SOPRunState.SUSPENDED
        assert ctx.suspended_step_id == "approve_sensitive_asset"
