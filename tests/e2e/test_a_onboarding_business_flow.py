"""L3 业务场景组 A —— 新员工 IT 设备入职分配(it-onboarding-v1 SOP)核心闭环。

真实依赖:真实 Neo4j 容器 + 真实 SHACL 校验 + 真实 SOPEngine 状态机 +
真实 FeedbackDB。每条断言的"数据是否落库"，都通过独立的 Cypher 读回验证，
不信任 SOPEngine/WriteGate 自身返回的状态字段。
"""

from __future__ import annotations

import pytest

from tests.e2e.business_data import (
    assignment_ttl,
    count_resource_nodes,
    hardware_asset_ttl,
    onboarding_data,
)
from workflow.sop_schema import SOPRunState

pytestmark = pytest.mark.integration


class TestA1_SensitiveAssetApprovedFlow:
    """A1: 敏感设备(HIGH)入职 → 主管审批通过 → 治理写入落库 → 审批记录留痕。"""

    async def test_sensitive_asset_approval_completes_and_persists(
        self, sop_engine, sop_definition, write_gate, neo4j_client, feedback_db
    ):
        report, nonce = write_gate.verify_shacl_compliance(
            "it-asset-mgmt", assignment_ttl("a1-assign-001")
        )
        assert report.is_valid

        data = onboarding_data(
            employee_id="EMP-A1-001",
            employee_name="王芳",
            asset_id="a1-asset-001",
            serial_number="MBP-A1-SN-001",
            model="MacBook Pro 16 M4",
            sensitivity="HIGH",
            assignment_id="a1-assign-001",
            nonce=nonce,
        )

        ctx = sop_engine.create_run(sop_definition, data)
        ctx = await sop_engine.run(sop_definition, ctx)

        assert ctx.state == SOPRunState.SUSPENDED
        assert ctx.suspended_step_id == "approve_sensitive_asset"

        ctx = await sop_engine.resume(
            sop_definition, ctx, decision="APPROVED", reason="设备型号符合规范",
            approver_id="ou_manager_a1",
        )

        assert ctx.state == SOPRunState.COMPLETED

        # ── 独立读回校验:不信任 ctx.step_results,直接查数据库 ──
        # 注意:SOP 里只有 execute_assignment(governed_write on assignment_ttl)
        # 这一个步骤会真正写 Neo4j。validate_employee / validate_asset 只做 SHACL
        # 校验，assignment_ttl 本身也不包含指向 employee/asset 的 RDF 关系，
        # 所以 employee/asset 节点预期为 0，只有 assignment 节点预期为 1。
        assert await count_resource_nodes(
            neo4j_client, "http://agent-os.local/data/employee/EMP-A1-001"
        ) == 0
        assert await count_resource_nodes(
            neo4j_client, "http://agent-os.local/data/asset/a1-asset-001"
        ) == 0
        assert await count_resource_nodes(
            neo4j_client, "http://agent-os.local/data/assignment/a1-assign-001"
        ) == 1, (
            "governed_write 步骤在 ctx.state 里报告 COMPLETED，"
            "但 Neo4j 里查不到对应的 assignment 节点。"
        )

        record = feedback_db.get_by_trace_id(ctx.run_id)
        assert record is not None
        assert record.decision == "APPROVED"
        assert record.reviewer == "ou_manager_a1"


