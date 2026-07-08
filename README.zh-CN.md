# 🛡️ Agent OS

<p align="center">
  <a href="https://github.com/WhitWei/agent-os-oss/actions"><img src="https://img.shields.io/github/actions/workflow/status/WhitWei/agent-os-oss/integration-ci.yml?branch=main&label=CI&style=flat-square" alt="CI Status"></a>
  <a href="LICENSE"><img src="https://img.shields.io/badge/license-MIT-blue.svg?style=flat-square" alt="License"></a>
  <a href="https://www.python.org/"><img src="https://img.shields.io/badge/python-3.11%20%7C%203.12-blue.svg?style=flat-square" alt="Python Versions"></a>
  <a href="https://github.com/WhitWei/agent-os-oss/releases"><img src="https://img.shields.io/badge/status-alpha%20v0.1.2-orange.svg?style=flat-square" alt="Alpha Status"></a>
</p>

<p align="center">
  <b>LLM Agent 的治理基础设施——极速响应、外科级精度、可插在任何 Agent 框架之下。</b>
</p>

<p align="center">
  <a href="README.md">🇺🇸 English README</a>
</p>

---

**Agent OS** 是一个可自托管的治理运行时，架在你的 LLM Agent 和它要碰的所有系统之间。它不是又一个 Agent 框架——它是你现有框架所缺失的那套 **安全带、知识后端、策略引擎和可观测性管道。**

它的内部安全内核——代号 **ZeroClaw**——是每一个检查点的执行引擎：**安全路径零延迟、策略执行猛如爪。**

- **极速（Fast）**—— 所有安全检查在微秒到毫秒级完成，安全路径上**不额外调用一次大模型**。0 次额外推理，0 次额外 API 调用。
- **安全（Safe）**—— 每一关的默认行为都是"拒绝"而非"放行"。6 道独立检查点做纵深防御。没有单点失效。
- **可插拔（Pluggable）**—— 可以独立作为 MCP 治理网关运行，也可以滑入 LangChain、LlamaIndex、Claude Desktop 或自研 Agent 框架之下。

> ⚡ **一句话哲学：** Agent OS 不会让你的 Agent 更聪明，但它能让你的 Agent *安全到你敢让它自己跑。*

---

## 🔌 3 秒接入：Claude Desktop MCP

在 `claude_desktop_config.json` 加三行配置：

```json
{
  "mcpServers": {
    "agent-os": {
      "command": "aos",
      "args": ["start-mcp", "--port", "8100"]
    }
  }
}
```

从此 Claude Desktop Agent 的每一次工具调用、每一次写入、每一次执行，都会先经过 Agent OS 的防火墙、策略引擎和写入网关，才会触及真实系统。

---

## 🚀 快速开始

```bash
pip install agent-os-oss

aos init                    # 生成默认策略
aos start-mcp --port 8100   # 启动治理网关
```

搞定。你的 Agent 现在有安全带了。

<details>
<summary><b>👀 一步一动看</b></summary>

```bash
# 1. 安装
python3 -m venv .venv && source .venv/bin/activate
pip install agent-os-oss

# 2. 初始化策略
aos init

# 3. 启动 MCP 治理网关
aos start-mcp --port 8100

# 4.（另一个终端）尝试未经合规校验的写入
aos write --domain it-asset-mgmt --ttl '{"name": "test"}'
# → 拦截：缺少 SHACL 合规令牌

# 5. 获取 Schema → 验证 → 写入
aos schema --domain it-asset-mgmt
aos validate --domain it-asset-mgmt --ttl '<valid_rdf>'
# → 通过：令牌已签发

aos write --domain it-asset-mgmt --ttl '<valid_rdf>' --nonce "<nonce>"
# → 已写入：令牌已消费，操作已审计
```
</details>

---

## ⚡ 核心差异：极速 + 安全

### 零额外推理

