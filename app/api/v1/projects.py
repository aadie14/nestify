"""Project-centric V1 API surface for upload, reports, deployment, and realtime updates."""

from __future__ import annotations

import asyncio
import json
import os
from dataclasses import asdict
from datetime import datetime, timezone
from typing import Any

from fastapi import APIRouter, BackgroundTasks, File, Form, HTTPException, UploadFile, WebSocket, WebSocketDisconnect
from fastapi.responses import Response
from pydantic import BaseModel, Field

from app.agents.fix_agent import FixAgent
from app.agents.security_agent import SecurityAgent
from app.core.orchestrator import AgentOrchestrator
from app.database import (
    add_log,
    get_deployment,
    get_fix_logs,
    get_project,
    get_project_logs,
    get_scan_results,
    list_deployment_outcomes,
    update_project,
)
from app.reports.pdf_generator import SecurityPdfGenerator
from app.routes.deploy import deploy as manual_deploy
from app.routes.upload import _append_progress, pipeline_progress, upload as legacy_upload
from app.services.project_source_service import ensure_preview_index, get_local_preview_url, load_source_text_map

router = APIRouter()

_SUPPORTED_DEPLOY_PROVIDERS = {"vercel", "netlify", "railway", "local"}
_ANALYSIS_READY_STATES = {"done", "complete", "completed", "success", "skipped"}


def _analysis_completed(project: dict[str, Any]) -> bool:
    status = str(project.get("status") or "").strip().lower()
    if status in {"completed", "live", "deploying", "failed"}:
        return True

    pipeline_raw = _parse_json(project.get("pipeline_state"))
    pipeline_states: dict[str, Any] = {}
    if isinstance(pipeline_raw, dict):
        nested = pipeline_raw.get("pipeline_states")
        if isinstance(nested, dict):
            pipeline_states = nested
        else:
            pipeline_states = pipeline_raw

    required_steps = [
        "code_analysis",
        "agent_debate",
        "security_audit",
    ]
    if not pipeline_states:
        return False

    for step in required_steps:
        state = str(pipeline_states.get(step) or "").strip().lower()
        if state not in _ANALYSIS_READY_STATES:
            return False
    return True


def _normalize_provider(provider: Any) -> str | None:
    normalized = str(provider or "").strip().lower()
    if not normalized:
        return None
    return normalized if normalized in _SUPPORTED_DEPLOY_PROVIDERS else None


def _format_deploy_failure(detail: Any) -> tuple[str, str, dict[str, Any]]:
    payload = detail if isinstance(detail, dict) else {"reason": str(detail)}
    reason = str(payload.get("reason") or payload.get("plain_english_error") or "Deployment failed.").strip()
    next_action = str(payload.get("next_action") or "Fix deployment prerequisites and retry.").strip()
    return reason, next_action, payload


def _provider_fallback_order(runtime: str, current: str | None) -> str:
    active = str(current or "").strip().lower()
    candidates = ["vercel", "netlify", "local"] if runtime == "node" else ["railway", "local"]
    for candidate in candidates:
        if candidate != active:
            return candidate
    return "local"


def _success_response(result: dict[str, Any]) -> DeployResponse:
    return DeployResponse(
        status="deployed",
        deployment_url=result.get("deployment_url"),
        provider=result.get("provider"),
        details=result.get("details") if isinstance(result.get("details"), dict) else {},
        action=None,
        blocking_reason=None,
        next_action=None,
    )


class GithubImportRequest(BaseModel):
    github_url: str
    provider: str = "auto"


class DeployResponse(BaseModel):
    status: str
    deployment_url: str | None = None
    provider: str | None = None
    details: dict[str, Any] | None = None
    action: str | None = None
    blocking_reason: str | None = None
    next_action: str | None = None


@router.get("/deployment-readiness")
async def get_deployment_readiness() -> dict[str, Any]:
    """Return deployment provider readiness so UI can explain live URL prerequisites."""
    has_vercel = bool(os.getenv("VERCEL_TOKEN", "").strip())
    has_netlify = bool(os.getenv("NETLIFY_API_TOKEN", "").strip())
    has_railway = bool(os.getenv("RAILWAY_API_KEY", "").strip())
    has_github = bool(os.getenv("GITHUB_TOKEN", "").strip())

    static_ready = has_vercel or has_netlify
    backend_ready = has_railway
    static_probability = 0.85 if static_ready else 0.12
    backend_probability = 0.88 if (backend_ready and has_github) else (0.55 if backend_ready else 0.08)

    messages: list[str] = []
    if not static_ready:
        messages.append("Static apps will use local preview URLs unless VERCEL_TOKEN or NETLIFY_API_TOKEN is configured.")
    if not backend_ready:
        messages.append("Backend apps need RAILWAY_API_KEY for public live URLs.")
    if not has_github:
        messages.append("Set GITHUB_TOKEN to improve GitHub import reliability and avoid API limits.")

    return {
        "static_ready": static_ready,
        "backend_ready": backend_ready,
        "github_ready": has_github,
        "estimated_success_probability": {
            "static": static_probability,
            "backend": backend_probability,
        },
        "providers": {
            "vercel": has_vercel,
            "netlify": has_netlify,
            "railway": has_railway,
        },
        "messages": messages,
    }


@router.post("/upload")
async def upload_project(
    background_tasks: BackgroundTasks,
    file: UploadFile = File(...),
    provider: str = Form("auto"),
) -> dict[str, Any]:
    """Upload code and start autonomous analysis asynchronously."""

    response = await legacy_upload(
        request=_SyntheticRequest(agentic=True),
        file=file,
        github_url=None,
        text=None,
        filename=None,
        description=None,
        provider=provider,
        require_fix_approval=False,
        agentic=True,
    )
    payload = json.loads(response.body.decode("utf-8"))
    return {"project_id": payload["project_id"], "status": "analyzing"}


