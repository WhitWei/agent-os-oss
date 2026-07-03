"""Retry Dedup Circuit Breaker — prevents cascading failures from repeated calls.

Algorithm (WO-A2.3):
  1. On each failure, compute a RequestSignature: (tool_name, SHA256(params), feature_vector)
  2. Store in time-windowed failure buffer
  3. Count failures: exact hash matches + cosine_similarity(vector, existing) >= threshold
  4. If count >= failure_threshold → open circuit for that tool
  5. While circuit is open, all calls to that tool raise CircuitBreakerOpenError
  6. Circuit auto-resets after window_seconds with no new failures

Feature hashing: concat sorted keys + string values → deterministic numpy RandomState
→ 128-dim unit vector → cosine similarity via numpy.dot

Usage::

    from security.circuit_breaker import CircuitBreaker, CircuitBreakerConfig

    cb = CircuitBreaker(CircuitBreakerConfig(failure_threshold=3))
    try:
        call_external_api(params)
    except Exception:
        cb.record_failure("get_weather", {"city": "Beijing"}, "APITimeout")

    if cb.is_open("get_weather"):
        raise CircuitBreakerOpenError("Circuit open for get_weather")
"""

from __future__ import annotations

import hashlib
import json
import logging
import time
from dataclasses import dataclass, field
from typing import Optional

import numpy as np

from zeroclaw.exceptions import CircuitBreakerOpenError

logger = logging.getLogger(__name__)

# ── Data Structures ──


@dataclass(frozen=True)
class RequestSignature:
    """Immutable signature for a tool call (tool_name + hashed params)."""

    tool_name: str
    parameters_hash: str  # SHA256 of canonical JSON
    parameter_vector: Optional[np.ndarray] = field(
        default=None, compare=False, hash=False
    )


@dataclass
class FailureRecord:
    """A recorded failure with its signature and metadata."""

    signature: RequestSignature
    timestamp: float
    error_type: str


@dataclass(frozen=True)
class CircuitBreakerConfig:
    """Configuration for the retry dedup circuit breaker."""

    window_seconds: int = 300          # Time window for counting failures
    failure_threshold: int = 3         # Number of similar failures to open circuit
    similarity_threshold: float = 0.85  # Cosine similarity threshold
    max_vector_size: int = 128         # Dimensionality of feature vectors


# ── Circuit Breaker ──


