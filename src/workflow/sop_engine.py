"""SOP YAML 流程引擎 — 声明式工作流执行器。

架构说明：
    SOPEngine 接收一个 SOPDefinition（由 YAML 解析而来），并基于 SOPRunContext 逐步执行。
    关键设计：
    1. 步骤幂等：通过 run_id + step_id 保证重放安全。
    2. Human-In-The-Loop (HITL)：遇到 human_approval 步骤时，引擎调用
       `approval_callback`（外部注入），挂起当前执行流，释放控制权给 IM 渠道。
    3. 恢复执行：当 IM 渠道回调到达时，调用 `resume(run_context, decision, reason)`
       继续剩余步骤。
    4. 可观测性：每个步骤结果写入 context.step_results，并可通过外部注入的
       telemetry_fn 发送 OpenTelemetry Span。

用法：
    engine = SOPEngine(
        schema_provider=schema_provider,
        write_gate=write_gate,
        feedback_db=feedback_db,
        feishu_card_sender=feishu_adapter.send_approval_card,  # 可选
    )
    sop = SOPEngine.load_sop("src/workflow/sop_examples/it-onboarding.sop.yaml")
    ctx = engine.create_run(sop, data={"employee": ..., "asset": ...})
    await engine.run(ctx)
    # 若 ctx.state == SOPRunState.SUSPENDED → 等待 Feishu 回调
    # 回调到达后：
    await engine.resume(ctx, decision="REJECTED", reason="...", approver_id="ou_xxx")
"""

from __future__ import annotations

import json
import logging
import uuid
from pathlib import Path
from typing import Any, Awaitable, Callable, Optional

import yaml
from pydantic import ValidationError

from workflow.sop_schema import (
    SOPDefinition,
    SOPRunContext,
    SOPRunState,
    SOPStep,
    StepType,
    ActionType,
)

logger = logging.getLogger(__name__)

# 审批卡片回调的函数签名类型
ApprovalCardSender = Callable[
    [str, str, str, str, dict[str, Any]],  # (chat_id, title, message, run_id, extra)
    Awaitable[None],
]


class SOPExecutionError(Exception):
    """SOP 步骤执行过程中的业务错误。"""


