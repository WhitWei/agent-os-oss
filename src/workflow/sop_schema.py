"""SOP YAML 文件的 Pydantic Schema 定义。

每个 SOP 文件描述一套标准操作流程（Standard Operating Procedure）。
引擎在运行时解析这些步骤，依序执行，并在 human_approval 步骤处挂起。

YAML 结构示例：
    sop_id: it-onboarding-v1
    name: "新员工 IT 设备入职分配"
    version: "1.0"
    steps:
      - id: check_employee
        type: validate
        description: "验证员工信息 SHACL 合规"
        domain: it-asset-mgmt
        data_ref: employee

      - id: provision_asset
        type: validate
        description: "验证分配资产 SHACL 合规"
        domain: it-asset-mgmt
        data_ref: asset

      - id: approve_sensitive
        type: human_approval
        description: "敏感资产分配需人工审批"
        condition: "asset.sensitivityLevel in ['HIGH', 'CRITICAL']"
        card_title: "🔐 敏感设备分配审批"
        card_message: "Agent 准备将 {asset_id} 分配给 {employee_id}，请审批。"
        timeout_seconds: 3600

      - id: execute_assignment
        type: action
        description: "执行资产分配并写入 Neo4j"
        action_type: governed_write
        domain: it-asset-mgmt
        data_ref: assignment
"""

from __future__ import annotations

from enum import Enum
from typing import Any, Optional

from pydantic import BaseModel, Field


class StepType(str, Enum):
    """SOP 步骤类型枚举。"""
    VALIDATE = "validate"              # SHACL 数据校验
    HUMAN_APPROVAL = "human_approval"  # 人机交互审批（触发 IM 卡片）
    ACTION = "action"                  # 执行动作（治理写入、通知等）
    NOTIFY = "notify"                  # 发送通知（无需等待回复）


class ActionType(str, Enum):
    """Action 步骤的具体动作类型。"""
    GOVERNED_WRITE = "governed_write"  # 通过 WriteGate 写入 Neo4j
    NOTIFY_IM = "notify_im"            # 发送 IM 通知（不含审批按钮）


class SOPStep(BaseModel):
    """单个 SOP 执行步骤。"""
    id: str = Field(..., description="步骤唯一标识符，用于 trace 和挂起/恢复")
    type: StepType
    description: str = Field(default="", description="步骤描述（日志/UI 展示用）")

    # validate 步骤字段
    domain: Optional[str] = Field(default=None, description="SHACL 校验使用的本体 domain 名称")
    data_ref: Optional[str] = Field(default=None, description="上下文中的数据 key（如 'employee'、'asset'）")

    # human_approval 步骤字段
    condition: Optional[str] = Field(
        default=None,
        description="条件表达式（Python eval），满足时才触发审批，否则自动通过"
    )
    card_title: Optional[str] = Field(default=None, description="Feishu 交互卡片标题")
    card_message: Optional[str] = Field(default=None, description="卡片消息模板（支持 {key} 插值）")
    timeout_seconds: int = Field(default=3600, description="等待审批超时秒数")
    approver_id: Optional[str] = Field(default=None, description="指定审批人 Feishu open_id（None = 通知所有管理员）")

    # action 步骤字段
    action_type: Optional[ActionType] = Field(default=None)

    # notify 步骤字段
    notify_message: Optional[str] = Field(default=None, description="通知文本模板")

    # 通用：任意扩展字段
    extra: dict[str, Any] = Field(default_factory=dict)


class SOPDefinition(BaseModel):
    """完整的 SOP 流程定义，从 YAML 文件加载。"""
    sop_id: str = Field(..., description="流程唯一 ID（e.g. 'it-onboarding-v1'）")
    name: str = Field(..., description="流程名称（中文可读）")
    version: str = Field(default="1.0")
    description: str = Field(default="")
    steps: list[SOPStep] = Field(default_factory=list, description="有序步骤列表")
    metadata: dict[str, Any] = Field(default_factory=dict, description="自定义元数据")


class SOPRunState(str, Enum):
    """SOP 执行实例的生命周期状态。"""
    PENDING = "PENDING"         # 尚未开始
    RUNNING = "RUNNING"         # 正在执行步骤
    SUSPENDED = "SUSPENDED"     # 挂起等待人工审批
    APPROVED = "APPROVED"       # 已获批准，继续执行
    REJECTED = "REJECTED"       # 已被驳回，流程终止
    COMPLETED = "COMPLETED"     # 全部步骤成功完成
    FAILED = "FAILED"           # 步骤执行失败


class SOPRunContext(BaseModel):
    """SOP 运行时上下文，在步骤间传递数据。"""
    run_id: str = Field(..., description="本次运行唯一 ID（trace_id）")
    sop_id: str
    state: SOPRunState = SOPRunState.PENDING
    current_step_index: int = 0
    data: dict[str, Any] = Field(default_factory=dict, description="步骤间共享数据字典")
    suspended_step_id: Optional[str] = None
    approval_result: Optional[str] = None   # 'APPROVED' | 'REJECTED'
    approval_reason: Optional[str] = None
    approver_id: Optional[str] = None
    errors: list[str] = Field(default_factory=list)
    step_results: list[dict[str, Any]] = Field(default_factory=list, description="各步骤执行结果日志")
