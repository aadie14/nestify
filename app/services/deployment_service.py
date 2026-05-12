"""Deployment provider orchestration for static and backend applications.

Consolidates Vercel, Netlify, and Railway deployment logic with
provider auto-selection, URL verification, and structured result output.
"""

from __future__ import annotations

import asyncio
import base64
import io
import json
import logging
import os
import re
import secrets
import shutil
import subprocess
import tempfile
import zipfile
from pathlib import Path
from typing import Any
from urllib.parse import quote

import httpx

from app.core.config import settings
from app.database import add_deployment_outcome, add_log, get_project, list_deployment_outcomes, update_project
from app.services.providers import GCPDeploymentProvider
from app.services.project_source_service import get_project_source_dir
from app.services.project_source_service import load_source_file_map
from app.services.project_source_service import ensure_preview_index, get_local_preview_url

logger = logging.getLogger(__name__)

# ─── Constants ───────────────────────────────────────────────────

VERCEL_DEPLOYMENTS_URL = "https://api.vercel.com/v13/deployments"
NETLIFY_API_URL = "https://api.netlify.com/api/v1"

STATIC_FILE_EXTENSIONS = {
    ".html", ".css", ".js", ".mjs", ".cjs", ".json", ".txt", ".xml",
    ".svg", ".map", ".webmanifest", ".png", ".jpg", ".jpeg", ".gif", ".ico", ".webp",
}
FRONTEND_FRAMEWORKS = {"react", "vite", "vue", "svelte", "astro", "next"}
NEEDS_CREDENTIALS_ACTION = "needs_credentials"
NEEDS_CREDENTIALS_ACTION_LEGACY = "حتاج_credentials"


# ─── App Kind Detection ─────────────────────────────────────────


def detect_app_kind(stack_info: dict[str, Any], files: list[dict[str, str]]) -> str:
    """Detect whether the project is a static site or backend application."""
    names = [f.get("name", "") for f in files]
    framework = stack_info.get("framework", "unknown")
    runtime = stack_info.get("runtime", "unknown")

    if any(n.endswith("index.html") for n in names) and framework in FRONTEND_FRAMEWORKS:
        return "static"
    if framework in FRONTEND_FRAMEWORKS and runtime == "node":
        return "static"
    if runtime in {"python", "go", "php", "ruby", "java", "rust"}:
        return "backend"
    if runtime == "node" and framework not in FRONTEND_FRAMEWORKS:
        return "backend"
    return "static" if any(n.endswith("index.html") for n in names) else "backend"


def choose_provider(app_kind: str, preferred_provider: str | None) -> str:
    """Select the deployment provider based on app kind and user preference."""
    static_order: list[str] = []
    if os.getenv("VERCEL_TOKEN"):
        static_order.append("vercel")
    if os.getenv("NETLIFY_API_TOKEN"):
        static_order.append("netlify")

    backend_order: list[str] = []
    if os.getenv("FLY_API_TOKEN"):
        backend_order.append("fly")
    if _gcp_credentials_ready():
        backend_order.append("gcp")
    if os.getenv("RAILWAY_API_KEY"):
        backend_order.append("railway")

    supported = static_order if app_kind == "static" else backend_order
    if preferred_provider in supported:
        return preferred_provider
    if not supported:
        if app_kind == "static":
            raise RuntimeError(
                "No static deployment provider token found. Configure VERCEL_TOKEN or NETLIFY_API_TOKEN for a public live URL."
            )
        raise RuntimeError(
            "No backend deployment provider token found. Configure FLY_API_TOKEN, RAILWAY_API_KEY, or GCP credentials for a public live URL."
        )
    return supported[0]


def _credentials_snapshot() -> dict[str, bool]:
    return {
        "vercel": bool(os.getenv("VERCEL_TOKEN", "").strip()),
        "netlify": bool(os.getenv("NETLIFY_API_TOKEN", "").strip()),
        "fly": bool(os.getenv("FLY_API_TOKEN", "").strip()),
        "railway": bool(os.getenv("RAILWAY_API_KEY", "").strip()),
        "gcp": _gcp_credentials_ready(),
        "github": bool((settings.github_token or os.getenv("GITHUB_TOKEN", "")).strip()),
        "railway_workspace": bool(os.getenv("RAILWAY_WORKSPACE_ID", "").strip()),
    }


def _gcp_credentials_ready() -> bool:
    project_id = os.getenv("GCP_PROJECT_ID", "").strip()
    service_account_json = os.getenv("GCP_SERVICE_ACCOUNT_JSON", "").strip()
    adc_path = os.getenv("GOOGLE_APPLICATION_CREDENTIALS", "").strip()
    return bool(service_account_json) or bool(adc_path) or bool(project_id)


def _estimate_success_probability(app_kind: str, provider_candidates: list[str], creds: dict[str, bool], github_url: str | None) -> float:
    score = 0.2
    if provider_candidates:
        score += 0.38
    if app_kind == "static":
        if creds.get("vercel") or creds.get("netlify"):
            score += 0.2
    else:
        if creds.get("gcp"):
            score += 0.2
        if creds.get("railway"):
            score += 0.14
        if github_url or creds.get("github"):
            score += 0.14
        if creds.get("railway_workspace"):
            score += 0.08
    return max(0.05, min(0.98, score))


def _graphql_fly_request(query: str, variables: dict[str, Any] | None = None) -> dict[str, Any]:
    """Send a Fly GraphQL request using the configured token."""
    token = os.getenv("FLY_API_TOKEN", "").strip()
    if not token:
        raise RuntimeError("FLY_API_TOKEN not set")
    response = httpx.post(
        "https://api.fly.io/graphql",
        headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
        json={"query": query, "variables": variables or {}},
        timeout=60,
    )
    payload = response.json() if response.content else {}
    if response.status_code >= 400 or payload.get("errors"):
        error_text = response.text[:500]
        if payload.get("errors"):
            error_text = payload["errors"][0].get("message", error_text)
        raise RuntimeError(f"Fly GraphQL error: {error_text}")
    return payload.get("data") or {}


def _fly_personal_organization() -> dict[str, Any]:
    """Return the active personal organization details for the Fly token owner."""
    data = _graphql_fly_request("query { personalOrganization { id slug name } }")
    org = data.get("personalOrganization") or {}
    if org.get("id") and org.get("slug"):
        return org

    data = _graphql_fly_request("query { organizations(first: 1, admin: true) { edges { node { id slug name } } } }")
    edges = ((data.get("organizations") or {}).get("edges") or [])
    if edges:
        return edges[0].get("node") or {}
    raise RuntimeError("Unable to determine a Fly organization for app creation")


def _fly_find_or_create_app(app_name: str) -> dict[str, Any]:
    """Find a Fly app by name or create it if it doesn't exist."""
    query = "query($name: String!) { app(name: $name) { id name appUrl ipAddresses { nodes { address type region } } } }"
    data = _graphql_fly_request(query, {"name": app_name})
    app = data.get("app")
    if app and app.get("id"):
        return app

    org = _fly_personal_organization()
    create_data = _graphql_fly_request(
        """
        mutation($input: CreateAppInput!) {
          createApp(input: $input) {
            app { id name appUrl ipAddresses { nodes { address type region } } }
          }
        }
        """,
        {
            "input": {
                "name": app_name,
                "organizationId": org["id"],
                "machines": True,
                "enableSubdomains": True,
            }
        },
    )
    created = ((create_data.get("createApp") or {}).get("app") or {})
    if not created.get("id"):
        raise RuntimeError("Fly app creation did not return an app id")
    return created


