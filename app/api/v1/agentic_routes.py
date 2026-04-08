"""Agentic API endpoints (additive, backward compatible)."""

from __future__ import annotations

import json
from collections import Counter
from pathlib import Path
from typing import Any

from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field

from app.database import get_project
from app.learning import InsightExtractor, PatternStore, SimilarityEngine
from app.api.v1.optimization import apply_project_optimization, analyze_project_optimization, ApplyOptimizationRequest

router = APIRouter()


class AgenticOptimizeRequest(BaseModel):
    memory_mb: int | None = Field(default=None, ge=128, le=8192)
    cpu: float | None = Field(default=None, ge=0.1, le=8.0)
    provider: str | None = None
    note: str | None = None


@router.get("/projects/{project_id}/report/pdf")
async def download_security_report(project_id: int):
    """Download generated security PDF report for a project."""

    project = get_project(project_id)
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")

    pdf_path = project.get("security_report_pdf")
    if not pdf_path:
        raise HTTPException(status_code=404, detail="PDF report not generated yet")

    file_path = Path(str(pdf_path))
    if not file_path.exists() or not file_path.is_file():
        raise HTTPException(status_code=404, detail="PDF report not found on disk")

    return FileResponse(
        path=str(file_path),
        media_type="application/pdf",
        filename=f"security_report_{project.get('name', 'project')}_{project_id}.pdf",
    )


@router.get("/stats")
async def get_agentic_stats(limit: int = 2000) -> dict[str, Any]:
    """Return learning statistics for the agentic system."""
    store = PatternStore()
    rows = store.recent_patterns(limit=max(1, min(limit, 20000)))

    outcome_counter: Counter[str] = Counter()
    for row in rows:
        outcome_counter[str(row.get("outcome") or "unknown").lower()] += 1

    total = len(rows)
    success = outcome_counter.get("live", 0) + outcome_counter.get("success", 0) + outcome_counter.get("completed", 0)
    success_rate = round(success / total, 4) if total else 0.0

    return {
        "total_deployments_analyzed": total,
        "patterns_discovered": total,
        "success_rate": success_rate,
        "outcomes": dict(outcome_counter),
    }


@router.get("/patterns/{project_id}")
async def get_similar_patterns(project_id: int, limit: int = 10) -> dict[str, Any]:
    """Find similar historical deployment patterns for a project."""
    project = get_project(project_id)
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")

    insights = project.get("agentic_insights")
    if isinstance(insights, str):
        try:
            insights = json.loads(insights)
        except json.JSONDecodeError:
            insights = {}
    if not isinstance(insights, dict):
        insights = {}

    code_profile = insights.get("code_profile") or {}
    if not code_profile:
        raise HTTPException(status_code=400, detail="Project has no code_profile in agentic insights")

    store = PatternStore()
    engine = SimilarityEngine()
    extractor = InsightExtractor()

    matches = await store.find_similar(code_profile=code_profile, limit=limit)
    ranked = engine.rank(matches=matches, code_profile=code_profile, limit=limit)
    insights_summary = extractor.extract_insights(ranked)

    return {
        "project_id": project_id,
        "similar_patterns": ranked,
        "insights": insights_summary,
    }


@router.post("/optimize/{project_id}")
async def apply_optimization(project_id: int, payload: AgenticOptimizeRequest) -> dict[str, Any]:
    """Analyze then apply optimization suggestion for a project."""
    _ = await analyze_project_optimization(project_id=project_id)

    result = await apply_project_optimization(
        project_id=project_id,
        payload=ApplyOptimizationRequest(
            memory_mb=payload.memory_mb,
            cpu=payload.cpu,
            provider=payload.provider,
            note=payload.note or "Applied via /api/v1/agentic/optimize",
        ),
    )

    return {
        "status": "ok",
        "project_id": project_id,
        "optimization": result,
    }
