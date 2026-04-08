"""Optimization API — practical analyze/apply endpoints for runtime cost tuning."""

from __future__ import annotations

from datetime import datetime
import time
from typing import Any

from fastapi import APIRouter, HTTPException
import httpx
from pydantic import BaseModel, Field

from app.agentic.agents.cost_optimization_agent import CostOptimizationSpecialist
from app.database import add_log, get_project, update_project
from app.services.project_source_service import load_source_text_map

router = APIRouter()


class ApplyOptimizationRequest(BaseModel):
    memory_mb: int | None = Field(default=None, ge=128, le=8192)
    cpu: float | None = Field(default=None, ge=0.1, le=8.0)
    provider: str | None = None
    note: str | None = None


def _ensure_dict(value: Any) -> dict[str, Any]:
    if isinstance(value, dict):
        return value
    return {}


_SUPPORTED_PROVIDERS = {"vercel", "netlify", "railway", "local"}
_COST_COMPARISON_PROVIDERS = ("netlify", "vercel", "railway")
_INR_RATE_CACHE: dict[str, Any] = {"value": None, "updated_at": 0.0}
_INR_RATE_TTL_SECONDS = 600
_INR_FALLBACK_RATE = 83.0


def _normalize_provider(project: dict[str, Any]) -> str:
    preferred = str(project.get("preferred_provider") or "").strip().lower()
    if preferred in _SUPPORTED_PROVIDERS:
        return preferred

    insights = _ensure_dict(project.get("agentic_insights"))
    deploy_intel = _ensure_dict(insights.get("deployment_intelligence"))
    chosen = str(deploy_intel.get("chosen_platform") or "").strip().lower()
    if chosen in _SUPPORTED_PROVIDERS:
        return chosen

    return "railway"


async def _get_usd_to_inr_rate() -> tuple[float, str, bool]:
    now = time.time()
    cached_value = _INR_RATE_CACHE.get("value")
    cached_updated = float(_INR_RATE_CACHE.get("updated_at") or 0.0)
    if isinstance(cached_value, (int, float)) and (now - cached_updated) < _INR_RATE_TTL_SECONDS:
        return float(cached_value), datetime.utcfromtimestamp(cached_updated).isoformat() + "Z", False

    try:
        async with httpx.AsyncClient(timeout=6) as client:
            response = await client.get("https://open.er-api.com/v6/latest/USD")
            payload = response.json() if response.content else {}
            rates = payload.get("rates") if isinstance(payload, dict) else None
            inr = rates.get("INR") if isinstance(rates, dict) else None
            if isinstance(inr, (int, float)) and inr > 0:
                _INR_RATE_CACHE["value"] = float(inr)
                _INR_RATE_CACHE["updated_at"] = now
                return float(inr), datetime.utcfromtimestamp(now).isoformat() + "Z", False
    except Exception:
        pass

    if isinstance(cached_value, (int, float)):
        return float(cached_value), datetime.utcfromtimestamp(cached_updated).isoformat() + "Z", True

    return _INR_FALLBACK_RATE, datetime.utcnow().isoformat() + "Z", True


def _build_profile_from_source(project_id: int) -> dict[str, Any]:
    files = list(load_source_text_map(project_id).keys())
    lower = "\n".join(path.lower() for path in files)

    framework = "unknown"
    runtime = "node"
    app_type = "backend"

    if "vite.config" in lower or "index.html" in lower:
        app_type = "frontend"
        framework = "vite_or_static"
        runtime = "node"

    if "package.json" in lower and "next.config" in lower:
        framework = "nextjs"
        app_type = "fullstack"

    if ".py" in lower or "requirements.txt" in lower:
        runtime = "python"
        framework = "fastapi_or_python"
        app_type = "backend"

    complexity = min(100, max(20, len(files) * 3))
    memory_mb = 512 if app_type in {"backend", "fullstack"} else 256

    return {
        "app_type": app_type,
        "framework": framework,
        "runtime": runtime,
        "deployment_complexity_score": complexity,
        "resource_prediction": {"memory_mb": memory_mb, "cpu": 0.5},
    }


def _get_code_profile(project: dict[str, Any]) -> dict[str, Any]:
    insights = _ensure_dict(project.get("agentic_insights"))
    profile = _ensure_dict(insights.get("code_profile"))
    if profile:
        return profile
    return _build_profile_from_source(int(project["id"]))


def _extract_current_resource_config(project: dict[str, Any], code_profile: dict[str, Any]) -> dict[str, Any]:
    insights = _ensure_dict(project.get("agentic_insights"))
    applied = _ensure_dict(insights.get("optimization_applied"))
    applied_cfg = _ensure_dict(applied.get("config"))
    if applied_cfg:
        return {
            "memory_mb": int(applied_cfg.get("memory_mb") or 512),
            "cpu": float(applied_cfg.get("cpu") or 0.5),
            "source": "optimization_applied",
        }

    prediction = _ensure_dict(code_profile.get("resource_prediction"))
    return {
        "memory_mb": int(prediction.get("memory_mb") or 512),
        "cpu": float(prediction.get("cpu") or 0.5),
        "source": "code_profile_prediction",
    }