def _fly_allocate_ip(app_id: str, ip_type: str) -> dict[str, Any] | None:
    """Allocate a Fly public IP if the app does not already have one of this type."""
    app_data = _graphql_fly_request(
        "query($id: ID!) { app(id: $id) { id ipAddresses { nodes { address type region } } } }",
        {"id": app_id},
    ).get("app") or {}
    current_ips = app_data.get("ipAddresses") or {}
    nodes = current_ips.get("nodes") or []
    if any(str(node.get("type") or "").lower() == ip_type.lower() for node in nodes):
        return None

    allocate_data = _graphql_fly_request(
        """
        mutation($input: AllocateIPAddressInput!) {
          allocateIpAddress(input: $input) {
            ipAddress { id address type region }
          }
        }
        """,
        {
            "input": {
                "appId": app_id,
                "type": ip_type,
            }
        },
    )
    return ((allocate_data.get("allocateIpAddress") or {}).get("ipAddress") or None)


def _copy_source_to_temp_dir(project_id: int) -> Path:
    """Copy persisted project source to a temp build directory for Docker."""
    source_dir = Path(get_project_source_dir(project_id)) / "source"
    if not source_dir.exists():
        raise RuntimeError("No persisted source directory found for Fly build")

    temp_dir = Path(tempfile.mkdtemp(prefix=f"nestify-fly-{project_id}-"))
    for path in source_dir.rglob("*"):
        if not path.is_file():
            continue
        rel = path.relative_to(source_dir)
        if any(part in {".git", "node_modules", "dist", "build", "__pycache__", ".venv", "venv", "env"} for part in rel.parts):
            continue
        target = temp_dir / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(path, target)
    return temp_dir


def _build_fly_dockerfile(build_dir: Path, project_name: str, stack_info: dict[str, Any]) -> Path:
    """Create a temporary Dockerfile suitable for a backend Fly deployment."""
    runtime = str(stack_info.get("runtime") or "").lower()
    if runtime == "node" or (build_dir / "package.json").exists():
        dockerfile = f"""
FROM node:20-slim
WORKDIR /app
ENV NODE_ENV=production PORT=8080
COPY package*.json ./
RUN if [ -f package-lock.json ]; then npm ci --omit=dev; else npm install --omit=dev; fi
COPY . .
EXPOSE 8080
CMD ["npm", "start"]
"""
    else:
        requirements = build_dir / "requirements.txt"
        if not requirements.exists() and (build_dir / "pyproject.toml").exists():
            dockerfile = f"""
FROM python:3.11-slim
WORKDIR /app
ENV PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1 PORT=8080
RUN apt-get update && apt-get install -y --no-install-recommends build-essential curl && rm -rf /var/lib/apt/lists/*
COPY . .
RUN pip install --no-cache-dir uvicorn fastapi
RUN pip install --no-cache-dir .
EXPOSE 8080
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8080"]
"""
        else:
            dockerfile = f"""
FROM python:3.11-slim
WORKDIR /app
ENV PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1 PORT=8080
RUN apt-get update && apt-get install -y --no-install-recommends build-essential curl && rm -rf /var/lib/apt/lists/*
COPY requirements.txt /tmp/requirements.txt
RUN pip install --no-cache-dir -r /tmp/requirements.txt
COPY . .
EXPOSE 8080
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8080"]
"""
    dockerfile_path = build_dir / "Dockerfile.fly"
    dockerfile_path.write_text(dockerfile.strip() + "\n", encoding="utf-8")
    return dockerfile_path


def _docker_build_and_push_fly_image(*, build_dir: Path, dockerfile_path: Path, app_name: str, tag: str, token: str) -> str:
    """Build a container image and push it to the Fly registry."""
    image_ref = f"registry.fly.io/{app_name}:{tag}"
    login = subprocess.run(
        ["docker", "login", "registry.fly.io", "-u", "x", "-p", token],
        capture_output=True,
        text=True,
        check=False,
    )
    if login.returncode != 0:
        raise RuntimeError(f"Docker login failed: {login.stderr.strip() or login.stdout.strip()}")

    build = subprocess.run(
        ["docker", "build", "-f", str(dockerfile_path), "-t", image_ref, str(build_dir)],
        capture_output=True,
        text=True,
        check=False,
    )
    if build.returncode != 0:
        raise RuntimeError(f"Docker build failed: {build.stderr.strip() or build.stdout.strip()}")

    push = subprocess.run(
        ["docker", "push", image_ref],
        capture_output=True,
        text=True,
        check=False,
    )
    if push.returncode != 0:
        raise RuntimeError(f"Docker push failed: {push.stderr.strip() or push.stdout.strip()}")
    return image_ref


def validate_pre_deployment(
    *,
    app_kind: str,
    preferred_provider: str | None,
    github_url: str | None,
) -> dict[str, Any]:
    """Validate deployment prerequisites before contacting any provider API."""
    creds = _credentials_snapshot()
    preferred = str(preferred_provider or "").strip().lower() or None

    static_candidates = [p for p in ["vercel", "netlify"] if creds.get(p)]
    backend_candidates = [provider for provider in ["fly", "railway", "gcp"] if creds.get(provider)]
    candidates = static_candidates if app_kind == "static" else backend_candidates

    if preferred and preferred in candidates:
        candidates = [preferred] + [p for p in candidates if p != preferred]

    probability = _estimate_success_probability(app_kind, candidates, creds, github_url)

    if not candidates:
        reason = (
            "No static deployment credentials were found."
            if app_kind == "static"
            else "No backend deployment credentials were found."
        )
        fix = (
            "Connect Vercel or Netlify credentials to enable public static deployment."
            if app_kind == "static"
            else "Configure FLY_API_TOKEN, Railway credentials, or GCP project credentials (GCP_PROJECT_ID + service account/ADC)."
        )
        return {
            "ok": False,
            "action": NEEDS_CREDENTIALS_ACTION,
            "action_legacy": NEEDS_CREDENTIALS_ACTION_LEGACY,
            "reason": reason,
            "fix_suggestion": fix,
            "next_action": "Connect a provider and retry deployment.",
            "options": [
                {
                    "option": "connect_provider",
                    "label": "Connect provider credentials",
                    "description": "Add VERCEL_TOKEN / NETLIFY_API_TOKEN for static apps, or GCP_PROJECT_ID + service account/ADC for backend apps.",
                },
                {
                    "option": "auto_publish_github_then_deploy",
                    "label": "Enable autonomous source publishing",
                    "description": "Set GITHUB_TOKEN so Nestify can auto-create a temporary GitHub repository and deploy once provider credentials are configured.",
                },
            ],
            "credentials": creds,
            "provider_candidates": candidates,
            "success_probability": probability,
        }

    if app_kind == "backend" and not github_url and not creds.get("github") and "gcp" not in candidates:
        return {
            "ok": False,
            "action": NEEDS_CREDENTIALS_ACTION,
            "action_legacy": NEEDS_CREDENTIALS_ACTION_LEGACY,
            "reason": "Backend deployment needs a repository source. No GitHub URL or GITHUB_TOKEN is configured.",
            "fix_suggestion": "Provide a GitHub repository URL or configure GITHUB_TOKEN for automatic temporary repository publishing.",
            "next_action": "Add github_url or GITHUB_TOKEN, then retry deployment.",
            "options": [
                {
                    "option": "connect_provider",
                    "label": "Connect provider credentials",
                    "description": "Keep Fly, Railway, or GCP credentials available for backend deployment.",
                },
                {
                    "option": "auto_publish_github_then_deploy",
                    "label": "Auto-create temporary GitHub repository",
                    "description": "Set GITHUB_TOKEN and let Nestify publish source automatically before deploy.",
                },
            ],
            "credentials": creds,
            "provider_candidates": candidates,
            "success_probability": probability,
        }

    selected = candidates[0]
    return {
        "ok": True,
        "provider": selected,
        "provider_candidates": candidates,
        "credentials": creds,
        "success_probability": probability,
    }


