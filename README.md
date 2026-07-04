# 🛡️ Agent OS

<p align="center">
  <a href="https://github.com/WhitWei/agent-os-oss/actions"><img src="https://img.shields.io/github/actions/workflow/status/WhitWei/agent-os-oss/integration-ci.yml?branch=main&label=CI&style=flat-square" alt="CI Status"></a>
  <a href="LICENSE"><img src="https://img.shields.io/badge/license-MIT-blue.svg?style=flat-square" alt="License"></a>
  <a href="https://www.python.org/"><img src="https://img.shields.io/badge/python-3.11%20%7C%203.12-blue.svg?style=flat-square" alt="Python Versions"></a>
</p>

<p align="center">
  <b>The Enterprise Governance Runtime for Autonomous LLM Agents.</b><br>
  <i>Empowering Super-Individuals and Enterprise AI Teams to deploy Agents that are not just "smart", but absolutely trustworthy, auditable, and physically bounded.</i>
</p>

---

## 💡 What is Agent OS?

There are many frameworks designed to "make LLM Agents smarter" (orchestration, reasoning, multi-agent collaboration). But when deploying AI to **real enterprise systems**—where Agents are allowed to allocate assets, modify financial ledgers, or approve HR processes—intelligence is not enough. You need **Trust and Governance**.

**Agent OS** is an **Enterprise Agent Governance Runtime**. It provides the essential "Security and Governance Moat" that enterprise clients demand before signing contracts. It ensures that every high-risk action taken by an LLM is cryptographically validated, semantically constrained, audited, and strictly bounded by budget and safety fuses.

```text
┌─────────────────────────────────────┐
│  The "Intelligence" Layer           │ ← Your LLM (Claude/GPT) + Business Prompts
│  (Bring Your Own LLM/Orchestrator)  │ 
├─────────────────────────────────────┤
│  The "Trust & Governance" Layer     │ ← Agent OS
│  (Write Gates / Security Fuses /    │
│   HITL Approvals / Observability)   │
└─────────────────────────────────────┘
```

---

## 🌟 Core Value Proposition

| Capability | Description |
| :--- | :--- |
| **3-Stage Governance Write Gate** | No Agent can write raw SQL/Cypher. Writes require a strict sequence: `get-schema` → `verify-compliance` (yielding a cryptographic HMAC Nonce) → `execute-write` (consuming the Nonce). Prevents data tampering, spoofing, and replay attacks. |
| **Ontology-as-Code** | Business data models and constraints are defined declaratively. CI pipelines automatically run Golden Dataset regressions to ensure validation rules never silently degrade. |
| **Declarative SOP & HITL** | Workflows are defined in YAML. Supports complex state machines, conditional Human-in-the-Loop (HITL) approvals, and persistent execution suspension/resumption across server restarts. |
| **Runtime Security Moat** | Hooks injected directly into the kernel dispatch cycle: **Semantic Firewall** (blocks prompt injections), **Circuit Breaker** (halts infinite loop failures), **Billing Fuse** (hard stops on API budget overruns), and **Micro-Sandbox** (isolated execution). |
| **Audit & Feedback Loop** | Every human approval/rejection decision is logged independently with the exact `run_id`, forming a closed loop for future AI behavioral fine-tuning and compliance audits. |
| **Decoupled Loop Engine Integration** | Seamlessly integrates with external reasoning engines (like GLE/BLE) via subprocess calls. Agent OS acts as the stable governance runtime, while the intelligence loop operates as an independent, loosely-coupled plugin, maximizing architectural flexibility. |
| **Full-Stack Observability** | Tracing and telemetry are built-in as first-class citizens. Security intercepts and validation errors are distinctly categorized in the trace topology, not buried in text logs. |

---

## ⚖️ The Agent OS Difference

| Security Threat | Standard Agent Frameworks | Agent OS Runtime |
| :--- | :--- | :--- |
| **Filesystem Safety** | ❌ None (raw path manipulation allowed) | ✅ Strict sandbox directory restrictions (`allowed_paths`) |
| **Command Execution** | ❌ Run any command (exec / system) | ✅ Rigid whitelist control & shell argument sanitization |
| **Prompt Injection** | ❌ Vulnerable to prompt jailbreaks | ✅ Run-time **SemanticFirewall** input sanitization |
| **Runaway Breaker** | ❌ Infinite loops leading to high API bill | ✅ **BillingFuse** spending quotas & **CircuitBreaker** logic |
| **Database Writes** | ❌ Raw queries execution | ✅ Cryptographic **WriteGate** 3-stage validation |

---

## 🔌 MCP Server (Claude Desktop Integration)

Agent OS can operate seamlessly as a **Model Context Protocol (MCP)** server, providing a Governance Gateway for any MCP-compatible client.

### 3-Line Setup for Claude Desktop
Edit your `claude_desktop_config.json`:
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
Your Claude Desktop agent is now strictly governed by Agent OS's semantic firewall and write gates.

---

## 🚀 Quick Start

Agent OS is distributed via PyPI.

```bash
# 1. Install the runtime
pip install agent-os-oss

# 2. Start the MCP server
agentos start-mcp --port 8100

# 3. (Optional) Run the demo SOP flow
agentos loop run --task "Run demo"
```

---

## 🛡️ The 3-Tier Testing Constitution (Rule 10)

Agent OS forces a strict engineering discipline to ensure "staged components" are actually physically wired into the main application. We ship with a three-tier defense system:

1. **L1 Unit Tests**: Pure component logic, no external dependencies.
2. **L2 Integration Tests**: Bootstraps actual physical databases via ephemeral containers. Strictly prohibits mocking internal security/governance components. Verifies the actual transactional batch writes.
3. **L3 E2E / UAT Tests**: Simulates full user business flows (e.g., employee onboarding SOP card approvals) acting entirely as a black-box tester against the outer endpoints.

Automated pipelines physically block code merges if orphaned capabilities (components written but not wired into the main execution path) are detected.

---

## 📄 License

Distributed under the MIT License. See [LICENSE](LICENSE) for more information.
