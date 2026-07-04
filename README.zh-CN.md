# 🛡️ Agent OS

<p align="center">
  <a href="https://github.com/WhitWei/agent-os-oss/actions"><img src="https://img.shields.io/github/actions/workflow/status/WhitWei/agent-os-oss/integration-ci.yml?branch=main&label=CI&style=flat-square" alt="CI Status"></a>
  <a href="LICENSE"><img src="https://img.shields.io/badge/license-MIT-blue.svg?style=flat-square" alt="License"></a>
  <a href="https://www.python.org/"><img src="https://img.shields.io/badge/python-3.11%20%7C%203.12-blue.svg?style=flat-square" alt="Python Versions"></a>
</p>

<p align="center">
  <b>专为大模型智能体打造的企业级治理运行时。</b><br>
  <i>赋能超级个体与企业 AI 团队，让 Agent 不仅“聪明”，更能做到绝对可信、可审计并受到物理边界约束。</i>
</p>

---

## 💡 什么是 Agent OS？

市面上有许多框架旨在“让大模型智能体更聪明”（如流程编排、逻辑推理、多智能体协作）。但是，当你将 AI 部署到**真实的生产环境与企业系统**中时——尤其是允许 Agent 分配资产、修改财务账本或审批 HR 流程时，仅仅“聪明”是不够的。你需要的是**信任与治理（Trust and Governance）**。

**Agent OS** 是一个**企业级智能体治理运行时**。它为企业客户在签署合同前最关心的安全问题提供了坚实的“安全与治理护城河”。它确保大模型的每一次高风险操作，都会经过密码学验证、语义约束、留痕审计，并受到预算与安全熔断器的严格物理限制。

```text
┌─────────────────────────────────────┐
│  “智能推理”层                        │ ← 你自己接入的 LLM（Claude/GPT）+ 业务 Prompts
│  (可自带任何 LLM 或编排框架)            │ 
├─────────────────────────────────────┤
│  “信任与治理”层                      │ ← Agent OS 提供
│  (三段式写入闸门 / 安全熔断器 /          │
│   人机协同审批 / 全栈可观测性)         │
└─────────────────────────────────────┘
```

---

## 🌟 核心商业价值

| 核心能力 | 详情说明 |
| :--- | :--- |
| **三段式治理写入闸门 (Write Gate)** | 严禁 Agent 裸写 SQL/Cypher。写入操作强制遵循严格的时序：`获取Schema` → `合规性校验`（并签发密码学 HMAC Nonce） → `执行写入`（消耗 Nonce）。从根本上杜绝数据篡改、伪造与重放攻击。 |
| **本体即代码 (Ontology-as-Code)** | 业务数据模型与约束规则通过声明式定义。CI 流水线会自动运行黄金数据集回归测试，确保校验规则永远不会发生静默退化。 |
| **声明式 SOP 与人机协同 (HITL)** | 纯 YAML 定义工作流。原生支持复杂状态机流转、基于条件的“人机协同 (HITL)”卡点审批，并且支持跨服务重启的持久化执行挂起与恢复。 |
| **运行时安全护城河 (Security Moat)** | 安全钩子直接注入系统内核分发周期：**语义防火墙**（拦截 Prompt 注入）、**循环熔断器**（阻断死循环故障）、**计费硬熔断**（触达 API 预算上限物理断电），以及**微沙箱**（隔离执行环境）。 |
| **审计与反馈闭环 (Feedback Loop)** | 每一次人类的批准/驳回决策，都会与确切的 `run_id` 独立绑定留痕，为未来的 AI 行为微调及合规性审计提供闭环数据支持。 |
| **解耦式循环引擎集成 (BLE/GLE)** | 无缝支持通过子进程调用与外部推理引擎（如 GLE / BLE）集成联动。Agent OS 负责作为绝对稳定的底层治理运行时，而大模型的智能推理循环（Loop）则作为松耦合的外部插件独立运行，最大化了企业架构的灵活性。 |
| **全栈可观测性 (Observability)** | 遥测与追踪作为系统一等公民内置。安全拦截事件与数据校验失败事件在 Trace 拓扑图中会被高亮分类，拒绝被淹没在海量的纯文本日志中。 |

---

## ⚖️ Agent OS 的绝对优势

| 安全威胁 | 传统普通 Agent 框架 | Agent OS 运行时 |
| :--- | :--- | :--- |
| **文件系统越权** | ❌ 无限制（允许原生路径操作） | ✅ 严格的沙箱目录白名单隔离 (`allowed_paths`) |
| **危险命令执行** | ❌ 随意执行系统命令 (exec / system) | ✅ 刚性的命令白名单控制与 Shell 参数净化 |
| **提示词注入 (Jailbreaks)** | ❌ 极易被恶意 Prompt 越狱劫持 | ✅ 运行时注入 **SemanticFirewall** (语义防火墙) 净化 |
| **死循环资源耗尽** | ❌ 陷入死循环导致天价 API 账单 | ✅ **BillingFuse** (计费熔断) 与 **CircuitBreaker** 双重保护 |
| **数据库非法篡改** | ❌ 允许执行原生的数据库语句 | ✅ 采用强密码学 **WriteGate** (写入闸门) 进行三段式校验 |

---

## 🔌 MCP Server (Claude Desktop 极简接入)

Agent OS 可以作为标准的 **Model Context Protocol (MCP)** 服务端无缝运行，为任何兼容 MCP 的客户端提供“治理网关”。

### Claude Desktop 3行配置起手式
编辑你的 `claude_desktop_config.json`：
```json
{
  "mcpServers": {
    "agent-os": {
      "command": "agentos",
      "args": ["start-mcp", "--port", "8100"]
    }
  }
}
```
配置完成！你的 Claude Desktop Agent 瞬间就穿上了 Agent OS 的语义防火墙与治理写入防弹衣。

---

## 🚀 快速开始

Agent OS 已在 PyPI 全球发布。

```bash
# 1. 安装 Agent OS 运行时
pip install agent-os-oss

# 2. 启动 MCP 服务
agentos start-mcp --port 8100

# 3. (可选) 运行 Demo SOP 演示流
agentos loop run --task "Run demo"
```

---

## 🛡️ 三层测试防御体系（Rule 10 宪法）

Agent OS 强制推行严苛的工程纪律，确保所有“宣称的安全组件”都被物理接线到了主运行流程中。我们交付的是一套三层防御体系：

1. **L1 单元测试**：纯组件级逻辑校验，剥离外部依赖。
2. **L2 集成/接线测试**：通过临时容器 (Ephemeral Containers) 物理拉起真实的数据库。**严禁** Mock 内部的安全与治理组件，真实断言批量事务写入的落库结果。
3. **L3 E2E / UAT 冒烟测试**：100% 模拟真实用户的业务工作流（如：员工入职 SOP 卡片审批），将整个系统作为黑盒进行外部端点断言。

自动化的 CI 流水线会在检测到任何“孤儿能力”（写了安全组件但没接入主入口）时，物理拦截代码合并。

---

## 📄 开源协议

本项目基于 MIT 协议开源。查看 [LICENSE](LICENSE) 获取更多信息。
