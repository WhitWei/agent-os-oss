"""Schema Provider — loads and serves domain ontology schemas.

Provides the "Stage 1" of the MCP 3-stage write gate:
returns the OWL class definitions and SHACL shape constraints
for a requested domain so the LLM can construct compliant data.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Optional

from rdflib import Graph, Namespace
from rdflib.namespace import OWL, RDF, RDFS

logger = logging.getLogger(__name__)

# Well-known namespaces
SH = Namespace("http://www.w3.org/ns/shacl#")
ASSET = Namespace("http://agent-os.local/ontology/it-asset-mgmt#")


class DomainSchema:
    """Holds the parsed schema for a single domain."""

    def __init__(self, name: str, owl_path: Path, shacl_path: Path) -> None:
        self.name = name
        self.owl_path = owl_path
        self.shacl_path = shacl_path
        self._owl_graph: Optional[Graph] = None
        self._shacl_graph: Optional[Graph] = None

    @property
    def owl_graph(self) -> Graph:
        if self._owl_graph is None:
            self._owl_graph = Graph()
            self._owl_graph.parse(str(self.owl_path), format="turtle")
        return self._owl_graph

    @property
    def shacl_graph(self) -> Graph:
        if self._shacl_graph is None:
            self._shacl_graph = Graph()
            self._shacl_graph.parse(str(self.shacl_path), format="turtle")
        return self._shacl_graph

    def get_classes(self) -> list[dict]:
        """Return all OWL classes in this domain."""
        classes = []
        for subject in self.owl_graph.subjects(RDF.type, OWL.Class):
            label = self.owl_graph.value(subject, RDFS.label)
            comment = self.owl_graph.value(subject, RDFS.comment)
            classes.append({
                "iri": str(subject),
                "label": str(label) if label else None,
                "comment": str(comment) if comment else None,
            })
        return classes

    def get_properties(self) -> list[dict]:
        """Return all OWL object and datatype properties in this domain."""
        properties = []
        for prop_type in (OWL.ObjectProperty, OWL.DatatypeProperty):
            for subject in self.owl_graph.subjects(RDF.type, prop_type):
                label = self.owl_graph.value(subject, RDFS.label)
                domain = self.owl_graph.value(subject, RDFS.domain)
                range_ = self.owl_graph.value(subject, RDFS.range)
                properties.append({
                    "iri": str(subject),
                    "type": "ObjectProperty" if prop_type == OWL.ObjectProperty else "DatatypeProperty",
                    "label": str(label) if label else None,
                    "domain": str(domain) if domain else None,
                    "range": str(range_) if range_ else None,
                })
        return properties

    def get_shacl_shapes(self) -> list[dict]:
        """Return all SHACL NodeShape definitions for this domain."""
        shapes = []
        for subject in self.shacl_graph.subjects(RDF.type, SH.NodeShape):
            target_class = self.shacl_graph.value(subject, SH.targetClass)
            properties = []
            for prop_shape in self.shacl_graph.objects(subject, SH.property):
                prop_info = self._parse_shacl_property(prop_shape)
                if prop_info:
                    properties.append(prop_info)
            shapes.append({
                "shape_iri": str(subject),
                "target_class": str(target_class) if target_class else None,
                "properties": properties,
            })
        return shapes

    def _parse_shacl_property(self, prop_shape) -> Optional[dict]:
        """Parse a single SHACL PropertyShape into a dict."""
        path = self.shacl_graph.value(prop_shape, SH.path)
        datatype = self.shacl_graph.value(prop_shape, SH.datatype)
        min_count = self.shacl_graph.value(prop_shape, SH.minCount)
        max_count = self.shacl_graph.value(prop_shape, SH.maxCount)
        name = self.shacl_graph.value(prop_shape, SH.name)
        description = self.shacl_graph.value(prop_shape, SH.description)

        # Parse sh:in enum values (simplified — RDF list parsing not needed for schema display)
        in_values = []

        return {
            "path": str(path) if path else None,
            "datatype": str(datatype) if datatype else None,
            "minCount": int(min_count) if min_count is not None else None,
            "maxCount": int(max_count) if max_count is not None else None,
            "name": str(name) if name else None,
            "description": str(description) if description else None,
            "allowedValues": in_values if in_values else None,
        }


class SchemaProvider:
    """Provides schema definitions for all configured ontology domains.

    Used by the MCP governance gateway's `get_{domain}_schema` tool
    to tell the LLM what structure a domain requires.
    """

    def __init__(self, owl_dir: str, shacl_dir: str, domains: list) -> None:
        self._domains: dict[str, DomainSchema] = {}
        owl_root = Path(owl_dir)
        shacl_root = Path(shacl_dir)

        for domain in domains:
            name = domain if isinstance(domain, str) else domain.name
            owl_file = domain if isinstance(domain, str) else domain.owl_file
            shacl_file = domain if isinstance(domain, str) else domain.shacl_file

            owl_path = owl_root / owl_file
            shacl_path = shacl_root / shacl_file

            if owl_path.exists():
                self._domains[name] = DomainSchema(name, owl_path, shacl_path)
                logger.info("Loaded domain schema: %s", name)
            else:
                logger.warning("OWL file not found for domain '%s': %s", name, owl_path)

    def list_domains(self) -> list[str]:
        """Return all available domain names."""
        return list(self._domains.keys())

    def get_domain(self, name: str) -> Optional[DomainSchema]:
        """Get a domain schema by name."""
        return self._domains.get(name)

    def get_schema_definition(self, domain_name: str) -> dict:
        """Return the full schema definition for a domain.

        This is the payload returned by `get_{domain}_schema`.
        Contains classes, properties, and SHACL shapes.
        """
        domain = self.get_domain(domain_name)
        if domain is None:
            return {
                "domain": domain_name,
                "error": f"Unknown domain: {domain_name}",
                "available_domains": self.list_domains(),
            }

        return {
            "domain": domain_name,
            "classes": domain.get_classes(),
            "properties": domain.get_properties(),
            "shacl_shapes": domain.get_shacl_shapes(),
            "owl_path": str(domain.owl_path),
            "shacl_path": str(domain.shacl_path),
        }
