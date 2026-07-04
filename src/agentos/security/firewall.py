"""Semantic Firewall - microsecond-level prompt-injection taint scanning.

Corresponds to WO-A2.3: taint scanning via regex hooks on third-party
API responses and RAG retrieval results before they reach the LLM context.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from typing import Optional, List, Pattern

from agentos.kernel.exceptions import SecurityInterceptError

logger = logging.getLogger(__name__)


# ── Patterns: known prompt-injection and jailbreak indicators ──

_DEFAULT_PATTERNS: List[str] = [
    # Direct injection delimiters
    r"(?i)ignore previous instructions?",
    r"(?i)disregard (all )?previous",
    r"(?i)forget everything",
    r"(?i)ignore (the |your )?(above|prior|earlier) (instructions?|prompts?|context)",
    # Role override
    r"(?i)you are now (an? )?(?:attacker|hacker|malicious) ",
    r"(?i)act as (a |an )?(?:system|admin|developer|attacker)",
    r"(?i)pretend to be (a |an )?(?:system|admin|developer|attacker)",
    # Credential / PII exfiltration
    r"(?i)password\s*[=:]\s*\S+",
    r"(?i)api[_-]?key\s*[=:]\s*\S+",
    r"(?i)(?:secret|token|credential)s?\s*[=:]\s*\S+",
    # Template injection markers
    r"\{\{[ ]*\.?[A-Za-z_]+[ ]*\}\}",  # {{ .system }}
    r"<\?[ ]*(?:php|python|js|bash)[ ]*\?>",  # <?php
    r"<\!\[CDATA",
    # Encoded / obfuscated payloads
    r"%3Cscript%3E",
    r"<script[\s/>]",
    r"javascript:[ ]*",
    r"data:text/html[;,]",
    # Unicode-directionality tricks
    r"\u202e",
    r"\u200e",
    r"\u202d",
]


# ── Result object ──

@dataclass(frozen=True)
class TaintScanResult:
    """Outcome of a taint scan (immutable)."""

    clean: bool
    input_type: str           # e.g. "rag_chunk", "api_response", "user_prompt"
    threats_found: int = 0
    matched_patterns: List[str] = field(default_factory=list)
    severity: str = "none"      # none / low / medium / high / critical

    def to_dict(self) -> dict:
        return {
            "clean": self.clean,
            "input_type": self.input_type,
            "threats_found": self.threats_found,
            "matched_patterns": self.matched_patterns,
            "severity": self.severity,
        }


# ── Firewall engine ──

class SemanticFirewall:
    """High-speed semantic firewall using compiled regex hooks.

    Executes in microseconds for typical RAG chunks / API responses.
    Designed as a **pre-processor** before LLM context assembly.
    """

    def __init__(
        self,
        extra_patterns: Optional[List[str]] = None,
        block_on_severity: Optional[List[str]] = None,
        tracer: Optional[object] = None,
    ) -> None:
        self.patterns: List[Pattern] = []
        raw = _DEFAULT_PATTERNS + (extra_patterns or [])
        for pat in raw:
            try:
                self.patterns.append(re.compile(pat))
            except re.error:
                logger.warning("Skipping invalid regex pattern: %s", pat)

        self.block_levels = set(block_on_severity or ["high", "critical"])
        self._tracer = tracer  # Optional OTel tracer for security event spans
        logger.info(
            "SemanticFirewall initialised with %d regex hooks. "
            "Block on severity: %s",
            len(self.patterns),
            self.block_levels,
        )

    # ── Core scan entrypoint ──

    def scan(
        self,
        text: str,
        input_type: str = "unknown",
        source: Optional[str] = None,
    ) -> TaintScanResult:
        """Run a microsecond regex sweep over *text*.

        Args:
            text: The untrusted content to scan.
            input_type: Label for telemetry (e.g. ``rag_chunk``).
            source: Optional upstream origin identifier.

        Returns:
            TaintScanResult -- clean=True if no threats.

        Raises:
            SecurityInterceptError: If a pattern matches *and*
            the inferred severity is in ``block_on_severity``.
        """
        matched: List[str] = []
        for pat in self.patterns:
            for m in pat.finditer(text):
                snippet = m.group(0)[:80]
                matched.append(snippet)
                logger.warning(
                    "Firewall: matched pattern %s in input_type=%s source=%s "
                    "snippet=%s",
                    pat.pattern,
                    input_type,
                    source,
                    snippet,
                )

        severity = self._classify_severity(matched, input_type)
        result = TaintScanResult(
            clean=len(matched) == 0,
            input_type=input_type,
            threats_found=len(matched),
            matched_patterns=matched[:10],  # cap for telemetry
            severity=severity,
        )

        if matched and severity in self.block_levels:
            # Emit security event span via OpenTelemetry (if tracer available)
            if self._tracer is not None:
                error = SecurityInterceptError(
                    message=f"Semantic firewall intercepted {result.threats_found} threat(s) "
                            f"in {input_type} (severity={severity}).",
                    trigger=matched[0],
                    severity=severity,
                )
                try:
                    from agentos.observability.security_dimensions import (
                        emit_security_intercept_span,
                    )
                    emit_security_intercept_span(self._tracer, error, input_type)
                except Exception:
                    pass  # Never let observability failures block security
                raise error

            raise SecurityInterceptError(
                message=f"Semantic firewall intercepted {result.threats_found} threat(s) "
                        f"in {input_type} (severity={severity}).",
                trigger=matched[0],
                severity=severity,
            )

        return result

    # ── Severity classifier (internal) ──

    def _classify_severity(
        self, matches: List[str], input_type: str
    ) -> str:
        """Heuristic: map matched content to severity tier."""
        if not matches:
            return "none"

        # Critical: credential exfiltration or direct system override
        critical_keywords = {"password", "api_key", "secret", "token", "credential",
                             "ignore previous", "disregard", "forget everything"}
        for m in matches:
            lower = m.lower()
            if any(kw in lower for kw in critical_keywords):
                return "critical"

        # High: script injection, role override
        high_keywords = {"script", "javascript", "you are now", "act as",
                           "pretend to be", "system", "admin"}
        for m in matches:
            if any(kw in m.lower() for kw in high_keywords):
                return "high"

        # Medium: template markers, suspicious unicode
        medium_keywords = {"{{", "<?", "CDATA", "\\u"}
        for m in matches:
            if any(kw in m for kw in medium_keywords):
                return "medium"

        return "low"


# Convenience singleton (lazy)
_default_firewall: SemanticFirewall | None = None


def get_firewall() -> SemanticFirewall:
    """Get the default global firewall instance."""
    global _default_firewall
    if _default_firewall is None:
        _default_firewall = SemanticFirewall()
    return _default_firewall
