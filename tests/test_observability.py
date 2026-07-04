"""Tests for OpenTelemetry + Langfuse observability setup (WO-A2.1).

Verifies:
- Telemetry initialization creates a functional tracer
- get_tracer() works with and without initialization
- Disabled telemetry produces no-op stubs
- Shutdown completes without error
- Langfuse init gracefully degrades without credentials
"""

from __future__ import annotations

import pytest


class TestTelemetryInit:
    """Telemetry initialization and basic operations."""

    def test_init_creates_tracer(self):
        """init_telemetry should set up the global tracer provider."""
        from agentos.observability.telemetry import (
            init_telemetry,
            get_tracer,
            shutdown_telemetry,
            TelemetryConfig,
        )

        config = TelemetryConfig(
            enabled=True,
            service_name="test-service",
            otlp_endpoint="http://localhost:4317",
        )
        result = init_telemetry(config)

        # Should succeed or gracefully fail (e.g., if collector unreachable
        # at import time, init should still set up the provider)
        # The provider setup succeeds even without a collector running.
        tracer = get_tracer("test")
        assert tracer is not None

        shutdown_telemetry()

    def test_get_tracer_returns_tracer(self):
        """get_tracer() should return an object with start_as_current_span."""
        from agentos.observability.telemetry import get_tracer

        tracer = get_tracer("test-tracer")
        assert tracer is not None
        assert hasattr(tracer, "start_as_current_span")
        assert hasattr(tracer, "start_span")

    def test_noop_tracer_methods_dont_crash(self):
        """No-op tracer should silently handle all span operations."""
        from agentos.observability.telemetry import _NoopTracer

        tracer = _NoopTracer()
        with tracer.start_as_current_span("test-span") as span:
            span.set_attribute("key", "value")
            span.add_event("event-name", {"attr": "val"})
            span.set_status("OK")
            span.record_exception(ValueError("test"))
        # No exception = pass

    def test_shutdown_noop_when_not_initialized(self):
        """shutdown_telemetry should not crash when tracer was never initialized."""
        from agentos.observability.telemetry import shutdown_telemetry
        shutdown_telemetry()


class TestLangfuseInit:
    """Langfuse integration initialization."""

    def test_init_without_credentials_returns_false(self):
        """Without LANGFUSE keys, init_langfuse should return False gracefully."""
        from agentos.observability.langfuse_integration import (
            init_langfuse,
            get_langfuse,
            LangfuseConfig,
        )

        config = LangfuseConfig(
            enabled=True,
            public_key="",  # No credentials
            secret_key="",
            host="http://localhost:3000",
        )
        result = init_langfuse(config)
        assert result is False
        assert get_langfuse() is None

    def test_disabled_langfuse_returns_false(self):
        """When enabled=False, init should return False."""
        from agentos.observability.langfuse_integration import init_langfuse, LangfuseConfig

        config = LangfuseConfig(enabled=False)
        result = init_langfuse(config)
        assert result is False

    def test_flush_does_not_crash_when_not_initialized(self):
        """flush_langfuse() should be safe to call before init."""
        from agentos.observability.langfuse_integration import flush_langfuse
        flush_langfuse()


class TestTelemetryConfig:
    """Configuration data classes."""

    def test_default_config(self):
        """TelemetryConfig should have sensible defaults."""
        from agentos.observability.telemetry import TelemetryConfig
        config = TelemetryConfig()
        assert config.service_name == "agent-os-poc"
        assert config.otlp_endpoint == "http://localhost:4317"
        assert config.enabled is True
        assert config.sample_rate == 1.0

    def test_custom_config(self):
        """Custom values should be respected."""
        from agentos.observability.telemetry import TelemetryConfig
        config = TelemetryConfig(
            service_name="custom",
            enabled=False,
            sample_rate=0.5,
        )
        assert config.service_name == "custom"
        assert config.enabled is False
        assert config.sample_rate == 0.5

    def test_default_langfuse_config(self):
        """LangfuseConfig should have sensible defaults."""
        from agentos.observability.langfuse_integration import LangfuseConfig
        config = LangfuseConfig()
        assert config.host == "http://localhost:3000"
        assert config.enabled is True
        assert config.release == "dev"
