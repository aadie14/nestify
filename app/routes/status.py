"""Pipeline status API — returns project data, progress, and logs."""

from __future__ import annotations

import json

from fastapi import APIRouter, HTTPException

from app.database import get_deployment, get_fix_logs, get_project, get_project_logs, get_scan_results
from app.routes.upload import pipeline_progress

router = APIRouter()


def _safe_json(value):
    """Parse JSON strings into dicts; pass through other types."""
    if value is None or isinstance(value, (dict, list, int, float)):
        return value
    try:
        return json.loads(value)
    except (json.JSONDecodeError, TypeError):
        return value


def _normalize_pipeline_state(raw_value):
    parsed = _safe_json(raw_value)
    if not isinstance(parsed, dict):
        return {}, {}

    if isinstance(parsed.get("pipeline_states"), dict):
        return parsed["pipeline_states"], parsed.get("execution_state") or {}

    return parsed, {}


@router.get("/{project_id}")
async def get_status(project_id: int):
    """Get the full status of a project including scan results, fixes, and deployment."""
    project = get_project(project_id)
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")

    deployment = get_deployment(project_id)
    pipeline_state, execution_state = _normalize_pipeline_state(project.get("pipeline_state"))

    return {
        "project": {
            "id": project["id"],
            "name": project["name"],
            "input_type": project["input_type"],
            "status": project["status"],
            "security_report": _safe_json(project.get("security_report")),
            "security_score": project.get("security_score", 0),
            "fix_report": _safe_json(project.get("fix_report")),
            "agentic_insights": _safe_json(project.get("agentic_insights")),
            "preferred_provider": project.get("preferred_provider"),
            "public_url": project.get("public_url"),
            "pipeline_state": pipeline_state,
            "execution_state": execution_state,
            "created_at": project.get("created_at"),
        },
        "scan_results": get_scan_results(project_id),
        "fix_logs": get_fix_logs(project_id),
        "deployment": dict(deployment) if deployment else None,
        "progress": pipeline_progress.get(project_id, []),
        "logs": get_project_logs(project_id),
    }
