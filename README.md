# 🛡️ Agent OS

<p align="center">
  <a href="https://github.com/WhitWei/agent-os-oss/actions"><img src="https://img.shields.io/github/actions/workflow/status/WhitWei/agent-os-oss/integration-ci.yml?branch=main&label=CI&style=flat-square" alt="CI Status"></a>
  <a href="LICENSE"><img src="https://img.shields.io/badge/license-MIT-blue.svg?style=flat-square" alt="License"></a>
  <a href="https://www.python.org/"><img src="https://img.shields.io/badge/python-3.11%20%7C%203.12-blue.svg?style=flat-square" alt="Python Versions"></a>
  <a href="https://github.com/WhitWei/agent-os-oss/releases"><img src="https://img.shields.io/badge/status-alpha%20v0.1.2-orange.svg?style=flat-square" alt="Alpha Status"></a>
</p>

<p align="center">
  <b>The governance layer for LLM agents — blazing fast, surgically precise, plug it under anything.</b>
</p>

<p align="center">
  <a href="README.zh-CN.md">🇨🇳 简体中文</a>
</p>

---

**Agent OS** is a self-hosted governance runtime that sits between your LLM agents and the systems they touch. It is not yet another agent framework — it's the **safety belt, knowledge backend, policy enforcer, and observability pipeline** your existing framework is missing.

Its internal security kernel — codenamed **ZeroClaw** — is the engine behind every checkpoint: **zero latency overhead on the safety path, claw-like grip when enforcing policy.**

- **Fast** — all security checks run in microseconds to milliseconds, with zero additional LLM inference calls. The safety path introduces no model round-trip.
- **Safe** — every gate fails closed. The default answer is always "no." Defense in depth across 6 independent checkpoints.
- **Pluggable** — use it as a standalone MCP governance gateway, or slide it under any agent framework. Works with LangChain, LlamaIndex, Claude Desktop, or your own custom agent.

> ⚡ **One-line philosophy:** Agent OS doesn't make your agent smarter. It makes your agent *safe enough to let run.*

---

## 🔌 3-Second Hook: MCP for Claude Desktop

Add this to your `claude_desktop_config.json`:

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

Every tool call, write, and execution your Claude Desktop agent attempts now passes through Agent OS's firewall, policy engine, and write gate before reaching any real system.

---

## 🚀 Quick Start

```bash
pip install agent-os-oss

aos init                    # generate a default policy
aos start-mcp --port 8100   # start the governance gateway
```

Done. Your agent now has a safety belt.

<details>
<summary><b>👀 Step-by-step walkthrough</b></summary>

```bash
# 1. Install
python3 -m venv .venv && source .venv/bin/activate
pip install agent-os-oss

# 2. Initialize policy
aos init

# 3. Start the MCP governance gateway
aos start-mcp --port 8100

# 4. (Another terminal) Try an ungoverned write
aos write --domain it-asset-mgmt --ttl '{"name": "test"}'
# → BLOCKED: missing SHACL compliance nonce

# 5. Get the schema, validate, then write
aos schema --domain it-asset-mgmt
aos validate --domain it-asset-mgmt --ttl '<valid_rdf>'
# → PASSED: nonce issued

aos write --domain it-asset-mgmt --ttl '<valid_rdf>' --nonce "<nonce>"
# → WRITTEN: nonce consumed, write audited
```
</details>

---

## ⚡ The Difference: Fast + Safe

### Zero extra inference

Most guardrail systems (NeMo Guardrails, Guardrails AI, etc.) run a second LLM call on the safety path — every prompt gets classified, every response gets checked. That's one extra model round-trip per agent action, which at scale means **seconds of latency and doubled API costs.**

Agent OS was designed from the ground up to **never add an LLM call on the safety path.** Every check — injection scan, policy enforcement, SHACL validation, nonce verification — runs in **microseconds to milliseconds** using compiled regex, in-memory data structures, and W3C-standard graph validation engines:

| Check | Time | No extra LLM? |
|-------|------|:-------------:|
| Prompt injection scan | ~10 μs | ✅ |
| Policy allowlist match | ~50 μs | ✅ |
| Circuit breaker check | ~5 μs | ✅ |
| Billing fuse deduction | ~100 μs | ✅ |
| **SHACL graph validation** | ~5-50 ms | ✅ |
| Nonce sign + verify | ~200 μs | ✅ |
| WASM sandbox execution | As needed | ✅ |
| **End-to-end total** | **~5-50 ms** | ✅ **0 extra inferences** |

