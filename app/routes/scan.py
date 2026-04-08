"""Security rescan route for existing projects."""

from __future__ import annotations

import json

from fastapi import APIRouter, HTTPException

from app.agents.security_agent import SecurityAgent
from app.database import get_project, update_project
from app.routes.upload import _append_progress, pipeline_progress
from app.services.project_source_service import load_source_text_map

router = APIRouter()


@router.post("/{project_id}")
async def scan(project_id: int):
    """Trigger a manual security rescan on an existing project."""
    project = get_project(project_id)
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")

    # Load files from disk
    files = [
        {"name": path, "content": content}
        for path, content in load_source_text_map(project_id).items()
    ]
    if not files:
        raise HTTPException(status_code=400, detail="No source files found for this project.")

    agent = SecurityAgent(project_id)

    try:
        pipeline_progress.setdefault(project_id, [])
        _append_progress(project_id, {
            "agent": "SecurityAgent",
            "phase": "scanning",
            "message": "Manual security rescan started.",
        })

        result = await agent.scan(files)

        update_project(project_id, {
            "security_report": result.report,
            "security_score": result.score,
        })

        return {
            "report": result.report,
            "security_score": result.score,
            "summary": result.summary,
            "metadata": result.metadata,
        }
    except Exception as error:
        raise HTTPException(status_code=500, detail=str(error))