def _failure_payload(
    *,
    provider: str,
    app_kind: str,
    reason: str,
    fix_suggestion: str,
    next_action: str,
    action: str = "resolve_error",
    success_probability: float | None = None,
    extra: dict[str, Any] | None = None,
) -> dict[str, Any]:
    details = {
        "reason": reason,
        "plain_english_error": reason,
        "fix_suggestion": fix_suggestion,
        "next_action": next_action,
        "action": action,
        "app_kind": app_kind,
    }
    if success_probability is not None:
        details["success_probability"] = max(0.0, min(1.0, float(success_probability)))
    if extra:
        details.update(extra)
    return {
        "provider": provider,
        "deployment_url": None,
        "status": "blocked" if action in {NEEDS_CREDENTIALS_ACTION, NEEDS_CREDENTIALS_ACTION_LEGACY} else "failed",
        "details": details,
    }


def _normalize_error_signature(message: str) -> str:
    text = str(message or "").lower()
    if not text:
        return "unknown_error"
    if "no deployable static bundle" in text or "build" in text and "dist" in text:
        return "missing_build_step"
    if "credential" in text or "token" in text:
        return "missing_credentials"
    if "github" in text and ("require" in text or "publish" in text):
        return "missing_github_source"
    if "timeout" in text or "reachable" in text:
        return "provider_timeout"
    if "unsupported" in text:
        return "provider_mismatch"
    if "free plan" in text or "resource provision" in text or "quota" in text:
        return "provider_quota_exceeded"
    return "provider_error"


def _parse_stack_info(project_row: dict[str, Any] | None) -> dict[str, Any]:
    if not project_row:
        return {}
    raw = project_row.get("stack_info")
    if isinstance(raw, dict):
        return raw
    if isinstance(raw, str) and raw.strip():
        try:
            parsed = json.loads(raw)
            return parsed if isinstance(parsed, dict) else {}
        except json.JSONDecodeError:
            return {}
    return {}


def _derive_learning_strategy(
    *,
    framework: str,
    provider_candidates: list[str],
) -> dict[str, Any]:
    outcomes = list_deployment_outcomes(limit=400)
    similar = [
        row for row in outcomes
        if str(row.get("framework") or "unknown").lower() == framework.lower()
    ]

    if not similar:
        return {
            "sample_size": 0,
            "apply_fix_first": False,
            "preferred_provider": None,
            "reason": "No similar deployment history yet.",
        }

    error_counts: dict[str, int] = {}
    provider_stats: dict[str, dict[str, int]] = {}

    for row in similar:
        provider = str(row.get("platform") or "").strip().lower()
        if provider:
            provider_stats.setdefault(provider, {"total": 0, "success": 0})
            provider_stats[provider]["total"] += 1
            if bool(row.get("success")):
                provider_stats[provider]["success"] += 1

        transcript = row.get("debate_transcript") or {}
        signatures = transcript.get("error_signatures") if isinstance(transcript, dict) else None
        if isinstance(signatures, list):
            for sig in signatures:
                key = str(sig or "unknown_error")
                error_counts[key] = error_counts.get(key, 0) + 1

    dominant_error = max(error_counts.items(), key=lambda item: item[1])[0] if error_counts else ""
    missing_build_count = error_counts.get("missing_build_step", 0)
    apply_fix_first = missing_build_count >= 2

    preferred_provider = None
    best_rate = 0.0
    for provider in provider_candidates:
        stats = provider_stats.get(provider)
        if not stats:
            rate = 0.5
        else:
            # Bayesian smoothing: lets the agent make a choice even when a provider has little history.
            rate = (stats["success"] + 1) / (stats["total"] + 2)
        if rate > best_rate:
            best_rate = rate
            preferred_provider = provider

    reason_bits = []
    if apply_fix_first:
        reason_bits.append(
            "Previous similar deployments often failed due to missing build output; applying build-validation fix first."
        )
    if preferred_provider:
        reason_bits.append(
            f"Historical success rate favors {preferred_provider} ({round(best_rate * 100)}% on similar projects)."
        )
    if not reason_bits:
        reason_bits.append("No dominant historical failure pattern detected.")

    return {
        "sample_size": len(similar),
        "apply_fix_first": apply_fix_first,
        "preferred_provider": preferred_provider,
        "dominant_error": dominant_error,
        "reason": " ".join(reason_bits),
    }


def _collect_fixes(details: dict[str, Any]) -> list[str]:
    fixes: list[str] = []
    for key in ("what_i_fixed", "fixes_applied", "changes"):
        values = details.get(key)
        if isinstance(values, list):
            fixes.extend(str(item) for item in values if str(item or "").strip())
    fix_suggestion = str(details.get("fix_suggestion") or "").strip()
    if fix_suggestion:
        fixes.append(fix_suggestion)
    return fixes[:20]


def _record_learning(
    *,
    project_id: int,
    framework: str,
    provider: str,
    result: dict[str, Any],
    error_signatures: list[str],
    strategy_reason: str,
) -> None:
    details = result.get("details") if isinstance(result.get("details"), dict) else {}
    fixes = _collect_fixes(details)
    success = bool(result.get("deployment_url")) and str(result.get("status") or "").lower() == "success"

    learnings = []
    if strategy_reason:
        learnings.append(strategy_reason)
    if error_signatures:
        learnings.append(
            f"Observed error patterns: {', '.join(sorted(set(error_signatures)))}"
        )

    add_deployment_outcome(
        project_id=project_id,
        framework=framework,
        platform=provider,
        success=success,
        duration_seconds=None,
        cost_per_month=None,
        fixes_applied=fixes,
        debate_transcript={
            "error_signatures": list(dict.fromkeys(error_signatures)),
            "result_status": result.get("status"),
            "provider": provider,
        },
        learnings=learnings,
        agentic_enabled=True,
    )


# ─── Helpers ─────────────────────────────────────────────────────


def _sanitize_project_name(name: str) -> str:
    slug = re.sub(r"[^a-z0-9-]+", "-", name.lower()).strip("-")
    return (re.sub(r"-{2,}", "-", slug) or "nestify-app")[:48]


def _build_unique_site_name(name: str) -> str:
    base = _sanitize_project_name(name)[:36].rstrip("-") or "nestify-app"
    return f"{base}-{secrets.token_hex(3)}"


def _normalize_public_url(url: str | None) -> str | None:
    """Ensure a URL has the https:// prefix."""
    if not url:
        return None
    url = url.strip()
    if not url.startswith("http"):
        url = f"https://{url}"
    return url


async def _wait_for_live_url(url: str, timeout_seconds: int = 60) -> bool:
    """Poll a URL until it returns a 2xx status."""
    deadline = asyncio.get_event_loop().time() + timeout_seconds
    async with httpx.AsyncClient(timeout=10, follow_redirects=True) as client:
        while asyncio.get_event_loop().time() < deadline:
            try:
                resp = await client.get(url)
                if 200 <= resp.status_code < 400:
                    return True
            except (httpx.RequestError, httpx.TimeoutException):
                pass
            await asyncio.sleep(3)
    return False


