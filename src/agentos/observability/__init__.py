"""Observability package — OpenTelemetry + Langfuse integration.

Provides:
- ``init_telemetry()`` — set up OpenTelemetry with OTLP exporter
- ``get_tracer()`` — get a tracer for manual instrumentation
- ``shutdown_telemetry()`` — graceful shutdown (flush + close)
- ``init_langfuse()`` — initialize Langfuse client for score tracking
"""

from __future__ import annotations

from agentos.observability.telemetry import (
    TelemetryConfig,
    init_telemetry,
    get_tracer,
    shutdown_telemetry,
)
from agentos.observability.langfuse_integration import (
    LangfuseConfig,
    init_langfuse,
    get_langfuse,
    flush_langfuse,
)

__all__ = [
    "TelemetryConfig",
    "init_telemetry",
    "get_tracer",
    "shutdown_telemetry",
    "LangfuseConfig",
    "init_langfuse",
    "get_langfuse",
    "flush_langfuse",
]