@router.get("/{project_id}/analyze")
async def analyze_project_optimization(project_id: int, probe_url: str | None = None) -> dict[str, Any]:
    """Analyze resource/cost options for a specific project."""
    project = get_project(project_id)
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")

    insights = _ensure_dict(project.get("agentic_insights"))
    code_profile = _get_code_profile(project)
    provider = _normalize_provider(project)

    effective_probe_url = probe_url or project.get("public_url")
    if isinstance(effective_probe_url, str) and not effective_probe_url.startswith("http"):
        effective_probe_url = None

    optimizer = CostOptimizationSpecialist()
    try:
        analysis = await optimizer.optimize(
            code_profile=code_profile,
            preferred_provider=provider,
            probe_url=effective_probe_url,
        )
    except Exception:
        prediction = _ensure_dict(code_profile.get("resource_prediction"))
        memory = int(prediction.get("memory_mb") or 512)
        cpu = float(prediction.get("cpu") or 0.5)
        monthly_cost = 12.0 if memory <= 512 else 24.0
        analysis = {
            "provider": provider,
            "recommended": {
                "config": {
                    "memory_mb": memory,
                    "cpu": cpu,
                    "label": "recommended",
                },
                "benchmark": {
                    "p50_ms": 120.0,
                    "p95_ms": 220.0,
                    "p99_ms": 320.0,
                    "success_rate": 0.995,
                    "meets_sla": False,
                },
                "monthly_cost_usd": monthly_cost,
            },
            "comparison_matrix": [
                {
                    "config": {"memory_mb": memory, "cpu": cpu, "label": "recommended"},
                    "benchmark": {"p50_ms": 120.0, "p95_ms": 220.0, "p99_ms": 320.0, "success_rate": 0.995, "meets_sla": False},
                    "monthly_cost_usd": monthly_cost,
                }
            ],
            "sla": {"p95_ms_lt": 200, "success_rate_gte": 0.999},
            "method": "fallback_estimation",
            "tested": False,
            "note": "Using fallback cost estimation because full optimization analysis was unavailable.",
        }

    existing_deploy_intel = _ensure_dict(insights.get("deployment_intelligence"))
    existing_estimate = existing_deploy_intel.get("estimated_monthly_cost_usd")
    current_monthly_cost = float(existing_estimate) if isinstance(existing_estimate, (int, float)) else None

    recommended_cost = float(analysis.get("recommended", {}).get("monthly_cost_usd") or 0.0)
    potential_savings = None
    if current_monthly_cost is not None:
        potential_savings = round(max(0.0, current_monthly_cost - recommended_cost), 2)

    recommended_cfg = _ensure_dict(_ensure_dict(analysis.get("recommended")).get("config"))
    recommended_memory = int(recommended_cfg.get("memory_mb") or 512)
    estimator = CostOptimizationSpecialist()
    provider_costs_usd: dict[str, float] = {
        provider_name: estimator._estimate_monthly_cost(provider_name, recommended_memory)
        for provider_name in _COST_COMPARISON_PROVIDERS
    }
    cheapest_provider = min(provider_costs_usd, key=provider_costs_usd.get) if provider_costs_usd else provider
    usd_to_inr, fx_updated_at, fx_fallback = await _get_usd_to_inr_rate()
    provider_costs_inr = {
        name: round(cost * usd_to_inr, 2)
        for name, cost in provider_costs_usd.items()
    }

    comparison_matrix = analysis.get("comparison_matrix") if isinstance(analysis, dict) else None
    if isinstance(comparison_matrix, list):
        for row in comparison_matrix:
            if not isinstance(row, dict):
                continue
            monthly_usd = row.get("monthly_cost_usd")
            if isinstance(monthly_usd, (int, float)):
                row["monthly_cost_inr"] = round(float(monthly_usd) * usd_to_inr, 2)

    recommended_row = analysis.get("recommended") if isinstance(analysis, dict) else None
    if isinstance(recommended_row, dict):
        monthly_usd = recommended_row.get("monthly_cost_usd")
        if isinstance(monthly_usd, (int, float)):
            recommended_row["monthly_cost_inr"] = round(float(monthly_usd) * usd_to_inr, 2)

    return {
        "project_id": project_id,
        "provider": cheapest_provider,
        "provider_requested": provider,
        "cheapest_provider": cheapest_provider,
        "analysis": analysis,
        "current_monthly_cost_usd": current_monthly_cost,
        "current_monthly_cost_inr": round(current_monthly_cost * usd_to_inr, 2) if isinstance(current_monthly_cost, (int, float)) else None,
        "recommended_monthly_cost_usd": recommended_cost,
        "recommended_monthly_cost_inr": round(recommended_cost * usd_to_inr, 2),
        "potential_monthly_savings_usd": potential_savings,
        "potential_monthly_savings_inr": round(potential_savings * usd_to_inr, 2) if isinstance(potential_savings, (int, float)) else None,
        "provider_costs_usd": provider_costs_usd,
        "provider_costs_inr": provider_costs_inr,
        "usd_to_inr_rate": round(usd_to_inr, 4),
        "fx_updated_at": fx_updated_at,
        "fx_fallback": fx_fallback,
        "already_applied": _ensure_dict(insights.get("optimization_applied")),
        "note": "Apply writes optimization intent to project insights; infra rollouts can consume this config.",
    }


