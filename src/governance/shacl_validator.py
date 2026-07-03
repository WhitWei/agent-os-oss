"""SHACL Validation Engine — Stage 2 of the MCP Write Gate.

Validates RDF data graphs against SHACL shapes using pyshacl.
Returns structured validation reports that can be serialized
as JSON-RPC responses.
"""

from __future__ import annotations

import logging
from typing import Any, Optional

import pyshacl
from rdflib import Graph, Literal, URIRef
from rdflib.namespace import RDF

from agentos_kernel.exceptions import SHACLValidationError

logger = logging.getLogger(__name__)


class SHACLValidationReport:
    """Structured result of a SHACL validation run."""

    def __init__(self, conforms: bool, results: list[dict]) -> None:
        self.conforms = conforms
        self.results = results

    @property
    def is_valid(self) -> bool:
        return self.conforms

    def to_dict(self) -> dict[str, Any]:
        return {
            "conforms": self.conforms,
            "is_valid": self.conforms,
            "result_count": len(self.results),
            "results": self.results,
        }

    def to_json_rpc_error(self) -> dict[str, Any]:
        """Format as a JSON-RPC 2.0 error response body."""
        return {
            "jsonrpc": "2.0",
            "error": {
                "code": -32602,
                "message": "SHACL validation failed — data does not comply with ontology constraints.",
                "data": {
                    "domain": "it-asset-mgmt",
                    "validation": self.to_dict(),
                    "hint": "Please fix the violations listed in 'results' and retry. Each result includes a 'fixHint' field.",
                },
            },
        }


class SHACLValidator:
    """Validates RDF data against SHACL shape graphs.

    Uses pyshacl (W3C SHACL Advanced) as the validation engine.
    Shapes are loaded from a SHACL .ttl file; data is constructed
    from LLM-supplied parameters and validated before any write.
    """

    def __init__(
        self,
        shacl_graph: Graph,
        tracer: Optional[object] = None,
        domain_name: Optional[str] = None,
    ) -> None:
        """Initialize the validator with a SHACL shapes graph.

        Args:
            shacl_graph: RDF graph containing SHACL shape definitions.
            tracer: Optional OpenTelemetry tracer for validation error spans.
            domain_name: Optional domain name for span attribution.
        """
        self._shacl_graph = shacl_graph
        self._tracer = tracer
        self._domain_name = domain_name
        from rdflib.namespace import SH as SH_NS
        shape_count = len(list(shacl_graph.subjects(RDF.type, SH_NS.NodeShape)))
        logger.info(
            "SHACL validator initialized with %d shapes", shape_count
        )

    def validate(self, data_graph: Graph) -> SHACLValidationReport:
        """Run SHACL validation of data_graph against the shape graph.

        Args:
            data_graph: RDF graph containing the data to validate.

        Returns:
            SHACLValidationReport with conforms flag and violation details.

        Raises:
            SHACLValidationError: If validation engine itself fails (not data violations).
        """
        try:
            conforms, results_graph, results_text = pyshacl.validate(
                data_graph,
                shacl_graph=self._shacl_graph,
                inference="rdfs",
                abort_on_first=False,
                meta_shacl=False,
                advanced=True,
            )
        except Exception as exc:
            raise SHACLValidationError(
                f"SHACL validation engine error: {exc}"
            ) from exc

        # Parse validation results into structured format
        results = self._parse_results(results_graph)

        report = SHACLValidationReport(conforms=conforms, results=results)

        if not conforms:
            logger.warning(
                "SHACL validation FAILED: %d violation(s)", len(results)
            )
            # Emit SHACL validation error span via OpenTelemetry
            if self._tracer is not None:
                try:
                    from observability.security_dimensions import (
                        emit_shacl_validation_error_span,
                    )
                    domain = self._domain_name or "unknown"
                    emit_shacl_validation_error_span(self._tracer, domain, report)
                except Exception:
                    pass  # Never let observability block validation
        else:
            logger.info("SHACL validation PASSED")

        return report

    def _parse_results(self, results_graph: Graph) -> list[dict]:
        """Parse pyshacl's internal results graph into a list of dicts.

        Each violation includes:
        - focusNode: The node that violates the constraint
        - resultPath: The property path that failed
        - resultMessage: Human-readable violation description
        - resultSeverity: sh:Violation, sh:Warning, or sh:Info
        - value: The offending value (if available)
        - fixHint: Suggestion for how to fix the violation
        """
        from rdflib.namespace import SH as SH_NS

        results = []
        for result_node in results_graph.subjects(RDF.type, SH_NS.ValidationResult):
            focus_node = results_graph.value(result_node, SH_NS.focusNode)
            result_path = results_graph.value(result_node, SH_NS.resultPath)
            result_message = results_graph.value(result_node, SH_NS.resultMessage)
            result_severity = results_graph.value(result_node, SH_NS.resultSeverity)
            value = results_graph.value(result_node, SH_NS.value)

            # Determine the severity level
            severity = "Violation"
            if result_severity == SH_NS.Warning:
                severity = "Warning"
            elif result_severity == SH_NS.Info:
                severity = "Info"

            # Generate a fix hint based on the violation
            msg_str = str(result_message) if result_message else ""
            path_str = str(result_path).split("#")[-1] if result_path else "?"

            fix_hint = self._generate_fix_hint(path_str, msg_str, severity)

            results.append({
                "focusNode": str(focus_node) if focus_node else None,
                "resultPath": str(result_path) if result_path else None,
                "resultMessage": msg_str,
                "severity": severity,
                "value": str(value) if value else None,
                "fixHint": fix_hint,
            })

        return results

    def _generate_fix_hint(self, path: str, message: str, severity: str) -> str:
        """Generate a helpful fix hint for the LLM based on the violation."""
        # Common patterns
        if "minCount" in message.lower() or "required" in message.lower():
            return f"Add the required property '{path}' to the entity."
        if "maxCount" in message.lower():
            return f"Remove duplicate values for property '{path}' — only one is allowed."
        if "in" in message.lower() or "allowed" in message.lower():
            return f"Change '{path}' to one of the allowed values listed in the schema."
        if "datatype" in message.lower() or "type" in message.lower():
            return f"Ensure '{path}' has the correct data type as defined in the schema."
        return f"Review the SHACL shape constraint for '{path}' and fix the data."

    @classmethod
    def from_file(
        cls,
        shacl_path: str,
        tracer: Optional[object] = None,
        domain_name: Optional[str] = None,
    ) -> "SHACLValidator":
        """Create a validator from a SHACL .ttl file path."""
        shacl_graph = Graph()
        shacl_graph.parse(shacl_path, format="turtle")
        return cls(shacl_graph, tracer=tracer, domain_name=domain_name)
