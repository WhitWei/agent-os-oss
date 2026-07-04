"""LLM Driver — pluggable LLM interface for Agent OS Kernel.

Defines an abstract LLMDriver that the kernel calls for:
1. Intent classification: parse a user message → structured intent
2. RDF data generation: turn natural-language business data into RDF/Turtle
3. SOP routing: decide which SOP best matches a given request

Two concrete implementations provided:
- ClaudeDriver: uses the Anthropic SDK (model='claude-sonnet-4-20250514')
- FallbackDriver: keyword-pattern stub (mirrors current kernel MVP behaviour)

Usage::

    driver = ClaudeDriver(api_key="sk-...", model="claude-sonnet-4-20250514")
    intent = await driver.decide_intent("Assign a MacBook to Alice")
    # -> IntentResult(intent="create", domain="it-asset-mgmt", ...)
"""

from __future__ import annotations

import json
import logging
import os
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any

logger = logging.getLogger(__name__)


# ── Shared data types ──


@dataclass
class IntentResult:
    """Structured intent parsed from a user message."""

    intent: str = "unknown"  # "query_schema" | "validate" | "governed_write" | "start_sop" | "unknown"
    domain: str = ""
    sop_id: str = ""
    data: dict[str, Any] = field(default_factory=dict)
    raw_text: str = ""
    confidence: float = 0.0


@dataclass
class RDFGenerationResult:
    """Result of LLM-driven RDF data generation."""

    rdf_turtle: str = ""
    domain: str = ""
    valid: bool = False
    error: str = ""
    raw_response: str = ""


# ── Abstract driver ──


class LLMDriver(ABC):
    """Pluggable LLM driver for Agent OS Kernel.

    Subclasses must implement:
    - decide_intent: classify a user message into structured intent
    - generate_rdf: produce RDF/Turtle from natural language + schema
    - route_to_sop: pick the best SOP for a free-form request
    """

    @abstractmethod
    async def decide_intent(
        self,
        message: str,
        domains: list[str],
        sops: list[dict[str, Any]] | None = None,
    ) -> IntentResult:
        """Parse a user message into a structured intent.

        Args:
            message: The raw user message text.
            domains: Available ontology domain names.
            sops: Optional list of available SOP definitions (id, name, description).

        Returns:
            IntentResult with the best-matching intent.
        """
        ...

    @abstractmethod
    async def generate_rdf(
        self,
        domain: str,
        schema: dict[str, Any],
        user_description: str,
    ) -> RDFGenerationResult:
        """Generate RDF/Turtle data from a natural-language description.

        Args:
            domain: Target ontology domain name.
            schema: The domain schema (from get_domain_schema).
            user_description: Natural-language description of the data.

        Returns:
            RDFGenerationResult containing the Turtle string.
        """
        ...

    @abstractmethod
    async def route_to_sop(
        self,
        message: str,
        available_sops: list[dict[str, Any]],
    ) -> str:
        """Select the best SOP for a free-form user request.

        Args:
            message: The user's request text.
            available_sops: List of dicts with 'sop_id', 'name', 'description'.

        Returns:
            The sop_id of the best-matching SOP, or empty string if none match.
        """
        ...


# ── Claude (Anthropic SDK) implementation ──


