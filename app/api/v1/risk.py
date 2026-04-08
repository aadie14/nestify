"""Risk API — Multi-factor risk analysis endpoints."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException

from app.database import get_project
from app.intelligence.graph_builder import build_project_graph
from app.intelligence.risk_engine import assess_project
from app.storage.neo4j_client import get_neo4j_client

router = APIRouter()


@router.get("/{project_id}")
async def get_risk_analysis(project_id: int):
    """Return multi-factor risk analysis for a project.

    Uses the code graph for reachability-aware scoring.
    Factors: Exploitability × Impact × Reachability × Sensitivity.
    """
    project = get_project(project_id)
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")

    security_report = project.get("security_report")
    if not security_report:
        raise HTTPException(status_code=404, detail="No security scan data — run a scan first")

    # Try to load the code graph
    client = await get_neo4j_client()
    graph = await client.get_graph(str(project_id))

    # Run risk assessment
    risk_report = assess_project(security_report, graph)

    return risk_report.to_dict()