**vs. alternative approaches:** An extra LLM guardrail call takes ~500-3000 ms per action, effectively doubling your API cost and latency. Agent OS adds <50 ms even to the most complex write operation.

### Every gate fails closed

```
Agent Call
  │
  ▼
┌──────────────────────────┐   ┌──────────────────────┐
│ 1. 🔥 Semantic Firewall  │──→│ Matches? → BLOCKED   │  ~10 μs
│    (injection patterns)  │   │ + OTel security span  │
└──────────┬───────────────┘   └──────────────────────┘
           ▼ pass
┌──────────────────────────┐   ┌──────────────────────┐
│ 2. 🔁 Circuit Breaker    │──→│ Repeated fail? → HALT│  ~5 μs
│    (failure dedup)       │   └──────────────────────┘
└──────────┬───────────────┘
           ▼ pass
┌──────────────────────────┐   ┌──────────────────────┐
│ 3. 📜 Autonomy Policy    │──→│ Disallowed? → BLOCKED│  ~50 μs
│    (YAML-declared rules) │   └──────────────────────┘
└──────────┬───────────────┘
           ▼ pass
┌──────────────────────────┐   ┌──────────────────────┐
│ 4. ✅ SHACL Validator    │──→│ Violation? → BLOCKED │  ~5-50 ms
│    (W3C graph standard)  │   │ + fix hints           │
└──────────┬───────────────┘   └──────────────────────┘
           ▼ pass
┌──────────────────────────┐
│ 5. 🔑 Nonce Issued       │  HMAC-signed, TTL-bound, data-hash-locked
│    (single-use token)    │  Replay? → REJECTED
└──────────┬───────────────┘
           ▼
┌──────────────────────────┐   ┌──────────────────────┐
│ 6. 📝 Governed Write     │──→│ cost logged, budget  │  ~200 μs
│    (Neo4j / system)      │   │ checked, span emitted │
└──────────────────────────┘   └──────────────────────┘
```

**Every gate defaults to block.** Every gate logs. Every gate emits an OpenTelemetry span.

---

## 🧩 What Agent OS Gives You

### 🔒 Layer 1: Zero-Trust Security (microsecond class)

| Mechanism | What it blocks | Speed |
|-----------|---------------|:-----:|
| **Semantic Firewall** | Prompt injection, jailbreak attempts, credential exfiltration — 20+ regex hooks with severity classification (critical/high/medium/low) | ~10 μs |
| **Autonomy Policy** | Declarative YAML policy: filesystem path allowlists, command allow/denylists, network egress, write quotas, session TTL — every agent action checked before execution | ~50 μs |
| **Circuit Breaker** | Repeated failures that would burn API budget in a retry storm | ~5 μs |
| **Billing Fuse** | Token spend by model (Claude/GPT pricing table), hard budget cap, optional credential revocation on trip | ~100 μs |
| **WASM Sandbox** | Untrusted code execution: 16 MB memory ceiling, 1B instruction fuel, zero filesystem/network preopens, sensitive-path preflight | Configurable |

### ✍️ Layer 2: The 3-Stage Write Gate (signature pattern)

Agent OS's most distinctive capability — a cryptographic chain of custody for every data write:

```
  Stage 1                      Stage 2                       Stage 3
┌──────────────┐           ┌──────────────┐              ┌──────────────┐
│ Agent fetches│           │ Agent submits│              │ Agent submits│
│ domain       │ ────────→ │ RDF data.    │ ───nonce───→ │ data + nonce │
│ schema via   │           │ SHACL engine │   (signed)   │ for execute. │
│ get_schema() │           │ validates.   │              │              │
│              │           │              │              │ Gate verifies:│
│ Returns:     │           │ On PASS:     │              │ ✓ signature   │
│ • OWL class  │           │ HMAC nonce   │              │ ✓ TTL         │
│   hierarchy  │           │ issued with: │              │ ✓ data hash   │
│ • SHACL      │           │ • timestamp  │              │ ✓ not replayed│
│   shape defs │           │ • data hash  │              └──────┬───────┘
│ • property   │           │ • signature  │                     │ pass
│   constraints│           │ • TTL (300s) │                     ▼
└──────────────┘           └──────────────┘              ┌──────────────┐
                                                         │ Write        │
                                                         │ executed.    │
                                                         │ Nonce burned.│
                                                         │ Audited.     │
                                                         └──────────────┘
```

**What this prevents:**

