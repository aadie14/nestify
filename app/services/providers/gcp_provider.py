"""Google Cloud deployment provider for Cloud Run with App Engine fallback."""

from __future__ import annotations

import asyncio
import json
import logging
import os
import re
import shutil
import subprocess
import tempfile
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import httpx
from google.auth.transport.requests import Request
from google.oauth2 import service_account
import google.auth

from app.core.config import settings
from app.database import add_log
from app.services.project_source_service import get_project_source_dir

logger = logging.getLogger(__name__)

CLOUD_RUN_REGION = "us-central1"
FREE_TIER_REQUESTS = 2_000_000
FREE_TIER_WARNING = 1_800_000


@dataclass(slots=True)
class DeploymentResult:
    live_url: str | None
    provider: str
    region: str
    image_uri: str | None
    cost_estimate_usd_monthly: float | None
    free_tier_usage_percent: float | None
    audit_log_url: str | None
    failure_reason: str | None


class GCPDeploymentProvider:
    """Deploy containerized workloads to Google Cloud Run with App Engine fallback."""

    def __init__(self, project_id: int, project_name: str, stack_info: dict[str, Any], app_kind: str) -> None:
        self.project_id = project_id
        self.project_name = project_name
        self.stack_info = stack_info or {}
        self.app_kind = app_kind
        self.region = CLOUD_RUN_REGION
        self.billing_status: dict[str, Any] | None = None
        self.cost_warning: str | None = None

    async def deploy(self, service_account_json: str | None = None) -> DeploymentResult:
        creds, gcp_project_id, adc_only = self._load_credentials(service_account_json)
        if not gcp_project_id:
            return self._failure(
                "missing_env",
                "GCP project id was not provided via GCP_PROJECT_ID or service account metadata.",
            )

        validation = await self._validate_credentials(creds, gcp_project_id)
        if not validation["ok"]:
            return self._failure("missing_env", validation["error"])

        estimated_requests = self._estimate_monthly_requests()
        usage_percent = round((estimated_requests / FREE_TIER_REQUESTS) * 100, 2)
        if estimated_requests >= FREE_TIER_WARNING:
            self.cost_warning = (
                f"Estimated monthly requests {estimated_requests} exceed 90% of the free tier."
            )
            add_log(self.project_id, "GCPProvider", self.cost_warning, "warn")

        try:
            image_uri, build_log_url = await self._build_and_push_image(creds, gcp_project_id, adc_only)
            live_url = await self._deploy_cloud_run(creds, gcp_project_id, image_uri)
            await self._attach_billing_status(creds, gcp_project_id)
            return DeploymentResult(
                live_url=live_url,
                provider="gcp",
                region=self.region,
                image_uri=image_uri,
                cost_estimate_usd_monthly=0.0,
                free_tier_usage_percent=usage_percent,
                audit_log_url=build_log_url,
                failure_reason=None,
            )
        except Exception as exc:
            failure_reason = str(exc)
            failure_type = self._classify_failure(failure_reason)
            build_log_url = self._extract_log_url(failure_reason)

            if failure_type == "infra_issue":
                fallback = await self._attempt_app_engine_fallback(adc_only, gcp_project_id)
                if fallback.get("live_url"):
                    await self._attach_billing_status(creds, gcp_project_id)
                    return DeploymentResult(
                        live_url=str(fallback["live_url"]),
                        provider="gcp",
                        region=self.region,
                        image_uri=None,
                        cost_estimate_usd_monthly=0.0,
                        free_tier_usage_percent=usage_percent,
                        audit_log_url=fallback.get("audit_log_url") or build_log_url,
                        failure_reason=None,
                    )

            return DeploymentResult(
                live_url=None,
                provider="gcp",
                region=self.region,
                image_uri=None,
                cost_estimate_usd_monthly=None,
                free_tier_usage_percent=usage_percent,
                audit_log_url=build_log_url,
                failure_reason=failure_reason,
            )

    def _load_credentials(self, service_account_json: str | None) -> tuple[Any, str | None, bool]:
        scopes = ["https://www.googleapis.com/auth/cloud-platform"]
        project_id = os.getenv("GCP_PROJECT_ID", "").strip() or None

        if service_account_json:
            raw = service_account_json.strip()
            payload = None
            if raw.startswith("{"):
                payload = json.loads(raw)
            elif os.path.exists(raw):
                payload = json.loads(Path(raw).read_text(encoding="utf-8"))
            if not isinstance(payload, dict):
                raise RuntimeError("Invalid service account JSON payload.")
            creds = service_account.Credentials.from_service_account_info(payload, scopes=scopes)
            project_id = project_id or payload.get("project_id")
            return creds, project_id, False

        creds, default_project = google.auth.default(scopes=scopes)
        project_id = project_id or default_project
        return creds, project_id, True

    async def _validate_credentials(self, creds: Any, project_id: str) -> dict[str, Any]:
        token = await asyncio.to_thread(self._get_access_token, creds)
        url = f"https://cloudresourcemanager.googleapis.com/v1/projects/{project_id}"
        headers = {"Authorization": f"Bearer {token}"}
        async with httpx.AsyncClient(timeout=15) as client:
            response = await client.get(url, headers=headers)

        if response.status_code >= 400:
            message = response.text[:200] if response.text else "Unauthorized"
            return {"ok": False, "error": f"GCP credential validation failed: {message}"}
        return {"ok": True}

    async def _build_and_push_image(self, creds: Any, project_id: str, adc_only: bool) -> tuple[str, str | None]:
        source_dir = Path(get_project_source_dir(self.project_id)) / "source"
        source_dir.mkdir(parents=True, exist_ok=True)
        self._ensure_dockerfile(source_dir)

        slug = self._slugify(self.project_name)
        tag = f"{self.project_id}-{slug}"
        repo = os.getenv("GCP_ARTIFACT_REPOSITORY", "nestify").strip() or "nestify"
        registry_host = f"{self.region}-docker.pkg.dev"
        image_uri = f"{registry_host}/{project_id}/{repo}/{slug}:{tag}"

        token = await asyncio.to_thread(self._get_access_token, creds)
        try:
            await asyncio.to_thread(
                self._docker_build_and_push,
                source_dir,
                image_uri,
                registry_host,
                token,
            )
            return image_uri, None
        except Exception as exc:
            reason = str(exc)
            build_log_url = self._extract_log_url(reason)
            if adc_only and self._gcloud_available():
                gcloud_result = await asyncio.to_thread(self._gcloud_build_submit, source_dir, image_uri, project_id)
                if gcloud_result["ok"]:
                    return image_uri, gcloud_result.get("log_url")
                raise RuntimeError(gcloud_result.get("error") or reason)
            raise

    async def _deploy_cloud_run(self, creds: Any, project_id: str, image_uri: str) -> str:
        token = await asyncio.to_thread(self._get_access_token, creds)
        service_name = self._slugify(self.project_name)
        base_url = f"https://run.googleapis.com/v2/projects/{project_id}/locations/{self.region}/services"
        headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}

        service_payload = {
            "ingress": "INGRESS_TRAFFIC_ALL",
            "template": {
                "containers": [
                    {
                        "image": image_uri,
                        "resources": {"limits": {"cpu": "1", "memory": "512Mi"}},
                    }
                ],
                "scaling": {"minInstanceCount": 0, "maxInstanceCount": 10},
            },
            "traffic": [{"percent": 100, "latestRevision": True}],
        }

        async with httpx.AsyncClient(timeout=60) as client:
            response = await client.post(
                f"{base_url}?serviceId={service_name}",
                headers=headers,
                json=service_payload,
            )
            if response.status_code == 409:
                patch_url = f"{base_url}/{service_name}?updateMask=template,traffic,ingress"
                response = await client.patch(patch_url, headers=headers, json=service_payload)

        if response.status_code >= 400:
            raise RuntimeError(f"Cloud Run deployment failed: {response.text[:300]}")

        await self._allow_unauthenticated(token, project_id, service_name)
        return await self._wait_for_service_url(token, project_id, service_name)

    async def _allow_unauthenticated(self, token: str, project_id: str, service_name: str) -> None:
        url = (
            f"https://run.googleapis.com/v2/projects/{project_id}"
            f"/locations/{self.region}/services/{service_name}:setIamPolicy"
        )
        policy = {
            "policy": {
                "bindings": [
                    {"role": "roles/run.invoker", "members": ["allUsers"]}
                ]
            }
        }
        headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}
        async with httpx.AsyncClient(timeout=20) as client:
            response = await client.post(url, headers=headers, json=policy)
        if response.status_code >= 400:
            raise RuntimeError(f"Cloud Run IAM policy update failed: {response.text[:200]}")

    async def _wait_for_service_url(self, token: str, project_id: str, service_name: str) -> str:
        url = f"https://run.googleapis.com/v2/projects/{project_id}/locations/{self.region}/services/{service_name}"
        headers = {"Authorization": f"Bearer {token}"}
        deadline = time.time() + 120
        async with httpx.AsyncClient(timeout=20) as client:
            while time.time() < deadline:
                response = await client.get(url, headers=headers)
                payload = response.json() if response.content else {}
                uri = str(payload.get("uri") or "").strip()
                if uri:
                    return uri
                await asyncio.sleep(3)
        raise RuntimeError("Cloud Run service did not become ready in time.")

    async def _attach_billing_status(self, creds: Any, project_id: str) -> None:
        token = await asyncio.to_thread(self._get_access_token, creds)
        url = f"https://cloudbilling.googleapis.com/v1/projects/{project_id}/billingInfo"
        headers = {"Authorization": f"Bearer {token}"}
        async with httpx.AsyncClient(timeout=15) as client:
            response = await client.get(url, headers=headers)
        if response.status_code >= 400:
            add_log(self.project_id, "GCPProvider", "Billing status lookup failed.", "warn")
            return
        payload = response.json() if response.content else {}
        self.billing_status = {
            "billing_enabled": bool(payload.get("billingEnabled")),
            "billing_account": payload.get("billingAccountName"),
        }
        add_log(self.project_id, "GCPProvider", f"Billing status: {self.billing_status}", "info")

    async def _attempt_app_engine_fallback(self, adc_only: bool, project_id: str) -> dict[str, Any]:
        if not adc_only or not self._gcloud_available():
            return {"ok": False, "error": "App Engine fallback requires gcloud with ADC."}

        source_dir = Path(get_project_source_dir(self.project_id)) / "source"
        runtime = str(self.stack_info.get("runtime") or "python").lower()
        runtime = "nodejs20" if runtime == "node" else "python311"

        temp_dir = Path(tempfile.mkdtemp(prefix="nestify-gcp-fallback-"))
        try:
            shutil.copytree(source_dir, temp_dir / "src", dirs_exist_ok=True)
            app_yaml = temp_dir / "src" / "app.yaml"
            app_yaml.write_text(f"runtime: {runtime}\nenv: standard\n", encoding="utf-8")

            cmd = [
                "gcloud",
                "app",
                "deploy",
                "--quiet",
                "--project",
                project_id,
            ]
            result = subprocess.run(
                cmd,
                cwd=str(temp_dir / "src"),
                capture_output=True,
                text=True,
                check=False,
            )
            output = (result.stdout or "") + "\n" + (result.stderr or "")
            log_url = self._extract_log_url(output)
            if result.returncode != 0:
                return {"ok": False, "error": output.strip(), "audit_log_url": log_url}

            live_url = f"https://{project_id}.uc.r.appspot.com"
            return {"ok": True, "live_url": live_url, "audit_log_url": log_url}
        finally:
            shutil.rmtree(temp_dir, ignore_errors=True)

    # ─── Dockerfile Templates ────────────────────────────────────────

    _DOCKERFILE_TEMPLATES: dict[str, str] = {
        "python": (
            "FROM python:3.11-slim\n"
            "WORKDIR /app\n"
            "COPY requirements.txt ./\n"
            "RUN pip install --no-cache-dir -r requirements.txt\n"
            "COPY . .\n"
            "ENV PORT=8080\n"
            "EXPOSE 8080\n"
            'CMD ["python", "-m", "uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8080"]\n'
        ),
        "node": (
            "FROM node:20-alpine\n"
            "WORKDIR /app\n"
            "COPY package*.json ./\n"
            "RUN npm ci || npm install\n"
            "COPY . .\n"
            "ENV PORT=8080\n"
            "EXPOSE 8080\n"
            'CMD ["npm", "start"]\n'
        ),
        "go": (
            "FROM golang:1.22-alpine AS builder\n"
            "WORKDIR /app\n"
            "COPY go.* ./\n"
            "RUN go mod download\n"
            "COPY . .\n"
            "RUN CGO_ENABLED=0 go build -o server .\n"
            "FROM alpine:3.19\n"
            "COPY --from=builder /app/server /server\n"
            "ENV PORT=8080\n"
            "EXPOSE 8080\n"
            'CMD ["/server"]\n'
        ),
        "ruby": (
            "FROM ruby:3.3-slim\n"
            "WORKDIR /app\n"
            "COPY Gemfile* ./\n"
            "RUN bundle install\n"
            "COPY . .\n"
            "ENV PORT=8080\n"
            "EXPOSE 8080\n"
            'CMD ["bundle", "exec", "ruby", "app.rb"]\n'
        ),
        "php": (
            "FROM php:8.3-apache\n"
            "COPY . /var/www/html/\n"
            "RUN a]enmod rewrite\n"
            "ENV PORT=8080\n"
            "EXPOSE 8080\n"
            'CMD ["apache2-foreground"]\n'
        ),
        "java": (
            "FROM eclipse-temurin:21-jdk-alpine AS builder\n"
            "WORKDIR /app\n"
            "COPY . .\n"
            "RUN if [ -f mvnw ]; then chmod +x mvnw && ./mvnw package -DskipTests; "
            "elif [ -f gradlew ]; then chmod +x gradlew && ./gradlew build -x test; fi\n"
            "FROM eclipse-temurin:21-jre-alpine\n"
            "COPY --from=builder /app/target/*.jar /app.jar\n"
            "ENV PORT=8080\n"
            "EXPOSE 8080\n"
            'CMD ["java", "-jar", "/app.jar"]\n'
        ),
        "static": (
            "FROM nginx:alpine\n"
            "COPY . /usr/share/nginx/html\n"
            "COPY <<'EOF' /etc/nginx/conf.d/default.conf\n"
            "server {\n"
            "    listen 8080;\n"
            "    location / {\n"
            "        root /usr/share/nginx/html;\n"
            "        index index.html;\n"
            "        try_files $uri $uri/ /index.html;\n"
            "    }\n"
            "}\n"
            "EOF\n"
            "ENV PORT=8080\n"
            "EXPOSE 8080\n"
            'CMD ["nginx", "-g", "daemon off;"]\n'
        ),
    }

    def _ensure_dockerfile(self, source_dir: Path) -> None:
        dockerfile = source_dir / "Dockerfile"
        if dockerfile.exists():
            return

        runtime = str(self.stack_info.get("runtime") or "unknown").lower()
        # Map common runtime aliases
        if runtime in ("nodejs", "javascript", "typescript"):
            runtime = "node"
        if runtime in ("golang",):
            runtime = "go"

        content = self._DOCKERFILE_TEMPLATES.get(runtime)

        # Fallback: if it looks like a static site, use nginx
        if not content and self.app_kind in ("static", "spa", "ssg"):
            content = self._DOCKERFILE_TEMPLATES["static"]
            runtime = "static"

        if not content:
            raise RuntimeError(
                f"Unable to generate Dockerfile for runtime '{runtime}'. "
                f"Supported: python, node, go, ruby, php, java, static. "
                f"Add a Dockerfile to your project for custom runtimes."
            )

        dockerfile.write_text(content, encoding="utf-8")
        add_log(self.project_id, "GCPProvider", f"Generated {runtime} Dockerfile for Cloud Run deploy.", "info")

    # ─── API & Registry Setup ─────────────────────────────────────

    @staticmethod
    async def _enable_required_apis(token: str, project_id: str) -> dict[str, Any]:
        """Attempt to enable Cloud Run, Artifact Registry, and Cloud Build APIs."""
        required_apis = [
            "run.googleapis.com",
            "artifactregistry.googleapis.com",
            "cloudbuild.googleapis.com",
        ]
        headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}
        results: dict[str, str] = {}
        async with httpx.AsyncClient(timeout=30) as client:
            for api in required_apis:
                url = f"https://serviceusage.googleapis.com/v1/projects/{project_id}/services/{api}:enable"
                try:
                    resp = await client.post(url, headers=headers, json={})
                    results[api] = "enabled" if resp.status_code < 400 else f"failed ({resp.status_code})"
                except Exception as exc:
                    results[api] = f"error: {exc}"
        return results

    async def _ensure_artifact_registry_repo(self, token: str, project_id: str) -> None:
        """Create the Artifact Registry Docker repository if it does not exist."""
        repo = os.getenv("GCP_ARTIFACT_REPOSITORY", "nestify").strip() or "nestify"
        url = (
            f"https://artifactregistry.googleapis.com/v1/projects/{project_id}"
            f"/locations/{self.region}/repositories/{repo}"
        )
        headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}
        async with httpx.AsyncClient(timeout=20) as client:
            check = await client.get(url, headers=headers)
            if check.status_code < 400:
                return  # Already exists

            create_url = (
                f"https://artifactregistry.googleapis.com/v1/projects/{project_id}"
                f"/locations/{self.region}/repositories?repositoryId={repo}"
            )
            payload = {"format": "DOCKER", "description": "Nestify deployment images"}
            resp = await client.post(create_url, headers=headers, json=payload)
            if resp.status_code >= 400 and resp.status_code != 409:
                logger.warning("Artifact Registry repo creation returned %s: %s", resp.status_code, resp.text[:200])

    # ─── Setup Validation ─────────────────────────────────────────

    @classmethod
    async def validate_setup(cls, project_id_str: str, service_account_json: str | None = None) -> dict[str, Any]:
        """Validate GCP credentials and check project access. Used by the guided setup API."""
        result: dict[str, Any] = {
            "ok": False,
            "project_id": project_id_str,
            "checks": {},
        }
        try:
            instance = cls(project_id=0, project_name="setup-check", stack_info={}, app_kind="backend")
            creds, resolved_project, _ = instance._load_credentials(service_account_json)
            effective_project = project_id_str or resolved_project
            if not effective_project:
                result["error"] = "No GCP project ID could be determined."
                return result
            result["project_id"] = effective_project

            token = await asyncio.to_thread(cls._get_access_token, creds)
            result["checks"]["auth"] = "ok"

            # Validate project access
            validation = await instance._validate_credentials(creds, effective_project)
            result["checks"]["project_access"] = "ok" if validation["ok"] else validation.get("error", "failed")

            if not validation["ok"]:
                result["error"] = validation.get("error", "Project access validation failed.")
                return result

            # Check which APIs are enabled
            apis_to_check = ["run.googleapis.com", "artifactregistry.googleapis.com", "cloudbuild.googleapis.com"]
            headers = {"Authorization": f"Bearer {token}"}
            api_status: dict[str, str] = {}
            async with httpx.AsyncClient(timeout=15) as client:
                for api in apis_to_check:
                    url = f"https://serviceusage.googleapis.com/v1/projects/{effective_project}/services/{api}"
                    try:
                        resp = await client.get(url, headers=headers)
                        if resp.status_code < 400:
                            state = (resp.json() or {}).get("state", "unknown")
                            api_status[api] = "enabled" if state == "ENABLED" else "disabled"
                        else:
                            api_status[api] = "unknown"
                    except Exception:
                        api_status[api] = "unknown"
            result["checks"]["apis"] = api_status

            # Check billing
            billing_url = f"https://cloudbilling.googleapis.com/v1/projects/{effective_project}/billingInfo"
            async with httpx.AsyncClient(timeout=15) as client:
                resp = await client.get(billing_url, headers=headers)
                if resp.status_code < 400:
                    billing = resp.json() or {}
                    result["checks"]["billing"] = "enabled" if billing.get("billingEnabled") else "disabled"
                else:
                    result["checks"]["billing"] = "unknown"

            result["ok"] = (
                result["checks"].get("project_access") == "ok"
                and result["checks"].get("billing") == "enabled"
            )
            if not result["ok"] and not result.get("error"):
                if result["checks"].get("billing") != "enabled":
                    result["error"] = (
                        "Billing is not enabled on this project. Google requires billing "
                        "to be enabled even for free-tier usage. No charges will occur within free limits."
                    )
                else:
                    result["error"] = "Some required checks did not pass."
        except Exception as exc:
            result["error"] = str(exc)
        return result

    # ─── Core Helpers ─────────────────────────────────────────────

    @staticmethod
    def _docker_build_and_push(source_dir: Path, image_uri: str, registry_host: str, token: str) -> None:
        try:
            import docker  # type: ignore[import-untyped]
        except Exception as exc:
            raise RuntimeError(f"Docker SDK unavailable: {exc}")

        client = docker.from_env()
        local_tag = f"nestify-local:{int(time.time())}"
        image, _ = client.images.build(path=str(source_dir), tag=local_tag, rm=True)
        client.login(username="oauth2accesstoken", password=token, registry=registry_host)
        image.tag(image_uri)
        for output in client.images.push(image_uri, stream=True, decode=True):
            if isinstance(output, dict) and output.get("error"):
                raise RuntimeError(output.get("error"))

    @staticmethod
    def _gcloud_build_submit(source_dir: Path, image_uri: str, project_id: str) -> dict[str, Any]:
        cmd = ["gcloud", "builds", "submit", "--tag", image_uri, "--project", project_id, "--quiet"]
        result = subprocess.run(cmd, cwd=str(source_dir), capture_output=True, text=True, check=False)
        output = (result.stdout or "") + "\n" + (result.stderr or "")
        log_url = GCPDeploymentProvider._extract_log_url(output)
        if result.returncode != 0:
            return {"ok": False, "error": output.strip(), "log_url": log_url}
        return {"ok": True, "log_url": log_url}

    @staticmethod
    def _get_access_token(creds: Any) -> str:
        if not creds.valid:
            creds.refresh(Request())
        return str(creds.token)

    @staticmethod
    def _slugify(value: str) -> str:
        slug = re.sub(r"[^a-z0-9-]+", "-", str(value or "").lower()).strip("-")
        slug = re.sub(r"-{2,}", "-", slug)
        return (slug or "nestify-app")[:48]

    def _estimate_monthly_requests(self) -> int:
        runtime = str(self.stack_info.get("runtime") or "unknown").lower()
        if self.app_kind in {"static", "spa", "ssg"}:
            return 600_000
        if runtime == "node":
            return 1_200_000
        if runtime == "python":
            return 1_000_000
        return 900_000

    @staticmethod
    def _classify_failure(message: str) -> str:
        text = str(message or "").lower()
        if any(token in text for token in ["env", "environment", "token", "credential", "apikey", "api key"]):
            return "missing_env"
        if any(token in text for token in ["module not found", "no module named", "dependency", "package"]):
            return "dependency_issue"
        if any(token in text for token in ["build", "compile", "docker", "artifact registry"]):
            return "build_error"
        if any(token in text for token in ["timeout", "rate limit", "unavailable", "network", "infra"]):
            return "infra_issue"
        return "unknown"

    @staticmethod
    def _extract_log_url(text: str) -> str | None:
        match = re.search(r"https://console\.cloud\.google\.com/cloud-build/builds[^\s]+", text or "")
        return match.group(0) if match else None

    @staticmethod
    def _gcloud_available() -> bool:
        return shutil.which("gcloud") is not None

    def _failure(self, failure_type: str, reason: str) -> DeploymentResult:
        detail = f"{failure_type}: {reason}"
        return DeploymentResult(
            live_url=None,
            provider="gcp",
            region=self.region,
            image_uri=None,
            cost_estimate_usd_monthly=None,
            free_tier_usage_percent=None,
            audit_log_url=None,
            failure_reason=detail,
        )
