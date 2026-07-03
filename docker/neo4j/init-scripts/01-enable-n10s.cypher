// 01-enable-n10s.cypher
// Auto-executed on first Neo4j container startup via docker-entrypoint-initdb.d
// Creates constraints and initializes Neosemantics (n10s) for RDF/OWL support.

// ── 1. Create uniqueness constraint for Resource URIs ──
CREATE CONSTRAINT n10s_unique_uri IF NOT EXISTS
FOR (r:Resource) REQUIRE r.uri IS UNIQUE;

// ── 2. Create constraint for Ontology entities ──
CREATE CONSTRAINT ontology_unique_iri IF NOT EXISTS
FOR (o:OntologyEntity) REQUIRE o.iri IS UNIQUE;

// ── 3. Initialize n10s graph config (W3C RDF mode) ──
// Note: This runs after n10s plugin is loaded. Since init scripts
// run before the DB is fully online, n10s procedures may not be
// available yet. The import_ontology.py script handles the actual
// n10s initialization. This file sets up pre-requisite constraints.

// ── 4. Create standard RDF namespace indices ──
CREATE INDEX rdf_type_idx IF NOT EXISTS FOR (n) ON (n.rdfType);
CREATE INDEX rdf_label_idx IF NOT EXISTS FOR (n) ON (n.label);
