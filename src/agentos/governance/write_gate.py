"""Write Gate — 3-stage governed write orchestration.

Implements the core safety pattern:

  Stage 1: get_{domain}_schema  → SchemaProvider returns OWL+SHACL definitions
  Stage 2: verify_shacl_compliance → SHACLValidator validates LLM-assembled data
           Returns a signed HMAC validation_nonce if valid
  Stage 3: execute_governed_write  → Only with valid nonce, writes to Neo4j

The nonce prevents bypass: Stage 3 cannot be called without going through Stage 2.
The nonce includes a TTL and a hash of the validated data, ensuring the data
wasn't tampered with between validation and execution.

Nonce replay protection: each nonce is single-use. Once consumed by a successful
execute_governed_write, it is burned and cannot be reused. This prevents an
attacker from replaying a valid nonce to perform multiple writes.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import logging
import time
from typing import Any, Optional

from rdflib import Graph, Literal, URIRef
from rdflib.namespace import RDF

from agentos.governance.neo4j_client import Neo4jClient
from agentos.governance.schema_provider import SchemaProvider
from agentos.governance.shacl_validator import SHACLValidationReport, SHACLValidator
from agentos.kernel.exceptions import (
    GovernanceError,
    SHACLValidationError,
    WriteGateError,
)

logger = logging.getLogger(__name__)

# Well-known namespaces
ASSET = "http://agent-os.local/ontology/it-asset-mgmt#"


def _sanitize_label(label: str) -> str:
    """Sanitize a string for use as a Cypher label or relationship type.

    Only alphanumeric characters and underscores are allowed.
    Everything else is replaced with underscores to prevent injection.
    """
    import re

    label = label.replace("-", "_").upper()
    # Replace any character that isn't alphanumeric or underscore
    return re.sub(r"[^A-Z0-9_]", "_", label, flags=re.IGNORECASE)


class WriteGate:
    """Orchestrates the 3-stage governed write pipeline.

    Usage:
        gate = WriteGate(schema_provider, neo4j_client, nonce_secret, nonce_ttl)

        # Stage 1: Get schema
        schema = gate.get_domain_schema("it-asset-mgmt")

        # LLM assembles data in RDF based on schema...

        # Stage 2: Validate
        report, nonce = gate.verify_shacl_compliance("it-asset-mgmt", data_rdf)

        # Stage 3: Write (only with valid nonce)
        result = gate.execute_governed_write("it-asset-mgmt", data_rdf, nonce)
    """

    def __init__(
        self,
        schema_provider: SchemaProvider,
        neo4j_client: Neo4jClient,
        nonce_secret: str = "dev-nonce-secret-change-in-prod",
        nonce_ttl_seconds: int = 300,
        tracer: Optional[object] = None,
        autonomy_policy: Optional[object] = None,
    ) -> None:
        self._schema_provider = schema_provider
        self._neo4j_client = neo4j_client
        self._nonce_secret = nonce_secret.encode("utf-8")
        self._nonce_ttl = nonce_ttl_seconds
        self._tracer = tracer
        self._autonomy_policy = autonomy_policy

        # Cache validators per domain (SHACL graphs don't change at runtime)
        self._validators: dict[str, SHACLValidator] = {}

        # Consumed nonces — prevents replay. Each nonce is burned after first use.
        # Key: nonce_signature → expiry_timestamp (for periodic cleanup)
        self._consumed_nonces: dict[str, float] = {}

    # ── Stage 1: Schema ──

    def get_domain_schema(self, domain_name: str) -> dict[str, Any]:
        """Return the OWL schema and SHACL shapes for a domain.

        This is the first stage of the write gate: the LLM calls this
        to understand what data structure is required before assembling
        the write payload.
        """
        definition = self._schema_provider.get_schema_definition(domain_name)
        if "error" in definition:
            raise GovernanceError(
                f"Unknown domain '{domain_name}'. Available: {definition.get('available_domains', [])}"
            )
        return definition

    # ── Stage 2: Validate ──

    def verify_shacl_compliance(
        self, domain_name: str, data_rdf: str, rdf_format: str = "turtle"
    ) -> tuple[SHACLValidationReport, Optional[str]]:
        """Validate RDF data against the domain's SHACL shapes.

        Args:
            domain_name: The domain to validate against (e.g., 'it-asset-mgmt').
            data_rdf: The RDF data string to validate.
            rdf_format: RDF serialization format (default: 'turtle').

        Returns:
            Tuple of (SHACLValidationReport, validation_nonce).
            The nonce is None if validation failed.

        Raises:
            GovernanceError: If the domain is unknown.
            SHACLValidationError: If the RDF is malformed.
        """
        # Get or create validator for this domain
        if domain_name not in self._validators:
            domain = self._schema_provider.get_domain(domain_name)
            if domain is None:
                raise GovernanceError(
                     f"Unknown domain '{domain_name}'. "
                     f"Available: {self._schema_provider.list_domains()}"
                )
            self._validators[domain_name] = SHACLValidator.from_file(
                str(domain.shacl_path),
                tracer=self._tracer,
                domain_name=domain_name,
            )

        validator = self._validators[domain_name]

        # Parse the RDF data
        data_graph = Graph()
        try:
            data_graph.parse(data=data_rdf, format=rdf_format)
        except Exception as exc:
            raise SHACLValidationError(
                f"Failed to parse RDF data: {exc}. "
                f"Ensure your data is valid {rdf_format.upper()} format."
            ) from exc

        # Run SHACL validation
        report = validator.validate(data_graph)

        # Generate nonce only if valid
        nonce = None
        if report.is_valid:
            nonce = self._generate_nonce(domain_name, data_rdf)

        return report, nonce

    # ── Stage 3: Write ──

    async def execute_governed_write(
        self,
        domain_name: str,
        data_rdf: str,
        validation_nonce: str,
        rdf_format: str = "turtle",
    ) -> dict[str, Any]:
        """Execute a governed write to Neo4j ONLY with a valid validation nonce.

        Args:
            domain_name: The domain to write to.
            data_rdf: The RDF data to write (must match what was validated).
            validation_nonce: The HMAC nonce from a prior verify_shacl_compliance call.
            rdf_format: RDF serialization format.

        Returns:
            Dict with write result, transaction_id, and node_ids.

        Raises:
            WriteGateError: If the nonce is missing, expired, or data doesn't match.
            SHACLValidationError: If re-validation fails (edge case).
        """
        # 0. Check autonomy policy write quota if configured
        if self._autonomy_policy is not None:
            self._autonomy_policy.check_write_quota(domain_name)

        # 1. Verify nonce (includes signature check, TTL check, data hash check,
        #    AND replay protection — nonce not yet consumed)
        self._verify_nonce(domain_name, data_rdf, validation_nonce)

        # 1b. Burn the nonce immediately after verification to prevent replay.
        #     Even if the subsequent write fails (e.g., Neo4j down), the nonce
        #     cannot be reused — the caller must re-validate.
        self._consume_nonce(validation_nonce)

        logger.info("Governed write authorized for domain '%s'", domain_name)

        # 2. Re-validate to be absolutely sure
        # (Double-check — the nonce proves prior validation, but data could
        #  have been manipulated if the nonce secret is compromised.)
        report, _ = self.verify_shacl_compliance(domain_name, data_rdf, rdf_format)
        if not report.is_valid:
            raise SHACLValidationError(
                "Re-validation failed: data does not match the previously validated payload. "
                "The write has been blocked.",
                validation_report=report.to_dict(),
            )

        # 3. Parse the RDF data into Cypher write statements
        # For MVP, we insert RDF data via n10s import
        # In production, this would be a proper RDF-to-Cypher translation
        data_graph = Graph()
        data_graph.parse(data=data_rdf, format=rdf_format)

        # Build a list of Cypher MERGE statements from the RDF triples
        cypher_statements = self._rdf_to_cypher_statements(data_graph, domain_name)

        # 4. Execute the write (async — called from async context)
        if self._neo4j_client is not None:
            logger.info("Executing write batch to Neo4j database")
            records_written = await self._neo4j_client.execute_write_batch(cypher_statements)
            return {
                "status": "success",
                "domain": domain_name,
                "transaction_id": hashlib.sha256(
                    f"{domain_name}:{time.time()}".encode()
                ).hexdigest()[:16],
                "records_written": records_written,
            }

        return {
            "status": "success",
            "domain": domain_name,
            "transaction_id": hashlib.sha256(
                f"{domain_name}:{time.time()}".encode()
            ).hexdigest()[:16],
        }

    # ── Nonce Management ──

    def _generate_nonce(self, domain_name: str, data_rdf: str) -> str:
        """Generate a signed HMAC nonce that binds validated data to the write stage.

        Nonce format: {timestamp}:{data_hash}:{signature}
        - timestamp: Unix epoch when validated
        - data_hash: SHA256 of the data_rdf
        - signature: HMAC-SHA256 of "{timestamp}:{data_hash}:{domain}"
        """
        timestamp = int(time.time())
        data_hash = hashlib.sha256(data_rdf.encode("utf-8")).hexdigest()
        payload = f"{timestamp}:{data_hash}:{domain_name}"
        signature = hmac.new(
            self._nonce_secret, payload.encode("utf-8"), hashlib.sha256
        ).hexdigest()
        nonce = f"{timestamp}:{data_hash}:{signature}"
        logger.debug("Generated validation nonce (ttl=%ds)", self._nonce_ttl)
        return nonce

    def _verify_nonce(self, domain_name: str, data_rdf: str, nonce: str) -> None:
        """Verify a validation nonce is valid, hasn't expired, and hasn't been replayed.

        Each nonce can only be used ONCE. After a successful write, the nonce
        is burned to prevent replay attacks.

        Raises:
            WriteGateError: If the nonce is invalid, expired, already consumed,
                            or data doesn't match.
        """
        try:
            parts = nonce.split(":")
            if len(parts) != 3:
                raise ValueError("Invalid nonce format")

            timestamp_str, data_hash, signature = parts
            timestamp = int(timestamp_str)

            # Check TTL
            if time.time() - timestamp > self._nonce_ttl:
                raise WriteGateError(
                    f"Validation nonce has expired (TTL={self._nonce_ttl}s). "
                    f"Please re-validate via verify_shacl_compliance."
                )

            # --- Replay protection: check if nonce was already consumed ---
            self._cleanup_expired_nonces()
            if signature in self._consumed_nonces:
                raise WriteGateError(
                    "Validation nonce has already been consumed. "
                    "Each nonce can only be used once. "
                    "Please re-validate via verify_shacl_compliance to get a new nonce."
                )

            # Verify signature
            expected_payload = f"{timestamp}:{data_hash}:{domain_name}"
            expected_signature = hmac.new(
                self._nonce_secret,
                expected_payload.encode("utf-8"),
                hashlib.sha256,
            ).hexdigest()

            if not hmac.compare_digest(signature, expected_signature):
                raise WriteGateError(
                    "Validation nonce signature is invalid. "
                    "This may indicate a tampering attempt. "
                    "Please re-validate via verify_shacl_compliance."
                )

            # Verify data matches
            actual_data_hash = hashlib.sha256(data_rdf.encode("utf-8")).hexdigest()
            if actual_data_hash != data_hash:
                raise WriteGateError(
                    "Data hash mismatch — the submitted data differs from "
                    "what was validated. Write blocked. "
                    "Please re-validate the correct data via verify_shacl_compliance."
                )

            logger.debug("Validation nonce verified (age=%ds)", int(time.time()) - timestamp)

        except WriteGateError:
            raise
        except Exception as exc:
            raise WriteGateError(
                f"Failed to verify validation nonce: {exc}. "
                f"Ensure you are passing the exact nonce returned by verify_shacl_compliance."
            ) from exc

    def _consume_nonce(self, nonce: str) -> None:
        """Mark a nonce as consumed after a successful write."""
        try:
            parts = nonce.split(":")
            if len(parts) == 3:
                signature = parts[2]
                self._consumed_nonces[signature] = time.time() + self._nonce_ttl
                logger.debug("Nonce consumed (expires from tracking at +%ds)", self._nonce_ttl)
        except Exception:
            logger.exception("Failed to consume validation nonce")
            pass  # Never block a successful write on nonce tracking failure

    def _cleanup_expired_nonces(self) -> None:
        """Remove expired nonces from the consumed set to bound memory."""
        now = time.time()
        expired = [
            sig for sig, expires_at in self._consumed_nonces.items()
            if expires_at <= now
        ]
        for sig in expired:
            del self._consumed_nonces[sig]
        if expired:
            logger.debug("Cleaned up %d expired consumed nonces", len(expired))

    def _rdf_to_cypher_statements(self, data_graph: Graph, domain_name: str) -> list[str]:
        """Convert an RDF graph to a list of Cypher MERGE statements.

        This is a simplified converter for the MVP. In production, this would
        use a proper RDF2Cypher mapping with the n10s schema.

        SECURITY: All values passed to Cypher are sanitized to prevent
        Cypher injection. Backticks and single quotes are escaped.
        """
        statements = []
        for subject, predicate, obj in data_graph:
            subj_str = self._sanitize_cypher_value(self._rdf_term_to_str(subject))
            pred_str = self._rdf_term_to_str(predicate)
            obj_str = self._sanitize_cypher_value(self._rdf_term_to_str(obj))

            # Sanitize the predicate label (used as relationship type)
            pred_label = pred_str.split("#")[-1] if "#" in pred_str else pred_str.split("/")[-1]
            # Only allow alphanumeric, underscore, and hyphen in relationship type names
            pred_label = _sanitize_label(pred_label)

            statements.append(
                f"MERGE (a:`Resource` {{uri: '{subj_str}'}}) "
                f"MERGE (b:`Resource` {{uri: '{obj_str}'}}) "
                f"MERGE (a)-[:`{pred_label}`]->(b)"
            )

        return statements

    @staticmethod
    def _sanitize_cypher_value(value: str) -> str:
        r"""Sanitize a string value for safe interpolation into Cypher.

        Escapes backslashes, single quotes, and removes control characters
        to prevent Cypher injection attacks.
        """
        return (
            value
            .replace("\\", "\\\\")
            .replace("'", "\\'")
            .replace("\x00", "")   # null byte
            .replace("\n", " ")    # newlines — break string literals
            .replace("\r", "")     # carriage returns
        )

    @staticmethod
    def _rdf_term_to_str(term) -> str:
        """Convert an RDF term to its string representation."""
        if isinstance(term, URIRef):
            return str(term)
        elif isinstance(term, Literal):
            return str(term.value)
        return str(term)