@router.post("/github")
async def import_github(payload: GithubImportRequest) -> dict[str, Any]:
    """Import a GitHub repository and trigger async analysis."""

    response = await legacy_upload(
        request=_SyntheticRequest(agentic=True),
        file=None,
        github_url=payload.github_url,
        text=None,
        filename=None,
        description=None,
        provider=payload.provider,
        require_fix_approval=False,
        agentic=True,
    )
    body = json.loads(response.body.decode("utf-8"))
    return {"project_id": body["project_id"], "status": "analyzing"}


@router.get("/{project_id}/status")
async def get_project_status(project_id: int) -> dict[str, Any]:
    """Return current project status and progress signals."""
    project = get_project(project_id)
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")

    progress = pipeline_progress.get(project_id, [])[-25:]
    parsed_pipeline = _parse_json(project.get("pipeline_state")) or {}
    if isinstance(parsed_pipeline, dict) and isinstance(parsed_pipeline.get("pipeline_states"), dict):
        pipeline_state = parsed_pipeline.get("pipeline_states") or {}
        execution_state = parsed_pipeline.get("execution_state") or {}
    else:
        pipeline_state = parsed_pipeline if isinstance(parsed_pipeline, dict) else {}
        execution_state = {}

    return {
        "project_id": project_id,
        "status": project.get("status", "unknown"),
        "pipeline_state": pipeline_state,
        "execution_state": execution_state,
        "progress": progress,
    }


@router.get("/{project_id}/report")
async def get_report(project_id: int) -> dict[str, Any]:
    """Return consolidated analysis report payload for frontend rendering."""
    project = get_project(project_id)
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")

    raw_findings = _group_findings(get_scan_results(project_id))
    project_logs = get_project_logs(project_id)
    findings = _augment_findings_with_logs(raw_findings, project_logs)
    remediation_steps = _build_remediation_steps(findings)

    report = {
        "project": {
            "id": project.get("id"),
            "name": project.get("name"),
            "status": project.get("status"),
            "security_score": int(project.get("security_score") or 0),
            "public_url": project.get("public_url"),
            "preferred_provider": project.get("preferred_provider"),
        },
        "code_profile": _parse_json(project.get("stack_info")) or {},
        "findings": findings,
        "fixes": get_fix_logs(project_id),
        "deployment": get_deployment(project_id),
        "logs": project_logs,
        "remediation_steps": remediation_steps,
        "agentic_insights": _sanitize_agentic_insights(_parse_json(project.get("agentic_insights")) or {}),
    }

    # Attach latest outcome/debate record for agent timeline visualizations.
    outcomes = [row for row in list_deployment_outcomes(limit=500) if int(row.get("project_id") or 0) == project_id]
    report["learning"] = outcomes[:3]
    return report


@router.get("/{project_id}/report/audit")
async def get_audit_report(project_id: int) -> dict[str, Any]:
    """Return a structured, audit-grade JSON report for machine/system consumption."""
    project = get_project(project_id)
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")
    return _build_audit_report_payload(project_id=project_id, project=project)


@router.get("/{project_id}/report/pdf")
async def download_pdf_report(project_id: int) -> Response:
    """Generate and download a PDF security report for the project."""
    project = get_project(project_id)
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")

    payload = _build_audit_report_payload(project_id=project_id, project=project)
    pdf_bytes = SecurityPdfGenerator().build(project=project, report=payload)
    filename = f"nestify-report-{project_id}.pdf"
    return Response(
        content=pdf_bytes,
        media_type="application/pdf",
        headers={"Content-Disposition": f"attachment; filename={filename}"},
    )


@router.post("/{project_id}/deploy", response_model=DeployResponse)
async def auto_deploy(project_id: int, provider: str | None = None) -> DeployResponse:
    """Trigger autonomous deployment for a previously analyzed project."""
    project = get_project(project_id)
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")
    if not _analysis_completed(project):
        raise HTTPException(
            status_code=409,
            detail="Analysis is still running. Deployment can start only after analysis is complete.",
        )

    requested_provider = str(provider or "").strip().lower()
    if requested_provider and requested_provider != "auto":
        if requested_provider not in _SUPPORTED_DEPLOY_PROVIDERS:
            raise HTTPException(status_code=400, detail=f"Unsupported provider '{requested_provider}'.")
        update_project(project_id, {"preferred_provider": requested_provider})

    _append_progress(
        project_id,
        {
            "agent": "DeploymentAgent",
            "phase": "deploying",
            "message": "Autonomous deploy requested. Reusing analysis context and selecting a provider based on backend compatibility, risk posture, and monthly cost fit.",
            "data": {
                "action": "Starting autonomous fix and deploy",
                "reason": "Analysis is complete and deployment prerequisites were validated",
                "result": "Deployment pipeline initiated",
            },
        },
    )

    try:
        result = await manual_deploy(project_id=project_id, force=False)
    except HTTPException as exc:
        detail = exc.detail if isinstance(exc.detail, dict) else {"reason": str(exc.detail)}
        action = "needs_credentials" if exc.status_code in {400, 409} else "resolve_error"
        blocking_reason = str(detail.get("reason") or detail.get("plain_english_error") or "Deployment failed.")
        next_action = str(detail.get("next_action") or "Fix deployment prerequisites and retry.")
        _append_progress(
            project_id,
            {
                "agent": "DeploymentAgent",
                "phase": "deploying",
                "message": "Deployment attempt failed. Preparing recovery guidance.",
                "data": {
                    "action": "Handling deployment failure",
                    "reason": blocking_reason,
                    "result": "Recovery action prepared",
                },
            },
        )
        return DeployResponse(
            status="blocked" if action == "needs_credentials" else "failed",
            deployment_url=None,
            provider=None,
            details={
                **detail,
                "action": action,
                "plain_english_error": blocking_reason,
                "next_action": next_action,
            },
            action=action,
            blocking_reason=blocking_reason,
            next_action=next_action,
        )
    details = result.get("details") if isinstance(result.get("details"), dict) else {}
    action = str(details.get("action") or "").strip() or None
    blocking_reason = str(details.get("reason") or details.get("plain_english_error") or "").strip() or None
    next_action = str(details.get("next_action") or "").strip() or None

    _append_progress(
        project_id,
        {
            "agent": "DeploymentAgent",
            "phase": "deploying",
            "message": "Deployment step completed.",
            "data": {
                "action": "Executing autonomous deployment",
                "reason": "Selected platform best matches project profile and runtime constraints",
                "result": "Deployment successful" if result.get("deployment_url") else "Deployment blocked",
            },
        },
    )

    # DB status column has a strict CHECK constraint and does not support "blocked".
    final_status = "live" if result.get("deployment_url") else "failed"
    update_project(project_id, {"status": final_status})

    return DeployResponse(
        status="deployed" if result.get("deployment_url") else ("blocked" if action else "failed"),
        deployment_url=result.get("deployment_url"),
        provider=result.get("provider"),
        details=result.get("details"),
        action=action,
        blocking_reason=blocking_reason,
        next_action=next_action,
    )