class ClaudeDriver(LLMDriver):
    """LLM driver using Claude via the Anthropic SDK.

    Requires: pip install anthropic
    Falls back gracefully if the SDK is not installed.
    """

    INTENT_SYSTEM_PROMPT = """You are an intent classifier for an Agent governance platform.
Analyze the user's message and return a JSON object with:
- "intent": one of "query_schema", "validate", "governed_write", "start_sop", "unknown"
- "domain": the ontology domain mentioned (from the available list), or ""
- "sop_id": if intent is "start_sop", the best-matching SOP ID, or ""
- "confidence": float 0.0-1.0
- "reasoning": brief one-sentence explanation

Available domains: {domains}
Available SOPs: {sops}

Return ONLY valid JSON, no markdown fences."""

    RDF_SYSTEM_PROMPT = """You are a data engineer that translates natural-language business descriptions into RDF/Turtle format.
You are given a domain schema (OWL classes + SHACL constraints) and a description.
Generate valid Turtle RDF that conforms to the schema.

Domain: {domain}
Schema:
{schema_json}

Rules:
1. Use the exact property names and classes from the schema
2. Include all required fields (sh:minCount >= 1)
3. Use correct datatypes (xsd:string, xsd:decimal, xsd:dateTime, etc.)
4. Return ONLY the Turtle RDF block, no explanations
5. Use the ontology namespace http://agent-os.local/ontology/{domain}#
6. Prefix each resource with the domain-specific prefix

Example Turtle format:
@prefix ex: <http://agent-os.local/ontology/{domain}#> .
@prefix xsd: <http://www.w3.org/2001/XMLSchema#> .

ex:Resource-001 a ex:ResourceType ;
    ex:propertyName "value"^^xsd:string ;
    ex:anotherProperty 123.45^^xsd:decimal ."""

    SOP_SYSTEM_PROMPT = """You are a workflow routing agent. Given a user request and a list of available
Standard Operating Procedures (SOPs), select the single best-matching SOP.

Available SOPs:
{sops}

Return ONLY the sop_id string of the best-matching SOP, or empty string if none match.
No explanations, no markdown."""

    def __init__(
        self,
        api_key: str | None = None,
        model: str = "claude-sonnet-4-20250514",
        max_tokens: int = 4096,
    ):
        self._api_key = api_key or os.environ.get("ANTHROPIC_API_KEY", "")
        self._model = model
        self._max_tokens = max_tokens
        self._client: Any = None

    def _ensure_client(self) -> bool:
        """Lazy-init the Anthropic client. Returns True if ready."""
        if self._client is not None:
            return True
        try:
            import anthropic
            self._client = anthropic.AsyncAnthropic(api_key=self._api_key)
            logger.info("ClaudeDriver initialised (model=%s)", self._model)
            return True
        except ImportError:
            logger.warning("anthropic SDK not installed — ClaudeDriver unavailable")
            return False
        except Exception as exc:
            logger.error("Failed to init Anthropic client: %s", exc)
            return False

    async def decide_intent(
        self,
        message: str,
        domains: list[str],
        sops: list[dict[str, Any]] | None = None,
    ) -> IntentResult:
        if not self._ensure_client():
            return self._fallback_intent(message, domains)

        sops_json = json.dumps(sops or [], indent=2)
        domains_str = ", ".join(domains) if domains else "none"

        try:
            response = await self._client.messages.create(
                model=self._model,
                max_tokens=512,
                system=self.INTENT_SYSTEM_PROMPT.format(
                    domains=domains_str, sops=sops_json
                ),
                messages=[{"role": "user", "content": message}],
            )
            raw = ""
            for block in response.content:
                if hasattr(block, "text"):
                    raw += block.text

            parsed = json.loads(raw.strip())
            return IntentResult(
                intent=parsed.get("intent", "unknown"),
                domain=parsed.get("domain", ""),
                sop_id=parsed.get("sop_id", ""),
                raw_text=message,
                confidence=float(parsed.get("confidence", 0.0)),
            )
        except Exception as exc:
            logger.warning("Claude intent classification failed: %s", exc)
            return self._fallback_intent(message, domains)

    async def generate_rdf(
        self,
        domain: str,
        schema: dict[str, Any],
        user_description: str,
    ) -> RDFGenerationResult:
        if not self._ensure_client():
            return RDFGenerationResult(
                domain=domain, valid=False,
                error="Claude SDK not available",
            )

        schema_json = json.dumps(schema, indent=2, default=str)
        try:
            response = await self._client.messages.create(
                model=self._model,
                max_tokens=self._max_tokens,
                system=self.RDF_SYSTEM_PROMPT.format(
                    domain=domain, schema_json=schema_json
                ),
                messages=[{"role": "user", "content": user_description}],
            )
            raw = ""
            for block in response.content:
                if hasattr(block, "text"):
                    raw += block.text

            turtle = raw.strip()
            # Validate it looks like Turtle (starts with @prefix or has triples)
            if not turtle or (not turtle.startswith("@prefix") and not turtle.startswith("<")):
                return RDFGenerationResult(
                    domain=domain, valid=False,
                    error="Response does not appear to be valid Turtle RDF",
                    raw_response=turtle,
                )

            return RDFGenerationResult(
                rdf_turtle=turtle,
                domain=domain,
                valid=True,
            )
        except Exception as exc:
            logger.warning("Claude RDF generation failed: %s", exc)
            return RDFGenerationResult(
                domain=domain, valid=False, error=str(exc),
            )

    async def route_to_sop(
        self,
        message: str,
        available_sops: list[dict[str, Any]],
    ) -> str:
        if not self._ensure_client():
            return ""

        sops_json = json.dumps(available_sops, indent=2)
        try:
            response = await self._client.messages.create(
                model=self._model,
                max_tokens=128,
                system=self.SOP_SYSTEM_PROMPT.format(sops=sops_json),
                messages=[{"role": "user", "content": message}],
            )
            raw = ""
            for block in response.content:
                if hasattr(block, "text"):
                    raw += block.text
            return raw.strip()
        except Exception as exc:
            logger.warning("Claude SOP routing failed: %s", exc)
            return ""

    # ── Internal fallback (keyword matching) ──

    @staticmethod
    def _fallback_intent(message: str, domains: list[str]) -> IntentResult:
        """Keyword-based fallback when Claude is unavailable."""
        lower = message.lower()
        domain = ""

        # Match domains by checking if ANY hyphen-separated token appears in the message.
        # e.g. "it-asset-mgmt" tokens = {"it", "asset", "mgmt"} → "create asset" matches.
        # Among multiple candidates, pick the one with the most token hits.
        best_domain = ""
        best_score = 0
        for d in domains:
            tokens = d.replace("-", " ").split()
            score = sum(1 for t in tokens if t in lower)
            if score > best_score:
                best_score = score
                best_domain = d
        domain = best_domain

        if "schema" in lower:
            return IntentResult("query_schema", domain, raw_text=message, confidence=0.5)
        if "validate" in lower or "verify" in lower:
            return IntentResult("validate", domain, raw_text=message, confidence=0.5)
        if "write" in lower or "execute" in lower or "create" in lower:
            return IntentResult("governed_write", domain, raw_text=message, confidence=0.5)
        return IntentResult("unknown", raw_text=message, confidence=0.0)