市面上大部分护栏系统（NeMo Guardrails、Guardrails AI 等）在安全路径上会跑第二次 LLM 调用——每条提示词先分类再放行、每次响应先审查再返回。这意味着每次 Agent 动作多一次模型往返，**数百毫秒延迟 + 双倍 API 成本。**

Agent OS 从设计第一行代码起，原则就是：**安全路径上绝不额外调用一次大模型。** 每一次检查——注入扫描、策略执行、SHACL 验证、Nonce 验签——全部在 **微秒到毫秒级** 完成，使用编译正则、内存数据结构和 W3C 标准图验证引擎：

| 检查项 | 耗时 | 需要额外 LLM？ |
|--------|:----:|:-------------:|
| 注入风险扫描 | ~10 μs | ✅ 不需要 |
| 策略白名单匹配 | ~50 μs | ✅ 不需要 |
| 熔断器状态检查 | ~5 μs | ✅ 不需要 |
| 计费扣减 | ~100 μs | ✅ 不需要 |
| **SHACL 图验证** | ~5-50 ms | ✅ 不需要 |
| 令牌签发 + 验签 | ~200 μs | ✅ 不需要 |
| WASM 沙箱执行 | 可配 | ✅ 不需要 |
| **端到端总延迟** | **~5-50 ms** | ✅ 0 次额外推理 |

**对比一下：** 如果安全路径走一次额外 LLM 调用（"判断这条提示词是否安全"），每次 Agent 动作要加 ~500-3000 ms。Agent OS 即使是最复杂的写操作，也在 50 ms 以内完成全部安全检查。

### 每一关默认拒绝

```
Agent 发起调用
  │
  ▼
┌──────────────────────────┐   ┌──────────────────────┐
│ 1. 🔥 语义防火墙          │──→│ 命中? → 拦截        │  ~10 μs
│    (注入模式扫描)        │   │ + OTel 安全事件 span │
└──────────┬───────────────┘   └──────────────────────┘
           ▼ 通过
┌──────────────────────────┐   ┌──────────────────────┐
│ 2. 🔁 熔断器             │──→│ 重复失败? → 熔断    │  ~5 μs
│    (失败去重)            │   └──────────────────────┘
└──────────┬───────────────┘
           ▼ 通过
┌──────────────────────────┐   ┌──────────────────────┐
│ 3. 📜 自治策略           │──→│ 不允许? → 拦截      │  ~50 μs
│    (YAML 声明式规则)     │   └──────────────────────┘
└──────────┬───────────────┘
           ▼ 通过
┌──────────────────────────┐   ┌──────────────────────┐
│ 4. ✅ SHACL 验证器       │──→│ 违规? → 拦截        │  ~5-50 ms
│    (W3C 图标准)          │   │ + 修复提示           │
└──────────┬───────────────┘   └──────────────────────┘
           ▼ 通过
┌──────────────────────────┐
│ 5. 🔑 签发一次性令牌      │  HMAC 签名、TTL 绑定、数据哈希锁定
│    (单次使用)            │  重放? → 拒绝
└──────────┬───────────────┘
           ▼
┌──────────────────────────┐   ┌──────────────────────┐
│ 6. 📝 执行受管控写入      │──→│ 计费、预算检查、span │  ~200 μs
│    (Neo4j / 系统)        │   │ 导出                │
└──────────────────────────┘   └──────────────────────┘
```

**每一关默认拒绝。** 每一关写日志。每一关发 OTel span。

---

## 🧩 Agent OS 能给你什么

### 🔒 第一层：零信任安全（微秒级）

