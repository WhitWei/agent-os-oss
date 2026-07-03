"""Neo4j client with connection pooling and transaction support."""

from __future__ import annotations

import logging
from contextlib import asynccontextmanager
from typing import Any, AsyncIterator, Optional

from neo4j import AsyncGraphDatabase, AsyncSession, AsyncTransaction
from agentos_kernel.config import Neo4jConfig
from agentos_kernel.exceptions import Neo4jConnectionError

logger = logging.getLogger(__name__)


class Neo4jClient:
    """Async Neo4j client wrapping the official neo4j driver.

    Provides connection pooling, health checks, transaction management,
    and helper methods for common graph operations.
    """

    def __init__(self, config: Neo4jConfig) -> None:
        self._config = config
        self._driver = AsyncGraphDatabase.driver(
            config.uri,
            auth=(config.user, config.password),
            max_connection_lifetime=3600,
            max_connection_pool_size=10,
        )
        logger.info("Neo4j driver initialized for %s", config.uri)

    async def close(self) -> None:
        """Close the driver and release all connections."""
        await self._driver.close()
        logger.info("Neo4j driver closed")

    async def health_check(self) -> bool:
        """Verify Neo4j connectivity and return True if healthy."""
        try:
            async with self._driver.session(database=self._config.database) as session:
                result = await session.run("RETURN 1 AS ok")
                record = await result.single()
                return record is not None and record["ok"] == 1
        except Exception as exc:
            logger.error("Neo4j health check failed: %s", exc)
            return False

    @asynccontextmanager
    async def session(self) -> AsyncIterator[AsyncSession]:
        """Context manager for a Neo4j session."""
        async with self._driver.session(
            database=self._config.database
        ) as session:
            yield session

    @asynccontextmanager
    async def transaction(self) -> AsyncIterator[AsyncTransaction]:
        """Context manager for a read/write transaction."""
        async with self.session() as session:
            tx = await session.begin_transaction()
            try:
                yield tx
            finally:
                if not tx.closed():
                    await tx.rollback()

    async def execute_write(self, cypher: str, params: dict[str, Any] | None = None) -> list[dict[str, Any]]:
        """Execute a write Cypher query and return results."""
        async with self.transaction() as tx:
            result = await tx.run(cypher, params or {})
            records = await result.data()
            await tx.commit()
            logger.debug("Write executed: %d records", len(records))
            return records

    async def execute_write_batch(self, statements: list[str]) -> int:
        """Execute multiple write Cypher queries within a single transaction."""
        total_written = 0
        async with self.transaction() as tx:
            for cypher in statements:
                if cypher.strip():
                    result = await tx.run(cypher, {})
                    summary = await result.consume()
                    total_written += summary.counters.nodes_created
                    total_written += summary.counters.relationships_created
            await tx.commit()
            logger.debug("Write batch executed: %d queries, %d records created", len(statements), total_written)
            return total_written

    async def execute_read(self, cypher: str, params: dict[str, Any] | None = None) -> list[dict[str, Any]]:
        """Execute a read-only Cypher query and return results."""
        async with self.session() as session:
            result = await session.run(cypher, params or {})
            records = await result.data()
            logger.debug("Read executed: %d records", len(records))
            return records

    async def get_node_by_id(self, node_id: str) -> Optional[dict[str, Any]]:
        """Retrieve a single node by its ID."""
        records = await self.execute_read(
            "MATCH (n) WHERE elementId(n) = $node_id RETURN n, labels(n) AS labels",
            {"node_id": node_id},
        )
        if records:
            record = records[0]
            return {
                "id": node_id,
                "labels": record.get("labels", []),
                "properties": dict(record.get("n", {})),
            }
        return None

    async def init_n10s(self) -> bool:
        """Initialize Neosemantics (n10s) plugin configuration.

        Sets up the n10s graph config for W3C RDF mode and creates
        a uniqueness constraint on Resource URIs.
        """
        try:
            # Create constraint for Resource URIs
            await self.execute_write(
                """
                CREATE CONSTRAINT n10s_unique_uri IF NOT EXISTS
                FOR (r:Resource) REQUIRE r.uri IS UNIQUE
                """
            )

            # Initialize n10s graph config for RDF
            await self.execute_write(
                """
                CALL n10s.graphconfig.init({
                    handleMultival: 'ARRAY',
                    multivalPropList: [
                        'http://www.w3.org/2000/01/rdf-schema#label',
                        'http://www.w3.org/2000/01/rdf-schema#comment'
                    ]
                })
                """
            )
            logger.info("Neosemantics (n10s) initialized successfully")
            return True
        except Exception as exc:
            logger.error("Failed to initialize n10s: %s", exc)
            return False
