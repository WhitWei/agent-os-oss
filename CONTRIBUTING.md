# 👩‍💻 Contributing to Agent OS

Thank you for your interest in contributing to Agent OS! We welcome community contributions to help make this runtime environment safer, more robust, and highly autonomous.

By contributing to this repository, you agree to adhere to our [Code of Conduct](CODE_OF_CONDUCT.md).

---

## 🛡️ Critical Quality Gate: Three-Tier Testing Constitution

To prevent "phantom merges" where individual modules pass tests but fail to work together in the main runtime route, we enforce a strict **Three-Tier Testing Constitution**. Any Pull Request that fails to provide verified testing evidence matching these boundaries will be automatically rejected.

### 1. Tier 1: Unit Testing (L1)
*   **What it verifies**: Internal calculation logic of a single class or method.
*   **Mocking Guideline**: All physical external dependencies (Docker, Neo4j database, web network, local files outside scratch) **MUST** be mocked or set to `None`.
*   **Owner**: Coding / Developer.
*   **Run command**: `pytest tests/ -v` (excluding integration markers).

### 2. Tier 2: Integration & Wiring Testing (L2) — *Mandatory for Core Security Changes*
*   **What it verifies**: Whether different modules are correctly wired and that data/intercept signals truly flow along the architectural arrows.
*   **Mocking Guideline**: **No mocking of internal core components** (e.g. firewall, circuit breaker, billing limits). You must use `testcontainers` to spin up a clean database instance (like Neo4j) to verify physical persistence. You are only allowed to mock out-of-boundary side effects (such as sending actual Feishu card messages).
*   **Requirement**: You must assert that when a malicious payload or quota overrun is dispatched via the primary kernel entrypoint (`AgentOSKernel.wake_up()`), the security firewall and breaker are **physically triggered and intercept the call**.
*   **Evidence**: When submitting a PR, you must attach the `testcontainers` logs and actual database query results proving that data was physically written or blocked.

### 3. Tier 3: E2E / UAT / Smoke Testing (L3)
*   **What it verifies**: The overall runtime and adapters usability for end users under happy path and major edge cases.
*   **Mocking Guideline**: Zero mocking. 100% real deployment in a sandbox environment.
*   **Owner**: UAT / Reviewer.

---

## 🛠️ Local Development & PR Workflow

### 1. Prerequisites
Ensure you have the following installed locally:
*   Python >= 3.11
*   Docker (required for L2 integration tests using `testcontainers`)

### 2. Set Up Environment
We recommend using a virtual environment:
```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
```

### 3. Running Code Style and Verification
Before committing, make sure the static wiring scan passes (detects any orphaned security classes):
```bash
python3 scripts/check_wiring.py
```

Run all unit and L2 integration tests (ensure your Docker daemon is running):
```bash
export RYUK_DISABLED=true  # Useful if Ryuk has NAT conflicts locally
python3 -m pytest tests/ -v
```

### 4. Submitting a Pull Request
1.  Fork the repository and create your branch from `main`.
2.  Write clean code following the kebab-case naming standard for files and camelCase/PascalCase guidelines.
3.  Add Tier 1 and Tier 2 tests covering your code changes.
4.  Ensure `check_wiring.py` and `pytest` are 100% green.
5.  Submit a PR with clear evidence (test outputs, logs) showing that you ran and validated your wiring.
