#!/bin/bash
# Agent OS MVP — Sprint 1 Setup Script
# =====================================
# One-command dev environment setup.
# Usage: bash scripts/setup.sh

set -euo pipefail
cd "$(dirname "$0")/.."

echo "🏗️  Agent OS MVP — Sprint 1 Setup"
echo "================================="
echo ""

# 1. Check prerequisites
echo "📋 Checking prerequisites..."
command -v python3.11 >/dev/null 2>&1 && echo "  ✅ Python 3.11: $(python3.11 --version)" || { echo "  ❌ Python 3.11 required"; exit 1; }
command -v docker >/dev/null 2>&1 && echo "  ✅ Docker: $(docker --version)" || { echo "  ⚠️  Docker not found — Neo4j will be unavailable"; }
command -v pytest >/dev/null 2>&1 && echo "  ✅ pytest: $(pytest --version | head -1)" || echo "  ⚠️  pytest not found"
echo ""

# 2. Install Python dependencies
echo "📦 Installing Python dependencies..."
python3.11 -m pip install -e ".[dev]" -q 2>&1 | tail -1
echo "  ✅ Dependencies installed"
echo ""

# 3. Create .env from example if not exists
if [ ! -f .env ]; then
    cp .env.example .env
    echo "  ✅ Created .env from .env.example (edit with your secrets)"
else
    echo "  ℹ️  .env already exists — skipping"
fi
echo ""

# 4. Start Neo4j (optional, requires Docker)
if command -v docker >/dev/null 2>&1; then
    echo "🐳 Starting Neo4j container..."
    cd docker
    docker compose up -d 2>/dev/null && echo "  ✅ Neo4j container started (wait for health check)" || echo "  ⚠️  Neo4j start failed — check Docker"
    cd ..
else
    echo "⚠️  Docker not available — skip 'docker compose up -d neo4j' to start Neo4j"
fi
echo ""

# 5. Run tests
echo "🧪 Running tests..."
python3.11 -m pytest tests/ -q 2>&1 | tail -5
echo ""

# 6. Done
echo "================================="
echo "✅ Setup complete!"
echo ""
echo "Next steps:"
echo "  1. Start Neo4j:    cd docker && docker compose up -d"
echo "  2. Import ontology: python3.11 scripts/import_ontology.py"
echo "  3. Run demo:        python3.11 scripts/run_demo.py"
echo "  4. Run tests:       python3.11 -m pytest tests/ -v"