@router.post("/{project_id}/redeploy", response_model=DeployResponse)
async def redeploy_project(project_id: int, provider: str | None = None) -> DeployResponse:
    """Force redeploy for a project."""
    requested_provider = str(provider or "").strip().lower()
    if requested_provider and requested_provider != "auto":
        if requested_provider not in _SUPPORTED_DEPLOY_PROVIDERS:
            raise HTTPException(status_code=400, detail=f"Unsupported provider '{requested_provider}'.")
        update_project(project_id, {"preferred_provider": requested_provider})

    _append_progress(
        project_id,
        {
            "agent": "DeploymentAgent",
            "phase": "deploying",
            "message": "Redeploy requested. Applying prior failure context to avoid repeating the same deployment path.",
            "data": {
                "action": "Retrying deployment",
                "reason": "Previous attempt failed and adaptive recovery strategy is available",
                "result": "Redeploy sequence started",
            },
        },
    )
    try:
        result = await manual_deploy(project_id=project_id, force=True)
    except HTTPException as exc:
        detail = exc.detail if isinstance(exc.detail, dict) else {"reason": str(exc.detail)}
        action = "needs_credentials" if exc.status_code in {400, 409} else "resolve_error"
        blocking_reason = str(detail.get("reason") or detail.get("plain_english_error") or "Deployment failed.")
        next_action = str(detail.get("next_action") or "Fix deployment prerequisites and retry.")
        _append_progress(
            project_id,
            {
                "agent": "DeploymentAgent",
                "phase": "deploying",
                "message": "Redeploy failed; escalation guidance prepared.",
                "data": {
                    "action": "Processing redeploy failure",
                    "reason": blocking_reason,
                    "result": "Next action generated",
                },
            },
        )
        return DeployResponse(
            status="blocked" if action == "needs_credentials" else "failed",
            deployment_url=None,
            provider=None,
            details={
                **detail,
                "action": action,
                "plain_english_error": blocking_reason,
                "next_action": next_action,
            },
            action=action,
            blocking_reason=blocking_reason,
            next_action=next_action,
        )
    details = result.get("details") if isinstance(result.get("details"), dict) else {}
    action = str(details.get("action") or "").strip() or None
    blocking_reason = str(details.get("reason") or details.get("plain_english_error") or "").strip() or None
    next_action = str(details.get("next_action") or "").strip() or None
    _append_progress(
        project_id,
        {
            "agent": "DeploymentAgent",
            "phase": "deploying",
            "message": "Redeploy step completed.",
            "data": {
                "action": "Applying autonomous recovery deploy",
                "reason": "Retry path incorporates prior failure signals",
                "result": "Deployment successful" if result.get("deployment_url") else "Deployment blocked",
            },
        },
    )

    # Persist only schema-supported statuses; blocked semantics are returned via payload fields.
    update_project(project_id, {"status": "live" if result.get("deployment_url") else "failed"})
    return DeployResponse(
        status="deployed" if result.get("deployment_url") else ("blocked" if action else "failed"),
        deployment_url=result.get("deployment_url"),
        provider=result.get("provider"),
        details=result.get("details"),
        action=action,
        blocking_reason=blocking_reason,
        next_action=next_action,
    )