def _decode_source_text_map(file_map: dict[str, bytes]) -> dict[str, str]:
    text_map: dict[str, str] = {}
    for path, content in file_map.items():
        try:
            text_map[path] = content.decode("utf-8")
        except UnicodeDecodeError:
            continue
    return text_map


def _choose_static_root(files_by_path: dict[str, str]) -> str | None:
    preferred = ["dist/index.html", "build/index.html", "public/index.html", "index.html"]
    for candidate in preferred:
        if candidate in files_by_path:
            return candidate.rsplit("/", 1)[0] if "/" in candidate else ""
    html_files = [path for path in files_by_path if path.endswith("index.html")]
    if not html_files:
        return None
    shallowest = min(html_files, key=lambda p: (p.count("/"), len(p)))
    return shallowest.rsplit("/", 1)[0] if "/" in shallowest else ""


def extract_static_bundle_from_project(project_id: int) -> dict[str, bytes] | None:
    """Extract deployable static files from a project's stored source."""
    file_map = load_source_file_map(project_id)
    if not file_map:
        return None
    text_map = _decode_source_text_map(file_map)
    root = _choose_static_root(text_map)
    if root is None:
        return None

    bundle: dict[str, bytes] = {}
    prefix = f"{root}/" if root else ""
    for path, content in file_map.items():
        if prefix and not path.startswith(prefix):
            continue
        rel_path = path[len(prefix):] if prefix else path
        ext = os.path.splitext(rel_path)[1].lower()
        if ext and ext not in STATIC_FILE_EXTENSIONS:
            continue
        bundle[rel_path] = content
    return bundle if "index.html" in bundle else None


# ─── Vercel ──────────────────────────────────────────────────────


async def _vercel_request(method: str, path: str = "", *, json_body: dict | None = None) -> dict:
    token = os.getenv("VERCEL_TOKEN")
    if not token:
        raise RuntimeError("VERCEL_TOKEN not set")
    async with httpx.AsyncClient(timeout=60) as client:
        response = await client.request(
            method,
            f"{VERCEL_DEPLOYMENTS_URL}{path}",
            headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
            json=json_body,
        )
    payload = response.json() if response.content else {}
    if response.status_code >= 400:
        message = payload.get("error", {}).get("message") or payload.get("message") or response.text
        raise RuntimeError(f"Vercel API error: {message}")
    return payload


async def deploy_static_to_vercel(project_name: str, bundle: dict[str, bytes]) -> dict[str, Any]:
    """Deploy a static site bundle to Vercel."""
    files_payload = [
        {"file": path, "data": base64.b64encode(content).decode("ascii"), "encoding": "base64"}
        for path, content in sorted(bundle.items())
    ]
    deployment = await _vercel_request(
        "POST",
        "?forceNew=1&skipAutoDetectionConfirmation=1",
        json_body={
            "name": _sanitize_project_name(project_name),
            "files": files_payload,
            "public": True,
            "projectSettings": {
                "framework": None, "buildCommand": None,
                "installCommand": None, "outputDirectory": None, "devCommand": None,
            },
            "target": "production",
        },
    )
    deployment_id = deployment["id"]
    status_payload = deployment
    for _ in range(40):
        ready_state = (status_payload.get("readyState") or status_payload.get("status") or "").upper()
        if ready_state == "READY":
            break
        if ready_state in {"ERROR", "CANCELED"}:
            raise RuntimeError(status_payload.get("errorMessage") or "Vercel deployment failed")
        await asyncio.sleep(3)
        status_payload = await _vercel_request("GET", f"/{deployment_id}")

    ready_url = _normalize_public_url(
        status_payload.get("aliasFinal") or status_payload.get("url") or deployment.get("url")
    )
    if not ready_url or not await _wait_for_live_url(ready_url, timeout_seconds=60):
        raise RuntimeError("Vercel deployment did not become reachable in time.")

    return {
        "provider": "vercel",
        "deployment_url": ready_url,
        "status": "success",
        "details": {
            "deployment_id": deployment_id,
            "inspector_url": status_payload.get("inspectorUrl"),
            "project_id": status_payload.get("projectId"),
        },
    }


# ─── Netlify ─────────────────────────────────────────────────────


async def _netlify_request(
    method: str, path: str, *, json_body: dict | None = None,
    content: bytes | None = None, content_type: str | None = None,
) -> dict:
    token = os.getenv("NETLIFY_API_TOKEN")
    if not token:
        raise RuntimeError("NETLIFY_API_TOKEN not set")
    headers: dict[str, str] = {"Authorization": f"Bearer {token}"}
    if content_type:
        headers["Content-Type"] = content_type
    elif json_body is not None:
        headers["Content-Type"] = "application/json"
    async with httpx.AsyncClient(timeout=90) as client:
        response = await client.request(method, f"{NETLIFY_API_URL}{path}", headers=headers, json=json_body, content=content)
    payload = response.json() if response.content else {}
    if response.status_code >= 400:
        raise RuntimeError(payload.get("message") or payload.get("error_message") or response.text)
    return payload


def _build_zip_bundle(bundle: dict[str, bytes]) -> bytes:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
        for path, content in sorted(bundle.items()):
            archive.writestr(path, content)
    return buffer.getvalue()


async def deploy_static_to_netlify(project_name: str, bundle: dict[str, bytes]) -> dict[str, Any]:
    """Deploy a static site bundle to Netlify."""
    site_name = _build_unique_site_name(project_name)
    site = await _netlify_request("POST", "/sites", json_body={"name": site_name})
    site_id = site["id"]
    deploy = await _netlify_request(
        "POST", f"/sites/{site_id}/deploys",
        content=_build_zip_bundle(bundle), content_type="application/zip",
    )
    deploy_id = deploy["id"]
    deploy_status = deploy
    for _ in range(40):
        state = (deploy_status.get("state") or "").lower()
        if state == "ready":
            break
        if state == "error":
            raise RuntimeError(deploy_status.get("error_message") or "Netlify deployment failed")
        await asyncio.sleep(3)
        deploy_status = await _netlify_request("GET", f"/deploys/{deploy_id}")

    site_status = await _netlify_request("GET", f"/sites/{site_id}")
    ready_url = _normalize_public_url(site_status.get("ssl_url") or site_status.get("url"))
    if not ready_url or not await _wait_for_live_url(ready_url, timeout_seconds=60):
        raise RuntimeError("Netlify deployment did not become reachable in time.")

    return {
        "provider": "netlify",
        "deployment_url": ready_url,
        "status": "success",
        "details": {
            "site_id": site_id, "deploy_id": deploy_id,
            "site_name": site_name, "admin_url": site_status.get("admin_url"),
        },
    }


def deploy_static_locally(
    project_id: int,
    project_name: str,
    bundle: dict[str, bytes],
    *,
    reason: str,
) -> dict[str, Any]:
    """Fallback deployment for static apps when external provider keys are unavailable."""
    root = Path(get_project_source_dir(project_id)) / "source"
    root.mkdir(parents=True, exist_ok=True)

    for rel_path, content in bundle.items():
        target = (root / rel_path).resolve()
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(content)

    local_url = f"http://127.0.0.1:{settings.port}/preview/{project_id}"
    return {
        "provider": "local",
        "deployment_url": local_url,
        "status": "success",
        "details": {
            "mode": "local_static_fallback",
            "project_name": project_name,
            "note": reason,
        },
    }


