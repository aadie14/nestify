"""Graph query tool that wraps existing Neo4j/in-memory graph client."""

from __future__ import annotations

import asyncio
import json
from typing import Any

from app.storage.neo4j_client import get_neo4j_client


class GraphQueryTool:
    name: str = "Query Code Graph"
    description: str = "Query project graph: get_complexity|get_callers|get_dependents|get_summary"

    def _run(self, query: str) -> str:
        return asyncio.run(self._arun(query))

    async def _arun(self, query: str) -> str:
        try:
            payload = json.loads(query)
        except json.JSONDecodeError:
            return json.dumps({"ok": False, "error": "query must be valid JSON"})

        project_id = str(payload.get("project_id") or "")
        query_type = str(payload.get("query_type") or "get_summary")
        node_id = str(payload.get("node_id") or "")

        if not project_id:
            return json.dumps({"ok": False, "error": "project_id required"})

        client = await get_neo4j_client()

        if query_type == "get_callers":
            data = await client.query_callers(project_id, node_id)
            return json.dumps({"ok": True, "query_type": query_type, "data": data})

        if query_type == "get_dependents":
            data = await client.query_dependents(project_id, node_id)
            return json.dumps({"ok": True, "query_type": query_type, "data": data})

        graph = await client.get_graph(project_id)
        if not graph:
            return json.dumps({"ok": True, "query_type": query_type, "data": {"nodes": 0, "edges": 0}})

        summary = {
            "nodes": len(graph.nodes),
            "edges": len(graph.edges),
            "node_types": graph.get_stats().get("node_types", {}),
            "relation_types": graph.get_stats().get("relation_types", {}),
            "complexity": graph.get_stats().get("complexity_score", 0),
        }
        return json.dumps({"ok": True, "query_type": query_type, "data": summary})