@router.post("/{project_id}/autonomous-fix-deploy", response_model=DeployResponse)
async def autonomous_fix_and_deploy(project_id: int) -> DeployResponse:
    """Run controlled autonomous fix and deploy sequence.

    Sequence:
    1) Try deploy
    2) Analyze error
    3) Run FixAgent
    4) Validate simulation-gated fixes
    5) Retry deploy
    6) Switch provider
    7) Retry deploy again
    8) Fallback to local preview
    """

    project = get_project(project_id)
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")
    if not _analysis_completed(project):
        raise HTTPException(
            status_code=409,
            detail="Analysis is still running. Autonomous Fix & Deploy can start only after analysis is complete.",
        )

    source_map = load_source_text_map(project_id)
    files = [{"name": path, "content": content} for path, content in source_map.items()]
    if not files:
        raise HTTPException(status_code=400, detail="No source files available for deployment.")

    _append_progress(
        project_id,
        {
            "agent": "Meta-Agent",
            "phase": "deploying",
            "message": "Autonomous Fix & Deploy started.",
            "data": {
                "action": "Starting autonomous fix and deploy",
                "reason": "Analysis-only phase is complete and deployment can now proceed",
                "result": "Executing controlled retry sequence",
            },
        },
    )

    # 1) Try deploy.
    try:
        first = await manual_deploy(project_id=project_id, force=False)
        if first.get("deployment_url"):
            _append_progress(
                project_id,
                {
                    "agent": "DeploymentAgent",
                    "phase": "deploying",
                    "message": "First deployment attempt succeeded.",
                    "data": {
                        "action": "Deploy",
                        "reason": "Initial deployment path is valid",
                        "result": "Live URL is available",
                    },
                },
            )
            update_project(project_id, {"status": "live"})
            return _success_response(first)
        reason = str((first.get("details") or {}).get("reason") or (first.get("details") or {}).get("plain_english_error") or "Deployment failed.")
    except HTTPException as exc:
        reason, _, _ = _format_deploy_failure(exc.detail)

    # 2) Analyze error.
    _append_progress(
        project_id,
        {
            "agent": "Meta-Agent",
            "phase": "deploying",
            "message": "Analyzing deployment failure.",
            "data": {
                "action": "Analyze deploy error",
                "reason": reason,
                "result": "Preparing remediation",
            },
        },
    )

    # 3) Run FixAgent.
    security_report = _parse_json(project.get("security_report"))
    security_report = security_report if isinstance(security_report, dict) else {}
    fix_agent = FixAgent(project_id)
    fix_result = await fix_agent.generate_and_apply(files, security_report)
    fix_report = {
        "applied": [asdict(item) for item in fix_result.applied],
        "manual_review": [asdict(item) for item in fix_result.manual_review],
        "env_vars_detected": fix_result.env_vars_detected,
        "simulation_blocked": [asdict(item) for item in fix_result.simulation_blocked],
    }
    update_project(project_id, {"fix_report": fix_report, "status": "fixing"})
    _append_progress(
        project_id,
        {
            "agent": "FixAgent",
            "phase": "fixing",
            "message": "FixAgent applied simulation-gated remediation.",
            "data": {
                "action": "Run FixAgent",
                "reason": "Deployment failed and remediation is required",
                "result": f"Applied {len(fix_result.applied)} fix(es)",
            },
        },
    )

    # 4) SimulationAgent validates.
    blocked_count = len(fix_result.simulation_blocked)
    _append_progress(
        project_id,
        {
            "agent": "SimulationAgent",
            "phase": "fixing",
            "message": "Simulation validation completed.",
            "data": {
                "action": "Validate fixes",
                "reason": "Every autonomous patch must pass simulation before deploy",
                "result": "All patches validated" if blocked_count == 0 else f"{blocked_count} patch(es) blocked",
            },
        },
    )

    # 5) Retry deploy.
    try:
        second = await manual_deploy(project_id=project_id, force=True)
        if second.get("deployment_url"):
            update_project(project_id, {"status": "live"})
            return _success_response(second)
        second_reason = str((second.get("details") or {}).get("reason") or (second.get("details") or {}).get("plain_english_error") or "Deployment retry failed.")
    except HTTPException as exc:
        second_reason, _, _ = _format_deploy_failure(exc.detail)

    # 6) Switch provider.
    runtime = str(SecurityAgent(project_id)._detect_stack(files).get("runtime") or "").strip().lower()
    current_provider = _normalize_provider(project.get("preferred_provider"))
    switched_provider = _provider_fallback_order(runtime=runtime, current=current_provider)
    update_project(project_id, {"preferred_provider": switched_provider})
    _append_progress(
        project_id,
        {
            "agent": "Meta-Agent",
            "phase": "deploying",
            "message": "Switching deployment provider for recovery.",
            "data": {
                "action": "Switch provider",
                "reason": second_reason,
                "result": f"Provider changed to {switched_provider}",
            },
        },
    )

    # 7) Retry again.
    try:
        third = await manual_deploy(project_id=project_id, force=True)
        if third.get("deployment_url"):
            update_project(project_id, {"status": "live"})
            return _success_response(third)
        third_reason = str((third.get("details") or {}).get("reason") or (third.get("details") or {}).get("plain_english_error") or "Provider-switch retry failed.")
    except HTTPException as exc:
        third_reason, _, _ = _format_deploy_failure(exc.detail)

    # 8) Fallback local.
    ensure_preview_index(project_id)
    preview_url = get_local_preview_url(project_id)
    fallback_details = {
        "mode": "local_preview_fallback",
        "reason": third_reason,
        "next_action": "Configure cloud provider credentials and retry cloud deploy when ready.",
    }
    update_project(
        project_id,
        {
            "status": "live",
            "public_url": preview_url,
            "deployment": {
                "provider": "local",
                "deployment_url": preview_url,
                "status": "success",
                "details": fallback_details,
            },
        },
    )
    _append_progress(
        project_id,
        {
            "agent": "DeploymentAgent",
            "phase": "deploying",
            "message": "Cloud retries exhausted; local fallback activated.",
            "data": {
                "action": "Fallback local",
                "reason": third_reason,
                "result": preview_url,
            },
        },
    )

    return DeployResponse(
        status="deployed",
        deployment_url=preview_url,
        provider="local",
        details=fallback_details,
        action="fallback_local",
        blocking_reason=third_reason,
        next_action=fallback_details["next_action"],
    )


