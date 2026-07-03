"""Tests for the Schema Provider.

Verifies:
- OWL file parsing (classes, properties)
- SHACL shapes extraction
- Domain listing and lookup
"""

from pathlib import Path

import pytest

from governance.schema_provider import SchemaProvider, DomainSchema
from zeroclaw.config import ConfigLoader


# ── Fixtures ──

@pytest.fixture(scope="module")
def schema_provider() -> SchemaProvider:
    """Create a SchemaProvider from the real project ontology files."""
    config_path = Path(__file__).parent.parent / "config.yaml"
    loader = ConfigLoader(str(config_path))
    config = loader.load()

    return SchemaProvider(
        owl_dir=config.ontology.owl_dir,
        shacl_dir=config.ontology.shacl_dir,
        domains=config.ontology.domains,
    )


@pytest.fixture(scope="module")
def domain_count(schema_provider: SchemaProvider) -> int:
    """Number of domains available."""
    return len(schema_provider.list_domains())


class TestSchemaProvider:
    """Schema provider loading and lookup."""

    def test_list_domains(self, schema_provider):
        """Should return list of domain names."""
        domains = schema_provider.list_domains()
        assert len(domains) > 0
        assert "it-asset-mgmt" in domains

    def test_get_domain(self, schema_provider):
        """Should return DomainSchema for valid domain."""
        domain = schema_provider.get_domain("it-asset-mgmt")
        assert domain is not None
        assert domain.name == "it-asset-mgmt"

    def test_get_unknown_domain(self, schema_provider):
        """Should return None for unknown domain."""
        domain = schema_provider.get_domain("nonexistent")
        assert domain is None


class TestDomainSchema:
    """Domain schema content verification."""

    def test_get_classes(self, schema_provider):
        """Should return list of OWL classes with labels."""
        domain = schema_provider.get_domain("it-asset-mgmt")
        classes = domain.get_classes()

        assert len(classes) > 0
        # Verify key classes exist
        class_labels = [c.get("label") for c in classes]
        assert "Hardware Asset" in class_labels
        assert "Employee" in class_labels
        assert "Software Asset" in class_labels

    def test_get_properties(self, schema_provider):
        """Should return object and datatype properties."""
        domain = schema_provider.get_domain("it-asset-mgmt")
        properties = domain.get_properties()

        assert len(properties) > 0
        prop_labels = [p.get("label") for p in properties]
        # Check for key properties
        assert "serial number" in prop_labels or "manages" in prop_labels

    def test_get_shacl_shapes(self, schema_provider):
        """Should return SHACL shape definitions."""
        domain = schema_provider.get_domain("it-asset-mgmt")
        shapes = domain.get_shacl_shapes()

        assert len(shapes) > 0
        # HardwareAssetShape should exist
        target_classes = [s.get("target_class", "") for s in shapes]
        assert any("HardwareAsset" in tc for tc in target_classes)
        assert any("Employee" in tc for tc in target_classes)

    def test_shacl_shape_has_properties(self, schema_provider):
        """Each SHACL shape should list its constrained properties."""
        domain = schema_provider.get_domain("it-asset-mgmt")
        shapes = domain.get_shacl_shapes()

        for shape in shapes:
            props = shape.get("properties", [])
            # Each shape should have at least one property constraint
            if shape.get("target_class"):  # Only check shapes with targets
                assert len(props) >= 1, f"Shape {shape['shape_iri']} has no properties"

    def test_get_schema_definition(self, schema_provider):
        """Full schema definition should be a comprehensive dict."""
        definition = schema_provider.get_schema_definition("it-asset-mgmt")

        assert "domain" in definition
        assert definition["domain"] == "it-asset-mgmt"
        assert "classes" in definition
        assert "properties" in definition
        assert "shacl_shapes" in definition
        assert "owl_path" in definition
        assert "shacl_path" in definition
        assert len(definition["classes"]) > 0
        assert len(definition["shacl_shapes"]) > 0

    def test_unknown_domain_definition(self, schema_provider):
        """Unknown domain definition returns error info."""
        definition = schema_provider.get_schema_definition("nonexistent")
        assert "error" in definition
        assert "available_domains" in definition


class TestSchemaCaching:
    """Verify that schema graphs are cached (lazy loaded)."""

    def test_owl_graph_cached(self, schema_provider):
        """OWL graph should be cached after first access."""
        domain = schema_provider.get_domain("it-asset-mgmt")

        # First access loads
        g1 = domain.owl_graph
        # Second access returns same instance
        g2 = domain.owl_graph
        assert g1 is g2

    def test_shacl_graph_cached(self, schema_provider):
        """SHACL graph should be cached after first access."""
        domain = schema_provider.get_domain("it-asset-mgmt")

        g1 = domain.shacl_graph
        g2 = domain.shacl_graph
        assert g1 is g2
