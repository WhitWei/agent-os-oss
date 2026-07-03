"""Workflow package — 声明式 SOP 流程引擎。

提供以下功能：
- ``SOPEngine``       — 主流程执行引擎（加载、运行、恢复）
- ``SOPDefinition``   — SOP YAML 的 Pydantic schema
- ``SOPRunContext``    — SOP 运行时状态上下文
- ``SOPRunState``      — 状态枚举
- ``build_approval_card`` — Feishu Interactive Card JSON 构建器
"""

from workflow.sop_engine import SOPEngine, SOPExecutionError, build_approval_card
from workflow.sop_schema import (
    SOPDefinition,
    SOPRunContext,
    SOPRunState,
    SOPStep,
    StepType,
    ActionType,
)

__all__ = [
    "SOPEngine",
    "SOPExecutionError",
    "build_approval_card",
    "SOPDefinition",
    "SOPRunContext",
    "SOPRunState",
    "SOPStep",
    "StepType",
    "ActionType",
]
