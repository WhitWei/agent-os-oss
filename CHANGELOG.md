# Changelog

All notable changes to the Agent OS project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

---

## [0.1.0-alpha] - 2026-07-03

This is the initial open-source release of the Agent OS MVP runtime environment. It establishes the baseline security boundaries, sandboxing execution environments, and governance gates for LLM agents.

### Added
- **AgentOSKernel**: The central orchestrator routing adapter messages, executing pre-dispatch policies, and processing command/write execution.
- **SemanticFirewall**: Pre-dispatch hook preventing prompt injection and jailbreak payloads, integrated with OpenTelemetry span logging.
- **CircuitBreaker**: Failure-state deduplication. Automatically trips and blocks repetitive execution failure cycles (identifying states within 60s windows) to conserve tokens.
- **BillingFuse**: Session-level LLM token pricing monitor. Enforces absolute spend limits (trips at custom thresholds like $0.50) to prevent agent runaways.
- **AutonomyPolicy**: Filesystem directory sandboxing (with Unix glob matching) and CLI command whitelist enforcement.
- **WasmSandbox**: Rust-compiled WASM bytecode runner using `wasmtime`, featuring WASI import restrictions and fuel limits.
- **WriteGate**: Cryptographic 3-stage validation pipeline:
  1. OWL Schema fetch.
  2. SHACL Compliance validation emitting signed validation nonces.
  3. Governed transactional batch writes to a Neo4j database executing actual Cypher queries.
- **OpenTelemetry & Langfuse Observability**: Integration spans tracing validation failures and security interventions.
- **check_wiring.py**: Static scanner for orphaned security capability declarations.

### Security & Integrity
- Added signed HMAC validation nonces to prevent payload tampering and replay attacks.
- Integrated `testcontainers` for automated regression checks against a real Neo4j community database in Tier 2 tests.