# ─── Backend Deployment (Railway) ────────────────────────────────


def _parse_env_template(env_template: str) -> dict[str, str]:
    """Parse a .env-style template into key/value pairs."""
    env_vars: dict[str, str] = {}
    for line in (env_template or "").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        if key.strip() and value.strip():
            env_vars[key.strip()] = value.strip()
    return env_vars


async def deploy_backend_to_railway(
    project_id: int, project_name: str, github_url: str, env_template: str,
) -> dict[str, Any]:
    """Deploy a backend app to Railway via their GraphQL API."""
    api_key = os.getenv("RAILWAY_API_KEY")
    if not api_key:
        raise RuntimeError("RAILWAY_API_KEY not set")

    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }
    gql_url = "https://backboard.railway.app/graphql/v2"
    env_vars = _parse_env_template(env_template)
    workspace_id = os.getenv("RAILWAY_WORKSPACE_ID", "").strip()

    async with httpx.AsyncClient(timeout=60) as client:
        # Step 1: Create project
        project_input = f'name: "{_sanitize_project_name(project_name)}"'
        if workspace_id:
            project_input += f', workspaceId: "{workspace_id}"'

        resp = await client.post(gql_url, headers=headers, json={
            "query": f"mutation {{ projectCreate(input: {{{project_input}}}) {{ id environments {{ edges {{ node {{ id }} }} }} }} }}"
        })
        if resp.status_code != 200:
            raise RuntimeError(f"Railway project creation failed: {resp.text[:300]}")
        payload = resp.json() if resp.content else {}
        data_block = payload.get("data") or {}
        if payload.get("errors"):
            err = payload["errors"][0].get("message", "Unknown Railway GraphQL error")
            err_l = str(err).lower()
            # Detect common Railway quota / free-tier provisioning messages and surface a clear error
            if "free plan" in err_l or "resource provision" in err_l or "provision limit" in err_l or "quota" in err_l:
                raise RuntimeError(f"Railway project creation failed: {err}")
            if "workspaceid" in err_l and not workspace_id:
                raise RuntimeError(
                    "Railway project creation failed: workspaceId is required. "
                    "Set RAILWAY_WORKSPACE_ID in environment for automated backend deploys."
                )
            raise RuntimeError(f"Railway project creation failed: {err}")

        project_data = data_block.get("projectCreate", {})
        railway_project_id = project_data.get("id")
        if not railway_project_id:
            raise RuntimeError("Railway did not return a project ID")

        # Extract the default environment ID
        env_edges = (project_data.get("environments") or {}).get("edges") or []
        environment_id = env_edges[0]["node"]["id"] if env_edges else None

        add_log(project_id, "deployment_agent", f"Railway project created: {railway_project_id}", "info")

        # Step 2: Create a service from the GitHub repo
        service_name = _sanitize_project_name(project_name)
        source_block = ""
        if github_url:
            source_block = f', source: {{ repo: "{github_url}" }}'

        svc_resp = await client.post(gql_url, headers=headers, json={
            "query": f'mutation {{ serviceCreate(input: {{ projectId: "{railway_project_id}", name: "{service_name}"{source_block} }}) {{ id }} }}'
        })
        svc_payload = svc_resp.json() if svc_resp.content else {}
        svc_data = (svc_payload.get("data") or {}).get("serviceCreate") or {}
        service_id = svc_data.get("id")

        if svc_payload.get("errors"):
            err = svc_payload["errors"][0].get("message", "Service creation failed")
            add_log(project_id, "deployment_agent", f"Railway service creation error: {err}", "warn")
        elif service_id:
            add_log(project_id, "deployment_agent", f"Railway service created: {service_id}", "info")

            # Step 3: Generate a public domain for the service
            if environment_id and service_id:
                domain_resp = await client.post(gql_url, headers=headers, json={
                    "query": f'mutation {{ serviceDomainCreate(input: {{ serviceId: "{service_id}", environmentId: "{environment_id}" }}) {{ domain }} }}'
                })
                domain_payload = domain_resp.json() if domain_resp.content else {}
                domain_data = (domain_payload.get("data") or {}).get("serviceDomainCreate") or {}
                assigned_domain = domain_data.get("domain")
                if assigned_domain:
                    add_log(project_id, "deployment_agent", f"Railway domain assigned: {assigned_domain}", "info")

                # Step 4: Set environment variables if any
                if env_vars and environment_id:
                    for key, value in env_vars.items():
                        await client.post(gql_url, headers=headers, json={
                            "query": f'mutation {{ variableUpsert(input: {{ projectId: "{railway_project_id}", serviceId: "{service_id}", environmentId: "{environment_id}", name: "{key}", value: "{value}" }}) }}'
                        })

    deployment_url = await _poll_railway_for_url(
        railway_project_id=railway_project_id,
        project_id=project_id,
        timeout_minutes=5,
    )

    return {
        "provider": "railway",
        "deployment_url": deployment_url,
        "status": "success" if deployment_url else "failed",
        "details": {"railway_project_id": railway_project_id},
    }


async def _poll_railway_for_url(
    railway_project_id: str,
    project_id: int,
    timeout_minutes: int = 5,
) -> str | None:
    """Poll Railway GraphQL API until a public service domain is available."""

    api_key = os.getenv("RAILWAY_API_KEY")
    if not api_key:
        return None

    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }
    gql_url = "https://backboard.railway.app/graphql/v2"

    # Step 1: Get services and environments for the project
    project_query = """
    query GetProject($id: String!) {
      project(id: $id) {
        services {
          edges {
            node {
              id
              name
            }
          }
        }
        environments {
          edges {
            node {
              id
              name
            }
          }
        }
      }
    }
    """

    # Step 2: Query domains per service
    domains_query = """
    query GetDomains($projectId: String!, $environmentId: String!, $serviceId: String!) {
      domains(projectId: $projectId, environmentId: $environmentId, serviceId: $serviceId) {
        serviceDomains {
          domain
        }
      }
    }
    """

    deadline = asyncio.get_event_loop().time() + (max(1, timeout_minutes) * 60)
    async with httpx.AsyncClient(timeout=30) as client:
        attempts = 0
        while asyncio.get_event_loop().time() < deadline:
            try:
                # Fetch project structure
                resp = await client.post(
                    gql_url,
                    headers=headers,
                    json={"query": project_query, "variables": {"id": railway_project_id}},
                )
                if resp.status_code != 200:
                    add_log(project_id, "deployment_agent", f"Railway poll HTTP {resp.status_code}", "warn")
                    sleep_seconds = min(30, 3 + attempts * 5)
                    attempts += 1
                    await asyncio.sleep(sleep_seconds)
                    continue

                payload = resp.json() if resp.content else {}
                project_data = (payload.get("data") or {}).get("project") or {}
                services = (project_data.get("services") or {}).get("edges") or []
                environments = (project_data.get("environments") or {}).get("edges") or []

                if not services or not environments:
                    add_log(project_id, "deployment_agent", "Waiting for Railway service to be ready...", "info")
                    sleep_seconds = min(30, 3 + attempts * 5)
                    attempts += 1
                    await asyncio.sleep(sleep_seconds)
                    continue

                env_id = environments[0]["node"]["id"]

                # Check domains for each service
                for edge in services:
                    svc_id = edge["node"]["id"]
                    dom_resp = await client.post(
                        gql_url,
                        headers=headers,
                        json={
                            "query": domains_query,
                            "variables": {
                                "projectId": railway_project_id,
                                "environmentId": env_id,
                                "serviceId": svc_id,
                            },
                        },
                    )
                    if dom_resp.status_code == 200:
                        dom_payload = dom_resp.json() if dom_resp.content else {}
                        service_domains = (
                            (dom_payload.get("data") or {})
                            .get("domains", {})
                            .get("serviceDomains", [])
                        )
                        for domain_row in service_domains:
                            domain = str(domain_row.get("domain") or "").strip()
                            if domain:
                                url = _normalize_public_url(domain)
                                add_log(project_id, "deployment_agent", f"Railway URL ready: {url}", "info")
                                return url

                add_log(project_id, "deployment_agent", "Waiting for Railway deployment URL...", "info")
                sleep_seconds = min(30, 3 + attempts * 5)
                attempts += 1
                await asyncio.sleep(sleep_seconds)
            except Exception as exc:
                add_log(project_id, "deployment_agent", f"Railway URL polling error: {exc}", "warn")
                sleep_seconds = min(45, 5 + attempts * 10)
                attempts += 1
                await asyncio.sleep(sleep_seconds)

    add_log(
        project_id,
        "deployment_agent",
        "Railway URL polling timed out; deployment may still be in progress",
        "warn",
    )
    return None