class SOPEngine:
    """声明式 SOP 流程引擎。

    职责：
    - 加载并验证 SOP YAML 文件。
    - 驱动 SOPRunContext 的状态流转。
    - 在 HITL 步骤处挂起，并触发 IM 卡片发送。
    - 恢复执行后决定继续或终止。
    - 将审批结果持久化到 FeedbackDB。
    """

    def __init__(
        self,
        *,
        schema_provider=None,  # governance.schema_provider.SchemaProvider
        write_gate=None,        # governance.write_gate.WriteGate
        feedback_db=None,       # database.feedback_db.FeedbackDB
        state_store=None,       # database.state_store.WorkflowStateStore
        approval_card_sender: Optional[ApprovalCardSender] = None,
        default_chat_id: str = "",
    ) -> None:
        self._schema_provider = schema_provider
        self._write_gate = write_gate
        self._feedback_db = feedback_db
        self._state_store = state_store
        self._approval_card_sender = approval_card_sender
        self._default_chat_id = default_chat_id

    # ── 静态工厂：加载 SOP YAML ──

    @staticmethod
    def load_sop(yaml_path: str | Path) -> SOPDefinition:
        """从 YAML 文件加载 SOP 定义并用 Pydantic 校验。

        Raises:
            FileNotFoundError: 文件不存在时。
            ValidationError: YAML 内容不符合 schema 时。
        """
        path = Path(yaml_path)
        if not path.exists():
            raise FileNotFoundError(f"SOP 文件不存在: {path}")
        raw = yaml.safe_load(path.read_text(encoding="utf-8"))
        try:
            return SOPDefinition.model_validate(raw)
        except ValidationError as exc:
            raise ValueError(f"SOP YAML schema 校验失败 ({path}): {exc}") from exc

    # ── 创建运行实例 ──

    def create_run(
        self,
        sop: SOPDefinition,
        data: Optional[dict[str, Any]] = None,
        run_id: Optional[str] = None,
    ) -> SOPRunContext:
        """为给定的 SOP 创建一个新的运行上下文（trace）。"""
        ctx = SOPRunContext(
            run_id=run_id or str(uuid.uuid4()),
            sop_id=sop.sop_id,
            state=SOPRunState.PENDING,
            data=data or {},
        )
        logger.info("[SOP:%s] 创建运行实例 run_id=%s", sop.sop_id, ctx.run_id)
        if self._state_store:
            self._state_store.save_state(ctx)
        return ctx

    def load_run(self, run_id: str) -> Optional[SOPRunContext]:
        """从状态存储中加载执行上下文。"""
        if not self._state_store:
            raise SOPExecutionError("未配置 state_store，无法加载状态。")
        return self._state_store.load_state(run_id)

    # ── 主执行入口 ──

    async def run(self, sop: SOPDefinition, ctx: SOPRunContext) -> SOPRunContext:
        """从当前步骤开始执行，直到完成、挂起或失败。

        Returns:
            更新后的 ctx（状态可能为 SUSPENDED、COMPLETED、FAILED）。
        """
        ctx.state = SOPRunState.RUNNING
        steps = sop.steps

        for idx in range(ctx.current_step_index, len(steps)):
            step = steps[idx]
            ctx.current_step_index = idx
            logger.info(
                "[SOP:%s][%s/%s] 执行步骤 %s (%s)",
                sop.sop_id, idx + 1, len(steps), step.id, step.type,
            )

            try:
                result = await self._execute_step(step, ctx)
                ctx.step_results.append({
                    "step_id": step.id,
                    "type": step.type,
                    "status": "ok",
                    "result": result,
                })
            except SOPExecutionError as exc:
                ctx.errors.append(str(exc))
                ctx.state = SOPRunState.FAILED
                logger.error("[SOP:%s] 步骤 %s 失败: %s", sop.sop_id, step.id, exc)
                if self._state_store:
                    self._state_store.save_state(ctx)
                return ctx

            # HITL 步骤挂起：引擎在此退出，等待外部 resume() 调用
            if ctx.state == SOPRunState.SUSPENDED:
                logger.info(
                    "[SOP:%s] 流程已挂起，等待审批 (step=%s, run_id=%s)",
                    sop.sop_id, step.id, ctx.run_id,
                )
                if self._state_store:
                    self._state_store.save_state(ctx)
                return ctx
            
            # 每完成一个步骤保存一次状态（可选，但安全）
            if self._state_store:
                self._state_store.save_state(ctx)

        # 全部步骤完成
        ctx.state = SOPRunState.COMPLETED
        logger.info("[SOP:%s] 流程已完成 (run_id=%s)", sop.sop_id, ctx.run_id)
        if self._state_store:
            self._state_store.save_state(ctx)
        return ctx

    # ── 恢复执行（Human 回调后调用）──

    async def resume(
        self,
        sop: SOPDefinition,
        ctx: SOPRunContext,
        decision: str,
        reason: Optional[str] = None,
        approver_id: str = "unknown",
    ) -> SOPRunContext:
        """处理审批回调，恢复 SOP 流程执行。

        Args:
            sop: 原始 SOPDefinition（用于继续步骤）。
            ctx: 当前已挂起的运行上下文。
            decision: 'APPROVED' | 'REJECTED'
            reason: 审批理由文本。
            approver_id: 审批人 ID。

        Returns:
            更新后的 ctx。
        """
        if ctx.state != SOPRunState.SUSPENDED:
            raise SOPExecutionError(
                f"resume() 只能在 SUSPENDED 状态下调用，当前状态: {ctx.state}"
            )

        ctx.approval_result = decision
        ctx.approval_reason = reason
        ctx.approver_id = approver_id

        # 持久化审批结果到 SQLite
        if self._feedback_db is not None:
            # NOTE: 获取当前步骤的 original_agent_output（step_results 最后一条）
            original_output = ""
            if ctx.step_results:
                last = ctx.step_results[-1]
                original_output = json.dumps(last.get("result", {}), ensure_ascii=False)

            self._feedback_db.insert_feedback(
                trace_id=ctx.run_id,
                reviewer=approver_id,
                decision=decision,
                reason=reason,
                original_agent_output=original_output,
            )
            logger.info(
                "[SOP:%s] 审批结果已写入 DB (run_id=%s, decision=%s)",
                sop.sop_id, ctx.run_id, decision,
            )

        if decision == "REJECTED":
            ctx.state = SOPRunState.REJECTED
            logger.warning(
                "[SOP:%s] 审批被驳回 (reviewer=%s, reason=%s)",
                sop.sop_id, approver_id, reason,
            )
            if self._state_store:
                self._state_store.save_state(ctx)
            return ctx

        # 批准 → 从下一步继续执行
        ctx.state = SOPRunState.APPROVED
        ctx.current_step_index += 1
        return await self.run(sop, ctx)

    # ── 步骤分发器 ──

    async def _execute_step(
        self, step: SOPStep, ctx: SOPRunContext
    ) -> dict[str, Any]:
        """根据步骤类型分发到对应处理器。"""
        if step.type == StepType.VALIDATE:
            return self._step_validate(step, ctx)
        elif step.type == StepType.HUMAN_APPROVAL:
            return await self._step_human_approval(step, ctx)
        elif step.type == StepType.ACTION:
            return await self._step_action(step, ctx)
        elif step.type == StepType.NOTIFY:
            return await self._step_notify(step, ctx)
        else:
            raise SOPExecutionError(f"未知步骤类型: {step.type}")

    # ── 步骤处理器：SHACL 校验 ──

    def _step_validate(self, step: SOPStep, ctx: SOPRunContext) -> dict[str, Any]:
        """执行 SHACL 数据校验步骤。"""
        if self._write_gate is None or step.domain is None:
            logger.warning("[step:%s] WriteGate 或 domain 未配置，跳过校验", step.id)
            return {"skipped": True, "reason": "write_gate or domain not configured"}

        data_key = step.data_ref or ""
        ttl_data = ctx.data.get(data_key, "")
        if not ttl_data:
            raise SOPExecutionError(
                f"步骤 {step.id} 需要 data['{data_key}']，但上下文中不存在"
            )

        report, nonce = self._write_gate.verify_shacl_compliance(step.domain, ttl_data)

        if not report.is_valid:
            violations = [v.get("resultMessage", "") for v in report.results]
            raise SOPExecutionError(
                f"SHACL 校验失败 (step={step.id}, domain={step.domain}): "
                + "; ".join(violations)
            )

        # 将 nonce 保存到上下文，供后续 governed_write 步骤使用
        ctx.data[f"_nonce_{data_key}"] = nonce
        logger.info("[step:%s] SHACL 校验通过，nonce 已存入上下文", step.id)
        return {"valid": True, "domain": step.domain, "data_ref": data_key}

    # ── 步骤处理器：Human-In-The-Loop 审批 ──

    async def _step_human_approval(
        self, step: SOPStep, ctx: SOPRunContext
    ) -> dict[str, Any]:
        """触发 IM 交互卡片并挂起流程。

        条件表达式（step.condition）：
            若表达式 eval 为 False → 自动通过，不发送卡片。
            若为 True 或无条件 → 发送卡片并挂起。

        安全：eval 在受限命名空间中执行，只能访问 ctx.data 中的值。
        """
        if step.condition:
            try:
                from simpleeval import EvalWithCompoundTypes
                # 仅允许访问 ctx.data 中的变量（基础类型）
                allowed_ns = {k: v for k, v in ctx.data.items() if isinstance(k, (str, int, float, bool))}
                # NOTE: 必须用 EvalWithCompoundTypes，而不是 simpleeval.simple_eval()。
                # simple_eval() 内部用的 SimpleEval 出于安全考虑禁用了列表/元组等
                # 复合类型字面量，SOP YAML 里常见的 `x in ['A', 'B']` 写法用
                # simple_eval() 求值必定抛异常，被下面的 except 吞掉并默认
                # should_trigger=True —— 等价于这条条件判断永远不生效。
                evaluator = EvalWithCompoundTypes(names=allowed_ns)
                should_trigger = bool(evaluator.eval(step.condition))
            except Exception as exc:
                logger.warning(
                    "[step:%s] 条件表达式求值失败，默认触发审批: %s", step.id, exc
                )
                should_trigger = True
        else:
            should_trigger = True

        if not should_trigger:
            logger.info("[step:%s] 条件不满足，自动通过审批", step.id)
            return {"auto_approved": True, "condition": step.condition}

        # 构建卡片消息（支持 {key} 插值）
        card_msg = (step.card_message or "请审批此操作").format_map(ctx.data)
        card_title = step.card_title or "🤖 Agent OS — 需要您的审批"

        # 生成 Feishu 交互卡片 JSON payload
        card_payload = build_approval_card(
            title=card_title,
            message=card_msg,
            run_id=ctx.run_id,
            step_id=step.id,
        )
        ctx.data["_pending_card"] = card_payload

        logger.info(
            "[step:%s] 触发审批卡片 (run_id=%s, title=%s)",
            step.id, ctx.run_id, card_title,
        )

        # 若配置了真实发卡函数（Feishu adapter），调用发送
        if self._approval_card_sender is not None:
            chat_id = step.extra.get("chat_id") or self._default_chat_id
            await self._approval_card_sender(
                chat_id, card_title, card_msg, ctx.run_id, card_payload
            )

        # 将卡片信息打印到控制台（CLI 模式下便于调试）
        _print_card_to_console(card_title, card_msg, ctx.run_id)

        # 挂起流程
        ctx.state = SOPRunState.SUSPENDED
        ctx.suspended_step_id = step.id
        return {
            "suspended": True,
            "step_id": step.id,
            "run_id": ctx.run_id,
            "card_title": card_title,
        }

    # ── 步骤处理器：执行动作 ──

    async def _step_action(self, step: SOPStep, ctx: SOPRunContext) -> dict[str, Any]:
        """执行 governed_write 或其他动作。"""
        if step.action_type == ActionType.GOVERNED_WRITE:
            return await self._action_governed_write(step, ctx)
        else:
            logger.warning("[step:%s] 未知 action_type: %s，跳过", step.id, step.action_type)
            return {"skipped": True}

    async def _action_governed_write(self, step: SOPStep, ctx: SOPRunContext) -> dict[str, Any]:
        """通过 WriteGate 执行受治理的 RDF 写入。"""
        if self._write_gate is None:
            logger.warning("[step:%s] WriteGate 未配置，模拟写入", step.id)
            return {"simulated": True}

        data_key = step.data_ref or ""
        ttl_data = ctx.data.get(data_key, "")
        nonce = ctx.data.get(f"_nonce_{data_key}", "")

        if not ttl_data or not nonce:
            raise SOPExecutionError(
                f"governed_write 步骤 {step.id} 缺少数据或 nonce (data_key='{data_key}')"
            )

        # execute_governed_write 可能抛出 WriteGateError/SHACLValidationError，
        # 也可能因下游 Neo4j 不可达而抛出连接层异常 —— 统一转换为
        # SOPExecutionError，交给 SOPEngine.run() 的既有错误处理契约
        # (捕获 SOPExecutionError → ctx.state = FAILED)，而不是让异常
        # 未经转换就冒出 run()，导致调用方拿到一个裸异常而不是诚实的 FAILED 状态。
        try:
            result = await self._write_gate.execute_governed_write(
                step.domain or "", ttl_data, validation_nonce=nonce
            )
        except Exception as exc:
            raise SOPExecutionError(
                f"governed_write 步骤 {step.id} 执行失败: {exc}"
            ) from exc

        logger.info("[step:%s] governed_write 执行成功: %s", step.id, result)
        return {"written": True, "result": str(result)}

    # ── 步骤处理器：通知 ──

    async def _step_notify(self, step: SOPStep, ctx: SOPRunContext) -> dict[str, Any]:
        """发送 IM 通知（无需等待回复）。"""
        msg = (step.notify_message or step.description or "").format_map(ctx.data)
        logger.info("[step:%s] 发送通知: %s", step.id, msg)
        # 若有发卡函数，可复用；此处仅打印
        print(f"\n📢 [SOP 通知] {msg}\n")
        return {"notified": True, "message": msg}