| 机制 | 拦截什么 | 速度 |
|------|---------|:----:|
| **语义防火墙** | 提示注入、越狱尝试、凭据窃取——20+ 正则规则，分级拦截（严重/高/中/低） | ~10 μs |
| **自治策略** | 声明式 YAML：文件路径白名单、命令允许/禁止列表、网络出口、写入配额、会话 TTL | ~50 μs |
| **熔断器** | 重复失败的调用——在烧光 API 预算前叫停 | ~5 μs |
| **计费熔断器** | 按模型定价表追踪 Token 消耗（Claude/GPT 全系列），硬预算上限，超限可吊销凭据 | ~100 μs |
| **WASM 沙箱** | 不可信代码执行：16 MB 内存上限、10 亿指令燃料上限、零文件系统和网络、敏感路径预检 | 可配置 |

### ✍️ 第二层：三段式写门（Agent OS 的招牌）

每一次数据写入的加密级权责链——写门不是简单"放/拦"，而是三段式验证 + 一次性加密令牌：

```
  第一步                         第二步                        第三步
┌──────────────┐           ┌──────────────┐              ┌──────────────┐
│ Agent 获取   │           │ Agent 提交   │              │ Agent 提交   │
│ 领域 Schema  │ ────────→ │ RDF 数据。   │ ───nonce───→ │ 数据 + 令牌  │
│ (get_schema) │           │ SHACL 引擎   │   (已签名)   │ 执行写入。   │
│              │           │ 验证。       │              │              │
│ 返回：       │           │              │              │ 写门验证：   │
│ • OWL 类层级 │           │ 通过时签发： │              │ ✓ 签名有效   │
│ • SHACL 形状 │           │ HMAC 一次性  │              │ ✓ 未过 TTL   │
│ • 属性约束   │           │ 令牌包含：   │              │ ✓ 数据哈希   │
│              │           │ • 时间戳     │              │ ✓ 未被重放   │
│              │           │ • 数据哈希   │              └──────┬───────┘
│              │           │ • 签名       │                     │ 通过
│              │           │ • TTL (300s) │                     ▼
└──────────────┘           └──────────────┘              ┌──────────────┐
                                                         │ 执行写入。   │
                                                         │ 令牌作废。   │
                                                         │ 记入审计。   │
                                                         └──────────────┘
```

**这堵住了什么：**

| 绕过方式 | Agent OS 如何拦截 |
|---------|------------------|
| Agent 跳过 Schema 直接写 | 没有 Nonce → 写门在第三步拒绝 |
| Agent 验证数据 A，写入数据 B | 数据哈希不匹配 → 写门检测到篡改 |
| 攻击者截获 Nonce 后重放 | Nonce 已消费 + TTL 过期 → 双重拒绝 |
| 攻击者伪造 Nonce | HMAC 签名无效 → 立即拒绝 |
| Agent 重试同一恶意写入 50 次 | 熔断器在 N 次失败后打开 |

Nonce 是**一次性使用、绑定数据、限时有效、加密签名的**。用过的 Nonce 立即作废，不能重用。

### 🧠 第三层：知识图谱 + 本体论（W3C 标准）

Agent OS 不只是拦截坏数据——它用正式的 W3C 语义网标准来理解"好数据长什么样"：

- **OWL 本体加载器** —— `.ttl` 格式的领域定义，含类、对象/数据属性、约束关系
- **SHACL 形状验证器** —— 业界标准图验证引擎（`pyshacl`），违规时返回 `fixHint` 让 LLM 自行修正
- **Neo4j 异步客户端** —— 连接池、健康检查、批量写入、Cypher 注入净化
- **n10s (Neosemantics)** —— 预配置的 RDF/OWL 导入管道

这就是 Agent OS 和简单"拦/放"防火墙的本质区别：它在每次写入之前，用你业务领域的正式语义模型去验证数据的**含义是否合规。**

### 🔁 第四层：工作流引擎（SOP + 人工审批）

用 YAML 定义多步标准操作流程，每一步都是类型化节点：

