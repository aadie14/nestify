"""Neo4j Client — Graph database adapter with in-memory fallback.

Provides async-compatible operations for persisting and querying code graphs.
Falls back to an in-memory NetworkX graph when Neo4j is unreachable—ensuring
the intelligence pipeline never blocks on infrastructure.
"""

from __future__ import annotations

import logging
from typing import Any

from app.intelligence.graph_builder import CodeGraph, GraphEdge, GraphNode, NodeType, RelationType

logger = logging.getLogger(__name__)

# ─── In-Memory Fallback ──────────────────────────────────────────────────

_in_memory_graphs: dict[str, CodeGraph] = {}


class Neo4jClient:
    """Async Neo4j driver wrapper with graceful in-memory fallback.

    If Neo4j is available, all operations go through the Bolt driver.
    If unavailable, operations are redirected to an in-memory store
    so the pipeline continues unblocked.
    """

    def __init__(
        self,
        uri: str = "bolt://localhost:7687",
        user: str = "neo4j",
        password: str = "nestify",
    ) -> None:
        self._uri = uri
        self._user = user
        self._password = password
        self._driver: Any = None
        self._connected = False

    # ── Connection ────────────────────────────────────────────────────

    async def connect(self) -> bool:
        """Attempt to connect to Neo4j.  Returns True if successful."""
        try:
            from neo4j import AsyncGraphDatabase  # type: ignore[import-untyped]
            self._driver = AsyncGraphDatabase.driver(
                self._uri, auth=(self._user, self._password),
            )
            # Verify connectivity
            async with self._driver.session() as session:
                await session.run("RETURN 1")
            self._connected = True
            logger.info("Connected to Neo4j at %s", self._uri)
        except Exception as exc:
            logger.warning(
                "Neo4j unavailable (%s) — using in-memory graph fallback", exc,
            )
            self._connected = False
        return self._connected

    async def close(self) -> None:
        if self._driver:
            await self._driver.close()
            self._driver = None
            self._connected = False

    @property
    def is_connected(self) -> bool:
        return self._connected

    # ── Write Operations ──────────────────────────────────────────────

    async def store_graph(self, project_id: str, graph: CodeGraph) -> None:
        """Persist a code graph for the given project.

        If Neo4j is available, upserts nodes and relationships.
        Otherwise stores in the in-memory dict.
        """
        if self._connected:
            await self._neo4j_store(project_id, graph)
        else:
            _in_memory_graphs[project_id] = graph

    async def _neo4j_store(self, project_id: str, graph: CodeGraph) -> None:
        """Persist graph to Neo4j using batched Cypher queries."""
        async with self._driver.session() as session:
            # Clear old graph for this project
            await session.run(
                "MATCH (n {project_id: $pid}) DETACH DELETE n",
                pid=project_id,
            )

            # Batch-create nodes
            for node in graph.nodes:
                await session.run(
                    """
                    CREATE (n:CodeNode {
                        id: $id,
                        project_id: $pid,
                        type: $type,
                        name: $name,
                        file_path: $file_path,
                        line_start: $line_start,
                        line_end: $line_end
                    })
                    """,
                    id=node.id, pid=project_id, type=node.type.value,
                    name=node.name, file_path=node.file_path,
                    line_start=node.line_start, line_end=node.line_end,
                )

            # Create relationships
            for edge in graph.edges:
                await session.run(
                    """
                    MATCH (a:CodeNode {id: $src, project_id: $pid})
                    MATCH (b:CodeNode {id: $tgt, project_id: $pid})
                    CREATE (a)-[r:RELATES {type: $rel}]->(b)
                    """,
                    src=edge.source_id, tgt=edge.target_id,
                    rel=edge.relation.value, pid=project_id,
                )

        logger.info("Stored %d nodes and %d edges in Neo4j for project %s",
                     len(graph.nodes), len(graph.edges), project_id)

    # ── Read Operations ───────────────────────────────────────────────

    async def get_graph(self, project_id: str) -> CodeGraph | None:
        """Retrieve the stored graph for a project."""
        if self._connected:
            return await self._neo4j_get(project_id)
        return _in_memory_graphs.get(project_id)

    async def _neo4j_get(self, project_id: str) -> CodeGraph:
        """Read graph back from Neo4j."""
        graph = CodeGraph()

        async with self._driver.session() as session:
            # Read nodes
            result = await session.run(
                "MATCH (n:CodeNode {project_id: $pid}) RETURN n",
                pid=project_id,
            )
            async for record in result:
                n = record["n"]
                graph.nodes.append(GraphNode(
                    id=n["id"],
                    type=NodeType(n["type"]),
                    name=n["name"],
                    file_path=n["file_path"],
                    line_start=n["line_start"],
                    line_end=n["line_end"],
                ))

            # Read edges
            result = await session.run(
                """
                MATCH (a:CodeNode {project_id: $pid})-[r:RELATES]->(b:CodeNode {project_id: $pid})
                RETURN a.id AS src, b.id AS tgt, r.type AS rel
                """,
                pid=project_id,
            )
            async for record in result:
                graph.edges.append(GraphEdge(
                    source_id=record["src"],
                    target_id=record["tgt"],
                    relation=RelationType(record["rel"]),
                ))

        return graph

    async def clear_project(self, project_id: str) -> None:
        """Remove all graph data for a project."""
        if self._connected:
            async with self._driver.session() as session:
                await session.run(
                    "MATCH (n {project_id: $pid}) DETACH DELETE n",
                    pid=project_id,
                )
        else:
            _in_memory_graphs.pop(project_id, None)

    async def query_callers(self, project_id: str, node_id: str) -> list[dict[str, Any]]:
        """Find all nodes that call a specific function.

        Works in both Neo4j and in-memory modes.
        """
        graph = await self.get_graph(project_id)
        if not graph:
            return []
        callers = graph.get_callers(node_id)
        return [{"id": c.id, "name": c.name, "type": c.type.value, "file": c.file_path} for c in callers]

    async def query_dependents(self, project_id: str, node_id: str) -> list[dict[str, Any]]:
        """Find all nodes that depend on a specific node."""
        graph = await self.get_graph(project_id)
        if not graph:
            return []
        deps = graph.get_dependents(node_id)
        return [{"id": d.id, "name": d.name, "type": d.type.value, "file": d.file_path} for d in deps]


# ─── Module-Level Singleton ──────────────────────────────────────────────

_client: Neo4jClient | None = None


async def get_neo4j_client() -> Neo4jClient:
    """Return the shared Neo4j client, initializing on first call."""
    global _client
    if _client is None:
        from app.core.config import settings
        _client = Neo4jClient(
            uri=settings.neo4j_uri,
            user=settings.neo4j_user,
            password=settings.neo4j_password,
        )
        await _client.connect()
    return _client