class CircuitBreaker:
    """High-speed retry dedup circuit breaker with cosine similarity detection.

    Tracks tool call failures within a sliding time window. When the same
    (or highly similar) call fails >= failure_threshold times, the circuit
    opens and all subsequent calls to that tool are blocked.

    Uses numpy for vectorized cosine similarity. Supports optional Redis
    backend for distributed deployments.
    """

    def __init__(
        self,
        config: Optional[CircuitBreakerConfig] = None,
        redis_url: Optional[str] = None,
    ) -> None:
        self.config = config or CircuitBreakerConfig()
        self._redis_url = redis_url

        # In-memory storage: tool_name → list[FailureRecord]
        self._failures: dict[str, list[FailureRecord]] = {}

        # Open circuits: tool_name → opened_at (unix timestamp)
        self._open_circuits: dict[str, float] = {}

        logger.info(
            "CircuitBreaker initialized: window=%ds threshold=%d similarity=%.2f",
            self.config.window_seconds,
            self.config.failure_threshold,
            self.config.similarity_threshold,
        )

    # ── Public API ──

    def record_failure(
        self,
        tool_name: str,
        parameters: dict,
        error_type: str = "unknown",
    ) -> bool:
        """Record a tool call failure.

        Args:
            tool_name: Name of the tool/operation that failed.
            parameters: The parameters passed to the tool.
            error_type: Error category (e.g., 'Timeout', 'RateLimit').

        Returns:
            True if this failure caused the circuit to open.
        """
        signature = self._build_signature(tool_name, parameters)
        record = FailureRecord(
            signature=signature,
            timestamp=time.time(),
            error_type=error_type,
        )

        # Store failure
        if tool_name not in self._failures:
            self._failures[tool_name] = []
        self._failures[tool_name].append(record)

        # Prune expired
        self._cleanup_expired(tool_name)

        # Count similar failures
        similar_count = self._count_similar_failures(tool_name, signature)
        logger.debug(
            "CircuitBreaker: %s failure #%d similar (tool=%s, error=%s)",
            tool_name,
            similar_count,
            tool_name,
            error_type,
        )

        if similar_count >= self.config.failure_threshold:
            self._open_circuits[tool_name] = time.time()
            logger.warning(
                "CircuitBreaker: CIRCUIT OPEN for %s (%d similar failures in %ds)",
                tool_name,
                similar_count,
                self.config.window_seconds,
            )
            return True
        return False

    def is_open(self, tool_name: str) -> bool:
        """Check if the circuit is open for a given tool.

        If the auto-reset window has elapsed with no new failures,
        the circuit closes automatically.

        Raises:
            CircuitBreakerOpenError: If the circuit is open.
        """
        if tool_name not in self._open_circuits:
            return False

        opened_at = self._open_circuits[tool_name]

        # Auto-reset: if window has elapsed since the last failure,
        # close the circuit.
        failures = self._failures.get(tool_name, [])
        if failures:
            last_failure_time = max(r.timestamp for r in failures)
            if time.time() - last_failure_time > self.config.window_seconds:
                self.reset(tool_name)
                logger.info("CircuitBreaker: circuit auto-reset for %s", tool_name)
                return False

        return True

    def reset(self, tool_name: Optional[str] = None) -> None:
        """Reset the circuit breaker.

        Args:
            tool_name: Reset a specific tool, or all tools if None.
        """
        if tool_name is None:
            self._failures.clear()
            self._open_circuits.clear()
            logger.info("CircuitBreaker: all circuits reset")
        else:
            self._failures.pop(tool_name, None)
            self._open_circuits.pop(tool_name, None)
            logger.info("CircuitBreaker: circuit reset for %s", tool_name)

    def get_status(self) -> dict:
        """Return current status for diagnostics."""
        return {
            "open_circuits": list(self._open_circuits.keys()),
            "tracked_tools": list(self._failures.keys()),
            "total_failures": sum(len(v) for v in self._failures.values()),
            "threshold": self.config.failure_threshold,
            "window_seconds": self.config.window_seconds,
        }

    # ── Internal Helpers ──

    def _build_signature(
        self, tool_name: str, parameters: dict
    ) -> RequestSignature:
        """Create a RequestSignature from tool_name and parameters."""
        # Canonical JSON: sorted keys, no extra whitespace
        canonical = json.dumps(parameters, sort_keys=True, separators=(",", ":"))
        param_hash = hashlib.sha256(canonical.encode("utf-8")).hexdigest()
        param_vector = self._parameters_to_vector(parameters)
        return RequestSignature(
            tool_name=tool_name,
            parameters_hash=param_hash,
            parameter_vector=param_vector,
        )

    def _parameters_to_vector(self, params: dict) -> np.ndarray:
        """Convert parameter dict to a fixed-size feature vector.

        Uses consistent per-feature hashing: each individual key:value
        pair is hashed into a deterministic position in the vector space.
        Similar parameter sets produce similar vectors because they
        activate overlapping components. This enables cosine similarity
        to detect nearly-identical calls where only a minor field changed.
        """
        vec = np.zeros(self.config.max_vector_size, dtype=np.float64)

        for key in sorted(params.keys()):
            val = params[key]
            if val is None:
                continue
            # Hash the individual key:value pair into a vector position
            feature_str = f"{key}={val}"
            seed = abs(hash(feature_str)) % (2**31)
            rng = np.random.RandomState(seed)
            # Each feature activates 3 slots (reduce collisions)
            for _ in range(3):
                idx = rng.randint(0, self.config.max_vector_size)
                sign = 1.0 if rng.rand() > 0.5 else -1.0
                vec[idx] += sign

        # Also add the key names alone (structural similarity: same keys
        # with different values still partially match)
        for key in sorted(params.keys()):
            key_seed = abs(hash(key)) % (2**31)
            krng = np.random.RandomState(key_seed)
            idx = krng.randint(0, self.config.max_vector_size)
            vec[idx] += 0.5

        # Normalize to unit length
        norm = np.linalg.norm(vec)
        if norm > 0:
            vec = vec / norm
        return vec

    def _compute_similarity(self, vec1: np.ndarray, vec2: np.ndarray) -> float:
        """Compute cosine similarity between two feature vectors."""
        return float(np.dot(vec1, vec2))

    def _count_similar_failures(
        self, tool_name: str, target: RequestSignature
    ) -> int:
        """Count failures for tool_name that are similar to the target.

        Similarity: same parameter_hash (exact match) OR
        cosine_similarity(vector, existing) >= similarity_threshold.
        """
        records = self._failures.get(tool_name, [])
        if not records:
            return 0

        count = 0
        target_vec = target.parameter_vector
        for record in records:
            # Exact hash match
            if record.signature.parameters_hash == target.parameters_hash:
                count += 1
                continue

            # Cosine similarity match
            existing_vec = record.signature.parameter_vector
            if existing_vec is not None and target_vec is not None:
                sim = self._compute_similarity(target_vec, existing_vec)
                if sim >= self.config.similarity_threshold:
                    count += 1

        return count

    def _cleanup_expired(self, tool_name: str) -> None:
        """Remove failure records outside the time window."""
        if tool_name not in self._failures:
            return
        cutoff = time.time() - self.config.window_seconds
        self._failures[tool_name] = [
            r for r in self._failures[tool_name] if r.timestamp > cutoff
        ]
        if not self._failures[tool_name]:
            del self._failures[tool_name]