async def deploy_backend_to_render(
    project_id: int, project_name: str, github_url: str, env_template: str,
) -> dict[str, Any]:
    """Deploy a backend app to Render."""
    api_key = os.getenv("RENDER_API_KEY")
    if not api_key:
        raise RuntimeError("RENDER_API_KEY not set")

    env_vars = _parse_env_template(env_template)
    headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}

    async with httpx.AsyncClient(timeout=60) as client:
        resp = await client.post(
            "https://api.render.com/v1/services",
            headers=headers,
            json={
                "type": "web_service",
                "name": _sanitize_project_name(project_name),
                "repo": github_url,
                "autoDeploy": "yes",
                "envVars": [{"key": k, "value": v} for k, v in env_vars.items()],
            },
        )
        if resp.status_code >= 400:
            raise RuntimeError(f"Render service creation failed: {resp.text[:300]}")
        service = resp.json().get("service", resp.json())
        service_id = service.get("id", "unknown")
        service_url = service.get("serviceDetails", {}).get("url")

    add_log(project_id, "deployment_agent", f"Render service created: {service_id}", "info")

    return {
        "provider": "render",
        "deployment_url": _normalize_public_url(service_url),
        "status": "success",
        "details": {"service_id": service_id},
    }


async def deploy_backend_to_fly(
    project_id: int,
    project_name: str,
    github_url: str,
    env_template: str,
    stack_info: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Deploy a backend app to Fly.io using the GraphQL + Docker registry flow."""
    token = os.getenv("FLY_API_TOKEN", "").strip()
    if not token:
        raise RuntimeError("FLY_API_TOKEN not set")

    app_name = _sanitize_project_name(project_name)
    env_vars = _parse_env_template(env_template)
    stack_info = stack_info or {}

    add_log(project_id, "deployment_agent", f"Preparing Fly.io deployment for app '{app_name}'.", "info")

    app = _fly_find_or_create_app(app_name)
    app_id = str(app.get("id") or "").strip()
    if not app_id:
        raise RuntimeError("Fly app lookup/create did not return an app id")

    # Allocate public networking. Fly requires both IP types for normal web access.
    try:
        ipv6 = _fly_allocate_ip(app_id, "v6")
        if ipv6:
            add_log(project_id, "deployment_agent", f"Allocated Fly IPv6: {ipv6.get('address') or ipv6.get('id')}", "info")
    except Exception as exc:
        add_log(project_id, "deployment_agent", f"Fly IPv6 allocation warning: {exc}", "warn")

    try:
        ipv4 = _fly_allocate_ip(app_id, "shared_v4")
        if ipv4:
            add_log(project_id, "deployment_agent", f"Allocated Fly shared IPv4: {ipv4.get('address') or ipv4.get('id')}", "info")
    except Exception as exc:
        add_log(project_id, "deployment_agent", f"Fly shared IPv4 allocation warning: {exc}", "warn")

    build_dir = _copy_source_to_temp_dir(project_id)
    dockerfile_path = _build_fly_dockerfile(build_dir, project_name, stack_info)
    image_tag = secrets.token_hex(4)
    image_ref = _docker_build_and_push_fly_image(
        build_dir=build_dir,
        dockerfile_path=dockerfile_path,
        app_name=app_name,
        tag=image_tag,
        token=token,
    )
    add_log(project_id, "deployment_agent", f"Fly image pushed: {image_ref}", "info")

    # Backend web service config for Fly Machines.
    machine_config = {
        "image": image_ref,
        "env": env_vars,
        "restart": {"policy": "always"},
        "guest": {"cpu_kind": "shared", "cpus": 1, "memory_mb": 1024},
        "services": [
            {
                "protocol": "tcp",
                "internal_port": 8080,
                "ports": [
                    {"port": 80, "handlers": ["http"], "force_https": True},
                    {"port": 443, "handlers": ["tls", "http"]},
                ],
                "autostart": True,
                "autostop": "stop",
                "min_machines_running": 1,
                "concurrency": {"type": "requests", "soft_limit": 20, "hard_limit": 50},
            }
        ],
        "metadata": {
            "fly_process_group": "app",
            "fly_platform_version": "v2",
            "nestify_project_id": str(project_id),
        },
    }

    launch_data = _graphql_fly_request(
        """
        mutation($input: LaunchMachineInput!) {
          launchMachine(input: $input) {
            app { id name appUrl }
            machine { id name state region }
          }
        }
        """,
        {
            "input": {
                "appId": app_id,
                "name": app_name,
                "config": machine_config,
            }
        },
    )
    launch_payload = launch_data.get("launchMachine") or {}
    machine = launch_payload.get("machine") or {}
    if not machine.get("id"):
        raise RuntimeError("Fly machine launch did not return a machine id")

    add_log(
        project_id,
        "deployment_agent",
        f"Fly machine launched: {machine.get('id')} in region {machine.get('region') or 'auto'}",
        "info",
    )

    public_url = f"https://{app_name}.fly.dev"
    if not await _wait_for_live_url(public_url, timeout_seconds=180):
        raise RuntimeError("Fly deployment did not become reachable in time.")

    return {
        "provider": "fly",
        "deployment_url": public_url,
        "status": "success",
        "details": {
            "app_id": app_id,
            "machine_id": machine.get("id"),
            "machine_region": machine.get("region"),
            "app_name": app_name,
        },
    }


async def _publish_source_to_temporary_github_repo(project_id: int, project_name: str) -> str:
    """Publish persisted source files to a temporary private GitHub repository.

    Returns the HTTPS repository URL that can be consumed by Railway deploy flow.
    """
    token = (settings.github_token or os.getenv("GITHUB_TOKEN", "")).strip()
    if not token:
        raise RuntimeError(
            "Backend deployment requires a GitHub repository URL or GITHUB_TOKEN for temporary repo publishing."
        )

    source_files = load_source_file_map(project_id, include_hidden=False)
    if not source_files:
        raise RuntimeError("Cannot publish temporary GitHub repo: no source files were found.")

    headers = {
        "Authorization": f"Bearer {token}",
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
        "User-Agent": "Nestify-Deployment-Agent",
    }

    repo_slug = f"nestify-temp-{_sanitize_project_name(project_name)}-{project_id}-{secrets.token_hex(3)}"
    repo_slug = repo_slug[:90].rstrip("-")

    async with httpx.AsyncClient(timeout=60) as client:
        user_resp = await client.get("https://api.github.com/user", headers=headers)
        if user_resp.status_code >= 400:
            raise RuntimeError(f"GitHub user lookup failed: {user_resp.text[:220]}")
        owner_login = str((user_resp.json() or {}).get("login") or "").strip()
        if not owner_login:
            raise RuntimeError("GitHub user lookup did not return an account login.")

        create_resp = await client.post(
            "https://api.github.com/user/repos",
            headers=headers,
            json={
                "name": repo_slug,
                "private": True,
                "auto_init": True,
                "description": f"Temporary Nestify deployment source for project {project_id}",
            },
        )
        if create_resp.status_code >= 400:
            raise RuntimeError(f"Temporary GitHub repo creation failed: {create_resp.text[:260]}")
        created_repo = create_resp.json() if create_resp.content else {}
        default_branch = str(created_repo.get("default_branch") or "main").strip() or "main"

        for rel_path, file_bytes in source_files.items():
            encoded_path = quote(rel_path, safe="/-_.")
            payload = {
                "message": f"Add {rel_path}",
                "content": base64.b64encode(file_bytes).decode("ascii"),
                "branch": default_branch,
            }
            put_url = f"https://api.github.com/repos/{owner_login}/{repo_slug}/contents/{encoded_path}"
            put_resp = await client.put(
                put_url,
                headers=headers,
                json=payload,
            )

            # If file exists (for example README from auto_init), GitHub requires sha for updates.
            if put_resp.status_code == 422 and "sha" in (put_resp.text or "").lower():
                existing_resp = await client.get(
                    put_url,
                    headers=headers,
                    params={"ref": default_branch},
                )
                if existing_resp.status_code < 400:
                    existing_payload = existing_resp.json() if existing_resp.content else {}
                    existing_sha = str(existing_payload.get("sha") or "").strip()
                    if existing_sha:
                        payload["sha"] = existing_sha
                        payload["message"] = f"Update {rel_path}"
                        put_resp = await client.put(
                            put_url,
                            headers=headers,
                            json=payload,
                        )

            if put_resp.status_code >= 400:
                raise RuntimeError(
                    f"Failed to push '{rel_path}' to temporary GitHub repo: {put_resp.text[:220]}"
                )

    repo_url = f"https://github.com/{owner_login}/{repo_slug}"
    add_log(
        project_id,
        "deployment_agent",
        f"Published source to temporary GitHub repo for backend deploy: {repo_url}",
        "info",
    )
    return repo_url


def _validate_github_token(token: str) -> str:
    """Validate a GitHub token synchronously (used for fail-fast checks).

    Returns the login name if valid, otherwise raises RuntimeError.
    """
    token = (token or "").strip()
    if not token:
        raise RuntimeError("GITHUB_TOKEN not configured")
    headers = {
        "Authorization": f"Bearer {token}",
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
        "User-Agent": "Nestify-Deployment-Agent",
    }
    try:
        resp = httpx.get("https://api.github.com/user", headers=headers, timeout=20)
    except Exception as exc:
        raise RuntimeError(f"GitHub token validation request failed: {exc}")
    if resp.status_code >= 400:
        raise RuntimeError(f"GitHub token invalid: {resp.text[:220]}")
    owner = (resp.json() or {}).get("login")
    if not owner:
        raise RuntimeError("GitHub token validation did not return a user login")
    return str(owner)


# ─── Unified Deployment Executor ─────────────────────────────────


async def execute_deployment(
    project_id: int,
    project_name: str,
    app_kind: str,
    preferred_provider: str | None,
    github_url: str | None,
    env_template: str,
) -> dict[str, Any]:
    """Execute the full deployment flow for a project."""
    project_row = get_project(project_id)
    stack_info = _parse_stack_info(project_row)
    framework = str(stack_info.get("framework") or app_kind or "unknown").lower()

    preflight = validate_pre_deployment(
        app_kind=app_kind,
        preferred_provider=preferred_provider,
        github_url=github_url,
    )
    provider_candidates = [
        str(item).strip().lower()
        for item in (preflight.get("provider_candidates") or [])
        if str(item).strip()
    ]
    strategy = _derive_learning_strategy(
        framework=framework,
        provider_candidates=provider_candidates,
    )
    success_probability = float(preflight.get("success_probability") or 0.0)
    error_signatures: list[str] = []

    if strategy.get("sample_size"):
        add_log(
            project_id,
            "deployment_agent",
            f"Learning strategy loaded ({strategy.get('sample_size')} similar outcomes): {strategy.get('reason')}",
            "info",
        )

    add_log(
        project_id,
        "deployment_agent",
        (
            f"Pre-deployment validation completed. "
            f"Estimated success probability: {round(success_probability * 100)}%."
        ),
        "info",
    )

    if not preflight.get("ok"):
        reason = str(preflight.get("reason") or "Deployment prerequisites are missing.")
        fix_suggestion = str(preflight.get("fix_suggestion") or "Configure the required credentials before retrying.")
        next_action = str(preflight.get("next_action") or "Configure credentials and retry deployment.")
        error_signatures.append(_normalize_error_signature(reason))
        blocker = _failure_payload(
            provider="none",
            app_kind=app_kind,
            reason=reason,
            fix_suggestion=fix_suggestion,
            next_action=next_action,
            action=str(preflight.get("action") or NEEDS_CREDENTIALS_ACTION),
            success_probability=success_probability,
            extra={
                "action_legacy": preflight.get("action_legacy"),
                "credentials": preflight.get("credentials") or {},
                "options": preflight.get("options") or [],
                "provider_candidates": preflight.get("provider_candidates") or [],
                "validation": "pre_deployment",
            },
        )
        add_log(
            project_id,
            "deployment_agent",
            f"Deployment blocked before provider call: {reason}",
            "warn",
        )
        update_project(project_id, {
            "deployment": blocker,
            # projects.status CHECK does not allow "blocked".
            "status": "failed",
        })
        try:
            _record_learning(
                project_id=project_id,
                framework=framework,
                provider="none",
                result=blocker,
                error_signatures=error_signatures,
                strategy_reason=str(strategy.get("reason") or ""),
            )
        except Exception as learn_error:
            add_log(project_id, "deployment_agent", f"Learning record skipped: {learn_error}", "warn")
        return blocker

    # Keep provider selection autonomous and deterministic by app kind + credentials.
    # Do not override with historical provider bias.
    provider = str(preflight.get("provider") or choose_provider(app_kind, None))

    if app_kind == "static":
        if strategy.get("apply_fix_first"):
            add_log(
                project_id,
                "deployment_agent",
                "Applying learned fix first: validating static build artifacts before provider deployment.",
                "info",
            )
        bundle = extract_static_bundle_from_project(project_id)
        if not bundle:
            reason = "No deployable static bundle was found for this project."
            error_signatures.append(_normalize_error_signature(reason))
            result = _failure_payload(
                provider=provider,
                app_kind=app_kind,
                reason=reason,
                fix_suggestion="Build the frontend so index.html and static assets are present in dist/ or build/.",
                next_action="Run the frontend build command, then retry deployment.",
                success_probability=success_probability,
            )
            ensure_preview_index(project_id)
            result["details"]["preview_url"] = get_local_preview_url(project_id)
            result["details"]["note"] = "Preview URL is available for local validation, but public deployment was not attempted."
            update_project(project_id, {
                "deployment": result,
                # Persist schema-supported status while blocked semantics stay in payload.
                "status": "failed",
            })
            try:
                _record_learning(
                    project_id=project_id,
                    framework=framework,
                    provider=provider,
                    result=result,
                    error_signatures=error_signatures,
                    strategy_reason=str(strategy.get("reason") or ""),
                )
            except Exception as learn_error:
                add_log(project_id, "deployment_agent", f"Learning record skipped: {learn_error}", "warn")
            return result
        providers_to_try = [provider] + [
            candidate
            for candidate in (preflight.get("provider_candidates") or [])
            if candidate != provider
        ]
        errors: list[str] = []
        result: dict[str, Any] | None = None
        for provider_name in providers_to_try:
            add_log(project_id, "deployment_agent", f"Deploying static bundle via {provider_name}", "info")
            try:
                if provider_name == "vercel":
                    result = await deploy_static_to_vercel(project_name, bundle)
                elif provider_name == "netlify":
                    result = await deploy_static_to_netlify(project_name, bundle)
                else:
                    raise RuntimeError(f"Unsupported static provider: {provider_name}")
                break
            except Exception as exc:
                error_text = str(exc)
                errors.append(f"{provider_name}: {error_text}")
                error_signatures.append(_normalize_error_signature(error_text))
                add_log(
                    project_id,
                    "deployment_agent",
                    f"Provider deploy failed ({provider_name}): {error_text}",
                    "warn",
                )

        if not result:
            result = _failure_payload(
                provider=provider,
                app_kind=app_kind,
                reason="All configured static providers failed to deploy this build.",
                fix_suggestion="Verify provider token scopes, project build output, and framework build settings.",
                next_action="Review the latest provider error, fix configuration, and retry deployment.",
                success_probability=success_probability,
                extra={"provider_attempts": errors},
            )
    else:
        if not github_url:
            add_log(
                project_id,
                "deployment_agent",
                "No GitHub URL provided for backend deployment. Attempting temporary GitHub repo publishing.",
                "info",
            )
            # Fail-fast validation for GitHub token to avoid repeated failing attempts
            token = (settings.github_token or os.getenv("GITHUB_TOKEN", "")).strip()
            if token:
                try:
                    owner = _validate_github_token(token)
                    add_log(project_id, "deployment_agent", f"Validated GitHub token for user: {owner}", "info")
                except Exception as exc:
                    reason = f"Invalid GITHUB_TOKEN: {exc}"
                    error_signatures.append(_normalize_error_signature(reason))
                    result = _failure_payload(
                        provider=provider,
                        app_kind=app_kind,
                        reason=reason,
                        fix_suggestion="Provide a valid GITHUB_TOKEN with repository creation permissions.",
                        next_action="Update GITHUB_TOKEN and retry, or provide a github_url.",
                        success_probability=success_probability,
                        action=NEEDS_CREDENTIALS_ACTION,
                    )
                    update_project(project_id, {
                        "deployment": result,
                        "status": "failed",
                    })
                    try:
                        _record_learning(
                            project_id=project_id,
                            framework=framework,
                            provider=provider,
                            result=result,
                            error_signatures=error_signatures,
                            strategy_reason=str(strategy.get("reason") or ""),
                        )
                    except Exception as learn_error:
                        add_log(project_id, "deployment_agent", f"Learning record skipped: {learn_error}", "warn")
                    return result
            try:
                github_url = await _publish_source_to_temporary_github_repo(project_id=project_id, project_name=project_name)
            except Exception as exc:
                reason = f"Could not publish source to temporary GitHub repository: {exc}"
                error_signatures.append(_normalize_error_signature(reason))
                result = _failure_payload(
                    provider=provider,
                    app_kind=app_kind,
                    reason=reason,
                    fix_suggestion="Configure GITHUB_TOKEN with repository write access or provide a GitHub repository URL.",
                    next_action="Set GITHUB_TOKEN or submit github_url, then retry deployment.",
                    success_probability=success_probability,
                    action=NEEDS_CREDENTIALS_ACTION,
                )
                update_project(project_id, {
                    "deployment": result,
                    # Persist schema-supported status while blocked semantics stay in payload.
                    "status": "failed",
                })
                try:
                    _record_learning(
                        project_id=project_id,
                        framework=framework,
                        provider=provider,
                        result=result,
                        error_signatures=error_signatures,
                        strategy_reason=str(strategy.get("reason") or ""),
                    )
                except Exception as learn_error:
                    add_log(project_id, "deployment_agent", f"Learning record skipped: {learn_error}", "warn")
                return result
        add_log(project_id, "deployment_agent", f"Deploying backend app via {provider}", "info")
        try:
            if provider == "gcp":
                provider_client = GCPDeploymentProvider(
                    project_id=project_id,
                    project_name=project_name,
                    stack_info=stack_info,
                    app_kind=app_kind,
                )
                gcp_result = await provider_client.deploy(os.getenv("GCP_SERVICE_ACCOUNT_JSON", "").strip() or None)
                failure_reason = gcp_result.failure_reason
                result = {
                    "provider": gcp_result.provider,
                    "deployment_url": gcp_result.live_url,
                    "status": "success" if gcp_result.live_url else "failed",
                    "details": {
                        "region": gcp_result.region,
                        "image_uri": gcp_result.image_uri,
                        "cost_estimate_usd_monthly": gcp_result.cost_estimate_usd_monthly,
                        "free_tier_usage_percent": gcp_result.free_tier_usage_percent,
                        "audit_log_url": gcp_result.audit_log_url,
                        "failure_reason": failure_reason,
                        "reason": failure_reason,
                        "plain_english_error": failure_reason,
                        "billing_status": provider_client.billing_status,
                        "cost_warning": provider_client.cost_warning,
                    },
                }
            elif provider == "railway":
                result = await deploy_backend_to_railway(project_id, project_name, github_url, env_template)
            elif provider == "fly":
                result = await deploy_backend_to_fly(project_id, project_name, github_url, env_template, stack_info)
            else:
                raise RuntimeError(
                    f"Unsupported backend provider: {provider}. Supported backend providers: gcp, railway, fly"
                )
        except Exception as exc:
            reason = f"Backend deployment failed on {provider}: {exc}"
            error_signatures.append(_normalize_error_signature(reason))
            result = _failure_payload(
                provider=provider,
                app_kind=app_kind,
                reason=reason,
                fix_suggestion="Verify provider credentials, workspace settings, and runtime configuration.",
                next_action="Apply the suggested configuration fix and retry deployment.",
                success_probability=success_probability,
            )

    # Update project with deployment info
    update_project(project_id, {
        "deployment": result,
        "public_url": result.get("deployment_url"),
        # projects.status CHECK does not allow "blocked".
        "status": "live" if result.get("deployment_url") else "failed",
    })

    details = result.get("details") if isinstance(result.get("details"), dict) else {}
    if result.get("status") != "success":
        failure_reason = str(details.get("reason") or details.get("plain_english_error") or "").strip()
        if failure_reason:
            error_signatures.append(_normalize_error_signature(failure_reason))

    try:
        _record_learning(
            project_id=project_id,
            framework=framework,
            provider=str(result.get("provider") or provider),
            result=result,
            error_signatures=error_signatures,
            strategy_reason=str(strategy.get("reason") or ""),
        )
    except Exception as learn_error:
        add_log(project_id, "deployment_agent", f"Learning record skipped: {learn_error}", "warn")

    return result