@router.post("/{project_id}/restart")
async def restart_project(project_id: int) -> dict[str, Any]:
    """Restart by triggering a forced redeploy."""
    _append_progress(
        project_id,
        {
            "agent": "DeploymentAgent",
            "phase": "deploying",
            "message": "Restart requested. Re-validating runtime health and redeploying with adaptive provider strategy.",
        },
    )
    try:
        result = await manual_deploy(project_id=project_id, force=True)
    except HTTPException as exc:
        detail = exc.detail if isinstance(exc.detail, dict) else {"reason": str(exc.detail)}
        action = "needs_credentials" if exc.status_code in {400, 409} else "resolve_error"
        return {
            "status": "blocked" if action == "needs_credentials" else "failed",
            "deployment_url": None,
            "provider": None,
            "details": {
                **detail,
                "action": action,
                "plain_english_error": detail.get("reason") or detail.get("plain_english_error") or "Deployment failed.",
                "next_action": detail.get("next_action") or "Fix deployment prerequisites and retry.",
            },
            "action": action,
            "blocking_reason": detail.get("reason") or detail.get("plain_english_error") or "Deployment failed.",
            "next_action": detail.get("next_action") or "Fix deployment prerequisites and retry.",
        }
    details = result.get("details") if isinstance(result.get("details"), dict) else {}
    action = str(details.get("action") or "").strip() or None
    # Persist only schema-supported statuses; blocked semantics are returned via payload fields.
    update_project(project_id, {"status": "live" if result.get("deployment_url") else "failed"})
    return {
        "status": "restarted" if result.get("deployment_url") else ("blocked" if action else "failed"),
        "deployment_url": result.get("deployment_url"),
        "provider": result.get("provider"),
        "details": result.get("details") or {},
        "action": action,
        "blocking_reason": details.get("reason") or details.get("plain_english_error"),
        "next_action": details.get("next_action"),
    }


@router.post("/{project_id}/stop")
async def stop_project(project_id: int) -> dict[str, Any]:
    """Mark project deployment as stopped in Nestify control plane."""
    project = get_project(project_id)
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")

    # "stopped" is not an allowed DB status value; use failed while preserving stop intent in logs/progress.
    update_project(project_id, {"status": "failed"})
    add_log(project_id, "DeploymentAgent", "Deployment marked as stopped by user.", "warn")
    _append_progress(
        project_id,
        {
            "agent": "DeploymentAgent",
            "phase": "stopped",
            "message": "Service marked as stopped. Current deployment context is preserved for faster and safer resume.",
        },
    )
    return {"status": "stopped", "project_id": project_id}


@router.get("/{project_id}/deployment")
async def get_project_deployment(project_id: int) -> dict[str, Any]:
    """Return latest deployment details for dashboard experience."""
    project = get_project(project_id)
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")

    deployment = get_deployment(project_id)
    if not deployment:
        return {
            "status": project.get("status") or "pending",
            "deployment_url": None,
            "provider": None,
            "details": {},
            "agentic_insights": _sanitize_agentic_insights(_parse_json(project.get("agentic_insights")) or {}),
            "security_report_pdf": project.get("security_report_pdf"),
        }

    details = _parse_json(deployment.get("details")) or {}
    provider = _normalize_provider(deployment.get("provider"))
    if str(details.get("mode") or "").strip().lower() == "local_static_fallback":
        provider = "local"

    return {
        "status": project.get("status") or deployment.get("status"),
        "deployment_url": deployment.get("deployment_url"),
        "provider": provider,
        "details": details,
        "agentic_insights": _sanitize_agentic_insights(_parse_json(project.get("agentic_insights")) or {}),
        "security_report_pdf": project.get("security_report_pdf"),
    }


@router.get("/{project_id}/autonomous-response")
async def get_autonomous_response(project_id: int) -> dict[str, Any]:
    """Return clean structured autonomous response contract for UI consumption."""

    project = get_project(project_id)
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")

    report = await get_report(project_id)
    deployment = await get_project_deployment(project_id)
    progress_entries = pipeline_progress.get(project_id, [])[-120:]

    feed: list[dict[str, Any]] = []
    for item in progress_entries:
        if not isinstance(item, dict):
            continue
        feed_item = item.get("feed") if isinstance(item.get("feed"), dict) else None
        if not feed_item:
            feed_item = {
                "agent": str(item.get("agent") or "system").lower(),
                "type": "status",
                "title": str(item.get("phase") or "update"),
                "severity": "info",
                "message": " ".join(str(item.get("message") or "").split())[:160],
                "timestamp": item.get("timestamp"),
            }
        feed.append(feed_item)

    findings = report.get("findings") if isinstance(report.get("findings"), dict) else {}
    security_issues = []
    for level in ("critical", "high", "medium"):
        for issue in (findings.get(level) or [])[:20]:
            security_issues.append(
                {
                    "severity": level,
                    "title": issue.get("title") or issue.get("type") or "security_issue",
                    "message": issue.get("description") or issue.get("message") or "Issue detected",
                    "action": issue.get("recommendation") or "Review and remediate",
                }
            )

    insights = report.get("agentic_insights") if isinstance(report.get("agentic_insights"), dict) else {}
    deploy_intel = insights.get("deployment_intelligence") if isinstance(insights.get("deployment_intelligence"), dict) else {}
    cost_opt = insights.get("cost_optimization") if isinstance(insights.get("cost_optimization"), dict) else {}
    recommended = cost_opt.get("recommended") if isinstance(cost_opt.get("recommended"), dict) else {}
    self_heal = insights.get("self_healing_report") if isinstance(insights.get("self_healing_report"), dict) else {}
    meta_agent = insights.get("meta_agent") if isinstance(insights.get("meta_agent"), dict) else {}

    attempts = self_heal.get("attempts") if isinstance(self_heal.get("attempts"), list) else []
    if not attempts:
        attempts = meta_agent.get("self_heal_attempts") if isinstance(meta_agent.get("self_heal_attempts"), list) else []
    if not attempts:
        derived_attempts: list[dict[str, Any]] = []
        attempt_no = 0
        for item in progress_entries:
            if not isinstance(item, dict):
                continue
            if str(item.get("agent") or "") != "DeploymentAgent":
                continue
            message = str(item.get("message") or "").lower()
            details = item.get("data") if isinstance(item.get("data"), dict) else {}
            if "deployment execution" in message or details.get("action") == "Starting deployment execution":
                attempt_no += 1
                derived_attempts.append(
                    {
                        "attempt": attempt_no,
                        "provider": deployment.get("provider") or "auto",
                        "status": "in_progress",
                        "reason": details.get("reason") or "deployment_started",
                        "fix_applied": None,
                    }
                )
            if derived_attempts and ("failed" in message or details.get("result") == "Recovery instructions prepared"):
                derived_attempts[-1]["status"] = "failed"
                derived_attempts[-1]["reason"] = details.get("reason") or "deployment_failed"
        attempts = derived_attempts

    final_url = deployment.get("deployment_url") or project.get("public_url")
    deployment_status = "success" if final_url else "failed"
    deployment_contract = {
        "status": deployment_status,
        "attempts": attempts,
        "final_url": final_url,
        "failure_reason": None if final_url else (deployment.get("details") or {}).get("reason"),
    }

    runtime_monitoring = insights.get("production_insights") if isinstance(insights.get("production_insights"), dict) else {}
    metrics = (runtime_monitoring.get("runtime") or {}) if isinstance(runtime_monitoring.get("runtime"), dict) else {}
    recommendations = []
    agent_report = runtime_monitoring.get("agent_report") if isinstance(runtime_monitoring.get("agent_report"), dict) else {}
    if isinstance(agent_report.get("recommendations"), list):
        recommendations = [str(item.get("action") or item) for item in agent_report.get("recommendations")[:6]]
    monitoring_contract = {
        "metrics": {
            "p50": metrics.get("p50_ms"),
            "p95": metrics.get("p95_ms"),
            "p99": metrics.get("p99_ms"),
            "error_rate": metrics.get("error_rate"),
        },
        "status": "healthy" if (metrics.get("error_rate") or 0) <= 0.01 else "degraded",
        "recommendations": recommendations,
    }

    confidence_values = [
        float(deploy_intel.get("confidence") or 0.0),
        float(meta_agent.get("confidence") or 0.0),
    ]
    confidence_score = round(sum(confidence_values) / max(1, len(confidence_values)), 2)
    audit = {
        "summary": f"Project {project_id} processed with status {project.get('status')}.",
        "security_issues": security_issues,
        "fixes": report.get("fixes") if isinstance(report.get("fixes"), list) else [],
        "deployment_plan": {
            "platform": deploy_intel.get("chosen_platform") or deployment.get("provider"),
            "reason": deploy_intel.get("reasoning") or (deployment.get("details") or {}).get("note") or "Deterministic policy selection",
            "confidence": float(deploy_intel.get("confidence") or 0.0),
        },
        "cost_estimate": {
            "provider": cost_opt.get("provider"),
            "monthly_cost_usd": recommended.get("monthly_cost_usd"),
            "config": recommended.get("config") if isinstance(recommended.get("config"), dict) else {},
        },
        "confidence_score": confidence_score,
    }

    return {
        "feed": feed,
        "audit": audit,
        "deployment": deployment_contract,
        "monitoring": monitoring_contract,
    }


