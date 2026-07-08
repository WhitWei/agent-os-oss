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