```yaml
sop_id: it-onboarding-v1
name: "新员工 IT 设备入职分配"
steps:
  - id: check_employee
    type: validate                     # SHACL 校验数据合规
    domain: it-asset-mgmt
    data_ref: employee

  - id: approve_sensitive
    type: human_approval              # 人工审批
    condition: "asset.sensitivityLevel in ['HIGH', 'CRITICAL']"

  - id: execute_assignment
    type: action
    action_type: governed_write       # 通过三段式写门执行写入
    domain: it-asset-mgmt
    data_ref: assignment
```

**人工审批渠道** —— 当前支持飞书/Lark 交互式审批卡片（Webhook 质询验证、HMAC 事件签名校验、卡片发送与回调解析、文本回复）。审批接口采用适配器模式，可扩展对接其他 IM 平台。

**状态持久化** —— 每一步写入 SQLite（WAL 模式），服务重启后精确恢复，不会丢失上下文。

### 📊 第五层：可观测性与治理看板（Web UI & OTel）

| 组件 | 提供什么 |
|------|---------|
| **内建 Web UI 看板** | 一键启动的开箱即用可视化大屏（`localhost:8000/dashboard`），实时呈现拦截统计、SOP 流程追溯、资金消耗。纯静态导出，FastAPI 单体挂载，零额外依赖！ |
| **OpenTelemetry** | OTLP gRPC 导出器、BatchSpanProcessor、TraceIdRatioBased 采样——可路由到任何 OTLP 后端 |
| **Langfuse SDK** | 评分追踪、数据集管理、Prompt 管理、batch/flush 防内存堆积 |
| **安全遥测** | 专用的 `emit_security_intercept_span` 和 `emit_shacl_validation_error_span`——安全事件有独立观测管道 |
| **反馈数据库** | SQLite 审计追踪：每次人工审批的 trace_id、审批人、决策、理由、Agent 原始输出完整记录 |
| **No-op 回退** | 未配置 telemetry 时静默丢弃所有 span——开发和部署之间无需改代码 |

---

## 🔗 扩展 Agent OS：Global Loop Engine

Agent OS 管安全和治理。但"执行自主性"怎么办——那个让 Agent 能干完多步任务的 **"思考 → 执行 → 批判 → 优化"** 循环？

