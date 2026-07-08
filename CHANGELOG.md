# Changelog

All notable changes to the Agent OS project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

---

## [0.1.2] - 2026-07-08

This release introduces the "Out-of-the-Box" Web UI Dashboard, completing Sprint 2. Agent OS now features a built-in visual console powered by Next.js and FastAPI, served as a monolithic binary.

### Added
- **Web UI Dashboard**: A standalone, zero-configuration React (Next.js + shadcn/ui) dashboard served statically through the backend.
- **FastAPI Single-Binary Delivery**: Bundled static files in `/dashboard` utilizing SPA fallback routing.
- **Local Persistence APIs**: Added REST endpoints for Dashboard consumption:
  - `GET /api/v1/metrics/overview`: Aggregated statistics on spends, intercepts, and active workflow runs.
  - `GET /api/v1/workflows/runs`: Trace tables powered by `StateStore`.
  - `GET /api/v1/governance/audits`: Intervention history powered by `FeedbackDB`.
- **E2E Traceability**: Verified physical logging mapping from internal `CircuitBreaker` and `SemanticFirewall` straight to UI audit tables.

### Fixed
- **Float Error**: Fixed a critical `TypeError: 'float' object is not callable` in `metrics.py` during L3 UAT testing.

---

## [0.1.1] - 2026-07-05

This release focuses on solidifying the backend, fixing bugs discovered during the physical integration testing (L2), and refining the namespace structure.

### Changed
- **Unified Service Architecture**: Moved all logic under the `src/agentos/` namespace for cleaner module boundaries.
- **SQLite Concurrency**: Re-engineered SQLite state persistence to use `threading.local()`, mitigating `SQLITE_BUSY` contention under heavy concurrency.
- **Deterministic Hashes**: Replaced non-deterministic `hash()` with `hashlib.sha256` in the `CircuitBreaker` to ensure determinism across deployments.
- **Clock Monotonicity**: Transitioned from `time.time()` to `time.monotonic()` for nonce signatures to eliminate risks related to system clock drifts.

### Fixed
- **CORS Conflict**: Resolved W3C CORS conflict by turning off `allow_credentials` when `allow_origins=["*"]`.
- **Config Loader Null Bugs**: Strict env var loader now raises `ConfigError` for missing vars instead of silently swallowing empty strings.
- **Hash Alteration Bug**: Fixed an issue where `text.strip()` was mutating RDF payloads, preventing cryptographic signature validation for database write operations.

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
