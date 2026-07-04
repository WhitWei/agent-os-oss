"""OpenTelemetry span attribute definitions for security events (WO-A2.4).

Defines custom span attributes for two security event types:

1. **Security Intercept Events** — emitted when the semantic firewall
   blocks a prompt injection or tainted input.

2. **SHACL Validation Error Events** — emitted when SHACL validation
   of RDF data fails (graph model constraint violation).

These attributes appear in the Langfuse dashboard as trace annotations,
enabling operators to visualize security incidents alongside normal
application traces.

Usage::

    from agentos.observability.security_dimensions import (
        SecuritySpanAttributes,
        SHACLSpanAttributes,
        emit_security_intercept_span,
        emit_shacl_validation_error_span,
    )

    # In firewall scan handler:
    emit_security_intercept_span(tracer, error, input_type="rag_chunk")

    # In SHACL validator:
    emit_shacl_validation_error_span(tracer, domain="it-asset-mgmt", report=report)
"""

from __future__ import annotations

import logging
from typing import Optional

logger = logging.getLogger(__name__)


# ── Span Attribute Keys ──


class SecuritySpanAttributes:
    """Custom OTel span attribute keys for security intercept events.

    These attributes are set on spans emitted when the semantic firewall
    blocks or flags suspicious input. They appear in Langfuse as trace
    attributes on the "Security Intercept" span.
    """

    # Core event identification
    EVENT_TYPE = "security.intercept.event.type"

    # What triggered the intercept (the matched pattern snippet)
    TRIGGER = "security.intercept.event.trigger"

    # Severity level: none / low / medium / high / critical
    SEVERITY = "security.intercept.event.severity"

    # Source of the tainted input: rag_chunk, api_response, user_prompt, etc.
    INPUT_TYPE = "security.intercept.event.input_type"

    # Number of threat patterns matched
    THREAT_COUNT = "security.intercept.event.threat_count"

    # First matched pattern (for quick dashboard scanning)
    FIRST_PATTERN = "security.intercept.event.first_pattern"


class SHACLSpanAttributes:
    """Custom OTel span attribute keys for SHACL validation error events.

    These attributes are set on spans emitted when a SHACL validation
    of RDF data fails, indicating a graph model constraint violation.
    """

    # Domain that failed validation
    DOMAIN = "shacl.validation_error.event.domain"

    # Number of SHACL violations found
    VIOLATION_COUNT = "shacl.validation_error.event.violation_count"

    # First violation focus node (the entity that failed)
    FOCUS_NODE = "shacl.validation_error.event.focus_node"

    # First violation result path (the property that failed)
    RESULT_PATH = "shacl.validation_error.event.result_path"

    # First violation message
    MESSAGE = "shacl.validation_error.event.message"

    # First violation severity (Violation, Warning, Info)
    RESULT_SEVERITY = "shacl.validation_error.event.result_severity"


# ── Span Emission Helpers ──


def emit_security_intercept_span(
    tracer: object,
    error: Exception,
    input_type: str = "unknown",
) -> None:
    """Emit an OpenTelemetry span for a security intercept event.

    Args:
        tracer: An OpenTelemetry Tracer instance.
        error: The SecurityInterceptError that was raised.
        input_type: Label for the tainted input source.
    """
    try:
        with tracer.start_as_current_span("security.intercept") as span:
            span.set_attribute(SecuritySpanAttributes.EVENT_TYPE, "intercept")
            span.set_attribute(SecuritySpanAttributes.INPUT_TYPE, input_type)

            # Extract error details if available
            trigger = getattr(error, "trigger", None)
            severity = getattr(error, "severity", "unknown")

            if trigger:
                span.set_attribute(SecuritySpanAttributes.TRIGGER, str(trigger)[:256])
            span.set_attribute(SecuritySpanAttributes.SEVERITY, str(severity))

            # Mark as error span
            span.set_status("ERROR", str(error)[:512])

            logger.debug(
                "Emitted security.intercept span: severity=%s input_type=%s",
                severity,
                input_type,
            )
    except Exception as exc:
        logger.debug("Failed to emit security intercept span: %s", exc)


def emit_shacl_validation_error_span(
    tracer: object,
    domain: str,
    report: object,  # SHACLValidationReport
) -> None:
    """Emit an OpenTelemetry span for a SHACL validation error.

    Args:
        tracer: An OpenTelemetry Tracer instance.
        domain: The ontology domain that failed validation.
        report: The SHACLValidationReport with violation details.
    """
    try:
        with tracer.start_as_current_span("shacl.validation_error") as span:
            span.set_attribute(SHACLSpanAttributes.DOMAIN, domain)

            # Extract report details
            violation_count = len(report.results) if hasattr(report, "results") else 0
            span.set_attribute(
                SHACLSpanAttributes.VIOLATION_COUNT, violation_count
            )

            # First violation details (for quick identification in dashboards)
            results = getattr(report, "results", [])
            if results:
                first = results[0]
                if first.get("focusNode"):
                    span.set_attribute(
                        SHACLSpanAttributes.FOCUS_NODE,
                        str(first["focusNode"])[:256],
                    )
                if first.get("resultPath"):
                    span.set_attribute(
                        SHACLSpanAttributes.RESULT_PATH,
                        str(first["resultPath"])[:256],
                    )
                if first.get("resultMessage"):
                    span.set_attribute(
                        SHACLSpanAttributes.MESSAGE,
                        str(first["resultMessage"])[:512],
                    )
                if first.get("severity"):
                    span.set_attribute(
                        SHACLSpanAttributes.RESULT_SEVERITY,
                        str(first["severity"]),
                    )

            # Mark as error span
            span.set_status(
                "ERROR",
                f"SHACL validation failed for domain '{domain}': "
                f"{violation_count} violation(s)",
            )

            logger.debug(
                "Emitted shacl.validation_error span: domain=%s violations=%d",
                domain,
                violation_count,
            )
    except Exception as exc:
        logger.debug("Failed to emit SHACL validation error span: %s", exc)
