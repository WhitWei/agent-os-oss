#!/usr/bin/env python3
"""Sprint 3 End-to-End UAT Test Script (WO-A3.4).

Verifies declarative SOP workflow engine, state store persistence, 
FeedbackDB logger, and interactive approval loop with write governance.
"""

import sys
import os
import json
import asyncio
import logging
from pathlib import Path

# Add 'src' to import path
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from zeroclaw.config import ConfigLoader
from governance.schema_provider import SchemaProvider
from governance.write_gate import WriteGate
from governance.neo4j_client import Neo4jClient
from database.feedback_db import FeedbackDB
from database.state_store import WorkflowStateStore
from workflow.sop_engine import SOPEngine
from workflow.sop_schema import SOPRunState

# Set up clean logs to standard output
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s"
)
logger = logging.getLogger("run_uat")


def cleanup_test_dbs(db_names: list[str]):
    """Clean up specified databases and their WAL/SHM sidecars."""
    for db in db_names:
        for suffix in ["", "-wal", "-shm"]:
            path = Path(db + suffix)
            if path.exists():
                try:
                    path.unlink()
                except Exception as exc:
                    logger.warning("Failed to delete temp file %s: %s", path, exc)


async def main():
    logger.info("======================================================================")
    logger.info("  Agent OS MVP — Sprint 3 UAT End-to-End Test (WO-A3.4)")
    logger.info("======================================================================")

    # ── 数据库清理（保持测试独立性） ──
    temp_dbs = ["test_agent_state.db", "test_agentos_feedback.db"]
    cleanup_test_dbs(temp_dbs)

    try:
        # ====================================================================
        # 1. 环境初始化
        # ====================================================================
        logger.info("--- Step 1: Initialize environment components ---")
        
        # 加载配置
        config = ConfigLoader("config.yaml").load()
        logger.info("✅ Configuration loaded successfully")

        # 初始化 SchemaProvider
        sp = SchemaProvider(
            owl_dir=config.ontology.owl_dir,
            shacl_dir=config.ontology.shacl_dir,
            domains=config.ontology.domains,
        )
        logger.info("✅ SchemaProvider loaded domains: %s", [d.name for d in config.ontology.domains])

        # 初始化真实的 Neo4j 客户端
        neo4j_client = Neo4jClient(config.neo4j)
        logger.info("✅ Neo4jClient connected to %s", config.neo4j.uri)

        # 初始化 WriteGate（真实写模式）
        gate = WriteGate(
            schema_provider=sp,
            neo4j_client=neo4j_client,
            nonce_secret=config.mcp.validation.nonce_secret,
            nonce_ttl_seconds=config.mcp.validation.nonce_ttl_seconds,
        )
        logger.info("✅ WriteGate initialized in real write mode with Neo4j backend")

        # 初始化 FeedbackDB & State Store
        feedback_db = FeedbackDB("test_agentos_feedback.db")
        state_store = WorkflowStateStore("test_agent_state.db")
        logger.info("✅ FeedbackDB & WorkflowStateStore connected")

        # 初始化 SOP Engine并注入依赖
        engine = SOPEngine(
            schema_provider=sp,
            write_gate=gate,
            feedback_db=feedback_db,
            state_store=state_store,
        )
        logger.info("✅ SOPEngine initialized with injected components")

        # 加载 onboarding SOP 定义
        sop_path = "src/workflow/sop_examples/it-onboarding.sop.yaml"
        sop = SOPEngine.load_sop(sop_path)
        logger.info("✅ SOP definition loaded from %s (ID: %s)", sop_path, sop.sop_id)

        # ====================================================================
        # 2. 测试场景：触发 SOP 并挂起
        # ====================================================================
        logger.info("\n--- Step 2: Trigger SOP and Suspend (Human-In-The-Loop) ---")

        # 构造合规的黄金业务数据（含合规的 Employee & HardwareAsset Turtle）
        employee_ttl = """
@prefix asset: <http://agent-os.local/ontology/it-asset-mgmt#> .
@prefix rdf: <http://www.w3.org/1999/02/22-rdf-syntax-ns#> .

<http://agent-os.local/data/employee/emp-uat-001>
    rdf:type asset:Employee ;
    asset:employeeId "EMP-UAT-001" ;
    asset:employeeName "李经理" .
"""

        asset_ttl = """
@prefix asset: <http://agent-os.local/ontology/it-asset-mgmt#> .
@prefix rdf: <http://www.w3.org/1999/02/22-rdf-syntax-ns#> .

<http://agent-os.local/data/asset/mbp-uat-001>
    rdf:type asset:HardwareAsset ;
    asset:serialNumber "MBP2024-UAT-001" ;
    asset:assetModel "MacBook Pro 14 M4" ;
    asset:sensitivityLevel "HIGH" .
"""

        assignment_ttl = """
@prefix asset: <http://agent-os.local/ontology/it-asset-mgmt#> .
@prefix rdf: <http://www.w3.org/1999/02/22-rdf-syntax-ns#> .
@prefix xsd: <http://www.w3.org/2001/XMLSchema#> .

<http://agent-os.local/data/assignment/assign-uat-001>
    rdf:type asset:AssetAssignment ;
    asset:assignedTo <http://agent-os.local/data/employee/emp-uat-001> ;
    asset:assignedAsset <http://agent-os.local/data/asset/mbp-uat-001> ;
    asset:assignedDate "2026-07-02" .
"""

        # 由于 SOP YAML 中 execute_assignment 步骤没有对应的 validate 步骤（没有 validate_assignment）
        # 故我们通过 WriteGate 手动预校验来生成合规 Nonce，满足 execute_assignment 步骤受治理写入的签名安全核验。
        report_assign, nonce_assign = gate.verify_shacl_compliance("it-asset-mgmt", assignment_ttl)
        assert report_assign.is_valid, "assignment_ttl 预校验失败"

        data = {
            "employee_ttl": employee_ttl,
            "asset_ttl": asset_ttl,
            "assignment_ttl": assignment_ttl,
            "employee_name": "李经理",
            "employee_id": "EMP-UAT-001",
            "asset_model": "MacBook Pro 14 M4",
            "asset_id": "mbp-uat-001",
            "sensitivity_level": "HIGH",
            "_nonce_assignment_ttl": nonce_assign,  # 预注入 Nonce
        }

        # 开启流程运行实例
        ctx = engine.create_run(sop, data)
        assert ctx.state == SOPRunState.PENDING, "初始状态必须为 PENDING"
        logger.info("✅ Create run context success (run_id: %s)", ctx.run_id)

        # 启动运行
        ctx = await engine.run(sop, ctx)

        # 断言 1: 流程进入 SUSPENDED 挂起状态
        assert ctx.state == SOPRunState.SUSPENDED, f"期望状态为 SUSPENDED，得到 {ctx.state}"
        logger.info("✅ Assertion Passed: ctx.state is SUSPENDED")

        # 断言 2: 挂起的步骤是审批步骤 (SOP 中定义为 approve_sensitive_asset)
        assert ctx.suspended_step_id == "approve_sensitive_asset", f"期望挂起步骤为 approve_sensitive_asset，得到 {ctx.suspended_step_id}"
        logger.info("✅ Assertion Passed: ctx.suspended_step_id is 'approve_sensitive_asset'")

        # 断言 3: 从数据库中加载该 RunContext 并验证反序列化正常且状态为 SUSPENDED
        loaded_ctx = state_store.load_state(ctx.run_id)
        assert loaded_ctx is not None, "无法从 state_store 中加载上下文"
        assert loaded_ctx.state == SOPRunState.SUSPENDED, f"从数据库反序列化得到的上下文状态非 SUSPENDED: {loaded_ctx.state}"
        logger.info("✅ Assertion Passed: Loaded state from db matches SUSPENDED state")

        # ====================================================================
        # 3. 测试场景：模拟经理驳回 (REJECTED)
        # ====================================================================
        logger.info("\n--- Step 3: Simulate Manager Rejection (REJECTED Branch) ---")

        # 恢复挂起的上下文并模拟审批驳回
        ctx = await engine.resume(
            sop, ctx, decision="REJECTED", reason="设备型号不符", approver_id="ou_manager123"
        )

        # 断言 1: 流程进入 REJECTED 状态并终止
        assert ctx.state == SOPRunState.REJECTED, f"驳回后期望状态为 REJECTED，得到 {ctx.state}"
        logger.info("✅ Assertion Passed: ctx.state is REJECTED")

        # 断言 2: 审批驳回记录正确落入 FeedbackDB
        record = feedback_db.get_by_trace_id(ctx.run_id)
        assert record is not None, f"未能在 FeedbackDB 中查询到 trace_id={ctx.run_id} 的审批反馈记录"
        assert record.decision == "REJECTED", f"FeedbackDB 记录中的审批决策期望为 REJECTED，得到 {record.decision}"
        assert record.reviewer == "ou_manager123", f"期望审批人为 ou_manager123，得到 {record.reviewer}"
        assert record.reason == "设备型号不符", f"期望驳回原因为 设备型号不符，得到 {record.reason}"
        logger.info("✅ Assertion Passed: Correct rejection record persisted in FeedbackDB")

        # ====================================================================
        # 4. 测试场景：新流程发起并模拟经理批准 (APPROVED)
        # ====================================================================
        logger.info("\n--- Step 4: Re-trigger SOP and Simulate Manager Approval (APPROVED Branch) ---")

        # 重新提交申请：建立全新流程实例
        ctx2 = engine.create_run(sop, data)
        ctx2 = await engine.run(sop, ctx2)
        assert ctx2.state == SOPRunState.SUSPENDED, f"重新启动期望挂起，得到 {ctx2.state}"
        logger.info("✅ Reset and restarted new workflow run success (run_id: %s)", ctx2.run_id)

        # 恢复挂起的上下文并模拟批准同意
        ctx2 = await engine.resume(
            sop, ctx2, decision="APPROVED", reason="同意分配", approver_id="ou_manager123"
        )

        # 断言 1: 流程进入 COMPLETED 状态（即 APPROVED 后后续步骤如 governed_write, notify 全部成功运行完）
        assert ctx2.state == SOPRunState.COMPLETED, f"期望完成状态为 COMPLETED，得到 {ctx2.state}"
        logger.info("✅ Assertion Passed: ctx2.state is COMPLETED")

        # 断言 2: 确认包含 governed_write (action 步骤) 运行通过记录
        found_write_action = False
        for result_item in ctx2.step_results:
            if result_item["step_id"] == "execute_assignment":
                found_write_action = True
                assert result_item["status"] == "ok", f"execute_assignment 步骤状态应为 ok，实际得到: {result_item['status']}"
                # 确认执行了受治理的写入，且返回了成功结果
                action_result = result_item["result"]
                assert action_result.get("written") is True, f"应当已成功执行写入，得到: {action_result}"
                # Neo4j real backend returns 'queued' or 'success'
                res_str = action_result.get("result", "")
                assert "success" in res_str or "queued" in res_str, f"写入返回的结果中应当包含 success 或 queued，得到: {action_result}"
                
                # 提取 transaction ID 作为真实写入证据
                import ast
                try:
                    res_dict = ast.literal_eval(res_str)
                    tx_id = res_dict.get("transaction_id")
                    logger.info("✅ Governed Write executed with Neo4j Transaction ID: %s", tx_id)
                except Exception:
                    pass
                
        assert found_write_action, "未在 step_results 日志中查找到 'execute_assignment' 步骤结果"
        logger.info("✅ Assertion Passed: 'execute_assignment' governed write executed successfully")

        # 断言 3: 审批通过记录正确落入 FeedbackDB
        record2 = feedback_db.get_by_trace_id(ctx2.run_id)
        assert record2 is not None, f"未能在 FeedbackDB 中查询到 trace_id={ctx2.run_id} 的审批反馈记录"
        assert record2.decision == "APPROVED", f"FeedbackDB 记录中的审批决策期望为 APPROVED，得到 {record2.decision}"
        assert record2.reviewer == "ou_manager123", f"期望审批人为 ou_manager123，得到 {record2.reviewer}"
        assert record2.reason == "同意分配", f"期望同意理由为 同意分配，得到 {record2.reason}"
        logger.info("✅ Assertion Passed: Correct approval record persisted in FeedbackDB")

        # ── 流程圆满完成 ──
        logger.info("\n======================================================================")
        logger.info("🎉 恭喜！Sprint 3 所有端到端 UAT 联调测试用例全部断言通过！(100% SUCCESS)")
        logger.info("======================================================================")

    except AssertionError as e:
        logger.error("\n❌ UAT 断言失败: %s", e)
        sys.exit(1)
    except Exception as e:
        logger.error("\n❌ UAT 运行过程中抛出未捕获异常", exc_info=e)
        sys.exit(1)
    finally:
        # 清理测试环境临时生成文件，保持工作区干净
        if "feedback_db" in locals():
            try:
                feedback_db.close()
            except Exception:
                pass
        if "neo4j_client" in locals():
            try:
                # asyncio.run handles the outer loop, but we are inside an async function here
                await neo4j_client.close()
            except Exception:
                pass
        cleanup_test_dbs(temp_dbs)
        logger.info("🧹 Test databases cleaned up.")


if __name__ == "__main__":
    asyncio.run(main())
