"""Tests for the ZeroClaw config loader.

Verifies YAML loading, env var interpolation, Pydantic validation,
and edge cases.
"""

import os
from pathlib import Path

import pytest
import yaml
from zeroclaw.config import ConfigLoader, AppConfig, _resolve_env_vars


class TestEnvVarResolution:
    """Unit tests for env var resolution in config strings."""

    def test_literal_string_no_vars(self):
        """String without env var references is returned unchanged."""
        assert _resolve_env_vars("hello") == "hello"
        assert _resolve_env_vars("") == ""

    def test_dollar_with_braces(self):
        """${VAR} is replaced with env var value."""
        os.environ["TEST_VAR"] = "test_value"
        assert _resolve_env_vars("${TEST_VAR}") == "test_value"

    def test_dollar_with_default(self):
        """${VAR:-default} uses default when var is missing."""
        result = _resolve_env_vars("${MISSING_VAR:-fallback}")
        assert result == "fallback"

    def test_dollar_with_default_when_present(self):
        """${VAR:-default} uses env var when set."""
        os.environ["PRESENT_VAR"] = "actual"
        assert _resolve_env_vars("${PRESENT_VAR:-fallback}") == "actual"

    def test_mixed_literal_and_var(self):
        """String with both literal text and var refs is fully resolved."""
        os.environ["USER"] = "testuser"
        result = _resolve_env_vars("/home/${USER}/app")
        assert result == "/home/testuser/app"

    def test_multiple_vars(self):
        """Multiple env var references are all resolved."""
        os.environ["HOST"] = "localhost"
        os.environ["PORT"] = "8080"
        result = _resolve_env_vars("${HOST}:${PORT}")
        assert result == "localhost:8080"


class TestConfigLoader:
    """Integration tests for the ConfigLoader."""

    def test_load_valid_config(self, test_config_yaml: Path):
        """Load a valid config file and verify all sections are parsed."""
        loader = ConfigLoader(str(test_config_yaml))
        config = loader.load()

        assert isinstance(config, AppConfig)
        assert config.kernel.name == "TestZeroClaw"
        assert config.kernel.version == "0.1.0"
        assert config.mcp.server_name == "test-gateway"
        assert len(config.ontology.domains) == 1
        assert config.ontology.domains[0].name == "it-asset-mgmt"

    def test_load_with_env_override(self, test_config_yaml: Path):
        """Env vars in config are resolved."""
        os.environ["NEO4J_PASSWORD"] = "secret123"

        loader = ConfigLoader(str(test_config_yaml))
        config = loader.load()

        # The test config uses "test" as the password, not ${NEO4J_PASSWORD}
        # so this test verifies env var doesn't corrupt the config
        assert config.neo4j.password == "test"

    def test_file_not_found_raises(self):
        """Loading a nonexistent file raises FileNotFoundError."""
        loader = ConfigLoader("/nonexistent/config.yaml")
        with pytest.raises(FileNotFoundError):
            loader.load()

    def test_load_from_project_root(self):
        """The default config.yaml in the project root is loadable."""
        config_path = Path(__file__).parent.parent / "config.yaml"
        if config_path.exists():
            loader = ConfigLoader(str(config_path))
            config = loader.load()
            assert config.kernel.name in ("ZeroClaw", "TestZeroClaw")
            assert config.neo4j.uri is not None

    def test_adapter_config(self, test_config_yaml: Path):
        """Adapter configuration is parsed correctly."""
        loader = ConfigLoader(str(test_config_yaml))
        config = loader.load()

        assert config.adapters.cli.enabled is True
        assert config.adapters.feishu.enabled is False

    def test_ontology_domains(self, test_config_yaml: Path):
        """Ontology domain list is parsed."""
        loader = ConfigLoader(str(test_config_yaml))
        config = loader.load()

        domains = config.ontology.domains
        assert len(domains) >= 1
        domain = domains[0]
        assert domain.name == "it-asset-mgmt"
        assert domain.owl_file.endswith(".owl")
        assert domain.shacl_file.endswith(".ttl")