@router.get("/{project_id}")
async def get_project_optimization(project_id: int, probe_url: str | None = None) -> dict[str, Any]:
    """Return optimization summary plus full analysis payload for frontend cost display wiring."""
    project = get_project(project_id)
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")

    analysis_response = await analyze_project_optimization(project_id=project_id, probe_url=probe_url)
    analysis = _ensure_dict(analysis_response.get("analysis"))
    recommended = _ensure_dict(analysis.get("recommended"))
    recommended_config = _ensure_dict(recommended.get("config"))

    code_profile = _get_code_profile(project)
    current_config = _extract_current_resource_config(project, code_profile)

    recommended_monthly = float(analysis_response.get("recommended_monthly_cost_usd") or recommended.get("monthly_cost_usd") or 0.0)
    recommended_monthly_inr = float(analysis_response.get("recommended_monthly_cost_inr") or 0.0)
    current_monthly_raw = analysis_response.get("current_monthly_cost_usd")
    current_monthly = float(current_monthly_raw) if isinstance(current_monthly_raw, (int, float)) else None
    current_monthly_inr_raw = analysis_response.get("current_monthly_cost_inr")
    current_monthly_inr = float(current_monthly_inr_raw) if isinstance(current_monthly_inr_raw, (int, float)) else None

    savings_pct = None
    if isinstance(current_monthly, (int, float)) and current_monthly > 0:
        savings_pct = round(((current_monthly - recommended_monthly) / current_monthly) * 100.0, 2)

    return {
        **analysis_response,
        "provider": str(analysis_response.get("provider") or analysis.get("provider") or "railway"),
        "cheapest_provider": str(analysis_response.get("cheapest_provider") or analysis_response.get("provider") or "railway"),
        "monthly_cost_usd": recommended_monthly,
        "monthly_cost_inr": recommended_monthly_inr,
        "recommended_resource_config": {
            "memory_mb": int(recommended_config.get("memory_mb") or 512),
            "cpu": float(recommended_config.get("cpu") or 0.5),
            "label": str(recommended_config.get("label") or "recommended"),
        },
        "current_resource_config": current_config,
        "current_monthly_cost_usd": current_monthly,
        "current_monthly_cost_inr": current_monthly_inr,
        "savings_percentage": savings_pct,
        "provider_costs_usd": analysis_response.get("provider_costs_usd") or {},
        "provider_costs_inr": analysis_response.get("provider_costs_inr") or {},
        "usd_to_inr_rate": analysis_response.get("usd_to_inr_rate"),
        "fx_updated_at": analysis_response.get("fx_updated_at"),
        "fx_fallback": bool(analysis_response.get("fx_fallback")),
    }


@router.post("/{project_id}/apply")
async def apply_project_optimization(project_id: int, payload: ApplyOptimizationRequest) -> dict[str, Any]:
    """Persist a selected optimization config for deployment/runtime consumers."""
    project = get_project(project_id)
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")

    analysis_response = await analyze_project_optimization(project_id=project_id)
    analysis = _ensure_dict(analysis_response.get("analysis"))

    comparison = analysis.get("comparison_matrix") or []
    selected = analysis.get("recommended") or {}

    if payload.memory_mb is not None:
        for row in comparison:
            config = _ensure_dict(row.get("config"))
            if int(config.get("memory_mb") or -1) == int(payload.memory_mb):
                selected = row
                break

    config = _ensure_dict(selected.get("config"))
    if payload.cpu is not None:
        config["cpu"] = payload.cpu
    if payload.memory_mb is not None:
        config["memory_mb"] = payload.memory_mb

    applied = {
        "applied_at": datetime.utcnow().isoformat() + "Z",
        "provider": payload.provider or analysis_response.get("provider") or project.get("preferred_provider"),
        "config": config,
        "estimated_monthly_cost_usd": float(selected.get("monthly_cost_usd") or 0.0),
        "source": "optimization_api_apply",
        "note": payload.note or "Applied via optimization endpoint",
    }

    existing_insights = _ensure_dict(project.get("agentic_insights"))
    updated_insights = {
        **existing_insights,
        "cost_optimization": analysis,
        "optimization_applied": applied,
    }

    update_project(project_id, {"agentic_insights": updated_insights})
    add_log(
        project_id,
        "CostOptimization",
        f"Applied optimization: provider={applied['provider']} memory={config.get('memory_mb')}MB cpu={config.get('cpu')}",
        "info",
    )

    return {
        "status": "applied",
        "project_id": project_id,
        "applied": applied,
        "next_steps": [
            "Use the selected config in deployment manifests or provider settings.",
            "Re-run analyze with a probe URL after deployment to validate SLA and savings.",
        ],
    }
