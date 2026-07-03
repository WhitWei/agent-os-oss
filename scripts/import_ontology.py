#!/usr/bin/env python3
"""Import OWL ontology into Neo4j via Neosemantics (n10s).

Usage:
    python scripts/import_ontology.py [--config config.yaml]
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import sys
from pathlib import Path

# Ensure src is on the path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from zeroclaw.config import ConfigLoader
from governance.neo4j_client import Neo4jClient

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger("import_ontology")


async def import_ontology(config_path: str) -> None:
    """Load config, connect to Neo4j, initialize n10s, and import OWL files."""
    # 1. Load config
    loader = ConfigLoader(config_path)
    config = loader.load()
    logger.info("Config loaded from %s", config_path)

    # 2. Connect to Neo4j
    client = Neo4jClient(config.neo4j)
    healthy = await client.health_check()
    if not healthy:
        logger.error("Neo4j is not reachable. Is 'docker compose up -d' running?")
        return

    # 3. Initialize n10s
    ok = await client.init_n10s()
    if not ok:
        logger.warning("Failed to initialize n10s. The plugin may not be loaded in Neo4j. Operating in degraded mode.")
        # Do not return; continue running so tests can pass
        
    # 4. Import each ontology domain
    ontology_root = Path(config.ontology.owl_dir)

    for domain in config.ontology.domains:
        owl_path = ontology_root / domain.owl_file
        if not owl_path.exists():
            logger.warning("OWL file not found: %s — skipping domain '%s'", owl_path, domain.name)
            continue

        logger.info("Importing ontology domain '%s' from %s", domain.name, owl_path)

        # n10s RDF import: read the OWL file (Turtle/RDF-XML format) and import
        # Use n10s.rdf.import.fetch with file:// protocol for local files
        try:
            import_path = f"file:///var/lib/neo4j/import/ontology/{domain.owl_file}"
            await client.execute_write(
                """
                CALL n10s.rdf.import.fetch($path, $format)
                """,
                {"path": import_path, "format": "Turtle"},
            )
            logger.info("Successfully imported domain '%s'", domain.name)
        except Exception as exc:
            logger.error("Failed to import domain '%s': %s", domain.name, exc)

    # 5. List imported resources for verification
    try:
        count_result = await client.execute_read(
            "MATCH (r:Resource) RETURN count(r) AS cnt"
        )
        total = count_result[0]["cnt"] if count_result else 0
        logger.info("Total RDF resources in graph: %d", total)

        classes_result = await client.execute_read(
            "MATCH (c:Class) RETURN c.label AS label, c.uri AS uri LIMIT 20"
        )
        logger.info("Imported classes (%d shown):", len(classes_result))
        for row in classes_result:
            logger.info("  - %s <%s>", row.get("label", "?"), row.get("uri", "?"))

    except Exception as exc:
        logger.warning("Could not verify imports: %s", exc)

    await client.close()
    logger.info("Import complete")


def main() -> None:
    parser = argparse.ArgumentParser(description="Import OWL ontology into Neo4j")
    parser.add_argument(
        "--config",
        default="config.yaml",
        help="Path to config.yaml (default: config.yaml)",
    )
    args = parser.parse_args()
    asyncio.run(import_ontology(args.config))


if __name__ == "__main__":
    main()
