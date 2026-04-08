"""Graph API — Dependency graph query endpoints."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from app.storage.neo4j_client import get_neo4j_client

router = APIRouter()


class GraphResponse(BaseModel):
    project_id: str
    nodes: list[dict]
    edges: list[dict]
    stats: dict


@router.get("/{project_id}")
async def get_graph(project_id: int):
    """Return the code dependency graph for a project.

    Returns nodes (Files, Functions, Classes, Imports) and edges
    (CONTAINS, CALLS, IMPORTS, DEPENDS_ON, INHERITS).
    """
    client = await get_neo4j_client()
    graph = await client.get_graph(str(project_id))

    if not graph or not graph.nodes:
        raise HTTPException(status_code=404, detail="No graph data found for this project")

    return graph.to_dict()


@router.get("/{project_id}/callers/{node_id:path}")
async def get_callers(project_id: int, node_id: str):
    """Find all nodes that call a specific function."""
    client = await get_neo4j_client()
    callers = await client.query_callers(str(project_id), node_id)
    return {"node_id": node_id, "callers": callers}


@router.get("/{project_id}/dependents/{node_id:path}")
async def get_dependents(project_id: int, node_id: str):
    """Find all nodes that depend on a specific node."""
    client = await get_neo4j_client()
    dependents = await client.query_dependents(str(project_id), node_id)
    return {"node_id": node_id, "dependents": dependents}