@router.websocket("/ws/projects/{project_id}")
async def websocket_updates(websocket: WebSocket, project_id: int) -> None:
    """Stream per-project progress updates in real time."""
    await websocket.accept()
    last_index = 0

    try:
        while True:
            entries = pipeline_progress.get(project_id, [])
            for idx in range(last_index, len(entries)):
                item = entries[idx]
                await websocket.send_json(
                    {
                        "type": "progress",
                        "timestamp": item.get("timestamp"),
                        "data": {
                            "agent": item.get("agent"),
                            "phase": item.get("phase"),
                            "message": item.get("message"),
                            "details": item.get("data"),
                            "feed": item.get("feed"),
                        },
                    }
                )
            last_index = len(entries)
            await asyncio.sleep(0.5)
    except WebSocketDisconnect:
        return


def _parse_json(value: Any) -> dict[str, Any] | list[dict[str, Any]] | None:
    if isinstance(value, (dict, list)):
        return value
    if not isinstance(value, str) or not value.strip():
        return None
    try:
        return json.loads(value)
    except json.JSONDecodeError:
        return None


def _sanitize_agentic_insights(insights: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(insights, dict):
        return {}

    clean = json.loads(json.dumps(insights))

    def _strip_verbose(value: Any) -> Any:
        if isinstance(value, dict):
            blocked_keys = {"reasoning", "thought", "decision_log", "reflections", "debate_transcript"}
            return {
                str(k): _strip_verbose(v)
                for k, v in value.items()
                if str(k) not in blocked_keys
            }
        if isinstance(value, list):
            return [_strip_verbose(item) for item in value]
        return value

    code_profile = clean.get("code_profile")
    if isinstance(code_profile, dict):
        code_profile.pop("reasoning", None)

    security_reasoning = clean.get("security_reasoning")
    if isinstance(security_reasoning, dict):
        security_reasoning.pop("reasoning", None)

    deployment_intel = clean.get("deployment_intelligence")
    if isinstance(deployment_intel, dict):
        deployment_intel.pop("reasoning", None)
        deployment_intel.pop("debate_transcript", None)

    meta_agent = clean.get("meta_agent")
    if isinstance(meta_agent, dict):
        meta_agent.pop("decision_log", None)
        meta_agent.pop("reflections", None)

    return _strip_verbose(clean)


def _extract_entry_points(source_map: dict[str, str]) -> list[str]:
    candidates = [
        "main.py",
        "app/main.py",
        "server.js",
        "src/main.ts",
        "src/main.tsx",
        "src/index.ts",
        "src/index.tsx",
        "index.js",
        "index.ts",
        "index.html",
    ]
    by_exact = [path for path in candidates if path in source_map]
    if by_exact:
        return by_exact[:5]

    discovered = [
        path for path in source_map
        if path.endswith(("main.py", "main.ts", "main.tsx", "index.js", "index.ts", "index.tsx", "index.html"))
    ]
    discovered.sort(key=lambda item: (item.count("/"), len(item)))
    return discovered[:5]


def _why_it_matters(item: dict[str, Any]) -> str:
    recommendation = str(item.get("recommendation") or "").strip()
    if recommendation:
        return recommendation
    issue_type = str(item.get("type") or item.get("title") or "security issue").strip().lower()
    return f"This {issue_type} can increase exploitability, reduce reliability, or block secure deployment."


def _build_applied_fixes(
    *,
    fix_logs: list[dict[str, Any]],
    deployment_details: dict[str, Any],
) -> list[dict[str, Any]]:
    applied: list[dict[str, Any]] = []

    for row in fix_logs[:20]:
        note = str(row.get("note") or "").strip()
        before_after = "Before state was unsafe or non-compliant; after state aligns with deployment and security requirements."
        if "->" in note:
            before_after = note
        elif note:
            before_after = f"Before: issue observed in {row.get('file') or 'target file'}. After: {note}"
        applied.append(
            {
                "change": str(row.get("fix_type") or row.get("file") or "Applied remediation"),
                "location": str(row.get("file") or "unknown"),
                "before_after": before_after,
                "status": str(row.get("status") or "applied"),
            }
        )

    details_fixes: list[str] = []
    for key in ("what_i_fixed", "fixes_applied", "changes"):
        values = deployment_details.get(key)
        if isinstance(values, list):
            details_fixes.extend(str(item) for item in values if str(item or "").strip())

    for text in details_fixes[:10]:
        applied.append(
            {
                "change": text,
                "location": "deployment configuration",
                "before_after": "Before: deployment path failed or was unstable. After: autonomous fix was applied and re-validated.",
                "status": "applied",
            }
        )

    return applied[:20]


def _build_audit_report_payload(project_id: int, project: dict[str, Any]) -> dict[str, Any]:
    findings = _augment_findings_with_logs(
        _group_findings(get_scan_results(project_id)),
        get_project_logs(project_id),
    )
    remediation_steps = _build_remediation_steps(findings)
    stack_info = _parse_json(project.get("stack_info")) or {}
    stack_info = stack_info if isinstance(stack_info, dict) else {}
    source_map = load_source_text_map(project_id)
    dependencies = stack_info.get("dependencies") if isinstance(stack_info.get("dependencies"), list) else []
    dependencies = [str(dep) for dep in dependencies[:50]]

    latest_deployment = get_deployment(project_id) or {}
    deployment_details = _parse_json(latest_deployment.get("details")) or {}
    deployment_details = deployment_details if isinstance(deployment_details, dict) else {}
    fix_logs = get_fix_logs(project_id)
    parsed_insights = _parse_json(project.get("agentic_insights")) or {}
    parsed_insights = parsed_insights if isinstance(parsed_insights, dict) else {}
    deploy_intel = parsed_insights.get("deployment_intelligence") or {}
    deploy_intel = deploy_intel if isinstance(deploy_intel, dict) else {}
    cost_opt = parsed_insights.get("cost_optimization") or {}
    cost_opt = cost_opt if isinstance(cost_opt, dict) else {}
    recommended = (cost_opt.get("recommended") or {}) if isinstance(cost_opt.get("recommended"), dict) else {}
    comparison = cost_opt.get("comparison_matrix") if isinstance(cost_opt.get("comparison_matrix"), list) else []

    alternatives = []
    for row in comparison[:6]:
        cfg = row.get("config") if isinstance(row, dict) and isinstance(row.get("config"), dict) else {}
        benchmark = row.get("benchmark") if isinstance(row, dict) and isinstance(row.get("benchmark"), dict) else {}
        alternatives.append(
            {
                "label": cfg.get("label") or "option",
                "memory_mb": cfg.get("memory_mb"),
                "cpu": cfg.get("cpu"),
                "monthly_cost_usd": row.get("monthly_cost_usd") if isinstance(row, dict) else None,
                "p95_ms": benchmark.get("p95_ms"),
                "success_rate": benchmark.get("success_rate"),
                "meets_sla": benchmark.get("meets_sla"),
            }
        )

    severity_groups: dict[str, list[dict[str, Any]]] = {"critical": [], "high": [], "medium": []}
    for severity in ("critical", "high", "medium"):
        for issue in findings.get(severity, []):
            severity_groups[severity].append(
                {
                    "description": str(issue.get("description") or issue.get("message") or issue.get("title") or "Security issue"),
                    "location": f"{issue.get('file') or issue.get('file_path') or 'unknown'}:{issue.get('line') or issue.get('line_number') or '?'}",
                    "why_it_matters": _why_it_matters(issue),
                }
            )

    exact_fix_steps = [
        {
            "step": idx,
            "action": item.get("recommendation"),
            "location": item.get("location"),
            "severity": item.get("severity"),
        }
        for idx, item in enumerate(remediation_steps[:20], start=1)
    ]
    code_level_suggestions = [
        item for item in exact_fix_steps
        if isinstance(item.get("location"), str) and item["location"].split(":", 1)[0] not in {"unknown", "none"}
    ][:12]
    config_changes = [
        item for item in exact_fix_steps
        if any(token in str(item.get("action") or "").lower() for token in ("env", "config", "token", "docker", "package", "dependency"))
    ][:12]

    if not code_level_suggestions:
        code_level_suggestions = exact_fix_steps[:6]
    if not config_changes:
        config_changes = [
            {
                "step": 1,
                "action": "Verify deployment env variables and provider credentials are configured for secure production rollout.",
                "location": "deployment configuration",
                "severity": "high",
            }
        ]

    applied_fixes = _build_applied_fixes(fix_logs=fix_logs, deployment_details=deployment_details)

    security_score = int(project.get("security_score") or 0)
    blocking_issues = []
    if severity_groups["critical"]:
        blocking_issues.append(f"{len(severity_groups['critical'])} critical vulnerabilities remain unresolved")
    if len(severity_groups["high"]) >= 3:
        blocking_issues.append(f"{len(severity_groups['high'])} high-severity issues require remediation")
    deployment_status = str(project.get("status") or latest_deployment.get("status") or "pending").lower()
    if deployment_status in {"failed", "blocked"}:
        blocking_issues.append("Latest deployment run is blocked or failed")

    safe_to_deploy = security_score >= 80 and len(severity_groups["critical"]) == 0 and len(severity_groups["high"]) <= 2
    if blocking_issues:
        safe_to_deploy = False

    est_cost = deploy_intel.get("estimated_monthly_cost_usd")
    if est_cost is None:
        est_cost = recommended.get("monthly_cost_usd")

    chosen_platform = deploy_intel.get("chosen_platform") or latest_deployment.get("provider") or project.get("preferred_provider") or "unknown"
    strategy_reason = (
        deploy_intel.get("rationale")
        or deploy_intel.get("reasoning")
        or deployment_details.get("note")
        or "Platform selected using deployment fit, security context, and cost model."
    )

    return {
        "metadata": {
            "report_type": "security_audit",
            "project_id": project_id,
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "version": "1.0",
        },
        "project": {
            "id": project.get("id"),
            "name": project.get("name"),
            "status": project.get("status"),
            "security_score": security_score,
            "public_url": project.get("public_url"),
            "preferred_provider": project.get("preferred_provider"),
        },
        "project_overview": {
            "detected_stack": {
                "framework": stack_info.get("framework") or "unknown",
                "runtime": stack_info.get("runtime") or "unknown",
            },
            "dependencies": dependencies,
            "entry_points": _extract_entry_points(source_map),
        },
        "vulnerability_analysis": {
            "critical": severity_groups["critical"],
            "high": severity_groups["high"],
            "medium": severity_groups["medium"],
        },
        "fix_recommendations": {
            "exact_fix_steps": exact_fix_steps,
            "code_level_suggestions": code_level_suggestions,
            "config_changes": config_changes,
        },
        "applied_fixes": applied_fixes,
        "deployment_readiness": {
            "score": security_score,
            "blocking_issues": blocking_issues,
            "safe_to_deploy": "Yes" if safe_to_deploy else "No",
        },
        "deployment_strategy": {
            "selected_platform": chosen_platform,
            "why_chosen": strategy_reason,
            "confidence": float(deploy_intel.get("confidence") or 0.0),
            "estimated_cost": est_cost,
        },
        "security_score": security_score,
        "findings": findings,
        "deployment_plan": {
            "chosen_platform": chosen_platform,
            "confidence": float(deploy_intel.get("confidence") or 0.0),
            "estimated_cost": est_cost,
            "reasoning": strategy_reason,
            "alternatives_considered": [
                alt.get("provider") for alt in (deploy_intel.get("alternatives") or []) if isinstance(alt, dict) and alt.get("provider")
            ],
            "cost_alternatives": alternatives,
            "failure_reason": deployment_details.get("plain_english_error") or deployment_details.get("error"),
            "recovery_plan": deployment_details.get("fix_suggestion") or "Nestify can apply recovery heuristics and retry deployment automatically.",
        },
        "similar_deployments": list_deployment_outcomes(limit=10),
        "remediation_steps": remediation_steps,
    }


def _group_findings(rows: list[dict[str, Any]]) -> dict[str, list[dict[str, Any]]]:
    grouped: dict[str, list[dict[str, Any]]] = {"critical": [], "high": [], "medium": [], "info": []}
    for row in rows:
        severity = str(row.get("severity") or "info").lower()
        if severity not in grouped:
            severity = "info"
        grouped[severity].append(row)
    return grouped


def _build_remediation_steps(findings: dict[str, list[dict[str, Any]]]) -> list[dict[str, Any]]:
    remediation_steps: list[dict[str, Any]] = []
    for severity in ("critical", "high", "medium", "info"):
        for item in findings.get(severity, [])[:20]:
            remediation_steps.append(
                {
                    "severity": severity,
                    "title": item.get("title") or item.get("type") or "Security finding",
                    "location": f"{item.get('file') or item.get('file_path') or 'unknown'}:{item.get('line') or item.get('line_number') or '?'}",
                    "recommendation": item.get("recommendation") or item.get("description") or item.get("message") or "Review and remediate.",
                }
            )
    return remediation_steps


def _augment_findings_with_logs(
    findings: dict[str, list[dict[str, Any]]],
    logs: list[dict[str, Any]],
) -> dict[str, list[dict[str, Any]]]:
    total = sum(len(findings.get(level, [])) for level in ("critical", "high", "medium", "info"))
    if total > 0:
        return findings

    synthesized_high: list[dict[str, Any]] = []
    synthesized_medium: list[dict[str, Any]] = []

    for row in logs[-60:]:
        message = str(row.get("message") or "").strip()
        if not message:
            continue
        lowered = message.lower()
        agent = str(row.get("agent") or row.get("source") or "system")

        if any(token in lowered for token in ("failed", "error", "exception", "crash", "blocked")):
            synthesized_high.append(
                {
                    "severity": "high",
                    "title": f"Pipeline failure from {agent}",
                    "message": message,
                    "recommendation": "Apply the recommended remediation, then rerun analysis and deployment.",
                }
            )
        elif any(token in lowered for token in ("warn", "warning", "retry", "timeout", "degraded")):
            synthesized_medium.append(
                {
                    "severity": "medium",
                    "title": f"Operational warning from {agent}",
                    "message": message,
                    "recommendation": "Review runtime warnings and tune provider/runtime configuration.",
                }
            )

    return {
        "critical": findings.get("critical", []),
        "high": synthesized_high[:10],
        "medium": synthesized_medium[:10],
        "info": findings.get("info", []),
    }


class _SyntheticRequest:
    """Small adapter so existing upload route can be reused by the v1 projects API."""

    def __init__(self, agentic: bool) -> None:
        self.query_params = {"agentic": "true" if agentic else "false"}
