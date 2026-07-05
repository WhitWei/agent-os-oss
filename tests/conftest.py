"""Shared fixtures and test utilities for Agent OS tests."""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Optional

import pytest
from agentos.kernel.config import AppConfig, ConfigLoader

logger = logging.getLogger(__name__)

# ── Project paths ──
PROJECT_ROOT = Path(__file__).resolve().parent.parent

# ── Mock Env Vars for ConfigLoader ──
import os
os.environ.setdefault("FEISHU_APP_ID", "cli_app_id")
os.environ.setdefault("FEISHU_APP_SECRET", "cli_app_secret")
os.environ.setdefault("FEISHU_VERIFICATION_TOKEN", "cli_verif_token")
os.environ.setdefault("FEISHU_ENCRYPT_KEY", "cli_encrypt_key")
os.environ.setdefault("MCP_NONCE_SECRET", "test-secret")

@pytest.fixture(scope="session")
def project_root() -> Path:
    """Return the project root directory."""
    return PROJECT_ROOT


@pytest.fixture(scope="session")
def app_config() -> AppConfig:
    """Load and return a test AppConfig."""
    config_path = PROJECT_ROOT / "config.yaml"
    loader = ConfigLoader(str(config_path))
    return loader.load()


@pytest.fixture
def test_config_yaml(tmp_path: Path) -> Path:
    """Create a minimal test config.yaml."""
    import yaml

    config = {
        "kernel": {"name": "TestAgentOS", "version": "0.1.0", "log_level": "DEBUG"},
        "adapters": {
            "feishu": {"enabled": False},
            "cli": {"enabled": True},
        },
        "neo4j": {
            "uri": "bolt://localhost:7687",
            "user": "neo4j",
            "password": "test",
            "database": "neo4j",
        },
        "mcp": {
            "server_name": "test-gateway",
            "transport": "streamable-http",
            "host": "127.0.0.1",
            "port": 8199,
            "validation": {
                "nonce_secret": "test-secret",
                "nonce_ttl_seconds": 300,
            },
        },
        "autonomy": {"policy_file": "src/policies/policy_config.yaml"},
        "ontology": {
            "owl_dir": str(PROJECT_ROOT / "docker" / "ontology"),
            "shacl_dir": str(PROJECT_ROOT / "docker" / "ontology"),
            "domains": [
                {
                    "name": "it-asset-mgmt",
                    "owl_file": "it-asset-mgmt.owl",
                    "shacl_file": "it-asset-mgmt.shacl.ttl",
                }
            ],
        },
    }
    config_path = tmp_path / "test_config.yaml"
    config_path.write_text(yaml.dump(config), encoding="utf-8")
    return config_path


# ── Sample RDF data fixtures ──

@pytest.fixture
def sample_valid_ttl() -> str:
    """Valid HardwareAsset RDF in Turtle format."""
    return """
@prefix asset: <http://agent-os.local/ontology/it-asset-mgmt#> .
@prefix rdf: <http://www.w3.org/1999/02/22-rdf-syntax-ns#> .

<http://agent-os.local/data/asset/mbp-001>
    rdf:type asset:HardwareAsset ;
    asset:serialNumber "MBP2024-X7K9" ;
    asset:assetModel "MacBook Pro 16-inch M4" ;
    asset:sensitivityLevel "MEDIUM" .
"""


@pytest.fixture
def sample_invalid_ttl() -> str:
    """Invalid HardwareAsset RDF — missing required serialNumber."""
    return """
@prefix asset: <http://agent-os.local/ontology/it-asset-mgmt#> .
@prefix rdf: <http://www.w3.org/1999/02/22-rdf-syntax-ns#> .

<http://agent-os.local/data/asset/laptop-bad>
    rdf:type asset:HardwareAsset ;
    asset:assetModel "ThinkPad X1" .
"""


@pytest.fixture
def sample_valid_employee_ttl() -> str:
    """Valid Employee RDF."""
    return """
@prefix asset: <http://agent-os.local/ontology/it-asset-mgmt#> .
@prefix rdf: <http://www.w3.org/1999/02/22-rdf-syntax-ns#> .

<http://agent-os.local/data/employee/emp-001>
    rdf:type asset:Employee ;
    asset:employeeId "EMP-001" ;
    asset:employeeName "张三" .
"""


@pytest.fixture
def sample_invalid_employee_ttl() -> str:
    """Invalid Employee RDF — missing required employeeName."""
    return """
@prefix asset: <http://agent-os.local/ontology/it-asset-mgmt#> .
@prefix rdf: <http://www.w3.org/1999/02/22-rdf-syntax-ns#> .

<http://agent-os.local/data/employee/emp-bad>
    rdf:type asset:Employee ;
    asset:employeeId "EMP-BAD" .
"""