# ── Factory ──


def create_llm_driver(
    provider: str = "claude",
    api_key: str | None = None,
    model: str | None = None,
) -> LLMDriver:
    """Factory: create the appropriate LLM driver.

    Args:
        provider: 'claude' (default) or 'fallback'.
        api_key: API key (reads ANTHROPIC_API_KEY env var if omitted).
        model: Model name override.

    Returns:
        Configured LLMDriver instance.
    """
    if provider == "claude":
        resolved_key = api_key or os.environ.get("ANTHROPIC_API_KEY", "")
        resolved_model = model or os.environ.get(
            "AGENT_OS_LLM_MODEL", "claude-sonnet-4-20250514"
        )
        if resolved_key:
            return ClaudeDriver(api_key=resolved_key, model=resolved_model)
        logger.info(
            "ANTHROPIC_API_KEY not set — using keyword fallback driver. "
            "Set ANTHROPIC_API_KEY to enable Claude-powered intent classification."
        )

    # Fallback: keyword-based (mirrors current kernel behaviour)
    from agentos_kernel.llm_driver import FallbackDriver
    return FallbackDriver()


class FallbackDriver(LLMDriver):
    """Keyword-pattern stub that mirrors the current kernel MVP behaviour."""

    async def decide_intent(
        self,
        message: str,
        domains: list[str],
        sops: list[dict[str, Any]] | None = None,
    ) -> IntentResult:
        return ClaudeDriver._fallback_intent(message, domains)

    async def generate_rdf(
        self,
        domain: str,
        schema: dict[str, Any],
        user_description: str,
    ) -> RDFGenerationResult:
        return RDFGenerationResult(
            domain=domain, valid=False,
            error="RDF generation requires a real LLM. Set ANTHROPIC_API_KEY.",
        )

    async def route_to_sop(
        self,
        message: str,
        available_sops: list[dict[str, Any]],
    ) -> str:
        return ""
