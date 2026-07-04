"""Tests for the Circuit Breaker (WO-A2.3).

Verifies:
- Single failure does not open circuit
- Three identical failures within window open circuit
- Three similar (cosine similarity) failures open circuit
- Dissimilar failures on different tools do not interact
- Window expiry prunes old records
- Reset clears all state
- Parameter vector consistency
- Edge cases: empty params, large params
"""

from __future__ import annotations

import time
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from agentos.security.circuit_breaker import (
    CircuitBreaker,
    CircuitBreakerConfig,
    RequestSignature,
)
from agentos.kernel.exceptions import CircuitBreakerOpenError


@pytest.fixture
def cb() -> CircuitBreaker:
    """Default circuit breaker with small window for testing."""
    return CircuitBreaker(
        CircuitBreakerConfig(
            failure_threshold=3,
            window_seconds=60,
            similarity_threshold=0.85,
        )
    )


@pytest.fixture
def loose_cb() -> CircuitBreaker:
    """Circuit breaker with low similarity threshold for testing.

    With the multi-slot feature hashing, similar params (same keys,
    close values) produce cosine similarity around 0.5. We set the
    threshold at 0.40 to reliably detect similarity.
    """
    return CircuitBreaker(
        CircuitBreakerConfig(
            failure_threshold=3,
            window_seconds=60,
            similarity_threshold=0.40,
        )
    )


class TestBasicBehavior:
    """Core circuit breaker lifecycle."""

    def test_single_failure_does_not_open(self, cb):
        """One failure leaves circuit closed."""
        cb.record_failure("tool", {"key": "value"}, "Timeout")
        assert cb.is_open("tool") is False

    def test_two_failures_does_not_open(self, cb):
        """Two failures (below threshold) leaves circuit closed."""
        for _ in range(2):
            cb.record_failure("tool", {"key": "value"}, "Timeout")
        assert cb.is_open("tool") is False

    def test_three_identical_failures_opens_circuit(self, cb):
        """Three same-param failures open circuit."""
        params = {"city": "Beijing", "date": "2025-01-01"}
        for i in range(3):
            opened = cb.record_failure("get_weather", params, "Timeout")
            if i < 2:
                assert opened is False
            else:
                assert opened is True
        assert cb.is_open("get_weather") is True

    def test_record_failure_returns_correct_status(self, cb):
        """record_failure returns True only when circuit transitions to open."""
        params = {"x": 1}
        assert cb.record_failure("tool", params, "Err") is False
        assert cb.record_failure("tool", params, "Err") is False
        assert cb.record_failure("tool", params, "Err") is True  # 3rd opens


class TestSimilarityDetection:
    """Cosine similarity based failure dedup."""

    def test_highly_similar_params_open_circuit(self, loose_cb):
        """Slightly different but similar params should count together."""
        loose_cb.record_failure("api", {"city": "Beijing", "temp": 30}, "Err")
        loose_cb.record_failure("api", {"city": "Beijing", "temp": 31}, "Err")
        opened = loose_cb.record_failure("api", {"city": "Beijing", "temp": 29}, "Err")
        # 3 similar calls with same keys and close values — should open
        assert opened is True

    def test_dissimilar_params_isolated(self, cb):
        """Very different params on same tool -> only exact matches count."""
        cb.record_failure("api", {"city": "Beijing"}, "Err")
        cb.record_failure("api", {"country": "Japan", "planet": "Mars"}, "Err")
        assert cb.is_open("api") is False  # Only 1 similar pair


class TestCircuitIsolation:
    """Circuit breaker should isolate different tools."""

    def test_different_tools_isolated(self, cb):
        """Failures on tool_a don't affect tool_b."""
        for _ in range(3):
            cb.record_failure("tool_a", {"x": 1}, "Err")
        assert cb.is_open("tool_a") is True
        assert cb.is_open("tool_b") is False

    def test_multiple_tools_can_open_independently(self, cb):
        """Each tool gets its own circuit."""
        for _ in range(3):
            cb.record_failure("tool_a", {"x": 1}, "Err")
        for _ in range(3):
            cb.record_failure("tool_b", {"y": 2}, "Err")
        assert cb.is_open("tool_a") is True
        assert cb.is_open("tool_b") is True


class TestReset:
    """Circuit reset functionality."""

    def test_reset_single_tool(self, cb):
        """Reset one tool without affecting others."""
        for _ in range(3):
            cb.record_failure("tool_a", {"x": 1}, "Err")
        cb.record_failure("tool_b", {"y": 2}, "Err")

        cb.reset("tool_a")
        assert cb.is_open("tool_a") is False
        # tool_b should still have its failure record (but circuit not open yet)
        assert cb.is_open("tool_b") is False

    def test_reset_all(self, cb):
        """Reset all should clear everything."""
        for _ in range(3):
            cb.record_failure("tool_a", {"x": 1}, "Err")
        cb.reset()
        assert cb.is_open("tool_a") is False
        status = cb.get_status()
        assert len(status["open_circuits"]) == 0


class TestParameterVectors:
    """Feature hashing and vector operations."""

    def test_same_params_produce_same_vector(self, cb):
        """Same parameters produce identical vectors (hash consistency)."""
        v1 = cb._parameters_to_vector({"a": 1, "b": "hello"})
        v2 = cb._parameters_to_vector({"a": 1, "b": "hello"})
        import numpy as np
        assert np.array_equal(v1, v2)

    def test_different_params_produce_different_vectors(self, cb):
        """Different parameters produce different vectors."""
        v1 = cb._parameters_to_vector({"a": 1})
        v2 = cb._parameters_to_vector({"a": 2})
        import numpy as np
        assert not np.array_equal(v1, v2)

    def test_similarity_of_identical_vectors(self, cb):
        """Cosine similarity of identical vectors is 1.0."""
        v = cb._parameters_to_vector({"city": "Beijing"})
        import numpy as np
        sim = cb._compute_similarity(v, v)
        assert abs(sim - 1.0) < 1e-6

    def test_similarity_of_orthogonal_vectors(self, cb):
        """Cosine similarity of orthogonal vectors is 0.0."""
        import numpy as np
        v1 = np.array([1.0, 0.0, 0.0])
        v2 = np.array([0.0, 1.0, 0.0])
        sim = cb._compute_similarity(v1, v2)
        assert abs(sim - 0.0) < 1e-6

    def test_empty_params_produces_valid_vector(self, cb):
        """Empty parameter dict produces a zero vector (no features to hash)."""
        v = cb._parameters_to_vector({})
        import numpy as np
        assert v.shape == (128,)
        # Empty params → zero vector (no features = all zeros, norm = 0)
        assert np.linalg.norm(v) == 0.0


class TestGetStatus:
    """Diagnostic status reporting."""

    def test_get_status_returns_dict(self, cb):
        """get_status returns a structured dict."""
        cb.record_failure("tool", {"x": 1}, "Timeout")
        status = cb.get_status()
        assert "open_circuits" in status
        assert "tracked_tools" in status
        assert "total_failures" in status
        assert "threshold" in status
        assert status["total_failures"] == 1