| Attack | How Agent OS blocks it |
|--------|----------------------|
| Agent bypasses schema check entirely | No nonce → gate rejects at Stage 3 |
| Agent validates data A, writes data B | Data hash mismatch → gate detects tampering |
| Attacker replays a captured nonce | Nonce consumed + TTL expired → double rejection |
| Attacker forges a nonce | HMAC signature invalid → immediate reject |
| Agent retries the same bad write 50 times | Circuit breaker opens after N failures |

The nonce is **single-use, data-bound, time-limited, and cryptographically signed.** Once consumed, it's burned and cannot be reused.

### 🧠 Layer 3: Knowledge Graph & Ontology (W3C standards)

Agent OS doesn't just block bad data — it understands what *good* data looks like, using formal W3C semantic web standards:

- **OWL ontology loader** — domain definitions in `.ttl` with classes, object/data properties, and constraints
- **SHACL shape validator** — industry-standard graph validation with `pyshacl`; violations return detailed `fixHint` messages for the LLM to self-correct
- **Neo4j async client** — connection pooling, health checks, batch writes, Cypher injection sanitization
- **n10s (Neosemantics)** — RDF/OWL import configured for knowledge graph interoperability

This is what makes Agent OS different from a simple allow/deny firewall: it validates the *semantic meaning* of every write against a formal model of your domain.

### 🔁 Layer 4: Workflow Engine (SOP + HITL)

Define multi-step standard operating procedures in YAML, where each step is a typed node:

```yaml
sop_id: it-onboarding-v1
name: "Employee IT Equipment Provisioning"
steps:
  - id: check_employee
    type: validate                     # SHACL checks data compliance
    domain: it-asset-mgmt
    data_ref: employee

  - id: approve_sensitive
    type: human_approval              # Human-in-the-loop
    condition: "asset.sensitivityLevel in ['HIGH', 'CRITICAL']"

  - id: execute_assignment
    type: action
    action_type: governed_write       # Write through the 3-stage gate
    domain: it-asset-mgmt
    data_ref: assignment
```

**HITL channels** — currently supports Feishu/Lark interactive cards (webhook verification, HMAC event signature, card send and callback parsing, text reply). The approval interface is adapter-based and can be extended to other IM platforms.

**State persistence** — every step state is saved to SQLite (WAL mode), surviving service restarts. Resume from exactly where the workflow was suspended.

### 📊 Fifth Layer: Observability and Governance Dashboard (Web UI & OTel)

| Component | What it provides |
|-----------|------------------|
| **Built-in Web UI Dashboard** | An out-of-the-box, zero-configuration visual console (`localhost:8000/dashboard`). Real-time metrics on intercepts, SOP traces, and token spend. Built with Next.js static export and served as a single FastAPI binary! |
| **OpenTelemetry** | OTLP gRPC exporter, BatchSpanProcessor, TraceIdRatioBased sampling — route traces to any OTLP backend |
| **Langfuse SDK** | Score tracking, dataset management, prompt management, and batch/flush to prevent memory bloat |
| **Security Telemetry** | Dedicated `emit_security_intercept_span` and `emit_shacl_validation_error_span` — distinct observability pipelines for security events |
| **Feedback Database** | SQLite audit trails: A complete record of trace_id, reviewer, decision, reason, and original agent output for every human approval |
| **No-op Fallback** | Silently drops spans when telemetry is unconfigured — no code changes needed between dev and prod |

---

## 🔗 Extending Agent OS: Global Loop Engine

Agent OS handles safety and governance. But what about *execution autonomy* — the "think → do → check → improve" loop that lets an agent complete multi-step tasks on its own?

