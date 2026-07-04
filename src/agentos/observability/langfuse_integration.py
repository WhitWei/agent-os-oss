"""Langfuse integration for score tracking and non-span features.

While primary tracing goes through OpenTelemetry → OTLP collector → Langfuse,
the Langfuse SDK is used for:
- Score tracking (e.g., quality scores, safety scores)
- Dataset management
- Prompt management
- Direct event logging

Usage::

    from agentos.observability.langfuse_integration import init_langfuse, get_langfuse

    init_langfuse(LangfuseConfig(public_key="...", secret_key="..."))
    langfuse = get_langfuse()
    if langfuse:
        langfuse.score(trace_id="...", name="safety", value=0.95)
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Optional

logger = logging.getLogger(__name__)

_langfuse_client: Optional[object] = None
_langfuse_enabled: bool = False


@dataclass(frozen=True)
class LangfuseConfig:
    """Configuration for Langfuse SDK client.

    Memory safety settings:
    - flush_at: Max events before auto-flush (smaller = less memory, more network)
    - flush_interval_seconds: Auto-flush interval regardless of batch size
    - max_retries: Max send retries before dropping events (prevents infinite buildup)
    - request_timeout_seconds: HTTP request timeout
    """

    public_key: str = ""
    secret_key: str = ""
    host: str = "http://localhost:3000"
    enabled: bool = True
    release: str = "dev"
    environment: str = "development"

    # Batch & retry — prevent memory buildup when collector is down
    flush_at: int = 15          # Flush after 15 events (default in langfuse SDK)
    flush_interval_seconds: float = 5.0  # Flush every 5 sec regardless
    max_retries: int = 3         # Drop events after 3 retries (don't build up infinitely)
    request_timeout_seconds: float = 10.0


def init_langfuse(config: Optional[LangfuseConfig] = None) -> bool:
    """Initialize the Langfuse SDK client.

    Args:
        config: Langfuse configuration. Uses defaults if None.

    Returns:
        True if Langfuse was successfully initialized, False otherwise.
    """
    global _langfuse_client, _langfuse_enabled

    if config is None:
        config = LangfuseConfig()

    if not config.enabled:
        logger.info("Langfuse integration disabled.")
        _langfuse_enabled = False
        return False

    if not config.public_key or not config.secret_key:
        logger.info(
            "Langfuse credentials not configured — skipping initialization. "
            "Set LANGFUSE_PUBLIC_KEY and LANGFUSE_SECRET_KEY."
        )
        _langfuse_enabled = False
        return False

    try:
        from langfuse import Langfuse

        _langfuse_client = Langfuse(
            public_key=config.public_key,
            secret_key=config.secret_key,
            host=config.host,
            release=config.release,
            environment=config.environment,
            flush_at=config.flush_at,
            flush_interval=config.flush_interval_seconds,
            timeout=int(config.request_timeout_seconds),
        )
        _langfuse_enabled = True
        logger.info(
            "Langfuse client initialized: host=%s release=%s",
            config.host,
            config.release,
        )
        return True

    except ImportError:
        logger.warning("langfuse package not installed. Run: pip install langfuse>=2.0")
        return False
    except Exception as exc:
        logger.warning("Failed to initialize Langfuse client: %s", exc)
        return False


def get_langfuse() -> Optional[object]:
    """Get the initialized Langfuse client, or None if not available."""
    if not _langfuse_enabled or _langfuse_client is None:
        return None
    return _langfuse_client


def flush_langfuse() -> None:
    """Flush any pending Langfuse events."""
    global _langfuse_client
    if _langfuse_client is not None:
        try:
            _langfuse_client.flush()
            logger.debug("Langfuse events flushed.")
        except Exception as exc:
            logger.warning("Error flushing Langfuse: %s", exc)
