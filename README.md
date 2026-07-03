# Agent OS MVP — ZeroClaw Kernel
# ================================
# A minimal viable Agent Operating System with production-grade safety:
# semantic ontology (Neo4j + OWL), MCP governance gateway (3-stage write gate),
# and least-privilege autonomy policy.

> 📖 完整平台介绍、架构说明、部署指南与常见问题，见 [docs/平台介绍与操作手册.md](docs/平台介绍与操作手册.md)。

## Quick Start

### 1. Prerequisites
- Python 3.11+
- Docker (for Neo4j)
- `pytest`, `pylint`, `ripgrep`

### 2. Install Dependencies
```bash
pip install -e ".[dev]"
```

### 3. Start Neo4j
```bash
cd docker
docker compose up -d
```

Wait for Neo4j health check to pass:
```bash
docker compose ps  # should show "healthy"
```

### 4. Import Ontology
```bash
python scripts/import_ontology.py
```

### 5. Run the Demo
```bash
python scripts/run_demo.py
```

### 6. Run Tests
```bash
pytest -v
```

## Architecture

```
IM Channel (Feishu/CLI)
       │
       ▼
  Channel Adapter ──► ChannelMessage
       │
       ▼
  ZeroClaw Kernel
       │
       ├─ Autonomy Policy Check
       │
       └─ MCP Governance Gateway (3-stage)
              │
              ├─ 1. get-schema
              ├─ 2. verify-shacl
              └─ 3. execute-write
                     │
                     ▼
              Neo4j + Neosemantics
```

## Project Structure

```
src/
├── zeroclaw/       # Kernel, config, exceptions
├── adapters/       # Feishu, CLI channel adapters
├── governance/     # MCP server, SHACL validator, write gate
└── policies/       # Autonomy policy enforcement
docker/
├── docker-compose.yml  # Neo4j + n10s
└── ontology/           # OWL + SHACL files
tests/                  # Unit + integration tests
scripts/                # Setup, import, demo
```

## Verifying Safety Guarantees

1. **SHACL rejection**: Submit invalid asset data — must get JSON-RPC error
2. **Direct write bypass**: Try `execute_governed_write` without a validation nonce — must be rejected
3. **Path traversal**: Attempt to read outside allowed_paths — must raise `PolicyViolationError`
4. **Command injection**: Attempt blocked shell command — must be denied