[**Global Loop Engine (GLE)**](https://github.com/WhitWei/global-loop-engine) is a LangGraph-powered execution layer that enforces strict **think → execute → critique → refine** cycles on every coding or automation task.

### Current integration: CLI-level loose coupling

Agent OS and GLE are currently integrated at the CLI/package level. Installing `agent-os-oss[loop]` gives you both CLIs, with GLE's execution steps routed through Agent OS's governance pipeline:

| | AOS alone | GLE alone | `aos[loop]` |
|:--|:----------|:----------|:------------|
| **Safety** | ✅ 6-gate security pipeline | ❌ Direct subprocess only | ✅ AOS governs every step |
| **Execution loop** | ❌ No autonomous loop | ✅ Think → Execute → Critique → Refine | ✅ GLE drives the loop |
| **Entry point** | `aos` CLI | `loop-engine` CLI | Two CLIs side by side |
| **Config** | `aos init` | `loop-engine --config` | Two separate configs |
| **Observability** | AOS OTel pipeline | GLE own instrumentation | Traces may split |

```bash
pip install agent-os-oss[loop]

aos start-mcp --port 8100               # governance gateway
loop-engine --task "..." --mode loop    # execution loop
```

### Proposed: GLE as a native SOP step type

A tighter integration would make GLE's execution loop a **first-class step type in Agent OS's SOP engine.** Instead of two CLIs, Agent OS becomes the single orchestrator that delegates execution steps to GLE:

```yaml
sop_id: refactor-auth-module
steps:
  - id: plan
    type: action
    action_type: llm_call                # Plan the refactor

  - id: gle_loop
    type: loop                           # ← Native SOP step type
    engine: global-loop-engine
    input_ref: plan.output
    constraints:
      max_iterations: 5
      test_integrity: true

  - id: review
    type: human_approval                 # Human signs off
    condition: "changes.files > 3"
```

| | CLI loose coupling (current) | SOP-native (planned) |
|---|---|---|
| **Entry point** | Two CLIs: `aos` + `loop-engine` | Single CLI: `aos` |
| **Configuration** | Separate configs | Unified `aos config` |
| **Workflow** | Can't reference GLE in SOP YAML | `type: loop` as a native SOP step |
| **Observability** | Two trace chains, potential break | Single OTel trace end-to-end |
| **Security** | GLE calls AOS MCP externally | GLE runs *inside* AOS security context |

This requires refactoring GLE from a standalone CLI into an execution engine library that AOS's SOP engine can invoke directly — planned for the v0.2 milestone.

---

## 📋 When Would You Use This?

**🏢 Enterprise IT Ops** — Let an agent manage user onboarding, asset provisioning, and access control with SHACL-validated writes to a Neo4j knowledge graph and human sign-off on sensitive actions.

**🛡️ Security / Red Team** — Run an adversarial probing agent bounded by Agent OS's command allowlists, filepath controls, and budget cap. Safe to let run unattended.

**🔬 AI Safety Research** — Experiment with agent autonomy levels via YAML policy: start at "everything requires human approval," gradually dial up to "auto-approve low-risk operations."

**🏭 Compliance-Critical Environments** — Every write validated against a formal ontology, signed with a single-use cryptographic token, and audited with full OpenTelemetry trace context.

---

## 🛡️ Three-Tier Testing (For Contributors)

Every change passes three test tiers to prevent "phantom merges":

1. **L1 · Unit tests** — fully mocked. Fast, no external dependencies.
2. **L2 · Integration tests** — real database via `testcontainers`. No mocking of core security components.
3. **L3 · End-to-end** — zero mocking. Full business flow (e.g. employee onboarding) start to finish.

---

## 🗺️ Roadmap

- [x] MCP governance gateway (Claude Desktop, any MCP client)
- [x] 3-stage write gate with cryptographic nonce
- [x] OWL ontology + SHACL validation engine
- [x] Neo4j knowledge graph backend
- [x] WASM micro-sandbox (wasmtime)
- [x] OpenTelemetry + Langfuse observability
- [x] Human-in-the-loop approval (Feishu/Lark adapter, extensible adapter interface)
- [x] GLE CLI-level integration (`agent-os-oss[loop]`)
- [ ] **GLE as native SOP step type** — `type: loop` in SOP YAML, single trace
- [ ] **PyPI distribution** — `pip install agent-os-oss` (planned v0.2)
- [ ] **Vector embedding layer** — text retrieval alongside structured ontology
- [ ] **Prometheus `/metrics` endpoint** — native Grafana dashboards
- [ ] **Docker Compose** — one-line startup with Neo4j + AOS + OTel collector
- [x] **Web UI dashboard** — real-time firewall traffic, write gate activity, budget
- [ ] **User preference learning** — extend Neo4j schema for per-user memory

---

## 🤝 Contributing

One-person project. Response times vary, but every issue and PR gets read. Adversarial / red-team reports are especially welcome given what this project aims to do.

- Read [CONTRIBUTING.md](CONTRIBUTING.md) before opening a PR
- Found a bug? [Open an issue](https://github.com/WhitWei/agent-os-oss/issues)
- [CODE_OF_CONDUCT.md](CODE_OF_CONDUCT.md)

---

## 📄 License

MIT. See [LICENSE](LICENSE).
