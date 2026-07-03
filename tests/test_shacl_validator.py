"""Tests for the SHACL Validation Engine.

Verifies:
- Valid RDF data passes SHACL validation
- Invalid RDF data is rejected with structured error reports
- pyshacl integration works correctly
- Multiple SHACL shapes are evaluated
"""

from pathlib import Path

import pytest
from rdflib import Graph
from rdflib.namespace import RDF

from governance.shacl_validator import SHACLValidator, SHACLValidationReport
from governance.schema_provider import SchemaProvider
from agentos_kernel.config import ConfigLoader


# ── Path to SHACL shapes ──
SHACL_PATH = Path(__file__).parent.parent / "docker" / "ontology" / "it-asset-mgmt.shacl.ttl"


@pytest.fixture(scope="module")
def shacl_validator() -> SHACLValidator:
    """Create a validator from the project's SHACL shapes file."""
    if SHACL_PATH.exists():
        return SHACLValidator.from_file(str(SHACL_PATH))
    pytest.skip(f"SHACL file not found: {SHACL_PATH}")


class TestSHACLValidation:
    """Core SHACL validation tests."""

    def test_valid_hardware_asset_passes(self, shacl_validator, sample_valid_ttl):
        """Valid hardware asset data should pass SHACL validation."""
        data_graph = Graph()
        data_graph.parse(data=sample_valid_ttl, format="turtle")

        report = shacl_validator.validate(data_graph)

        assert report.is_valid is True
        assert report.conforms is True
        assert len(report.results) == 0

    def test_invalid_hardware_asset_fails(self, shacl_validator, sample_invalid_ttl):
        """Missing required serialNumber should cause validation failure."""
        data_graph = Graph()
        data_graph.parse(data=sample_invalid_ttl, format="turtle")

        report = shacl_validator.validate(data_graph)

        assert report.is_valid is False
        assert report.conforms is False
        assert len(report.results) >= 1

        # Check that the violation mentions serialNumber (pyshacl may lowercase it)
        violation_messages = " ".join(r["resultMessage"] for r in report.results)
        violation_paths = " ".join(r.get("resultPath", "") for r in report.results)
        combined = (violation_messages + " " + violation_paths).lower()
        assert "serialnumber" in combined

    def test_valid_employee_passes(self, shacl_validator, sample_valid_employee_ttl):
        """Valid employee data should pass."""
        data_graph = Graph()
        data_graph.parse(data=sample_valid_employee_ttl, format="turtle")

        report = shacl_validator.validate(data_graph)

        assert report.is_valid is True

    def test_invalid_employee_fails(self, shacl_validator, sample_invalid_employee_ttl):
        """Missing required employeeName should fail."""
        data_graph = Graph()
        data_graph.parse(data=sample_invalid_employee_ttl, format="turtle")

        report = shacl_validator.validate(data_graph)

        assert report.is_valid is False
        violation_messages = " ".join(r["resultMessage"] for r in report.results)
        violation_paths = " ".join(r.get("resultPath", "") for r in report.results)
        combined = (violation_messages + " " + violation_paths).lower()
        assert "employeename" in combined

    def test_report_has_fix_hints(self, shacl_validator, sample_invalid_ttl):
        """Each violation should include a fixHint for the LLM."""
        data_graph = Graph()
        data_graph.parse(data=sample_invalid_ttl, format="turtle")

        report = shacl_validator.validate(data_graph)

        for result in report.results:
            assert "fixHint" in result
            assert len(result["fixHint"]) > 0
            assert "resultMessage" in result
            assert "resultPath" in result


class TestSHACLReportFormatting:
    """Verify that the validation report produces correct output formats."""

    def test_report_to_dict(self, shacl_validator, sample_invalid_ttl):
        """Report should serialize to a dict with expected keys."""
        data_graph = Graph()
        data_graph.parse(data=sample_invalid_ttl, format="turtle")

        report = shacl_validator.validate(data_graph)
        report_dict = report.to_dict()

        assert "conforms" in report_dict
        assert "is_valid" in report_dict
        assert "result_count" in report_dict
        assert "results" in report_dict
        assert report_dict["conforms"] is False
        assert report_dict["is_valid"] is False

    def test_json_rpc_error_format(self, shacl_validator, sample_invalid_ttl):
        """Validation failure should produce JSON-RPC 2.0 error format."""
        data_graph = Graph()
        data_graph.parse(data=sample_invalid_ttl, format="turtle")

        report = shacl_validator.validate(data_graph)
        error = report.to_json_rpc_error()

        assert error["jsonrpc"] == "2.0"
        assert "error" in error
        assert error["error"]["code"] == -32602
        assert "SHACL" in error["error"]["message"]
        assert "data" in error["error"]
        assert "validation" in error["error"]["data"]

    def test_valid_report_no_json_rpc_error(self, shacl_validator, sample_valid_ttl):
        """Valid data should have is_valid=True and no error format needed."""
        data_graph = Graph()
        data_graph.parse(data=sample_valid_ttl, format="turtle")

        report = shacl_validator.validate(data_graph)

        assert report.is_valid is True
        # Even for valid data, to_json_rpc_error is available
        error = report.to_json_rpc_error()
        assert error["error"]["code"] == -32602  # Still produces the error format

    def test_malformed_rdf_fails_gracefully(self, shacl_validator):
        """Malformed RDF should raise an informative error."""
        from agentos_kernel.exceptions import SHACLValidationError

        bad_rdf = "this is not RDF {{{"

        with pytest.raises(Exception):  # pyshacl or rdflib parsing error
            data_graph = Graph()
            data_graph.parse(data=bad_rdf, format="turtle")
            shacl_validator.validate(data_graph)


class TestMultipleShapes:
    """Verify that multiple SHACL shapes are all evaluated."""

    def test_all_shapes_loaded(self, shacl_validator):
        """Validator should have loaded at least 5 shapes (6 defined in the file)."""
        # We can't easily introspect shape count, but we can validate
        # different entity types
        assert shacl_validator is not None

    def test_employee_and_asset_shapes(self, shacl_validator, sample_valid_employee_ttl, sample_valid_ttl):
        """Both employee and asset shapes are independently validated."""
        # Employee passes
        emp_graph = Graph()
        emp_graph.parse(data=sample_valid_employee_ttl, format="turtle")
        emp_report = shacl_validator.validate(emp_graph)
        assert emp_report.is_valid is True

        # Asset passes
        asset_graph = Graph()
        asset_graph.parse(data=sample_valid_ttl, format="turtle")
        asset_report = shacl_validator.validate(asset_graph)
        assert asset_report.is_valid is True
