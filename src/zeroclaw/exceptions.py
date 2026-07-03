"""Custom exception hierarchy for Agent OS."""

from __future__ import annotations


class AgentOSException(Exception):
    """Base exception for all Agent OS errors."""


class KernelException(AgentOSException):
    """Errors originating from the ZeroClaw kernel."""


class ConfigError(AgentOSException):
    """Configuration loading or validation errors."""


class AdapterError(AgentOSException):
    """Errors from channel adapters (Feishu, CLI, etc.)."""


class GovernanceError(AgentOSException):
    """Errors from the MCP governance gateway."""


class SHACLValidationError(GovernanceError):
    """SHACL validation failed — payload does not comply with ontology constraints."""

    def __init__(self, message: str, validation_report: dict | None = None):
        super().__init__(message)
        self.validation_report = validation_report or {}


class WriteGateError(GovernanceError):
    """Write gate rejected the operation (missing or invalid nonce, bypass attempt)."""


class PolicyViolationError(AgentOSException):
    """Autonomy policy violation — operation blocked by least-privilege rules."""


class Neo4jConnectionError(AgentOSException):
    """Cannot connect to Neo4j database."""

class SandboxError(AgentOSException):
    """WASM sandbox execution failure or policy violation."""
    def __init__(self, message: str, trap_reason: str | None = None):
        super().__init__(message)
        self.trap_reason = trap_reason


class SecurityInterceptError(AgentOSException):
    """Raised when the semantic firewall or safety guard intercepts suspicious input."""
    def __init__(self, message: str, trigger: str | None = None, severity: str = "high"):
        super().__init__(message)
        self.trigger = trigger
        self.severity = severity


class BillingFuseTrippedError(AgentOSException):
    """Raised when the billing hard-fuse trips due to budget exhaustion."""
    def __init__(self, message: str, budget_usd: float = 0.0, spent_usd: float = 0.0):
        super().__init__(message)
        self.budget_usd = budget_usd
        self.spent_usd = spent_usd


class CircuitBreakerOpenError(AgentOSException):
    """Raised when a circuit breaker opens to prevent cascading failures."""
    def __init__(self, message: str, key: str | None = None):
        super().__init__(message)
        self.key = key
