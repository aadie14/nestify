"""Fix route — apply automatic remediation to an existing project."""

from __future__ import annotations

import json
from dataclasses import asdict

from fastapi import APIRouter, HTTPException

from app.agents.fix_agent import FixAgent
from app.agents.deployment_agent import DeploymentAgent
from app.agents.security_agent import SecurityAgent
from app.core.config import settings
from app.database import add_deployment, add_log, get_project, update_project
from app.routes.upload import _append_progress, pipeline_progress
from app.services.deployment_service import deploy_static_locally, extract_static_bundle_from_project
from app.services.project_source_service import load_source_text_map

router = APIRouter()


def _safe_json(value):
    if isinstance(value, str):
        return json.loads(value or "{}")
    return value or {}


@router.post("/{project_id}")
async def fix(project_id: int):
    """Apply automatic fixes for a project's security findings."""
    project = get_project(project_id)
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")

    # Load security report
    security_report = project.get("security_report", {})
    if isinstance(security_report, str):
        security_report = json.loads(security_report or "{}")

    if not any(security_report.get(sev) for sev in ("critical", "high", "medium")):
        return {"message": "No fixable security issues found.", "applied": [], "manual_review": []}

    # Load files from disk
    files = [
        {"name": path, "content": content}
        for path, content in load_source_text_map(project_id).items()
    ]

    agent = FixAgent(project_id)

    try:
        pipeline_progress.setdefault(project_id, [])
        _append_progress(project_id, {
            "agent": "FixAgent",
            "phase": "fixing",
            "message": "Manual fix requested.",
        })

        result = await agent.generate_and_apply(files, security_report)

        fix_report = {
            "applied": [asdict(a) for a in result.applied],
            "manual_review": [asdict(a) for a in result.manual_review],
            "env_vars_detected": result.env_vars_detected,
        }
        update_project(project_id, {"fix_report": fix_report})

        return fix_report
    except Exception as error:
        add_log(project_id, "FixAgent", f"Manual fix failed: {error}", "error")
        raise HTTPException(status_code=500, detail=str(error))


@router.post("/{project_id}/defer")
async def defer_to_user(project_id: int):
    """Mark project as awaiting user-owned remediation changes."""
    project = get_project(project_id)
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")

    pipeline_progress.setdefault(project_id, [])
    _append_progress(project_id, {
        "agent": "FixAgent",
        "phase": "deferred_to_user",
        "message": "User chose manual remediation. Waiting for user changes.",
    })
    update_project(project_id, {"status": "completed"})
    add_log(project_id, "FixAgent", "User chose manual remediation path", "info")
    return {"status": "ok", "message": "Project set to manual remediation mode."}


@router.post("/{project_id}/auto-apply-deploy")
async def auto_apply_and_deploy(project_id: int):
    """Apply recommended fixes automatically, rescan, and prepare deploy gate."""
    project = get_project(project_id)
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")

    security_report = _safe_json(project.get("security_report"))
    source_payload = _safe_json(project.get("source_payload"))

    files = [
        {"name": path, "content": content}
        for path, content in load_source_text_map(project_id).items()
    ]

    if not files:
        raise HTTPException(status_code=400, detail="No source files available for remediation.")

    pipeline_progress.setdefault(project_id, [])
    try:
        _append_progress(project_id, {
            "agent": "FixAgent",
            "phase": "fixing",
            "message": "Auto-Fix approved. Applying recommended changes...",
        })

        # 1) Apply fixes through simulation-gated FixAgent.
        fix_agent = FixAgent(project_id)
        fix_result = await fix_agent.generate_and_apply(files, security_report)
        fix_report = {
            "applied": [asdict(a) for a in fix_result.applied],
            "manual_review": [asdict(a) for a in fix_result.manual_review],
            "env_vars_detected": fix_result.env_vars_detected,
            "simulation_blocked": [asdict(a) for a in fix_result.simulation_blocked],
        }
        update_project(project_id, {"fix_report": fix_report, "status": "fixing"})

        # 2) Rescan after fixes.
        refreshed_files = [
            {"name": path, "content": content}
            for path, content in load_source_text_map(project_id).items()
        ]
        security_agent = SecurityAgent(project_id)
        _append_progress(project_id, {
            "agent": "SecurityAgent",
            "phase": "rescanning",
            "message": "Rescanning after approved remediation...",
        })
        rescan = await security_agent.scan(refreshed_files)
        update_project(project_id, {
            "security_report": rescan.report,
            "security_score": rescan.score,
            "status": "scanning",
        })

        # 3) Build post-rescan deployment checklist and wait for user confirmation.
        critical_count = len(rescan.report.get("critical", []))
        high_count = len(rescan.report.get("high", []))

        high_dep_findings = [
            finding
            for finding in rescan.report.get("high", [])
            if str(finding.get("type", "")).lower() in {"dependency_vuln", "outdated_dependency"}
            or "dependency" in str(finding.get("title", "")).lower()
        ]

        deployment_safe = (critical_count == 0 and high_count == 0 and rescan.score >= settings.security_score_threshold)
        simulation_passed = len(fix_result.simulation_blocked) == 0
        no_high_risk_dependencies = len(high_dep_findings) == 0
        ready_to_deploy = deployment_safe and simulation_passed and no_high_risk_dependencies

        deployment_gate = {
            "security_score": rescan.score,
            "score_target": max(settings.security_score_threshold, 82),
            "simulation_passed": simulation_passed,
            "no_high_risk_dependencies": no_high_risk_dependencies,
            "deployment_safe": deployment_safe,
            "ready_to_deploy": ready_to_deploy,
            "critical_count": critical_count,
            "high_count": high_count,
        }

        fix_report["deployment_gate"] = deployment_gate

        existing_pipeline_state = _safe_json(project.get("pipeline_state"))
        existing_pipeline_state["deployment_gate"] = "ready" if ready_to_deploy else "review_required"

        update_project(project_id, {
            "fix_report": fix_report,
            "pipeline_state": existing_pipeline_state,
            "status": "completed",
        })

        _append_progress(project_id, {
            "agent": "DeploymentAgent",
            "phase": "ready_for_deploy",
            "message": "Remediation complete. Review checklist and click Deploy Now.",
            "data": deployment_gate,
        })

        return {
            "status": "ok",
            "security_score": rescan.score,
            "fix_report": fix_report,
            "deployment": None,
            "deployment_gate": deployment_gate,
        }
    except Exception as error:
        add_log(project_id, "FixAgent", f"Auto-fix-and-deploy failed: {error}", "error")
        _append_progress(project_id, {
            "agent": "Orchestrator",
            "phase": "error",
            "message": str(error),
        })
        raise HTTPException(status_code=500, detail=str(error))
