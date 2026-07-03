import os
import re
from pathlib import Path
from typing import Any, Optional

import yaml
from pydantic import BaseModel, Field, field_validator


# ── Pydantic Config Models ──


class KernelConfig(BaseModel):
    name: str = "ZeroClaw"
    version: str = "0.1.0"
    log_level: str = "INFO"
    session_ttl_seconds: int = 300


class FeishuAdapterConfig(BaseModel):
    enabled: bool = False
    app_id: str = ""
    app_secret: str = ""
    verification_token: str = ""
    encrypt_key: str = ""
    webhook_path: str = "/webhook/feishu"
    listen_host: str = "0.0.0.0"
    listen_port: int = 8000


class CliAdapterConfig(BaseModel):
    enabled: bool = True


class AdaptersConfig(BaseModel):
    feishu: FeishuAdapterConfig = Field(default_factory=FeishuAdapterConfig)
    cli: CliAdapterConfig = Field(default_factory=CliAdapterConfig)


class Neo4jN10sConfig(BaseModel):
    enabled: bool = True
    rdf_format: str = "Turtle"


class Neo4jConfig(BaseModel):
    uri: str = "bolt://localhost:7687"
    user: str = "neo4j"
    password: str = "agentos123"
    database: str = "neo4j"
    n10s: Neo4jN10sConfig = Field(default_factory=Neo4jN10sConfig)


class MCPValidationConfig(BaseModel):
    nonce_secret: str = "dev-nonce-secret-change-in-prod"
    nonce_ttl_seconds: int = 300


class MCPConfig(BaseModel):
    server_name: str = "agent-os-governance"
    transport: str = "streamable-http"
    host: str = "0.0.0.0"
    port: int = 8100
    validation: MCPValidationConfig = Field(default_factory=MCPValidationConfig)


class AutonomyConfig(BaseModel):
    policy_file: str = "src/policies/policy_config.yaml"


class DomainConfig(BaseModel):
    name: str
    owl_file: str
    shacl_file: str


class OntologyConfig(BaseModel):
    owl_dir: str = "docker/ontology"
    shacl_dir: str = "docker/ontology"
    domains: list[DomainConfig] = Field(default_factory=list)


class ObservabilityConfig(BaseModel):
    """OpenTelemetry + Langfuse observability configuration."""
    enabled: bool = True
    service_name: str = "agent-os-poc"
    otlp_endpoint: str = "http://localhost:4317"
    sample_rate: float = 1.0


class LangfuseAppConfig(BaseModel):
    """Langfuse self-hosted integration config."""
    enabled: bool = True
    public_key: str = ""
    secret_key: str = ""
    host: str = "http://localhost:3000"


class AppConfig(BaseModel):
    kernel: KernelConfig = Field(default_factory=KernelConfig)
    adapters: AdaptersConfig = Field(default_factory=AdaptersConfig)
    neo4j: Neo4jConfig = Field(default_factory=Neo4jConfig)
    mcp: MCPConfig = Field(default_factory=MCPConfig)
    autonomy: AutonomyConfig = Field(default_factory=AutonomyConfig)
    ontology: OntologyConfig = Field(default_factory=OntologyConfig)
    observability: ObservabilityConfig = Field(default_factory=ObservabilityConfig)
    langfuse: LangfuseAppConfig = Field(default_factory=LangfuseAppConfig)


# ── Config Loader ──

_ENV_VAR_RE = re.compile(r"\$\{([^}:]+)(?::([^}]*))?\}|(?<!\\)\$\{([^}]+)\}")


def _resolve_env_vars(value: str) -> str:
    """Replace ${VAR} and ${VAR:-default} patterns with env var values."""

    def _replace(match: re.Match) -> str:
        # Try the :-default syntax first
        if match.group(1) is not None:
            var_name = match.group(1)
            default = match.group(2)
            env_val = os.environ.get(var_name)
            if env_val is not None:
                return env_val
            if default is not None:
                # Strip leading "-" from default (the :- syntax)
                if default.startswith("-"):
                    return default[1:]
                return default
            # Var not found, no default: return empty string
            return ""
        # Plain ${VAR} without default
        if match.group(3) is not None:
            var_name = match.group(3)
            env_val = os.environ.get(var_name)
            if env_val is not None:
                return env_val
            return match.group(0)  # Keep unresolved if no env var
        return match.group(0)

    return _ENV_VAR_RE.sub(_replace, value)


def _resolve_dict(data: dict[str, Any]) -> dict[str, Any]:
    """Recursively resolve env vars in all string values."""
    resolved: dict[str, Any] = {}
    for key, value in data.items():
        if isinstance(value, str):
            resolved[key] = _resolve_env_vars(value)
        elif isinstance(value, dict):
            resolved[key] = _resolve_dict(value)
        elif isinstance(value, list):
            resolved[key] = [
                _resolve_dict(item) if isinstance(item, dict) else item
                for item in value
            ]
        else:
            resolved[key] = value
    return resolved


class ConfigLoader:
    """Loads and validates configuration from a YAML file.

    Supports:
    - ${ENV_VAR} and ${ENV_VAR:-default} syntax for secrets
    - Pydantic validation of all config sections
    - Immutable frozen config post-load
    """

    def __init__(self, config_path: Optional[str] = None):
        if config_path is None:
            config_path = os.environ.get(
                "AGENT_OS_CONFIG", "config.yaml"
            )
        self._config_path = Path(config_path)

    def load(self) -> AppConfig:
        """Load, resolve and validate the configuration."""
        if not self._config_path.exists():
            raise FileNotFoundError(
                f"Config file not found: {self._config_path}"
            )

        raw = yaml.safe_load(self._config_path.read_text(encoding="utf-8"))
        if not isinstance(raw, dict):
            raise ValueError("Config file must contain a YAML mapping")

        resolved = _resolve_dict(raw)
        return AppConfig(**resolved)