class TestA2_SensitiveAssetRejectedFlow:
    """A2: 敏感设备(CRITICAL)入职 → 主管驳回 → 流程终止且零副作用。"""

    async def test_sensitive_asset_rejection_has_zero_side_effects(
        self, sop_engine, sop_definition, write_gate, neo4j_client, feedback_db
    ):
        report, nonce = write_gate.verify_shacl_compliance(
            "it-asset-mgmt", assignment_ttl("a2-assign-001")
        )
        assert report.is_valid

        data = onboarding_data(
            employee_id="EMP-A2-001",
            employee_name="赵磊",
            asset_id="a2-asset-001",
            serial_number="MBP-A2-SN-001",
            model="MacBook Pro 16 M4",
            sensitivity="CRITICAL",
            assignment_id="a2-assign-001",
            nonce=nonce,
        )

        ctx = sop_engine.create_run(sop_definition, data)
        ctx = await sop_engine.run(sop_definition, ctx)
        assert ctx.state == SOPRunState.SUSPENDED

        ctx = await sop_engine.resume(
            sop_definition, ctx, decision="REJECTED", reason="设备型号不在采购目录内",
            approver_id="ou_manager_a2",
        )

        assert ctx.state == SOPRunState.REJECTED

        # ── 驳回后不应有任何数据写入 Neo4j(execute_assignment 步骤从未被执行) ──
        assert await count_resource_nodes(
            neo4j_client, "http://agent-os.local/data/assignment/a2-assign-001"
        ) == 0

        record = feedback_db.get_by_trace_id(ctx.run_id)
        assert record is not None
        assert record.decision == "REJECTED"
        assert record.reason == "设备型号不在采购目录内"


class TestA3_LowSensitivityAutoApproveFlow:
    """A3: 非敏感设备(MEDIUM)入职 → 审批条件不触发 → 无需人工介入直接完成。

    覆盖 SOPEngine._step_human_approval 里从未被 run_uat.py 覆盖过的
    "条件为假 → 自动通过、不挂起、不发卡片" 分支。
    """

    async def test_low_sensitivity_asset_skips_approval_entirely(
        self, sop_engine, sop_definition, write_gate, neo4j_client
    ):
        report, nonce = write_gate.verify_shacl_compliance(
            "it-asset-mgmt", assignment_ttl("a3-assign-001")
        )
        assert report.is_valid

        data = onboarding_data(
            employee_id="EMP-A3-001",
            employee_name="陈静",
            asset_id="a3-asset-001",
            serial_number="DELL-A3-SN-001",
            model="Dell Latitude 5440",
            sensitivity="MEDIUM",
            assignment_id="a3-assign-001",
            nonce=nonce,
        )

        ctx = sop_engine.create_run(sop_definition, data)
        ctx = await sop_engine.run(sop_definition, ctx)

        # 单次 run() 调用内直接跑完全部步骤，不需要 resume()
        assert ctx.state == SOPRunState.COMPLETED
        assert ctx.suspended_step_id is None

        approval_step = next(
            r for r in ctx.step_results if r["step_id"] == "approve_sensitive_asset"
        )
        assert approval_step["result"]["auto_approved"] is True

        assert await count_resource_nodes(
            neo4j_client, "http://agent-os.local/data/assignment/a3-assign-001"
        ) == 1


class TestA4_InvalidEmployeeDataFailsBeforeApproval:
    """A4: 员工信息不合规(缺 employeeName)→ 在校验阶段真实失败，
    从未触达审批或写入阶段。"""

    async def test_invalid_employee_data_fails_at_validation_step(
        self, sop_engine, sop_definition, neo4j_client, sample_invalid_employee_ttl
    ):
        data = {
            "employee_ttl": sample_invalid_employee_ttl,
            "asset_ttl": hardware_asset_ttl(
                "a4-asset-001", "SN-A4-001", "ThinkPad X1", "LOW"
            ),
            "assignment_ttl": assignment_ttl("a4-assign-001"),
            "employee_name": "未命名员工",
            "employee_id": "EMP-A4-BAD",
            "asset_model": "ThinkPad X1",
            "asset_id": "a4-asset-001",
            "sensitivity_level": "LOW",
        }

        ctx = sop_engine.create_run(sop_definition, data)
        ctx = await sop_engine.run(sop_definition, ctx)

        assert ctx.state == SOPRunState.FAILED
        assert len(ctx.errors) >= 1
        # 只跑到第一个步骤(validate_employee)就失败，后续步骤从未被记录为已执行
        executed_step_ids = [r["step_id"] for r in ctx.step_results]
        assert "execute_assignment" not in executed_step_ids
        assert "validate_asset" not in executed_step_ids

        assert await count_resource_nodes(
            neo4j_client, "http://agent-os.local/data/assignment/a4-assign-001"
        ) == 0
