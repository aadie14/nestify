"""GCP guided setup API — helps users configure Google Cloud for free deployments."""

from __future__ import annotations

import os
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

router = APIRouter()


class GCPValidateRequest(BaseModel):
    project_id: str
    service_account_json: str | None = None


# ─── Setup Guide ──────────────────────────────────────────────────────

@router.get("/setup-guide")
async def setup_guide():
    """Return structured step-by-step GCP setup instructions."""
    return {
        "title": "Deploy to Google Cloud for Free",
        "subtitle": "Cloud Run gives you 2 million free requests/month with automatic scale-to-zero",
        "steps": [
            {
                "step": 1,
                "title": "Create a Google Cloud Account",
                "description": "Sign up for a free Google Cloud account. New users get $300 in free credits.",
                "link": "https://console.cloud.google.com/freetrial",
                "cli_alternative": None,
                "estimated_time": "2 minutes",
            },
            {
                "step": 2,
                "title": "Create a New Project",
                "description": "Create a new GCP project to host your deployments. Pick any name you like.",
                "link": "https://console.cloud.google.com/projectcreate",
                "cli_alternative": "gcloud projects create YOUR-PROJECT-ID --name=\"My Project\"",
                "estimated_time": "1 minute",
            },
            {
                "step": 3,
                "title": "Enable Billing",
                "description": (
                    "Google requires a billing account even for free-tier usage. "
                    "You will NOT be charged as long as you stay within free limits "
                    "(2M requests/month, scales to zero when idle)."
                ),
                "link": "https://console.cloud.google.com/billing",
                "cli_alternative": None,
                "estimated_time": "2 minutes",
            },
            {
                "step": 4,
                "title": "Create a Service Account",
                "description": (
                    "Create a service account with Editor role, then download the JSON key file. "
                    "This allows Nestify to deploy on your behalf."
                ),
                "link": "https://console.cloud.google.com/iam-admin/serviceaccounts/create",
                "cli_alternative": (
                    "gcloud iam service-accounts create nestify-deployer "
                    '--display-name="Nestify Deployer"\n'
                    "gcloud projects add-iam-policy-binding YOUR-PROJECT-ID "
                    "--member=serviceAccount:nestify-deployer@YOUR-PROJECT-ID.iam.gserviceaccount.com "
                    "--role=roles/editor\n"
                    "gcloud iam service-accounts keys create key.json "
                    "--iam-account=nestify-deployer@YOUR-PROJECT-ID.iam.gserviceaccount.com"
                ),
                "estimated_time": "3 minutes",
            },
            {
                "step": 5,
                "title": "Upload Key to Nestify",
                "description": "Drag and drop the JSON key file below, or paste the JSON content. Nestify stores it in memory only — never saved to disk.",
                "link": None,
                "cli_alternative": "Set GCP_SERVICE_ACCOUNT_JSON in your .env file",
                "estimated_time": "30 seconds",
            },
            {
                "step": 6,
                "title": "Validate & Deploy",
                "description": "Nestify will verify your credentials, enable required APIs, and you're ready to deploy for free!",
                "link": None,
                "cli_alternative": None,
                "estimated_time": "30 seconds",
            },
        ],
        "free_tier_details": {
            "requests_per_month": 2_000_000,
            "cpu_seconds_per_month": 180_000,
            "memory_gb_seconds_per_month": 360_000,
            "network_egress_gb_per_month": 1,
            "scale_to_zero": True,
            "estimated_monthly_cost": "$0.00",
        },
    }


# ─── Status Check ────────────────────────────────────────────────────

@router.get("/status")
async def gcp_status():
    """Check current GCP configuration status."""
    project_id = os.getenv("GCP_PROJECT_ID", "").strip()
    sa_json = os.getenv("GCP_SERVICE_ACCOUNT_JSON", "").strip()
    adc_path = os.getenv("GOOGLE_APPLICATION_CREDENTIALS", "").strip()

    configured = bool(sa_json) or bool(adc_path) or bool(project_id)

    return {
        "configured": configured,
        "project_id": project_id or None,
        "auth_method": (
            "service_account" if sa_json
            else "adc" if adc_path
            else "project_id_only" if project_id
            else "none"
        ),
        "has_service_account_json": bool(sa_json),
        "has_adc": bool(adc_path),
        "region": os.getenv("GCP_REGION", "us-central1"),
    }


# ─── Validate Credentials ────────────────────────────────────────────

@router.post("/validate")
async def validate_credentials(body: GCPValidateRequest):
    """Validate GCP credentials and project access."""
    try:
        from app.services.providers.gcp_provider import GCPDeploymentProvider
        result = await GCPDeploymentProvider.validate_setup(
            project_id_str=body.project_id,
            service_account_json=body.service_account_json,
        )
        return result
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc))


# ─── Configure (in-memory) ───────────────────────────────────────────

@router.post("/configure")
async def configure_gcp(body: GCPValidateRequest):
    """Store GCP credentials in environment for the current session.

    These are kept in-process memory only — never written to disk.
    """
    if body.project_id:
        os.environ["GCP_PROJECT_ID"] = body.project_id.strip()
    if body.service_account_json:
        os.environ["GCP_SERVICE_ACCOUNT_JSON"] = body.service_account_json.strip()

    # Validate after configuring
    try:
        from app.services.providers.gcp_provider import GCPDeploymentProvider
        result = await GCPDeploymentProvider.validate_setup(
            project_id_str=body.project_id,
            service_account_json=body.service_account_json,
        )
        return {
            "configured": True,
            "validation": result,
            "message": (
                "GCP credentials configured and validated."
                if result.get("ok")
                else f"Credentials saved but validation found issues: {result.get('error', 'unknown')}"
            ),
        }
    except Exception as exc:
        return {
            "configured": True,
            "validation": {"ok": False, "error": str(exc)},
            "message": f"Credentials saved but validation failed: {exc}",
        }


# ─── Enable APIs ─────────────────────────────────────────────────────

@router.post("/enable-apis")
async def enable_apis(body: GCPValidateRequest):
    """Enable required GCP APIs (Cloud Run, Artifact Registry, Cloud Build)."""
    try:
        from app.services.providers.gcp_provider import GCPDeploymentProvider
        instance = GCPDeploymentProvider(
            project_id=0, project_name="api-setup", stack_info={}, app_kind="backend"
        )
        creds, resolved_project, _ = instance._load_credentials(body.service_account_json)
        effective_project = body.project_id or resolved_project
        if not effective_project:
            raise HTTPException(status_code=400, detail="No GCP project ID found.")

        import asyncio
        token = await asyncio.to_thread(GCPDeploymentProvider._get_access_token, creds)
        results = await GCPDeploymentProvider._enable_required_apis(token, effective_project)

        all_ok = all(v == "enabled" for v in results.values())
        return {
            "ok": all_ok,
            "apis": results,
            "message": "All required APIs enabled." if all_ok else "Some APIs could not be enabled.",
        }
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc))