# ── Feishu Interactive Card Builder ──

def build_approval_card(
    title: str,
    message: str,
    run_id: str,
    step_id: str,
) -> dict[str, Any]:
    """构建 Feishu Interactive Card JSON。

    格式遵循 Feishu Card 2.0 规范（card_link + action_block）。
    当用户点击 "批准" 或 "驳回" 时，Feishu 会向回调地址发送 action 事件，
    事件体中包含 value.run_id 以定位正在等待的 SOP 实例。

    参考: https://open.feishu.cn/document/ukTMukTMukTM/uEjNwUjLxYDM
    """
    return {
        "config": {"wide_screen_mode": True},
        "header": {
            "title": {"tag": "plain_text", "content": title},
            "template": "orange",
        },
        "elements": [
            {
                "tag": "div",
                "text": {
                    "tag": "lark_md",
                    "content": message,
                },
            },
            {
                "tag": "hr",
            },
            {
                "tag": "div",
                "text": {
                    "tag": "lark_md",
                    "content": f"**Run ID**: `{run_id}`\n**Step**: `{step_id}`",
                },
            },
            {
                "tag": "action",
                "actions": [
                    {
                        "tag": "button",
                        "text": {"tag": "plain_text", "content": "✅ 批准"},
                        "type": "primary",
                        "value": {
                            "action": "APPROVED",
                            "run_id": run_id,
                            "step_id": step_id,
                        },
                    },
                    {
                        "tag": "button",
                        "text": {"tag": "plain_text", "content": "❌ 驳回"},
                        "type": "danger",
                        "value": {
                            "action": "REJECTED",
                            "run_id": run_id,
                            "step_id": step_id,
                        },
                    },
                ],
            },
            {
                "tag": "note",
                "elements": [
                    {
                        "tag": "plain_text",
                        "content": "⚠️ 此卡片由 Agent OS 自动生成，请仔细核对后再做决定。",
                    }
                ],
            },
        ],
    }


def _print_card_to_console(title: str, message: str, run_id: str) -> None:
    """CLI 模式下将卡片内容可视化打印到终端（供本地调试和 UAT 使用）。"""
    print("\n" + "=" * 65)
    print(f"  🃏  Feishu Interactive Card 审批请求")
    print("=" * 65)
    print(f"  标题:   {title}")
    print(f"  内容:   {message}")
    print(f"  Run ID: {run_id}")
    print("-" * 65)
    print("  [按钮 1] ✅ 批准   |   [按钮 2] ❌ 驳回")
    print("=" * 65 + "\n")
