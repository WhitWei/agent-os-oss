"""OpenTelemetry setup — tracer provider, OTLP exporter, span helpers.

Configures the global TracerProvider with BatchSpanProcessor exporting
to an OTLP collector (gRPC). The collector then routes traces to Langfuse.

Usage::

    from agentos.observability.telemetry import init_telemetry, get_tracer, TelemetryConfig

    config = TelemetryConfig(service_name="agent-os-poc")
    init_telemetry(config)

    tracer = get_tracer()
    with tracer.start_as_current_span("my-operation"):
        ...
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Optional

logger = logging.getLogger(__name__)

# Lazy imports — OpenTelemetry is heavy; only import when actually used.
_OTEL_IMPORTED = False
_tracer_provider = None


def _ensure_otel_imported() -> bool:
    """Import OpenTelemetry modules; returns True if available."""
    global _OTEL_IMPORTED
    if _OTEL_IMPORTED:
        return True
    try:
        from opentelemetry import trace  # noqa: F811
        from opentelemetry.sdk.trace import TracerProvider
        from opentelemetry.sdk.resources import Resource, SERVICE_NAME, SERVICE_VERSION
        from opentelemetry.sdk.trace.export import BatchSpanProcessor
        from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import OTLPSpanExporter

        _OTEL_IMPORTED = True
        return True
    except ImportError:
        logger.warning(
            "OpenTelemetry SDK not installed. Install it: "
            "pip install opentelemetry-sdk opentelemetry-exporter-otlp"
        )
        return False


# ── Configuration ──


@dataclass(frozen=True)
class TelemetryConfig:
    """Configuration for OpenTelemetry tracing."""

    service_name: str = "agent-os-poc"
    service_version: str = "0.1.1"
    otlp_endpoint: str = "http://localhost:4317"
    enabled: bool = True
    sample_rate: float = 1.0  # 0.0 → drop all, 1.0 → sample all


# ── Public API ──


def init_telemetry(config: Optional[TelemetryConfig] = None) -> bool:
    """Initialize OpenTelemetry tracing with OTLP exporter.

    Args:
        config: Telemetry configuration. Uses defaults if None.

    Returns:
        True if telemetry was successfully initialized, False otherwise.
    """
    global _tracer_provider

    if config is None:
        config = TelemetryConfig()

    if not config.enabled:
        logger.info("Telemetry is disabled — no traces will be exported.")
        return False

    if not _ensure_otel_imported():
        return False

    try:
        from opentelemetry import trace
        from opentelemetry.sdk.trace import TracerProvider
        from opentelemetry.sdk.resources import Resource, SERVICE_NAME, SERVICE_VERSION
        from opentelemetry.sdk.trace.export import BatchSpanProcessor
        from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import OTLPSpanExporter
        from opentelemetry.sdk.trace.sampling import TraceIdRatioBased

        # Build resource attributes
        resource = Resource.create({
            SERVICE_NAME: config.service_name,
            SERVICE_VERSION: config.service_version,
        })

        # Create exporter
        exporter = OTLPSpanExporter(
            endpoint=config.otlp_endpoint,
            insecure=True,  # Local dev — no TLS for collector
        )

        # Create sampler
        sampler = TraceIdRatioBased(config.sample_rate)

        # Create provider
        provider = TracerProvider(
            resource=resource,
            sampler=sampler,
        )
        provider.add_span_processor(BatchSpanProcessor(exporter))

        # Set as global
        trace.set_tracer_provider(provider)
        _tracer_provider = provider

        logger.info(
            "OpenTelemetry tracing initialized: service=%s endpoint=%s rate=%.2f",
            config.service_name,
            config.otlp_endpoint,
            config.sample_rate,
        )
        return True

    except Exception as exc:
        logger.warning("Failed to initialize OpenTelemetry: %s", exc)
        return False


def get_tracer(name: str = "agent-os-poc") -> object:
    """Get an OpenTelemetry tracer for manual instrumentation.

    Args:
        name: Tracer name (typically the instrumenting library/module).

    Returns:
        An OpenTelemetry Tracer, or a no-op stub if telemetry is not initialized.
    """
    if not _ensure_otel_imported():
        return _NoopTracer()

    try:
        from opentelemetry import trace
        return trace.get_tracer(name)
    except Exception:
        return _NoopTracer()


def shutdown_telemetry() -> None:
    """Gracefully shut down the tracer provider (flush + close)."""
    global _tracer_provider
    if _tracer_provider is not None:
        try:
            _tracer_provider.shutdown()
            logger.info("OpenTelemetry tracing shut down.")
        except Exception as exc:
            logger.warning("Error shutting down telemetry: %s", exc)
        _tracer_provider = None


# ── No-op stub ──


class _NoopTracer:
    """No-op tracer that silently drops all span operations.

    Used when OpenTelemetry SDK is not installed or telemetry is disabled,
    so application code can call tracer methods without checking.
    """

    def start_as_current_span(self, name: str, *args, **kwargs):
        return _NoopSpan()

    def start_span(self, name: str, *args, **kwargs):
        return _NoopSpan()


class _NoopSpan:
    """No-op span context manager."""

    def __enter__(self):
        return self

    def __exit__(self, *args):
        pass

    def set_attribute(self, key: str, value: str):
        pass

    def add_event(self, name: str, attributes: dict | None = None):
        pass

    def set_status(self, status, description: str = ""):
        pass

    def record_exception(self, exception, attributes=None):
        pass

    def end(self):
        pass
