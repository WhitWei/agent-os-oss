"""L2 集成/接线测试包 — Rule 10 (三层测试防御体系)。

本包下的测试一律遵循 Rule 10.2 的行为准则：
- 主体必须是系统的主运行入口（AgentOSKernel.wake_up() / WriteGate.execute_governed_write()），
  不允许通过孤立脚本直接拼调用组件充当"接线证据"。
- 禁止 Mock 内部安全/治理组件（防火墙、熔断器、计费熔断、SHACL 校验、Neo4j 写入）。
  只允许在最外层（真实数据库容器、真实 IM API）处打桩或降级。
"""