[**Global Loop Engine (GLE)**](https://github.com/WhitWei/global-loop-engine) 是一个 LangGraph 驱动的执行层，对每次编码或自动化任务强制 **think → execute → critique → refine** 循环。

### 当前集成方式：CLI 级松耦合

Agent OS 和 GLE 目前在 CLI/包管理层面集成。安装 `agent-os-oss[loop]` 后同时获得两个 CLI，GLE 的执行步骤通过 Agent OS 治理管道做安全校验：

| | 仅有 AOS | 仅有 GLE | `aos[loop]` |
|:--|:---------|:---------|:------------|
| **安全** | ✅ 6 道安全门 | ❌ 裸子进程 | ✅ AOS 管控每一步 |
| **执行循环** | ❌ 无自主循环 | ✅ Think → Execute → Critique → Refine | ✅ GLE 驱动循环 |
| **入口** | `aos` CLI | `loop-engine` CLI | 两个 CLI 并列 |
| **配置** | `aos init` | `loop-engine --config` | 两套独立配置 |
| **可观测** | AOS OTel 管道 | GLE 自有埋点 | 追踪链可能断 |

```bash
pip install agent-os-oss[loop]

aos start-mcp --port 8100               # 治理网关
loop-engine --task "..." --mode loop    # 执行循环
```

### 演进方向：GLE 作为 SOP 原生步骤类型

更合理的集成方案是把 GLE 的执行循环变成 **Agent OS SOP 引擎的一个第一类步骤类型。** 不再需要两个 CLI，Agent OS 成为统一调度入口，将执行步骤委派给 GLE：

```yaml
sop_id: refactor-auth-module
steps:
  - id: plan
    type: action
    action_type: llm_call                # 先用 LLM 出方案

  - id: gle_loop
    type: loop                           # ← SOP 原生步骤类型
    engine: global-loop-engine
    input_ref: plan.output
    constraints:
      max_iterations: 5
      test_integrity: true

  - id: review
    type: human_approval                 # 人工审批最终结果
    condition: "changes.files > 3"
```

| | CLI 松耦合（现状） | SOP 原生集成（规划中） |
|---|---|---|
| **入口** | 两个 CLI：`aos` + `loop-engine` | 一个 CLI：`aos` |
| **配置** | 各自独立配置 | 统一 `aos config` |
| **工作流** | SOP YAML 不能引用 GLE 循环 | `type: loop` 作为原生步骤 |
| **可观测** | 两条追踪链，可能断裂 | 同一 OTel trace 不间断 |
| **安全** | GLE 外部调用 AOS MCP | GLE 在 AOS 安全上下文中运行 |

这需要把 GLE 从独立 CLI 重构为可被 AOS SOP 引擎直接调用的执行引擎库——规划在 v0.2 路线图中。

---

## 📋 什么时候用这个？

**🏢 企业 IT 运维** —— 让 Agent 管理员工入职、资产分配、权限控制，数据写入经 SHACL 验证到 Neo4j 知识图谱，敏感操作人工审批。

**🛡️ 安全 / 红队** —— 运行一个探测性 Agent，被 Agent OS 的命令白名单、文件路径控制和预算硬上限约束——可以安全地无人值守运行。

**🔬 AI 安全研究** —— 通过 YAML 策略文件实验 Agent 自主级别：从"全部人工审批"到"低风险自动放行"。

**🏭 合规敏感环境** —— 每次写入经正式本体验证、加密令牌签名、全链路 OpenTelemetry 追踪审计。

---

## 🛡️ 三层测试标准（给贡献者）

每次改动要过三层测试，防止"幽灵合并"：

1. **L1 · 单元测试** —— 全 Mock，只验证独立逻辑。快，无外部依赖。
2. **L2 · 集成测试** —— 用 `testcontainers` 启动真实数据库，核心安全组件不 Mock。
3. **L3 · 端到端测试** —— 零 Mock，完整业务流程从头走到尾（如员工入职审批）。

---

## 🗺️ 路线图

- [x] MCP 治理网关（Claude Desktop 及任何 MCP 客户端）
- [x] 三段式 WriteGate + 加密 Nonce
- [x] OWL 本体 + SHACL 验证引擎
- [x] Neo4j 知识图谱后端
- [x] WASM 微沙箱（wasmtime）
- [x] OpenTelemetry + Langfuse 可观测性
- [x] 人工审批（飞书/Lark 适配器，可扩展接口）
- [x] GLE CLI 级集成（`agent-os-oss[loop]`）
- [ ] **GLE 作为 SOP 原生步骤类型** —— SOP YAML 中 `type: loop`，统一追踪链
- [ ] **PyPI 发布** —— `pip install agent-os-oss`（规划 v0.2）
- [ ] **向量嵌入层** —— 在结构化本体之外补全文本检索 RAG
- [ ] **Prometheus `/metrics` 端点** —— 原生对接 Grafana 看板
- [ ] **Docker Compose 一键启动** —— 预配置 Neo4j + AOS + OTel 收集器
- [x] **Web UI 看板** —— 实时查看防火墙流量、写门活动、预算消耗
- [ ] **用户偏好学习** —— 扩展 Neo4j Schema 支持跨会话用户记忆

---

## 🤝 贡献与社区

单人维护项目。响应时间有波动，但每个 issue 和 PR 都会被认真阅读。考虑到这个项目的定位，对抗性/红队式的问题报告尤其受欢迎。

- 提 PR 前请先看 [CONTRIBUTING.md](CONTRIBUTING.md)
- 发现 bug？[提一个 issue](https://github.com/WhitWei/agent-os-oss/issues)
- [CODE_OF_CONDUCT.md](CODE_OF_CONDUCT.md)

---

## 📄 授权协议

MIT。见 [LICENSE](LICENSE)。
