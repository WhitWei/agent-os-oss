"""MCP Governance Gateway Server.

Implements the Model Context Protocol (MCP) server that exposes three tools
per domain, implementing the 3-stage governed write pattern:

Tools:
  1. get_{domain}_schema     — Return OWL/SHACL schema for the domain
  2. verify_shacl_compliance — Validate data against SHACL shapes
  3. execute_governed_write  — Execute write (requires validation nonce)

The server uses streamable HTTP transport so it can coexist with the
Feishu webhook FastAPI server in the same process.
"""

from __future__ import annotations

import json
import logging
from typing import Any

from mcp.server.fastmcp import FastMCP

from governance.schema_provider import SchemaProvider
from governance.write_gate import WriteGate
from agentos_kernel.config import AppConfig
from agentos_kernel.exceptions import (
    SHACLValidationError,
    WriteGateError,
)

logger = logging.getLogger(__name__)


class GovernanceGateway:
    """MCP Governance Gateway wrapping FastMCP with 3-stage write gate tools.

    Each configured domain gets three tools auto-registered. The gateway
    enforces that NO write can occur without first passing SHACL validation.
    """

    def __init__(self, write_gate: WriteGate, config: AppConfig) -> None:
        self._write_gate = write_gate
        self._config = config
        self._mcp = FastMCP(
            name=config.mcp.server_name,
            host=config.mcp.host,
            port=config.mcp.port,
        )
        self._register_tools()
        logger.info(
            "Governance Gateway '%s' initialized on %s:%d",
            config.mcp.server_name,
            config.mcp.host,
            config.mcp.port,
        )

    @property
    def mcp_server(self) -> FastMCP:
        """The underlying FastMCP server instance."""
        return self._mcp

    def _register_tools(self) -> None:
        """Register all governance tools for each configured domain."""
        mcp = self._mcp
        write_gate = self._write_gate

        for domain in self._config.ontology.domains:
            domain_name = domain.name

            # ── Tool 1: get_{domain}_schema ──
            schema_tool_name = f"get_{domain_name.replace('-', '_')}_schema"

            def make_schema_handler(dn=domain_name):
                async def handler() -> str:
                    """Get the OWL ontology and SHACL shape definitions for the domain."""
                    try:
                        schema = write_gate.get_domain_schema(dn)
                        return json.dumps(schema, indent=2)
                    except Exception as exc:
                        return json.dumps({
                            "jsonrpc": "2.0",
                            "error": {
                                "code": -32603,
                                "message": str(exc),
                            },
                        })

                return handler

            mcp.tool(name=schema_tool_name)(make_schema_handler())

            # ── Tool 2: verify_shacl_compliance_{domain} ──
            verify_tool_name = f"verify_shacl_compliance_{domain_name.replace('-', '_')}"

            def make_verify_handler(dn=domain_name):
                async def handler(data_rdf: str, rdf_format: str = "turtle") -> str:
                    """Validate RDF data against domain SHACL shapes before writing.

                    Args:
                        data_rdf: The RDF data to validate (Turtle format by default).
                        rdf_format: RDF format (turtle, xml, n3, json-ld). Default: turtle.

                    Returns:
                        JSON-RPC response. If valid, includes a validation_nonce
                        required for execute_governed_write. If invalid, returns
                        detailed SHACL violation errors.
                    """
                    try:
                        report, nonce = write_gate.verify_shacl_compliance(
                            dn, data_rdf, rdf_format
                        )
                        result = report.to_dict()
                        result["validation_nonce"] = nonce
                        result["next_step"] = (
                            "Use execute_governed_write with this validation_nonce "
                            "to complete the write."
                            if nonce
                            else "Fix the SHACL violations listed above and retry."
                        )
                        return json.dumps({
                            "jsonrpc": "2.0",
                            "result": result,
                        }, indent=2)
                    except SHACLValidationError as exc:
                        error_data = report.to_json_rpc_error() if 'report' in dir() else {
                            "jsonrpc": "2.0",
                            "error": {
                                "code": -32602,
                                "message": str(exc),
                                "data": exc.validation_report if exc.validation_report else {},
                            },
                        }
                        return json.dumps(error_data, indent=2)
                    except Exception as exc:
                        return json.dumps({
                            "jsonrpc": "2.0",
                            "error": {
                                "code": -32603,
                                "message": f"Validation error: {exc}",
                            },
                        }, indent=2)

                return handler

            mcp.tool(name=verify_tool_name)(make_verify_handler())

            # ── Tool 3: execute_governed_write_{domain} ──
            write_tool_name = f"execute_governed_write_{domain_name.replace('-', '_')}"
            def make_write_handler(dn=domain_name):
                async def handler(
                    data_rdf: str,
                    validation_nonce: str,
                    rdf_format: str = "turtle",
                ) -> str:
                    """Execute a governed write to Neo4j.

                    REQUIRES a valid validation_nonce from a prior call to
                    verify_shacl_compliance. Without it, the write is REJECTED.

                    Args:
                        data_rdf: The RDF data to write (must match what was validated).
                        validation_nonce: The nonce from verify_shacl_compliance.
                        rdf_format: RDF format. Default: turtle.

                    Returns:
                        JSON-RPC response with write result.
                    """
                    try:
                        result = await write_gate.execute_governed_write(
                            dn, data_rdf, validation_nonce, rdf_format
                        )
                        return json.dumps({
                            "jsonrpc": "2.0",
                            "result": result,
                        }, indent=2)
                    except (SHACLValidationError, WriteGateError) as exc:
                        return json.dumps({
                            "jsonrpc": "2.0",
                            "error": {
                                "code": -32602,
                                "message": str(exc),
                                "data": getattr(exc, "validation_report", None),
                            },
                        }, indent=2)
                    except Exception as exc:
                        return json.dumps({
                            "jsonrpc": "2.0",
                            "error": {
                                "code": -32603,
                                "message": f"Write execution error: {exc}",
                            },
                        }, indent=2)

                return handler

            mcp.tool(name=f"execute_governed_write_{domain_name.replace('-', '_')}")(make_write_handler())

            logger.info(
                "Registered MCP tools for domain '%s': %s, %s, %s",
                domain_name,
                schema_tool_name,
                verify_tool_name,
                write_tool_name,
            )

    def run(self) -> None:
        """Start the MCP server (stdio transport)."""
        logger.info("Starting MCP Governance Gateway on stdio...")
        self._mcp.run(transport="stdio")

    def close(self) -> None:
        """Shut down the MCP server."""
        logger.info("Stopping MCP Governance Gateway...")
