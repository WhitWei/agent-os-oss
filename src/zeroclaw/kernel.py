"""
AgentOS Kernel — Agent OS MVP Runtime.
========================================

The kernel is the central orchestrator: it receives normalized messages from
channel adapters, enforces autonomy policy, and routes through the MCP
governance gateway for safe execution.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Optional

from zeroclaw.config import AppConfig
from zeroclaw.exceptions import (
    AgentOSException,
    PolicyViolationError,
)

logger = logging.getLogger(__name__)


class ZeroClawKernel:
    """Core orchestrator for the Agent OS runtime.

    Lifecycle:
    1. Receive ChannelMessage from an adapter (Feishu, CLI, etc.)
    2. Enforce autonomy policy (path access, command allowlist, quotas)
    3. Route actionable commands through the MCP governance gateway
    4. Return response to the adapter for delivery
    """

    def __init__(
        self,
        config: AppConfig,
        write_gate: Optional[object] = None,
        autonomy_policy: Optional[object] = None,
        firewall: Optional[object] = None,
        circuit_breaker: Optional[object] = None,
        billing_fuse: Optional[object] = None,
    ) -> None:
        self._config = config
        self._write_gate = write_gate  # WriteGate from governance layer
        self._autonomy_policy = autonomy_policy  # AutonomyPolicy from policies layer
        self._session_count = 0

        # Resolve OTel Tracer
        from observability.telemetry import get_tracer
        self._tracer = get_tracer()

        # Initialize Security hooks (WO-A2.3 & 决策5)
        from security.firewall import SemanticFirewall
        from security.circuit_breaker import CircuitBreaker
        from security.billing_fuse import BillingFuse

        self._firewall = firewall or SemanticFirewall(tracer=self._tracer)
        self._circuit_breaker = circuit_breaker or CircuitBreaker()
        self._billing_fuse = billing_fuse or BillingFuse()

        # Ensure write_gate is aware of autonomy_policy and tracer
        if self._write_gate and hasattr(self._write_gate, "_autonomy_policy") and getattr(self._write_gate, "_autonomy_policy") is None:
            self._write_gate._autonomy_policy = self._autonomy_policy
        if self._write_gate and hasattr(self._write_gate, "_tracer") and getattr(self._write_gate, "_tracer") is None:
            self._write_gate._tracer = self._tracer

        logger.info(
            "ZeroClaw kernel v%s initialized (policy=%s, governance=%s, security_hooks=active)",
            config.kernel.version,
            "enabled" if autonomy_policy else "disabled",
            "enabled" if write_gate else "disabled",
        )

    async def wake_up(self, message: ChannelMessage) -> ChannelResponse:
        """Main entry point: process an incoming channel message.

        Args:
            message: Normalized message from any channel adapter.

        Returns:
            ChannelResponse with the result/error to send back.
        """
        self._session_count += 1
        session_id = self._session_count
        text = message.text.strip()

        logger.info(
            "Session #%d: processing message from channel=%s user=%s",
            session_id,
            message.channel,
            message.sender_name,
        )

        from zeroclaw.exceptions import (
            SecurityInterceptError,
            CircuitBreakerOpenError,
            BillingFuseTrippedError,
        )

        try:
            # ── Pre-Dispatch Hook 1: Semantic Firewall ──
            self._firewall.scan(text, input_type="user_prompt", source=message.sender_name)

            # ── Pre-Dispatch Hook 2: Retry Dedup Circuit Breaker ──
            if self._circuit_breaker.is_open(text):
                raise CircuitBreakerOpenError(
                    f"Circuit is open for input pattern due to repeated failures.",
                    key=text
                )

            # ── Pre-Dispatch Hook 3: Enforce Autonomy Policy ──
            if self._autonomy_policy:
                await self._enforce_policy(message)

            # ── Step 2: Process the message ──
            result = await self._process_message(message)

            # ── Post-Dispatch Hook: Billing Fuse Usage Tracking ──
            if any(keyword in text.lower() for keyword in ["validate", "verify", "write", "execute"]):
                from security.billing_fuse import TokenUsage
                self._billing_fuse.record_usage(
                    TokenUsage(
                        prompt_tokens=800,
                        completion_tokens=400,
                        model="claude-sonnet-4",
                    )
                )

            return ChannelResponse(
                text=result,
                channel=message.channel,
                metadata={
                    "session_id": session_id,
                    "status": "ok",
                },
            )

        except PolicyViolationError as exc:
            logger.warning(
                "Session #%d: policy violation — %s", session_id, exc
            )
            return ChannelResponse(
                text=f"⛔ Operation blocked by autonomy policy: {exc}",
                channel=message.channel,
                metadata={"session_id": session_id, "status": "blocked"},
                error=str(exc),
            )

        except CircuitBreakerOpenError as exc:
            logger.warning(
                "Session #%d: circuit breaker blocked call — %s", session_id, exc
            )
            return ChannelResponse(
                text=f"🔌 Circuit breaker active: {exc}",
                channel=message.channel,
                metadata={"session_id": session_id, "status": "tripped"},
                error=str(exc),
            )

        except SecurityInterceptError as exc:
            logger.warning(
                "Session #%d: security firewall blocked call — %s", session_id, exc
            )
            return ChannelResponse(
                text=f"🛡️ Security intercept: {exc}",
                channel=message.channel,
                metadata={"session_id": session_id, "status": "intercepted"},
                error=str(exc),
            )

        except BillingFuseTrippedError as exc:
            logger.warning(
                "Session #%d: billing budget exceeded — %s", session_id, exc
            )
            return ChannelResponse(
                text=f"💸 Billing limit reached: {exc}",
                channel=message.channel,
                metadata={"session_id": session_id, "status": "exhausted"},
                error=str(exc),
            )

        except AgentOSException as exc:
            # Record failure in the circuit breaker to enable de-duplication
            self._circuit_breaker.record_failure(
                tool_name=text,
                parameters={"input": text},
                error_type=exc.__class__.__name__,
            )
            logger.error(
                "Session #%d: agent OS error — %s", session_id, exc
            )
            return ChannelResponse(
                text=f"❌ Agent OS error: {exc}",
                channel=message.channel,
                metadata={"session_id": session_id, "status": "error"},
                error=str(exc),
            )

        except Exception as exc:
            # Record failure in the circuit breaker to enable de-duplication
            self._circuit_breaker.record_failure(
                tool_name=text,
                parameters={"input": text},
                error_type=exc.__class__.__name__,
            )
            logger.exception(
                "Session #%d: unexpected error", session_id
            )
            return ChannelResponse(
                text=f"💥 Unexpected error: {exc}",
                channel=message.channel,
                metadata={"session_id": session_id, "status": "error"},
                error=str(exc),
            )

    async def _enforce_policy(self, message: ChannelMessage) -> None:
        """Run autonomy policy checks on the incoming message."""
        policy = self._autonomy_policy

        # Check session is still alive
        policy.check_session_alive()

        # If the message looks like a shell command, check it
        text = message.text.strip()
        if self._looks_like_command(text):
            policy.check_command(text)

        logger.debug("Policy checks passed for session")

    async def _process_message(self, message: ChannelMessage) -> str:
        """Process the message through the governance pipeline.

        For the MVP, this is a simple intent parser. In production,
        this would use an LLM to parse the user's intent and map it
        to governance gate operations.
        """
        text = message.text.strip()

        # Simple intent detection for MVP demo
        text_lower = text.lower()

        if "schema" in text_lower and "it-asset" in text_lower:
            if self._write_gate:
                schema = self._write_gate.get_domain_schema("it-asset-mgmt")
                return self._format_schema_response(schema)
            return "Governance gateway not configured — cannot retrieve schema."

        if "validate" in text_lower or "verify" in text_lower:
            return (
                "To validate data, use the MCP tool `verify_shacl_compliance` "
                "with your RDF data in Turtle format."
            )

        if "write" in text_lower or "execute" in text_lower:
            return (
                "To execute a governed write, first call "
                "`verify_shacl_compliance` to get a validation nonce, "
                "then call `execute_governed_write` with the nonce."
            )

        # Default response
        return (
            f"👋 Hello {message.sender_name}! "
            f"I'm ZeroClaw v{self._config.kernel.version}. "
            f"Available domains: {self._list_domains()}. "
            f"Try asking for a schema, validating data, or executing a write."
        )

    def _list_domains(self) -> str:
        """List available ontology domains."""
        domains = [d.name for d in self._config.ontology.domains]
        return ", ".join(domains) if domains else "none configured"

    def _format_schema_response(self, schema: dict) -> str:
        """Format a schema definition as a readable text response."""
        lines = [f"📋 Schema for domain: {schema.get('domain', '?')}"]
        classes = schema.get("classes", [])
        if classes:
            lines.append("\n🏷️ Classes:")
            for cls in classes[:10]:
                label = cls.get("label") or cls.get("iri", "?")
                comment = cls.get("comment", "")
                lines.append(f"  - {label}" + (f" — {comment}" if comment else ""))

        shapes = schema.get("shacl_shapes", [])
        if shapes:
            lines.append("\n✅ SHACL Constraints:")
            for shape in shapes[:5]:
                target = shape.get("target_class", "?").split("#")[-1]
                lines.append(f"  - {target}: {len(shape.get('properties', []))} required fields")

        return "\n".join(lines)

    @staticmethod
    def _looks_like_command(text: str) -> bool:
        """Heuristic: does this message look like a shell command?

        Returns True only if the message starts with a known command-like pattern:
        - Starts with `/` or `./` (paths)
        - Contains `--` flag or `-` single-char flag with space
        - Matches a known system command pattern (single lowercase word
          followed by arguments that include flags or paths)

        This is intentionally narrow to avoid false positives on natural
        language messages like "hello world" or "how are you".
        """
        if not text or not text.strip():
            return False

        first_token = text.split()[0] if text.split() else ""
        rest = text[len(first_token):].strip()

        # Path-based commands: starts with / or ./
        if first_token.startswith("/") or first_token.startswith("./"):
            return True

        # Must be a single lowercase word at least 2 chars
        if not (first_token and len(first_token) >= 2 and
                " " not in first_token and
                first_token.islower()):
            return False

        # Strong signal: contains a flag like --help, -v, -rf
        if rest and ("--" in rest or (rest.startswith("-") and len(rest) >= 3)):
            return True

        # Strong signal: reference to a file path or pipe
        if rest and any(pattern in rest for pattern in ["/", "|", ">", "<", "&"]):
            return True

        # Otherwise, it's probably natural language (e.g., "hello world").
        # Single-word messages without flags/paths are not treated as commands.
        return False


# ── Message / Response Data Classes ──


@dataclass
class ChannelMessage:
    """Normalized message received from any channel adapter."""

    text: str
    sender_id: str
    sender_name: str
    channel: str  # "feishu", "cli", etc.
    message_id: str = ""
    metadata: dict = field(default_factory=dict)


@dataclass
class ChannelResponse:
    """Normalized response to send back through a channel adapter."""

    text: str
    channel: str
    metadata: dict = field(default_factory=dict)
    error: Optional[str] = None
