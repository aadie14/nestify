"""Manual deployment trigger for projects that have passed security review."""

from __future__ import annotations

import json

from fastapi import APIRouter, HTTPException

from app.agents.deployment_agent import DeploymentAgent
from app.core.config import settings
from app.database import add_log, get_project, update_project
from app.routes.upload import _append_progress, pipeline_progress
from app.services.project_source_service import load_source_text_map

router = APIRouter()

_SUPPORTED_DEPLOY_PROVIDERS = {"vercel", "netlify", "railway", "gcp_cloud_run"}


@router.post("/{project_id}")
async def deploy(project_id: int, force: bool = False):
    """Trigger manual deployment for a project that passed security review."""
    project = get_project(project_id)
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")

    security_score = int(project.get("security_score") or 0)
    if settings.enforce_security_threshold and not force and security_score < settings.security_score_threshold:
        raise HTTPException(
            status_code=400,
            detail=(
                f"Security score ({security_score}/100) is below the deployment threshold "
                f"({settings.security_score_threshold})."
            ),
        )

    # Parse stored data
    source_payload = project.get("source_payload", {})
    if isinstance(source_payload, str):
        source_payload = json.loads(source_payload or "{}")

    # Load files and detect stack
    files = [
        {"name": path, "content": content}
        for path, content in load_source_text_map(project_id).items()
    ]

    # Build stack info from SecurityAgent
    from app.agents.security_agent import SecurityAgent
    stack_info = SecurityAgent(project_id)._detect_stack(files)

    agent = DeploymentAgent(project_id)

    try:
        pipeline_progress.setdefault(project_id, [])
        _append_progress(project_id, {
            "agent": "DeploymentAgent",
            "phase": "deploying",
            "message": "Manual deployment requested.",
            "data": {
                "action": "Starting deployment execution",
                "reason": "User approved autonomous deploy run",
                "result": "Provider execution started",
            },
        })

        result = await agent.deploy(
            project_name=project["name"],
            files=files,
            stack_info=stack_info,
            preferred_provider=(
                str(project.get("preferred_provider") or "").strip().lower()
                if str(project.get("preferred_provider") or "").strip().lower() in _SUPPORTED_DEPLOY_PROVIDERS
                else None
            ),
            github_url=source_payload.get("github_url"),
            env_template=project.get("env_template", "") or "",
        )

        _append_progress(project_id, {
            "agent": "DeploymentAgent",
            "phase": "deploying",
            "message": "Deployment execution completed.",
            "data": {
                "action": "Finalizing deployment",
                "reason": "Provider workflow finished and verification completed",
                "result": "Deployment successful" if result.deployment_url else "Deployment blocked",
            },
        })

        return {
            "provider": result.provider,
            "deployment_url": result.deployment_url,
            "status": result.status,
            "details": result.details,
            "app_kind": result.app_kind,
        }
    except Exception as error:
        add_log(project_id, "DeploymentAgent", f"Manual deployment failed: {error}", "error")
        update_project(project_id, {"status": "failed"})
        _append_progress(project_id, {
            "agent": "DeploymentAgent",
            "phase": "deploying",
            "message": "Deployment execution failed.",
            "data": {
                "action": "Handling deployment failure",
                "reason": str(error),
                "result": "Recovery instructions prepared",
            },
        })
        message = str(error)
        lowered = message.lower()
        detail_payload = {
            "reason": message,
            "fix_suggestion": "Check deployment credentials and provider settings, then retry.",
            "next_action": "Update credentials/configuration and redeploy.",
        }
        if "no backend deployment provider token" in lowered or "no static deployment provider token" in lowered:
            detail_payload["fix_suggestion"] = "Configure required provider credentials before deployment."
            detail_payload["next_action"] = "Set VERCEL_TOKEN/NETLIFY_API_TOKEN for static apps or RAILWAY_API_KEY for backend apps."
            raise HTTPException(status_code=400, detail=detail_payload)
        if "require a github repository" in lowered:
            detail_payload["fix_suggestion"] = "Provide github_url or configure GITHUB_TOKEN for temporary repository publishing."
            detail_payload["next_action"] = "Add source repository access and redeploy."
            raise HTTPException(status_code=400, detail=detail_payload)
        raise HTTPException(status_code=502, detail=detail_payload)
