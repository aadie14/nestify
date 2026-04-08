"""DeploymentAgent — Intelligent deployment routing and provider handoff.

V2 Decision Logic:
    static  → Vercel
    backend → Railway
    docker  → Railway

Uses graph data and stack detection for accurate app-type classification.
"""

from __future__ import annotations

import logging
from dataclasses import asdict, dataclass
from typing import Any

from app.database import add_deployment, add_log, update_deployment, update_project
from app.services.deployment_service import (
    choose_provider,
    detect_app_kind,
    execute_deployment,
)
from app.services.project_source_service import (
    build_static_source_in_docker,
    ensure_preview_index,
    get_local_preview_url,
    is_frontend_build_framework,
    normalize_framework_name,
    project_has_package_json,
)

logger = logging.getLogger(__name__)

_SUPPORTED_DEPLOY_PROVIDERS = {"vercel", "netlify", "railway"}


# ─── V2 Routing Rules ────────────────────────────────────────────────────

_V2_ROUTING: dict[str, str] = {
    "static": "vercel",
    "ssg": "vercel",
    "spa": "vercel",
    "backend": "railway",
    "api": "railway",
    "fullstack": "railway",
    "docker": "railway",
    "dockerized": "railway",
}


@dataclass(slots=True)
class DeploymentResult:
    """Structured deployment output."""
    app_kind: str
    provider: str
    deployment_url: str | None
    status: str
    details: dict[str, Any]


class DeploymentAgent:
    """Intelligent deployment routing with provider selection.

    V2 Enhancements:
            - Deterministic routing: static→Vercel, backend→Railway, docker→Railway
      - Graph-aware app type detection
      - Credential validation before attempting deployment
    """

    def __init__(self, project_id: int) -> None:
        self.project_id = project_id

    def _detect_app_kind_v2(
        self,
        stack_info: dict[str, Any],
        files: list[dict[str, str]],
    ) -> str:
        """Enhanced app-type detection using stack info and file analysis.

        Returns one of: 'static', 'backend', 'docker'
        """
        names = [f.get("name", "") for f in files]

        # Docker detection
        has_dockerfile = any(
            n.lower() in ("dockerfile", "docker-compose.yml", "docker-compose.yaml")
            or n.lower().endswith("dockerfile")
            for n in names
        )
        if has_dockerfile:
            return "docker"

        # Backend detection
        runtime = stack_info.get("runtime", "unknown")
        framework = stack_info.get("framework", "unknown")

        backend_frameworks = {"fastapi", "flask", "django", "express", "koa", "nest"}
        if framework in backend_frameworks:
            return "backend"

        # Python with no frontend → backend
        if runtime == "python" and not any(n.endswith((".html", ".jsx", ".tsx")) for n in names):
            return "backend"

        # Node with server files → backend
        if runtime == "node":
            has_server = any(
                "server" in n.lower() or "index.js" == n.lower()
                for n in names
            )
            if has_server and framework not in ("react", "vue", "svelte", "next"):
                return "backend"

        # Default: static
        return "static"

    def _select_provider_v2(
        self,
        app_kind: str,
        preferred_provider: str | None = None,
    ) -> str:
        """Select deployment provider using V2 deterministic routing.

        Respects user preference if set, otherwise uses the routing table.
        """
        if preferred_provider:
            normalized = preferred_provider.strip().lower()
            if normalized in _SUPPORTED_DEPLOY_PROVIDERS:
                return normalized

        return _V2_ROUTING.get(app_kind, "railway")

    async def deploy(
        self,
        project_name: str,
        files: list[dict[str, str]],
        stack_info: dict[str, Any],
        preferred_provider: str | None = None,
        github_url: str | None = None,
        env_template: str = "",
    ) -> DeploymentResult:
        """Execute the full deployment flow with V2 routing.

        Args:
            project_name: Display name for the project.
            files: List of project files.
            stack_info: Stack analysis dictionary.
            preferred_provider: User's preferred deployment target.
            github_url: GitHub repository URL (required for backend deploys).
            env_template: .env-style template for backend environment variables.

        Returns:
            DeploymentResult with provider, URL, status, and details.
        """
        # V2 app type detection
        app_kind = self._detect_app_kind_v2(stack_info, files)

        framework = normalize_framework_name(stack_info.get("framework"))
        static_build_required = app_kind == "static" and is_frontend_build_framework(framework)

        # V2 provider selection
        provider = self._select_provider_v2(app_kind, preferred_provider)

        if static_build_required:
            add_log(
                self.project_id,
                "DeploymentAgent",
                f"Static framework '{framework}' detected. Preparing deployment artifacts before provider deploy.",
                "info",
            )

            if not project_has_package_json(self.project_id):
                ensure_preview_index(self.project_id)
                provider = "local"
                add_log(
                    self.project_id,
                    "DeploymentAgent",
                    "No package.json found for static framework app. Serving source through local preview fallback.",
                    "warn",
                )
            else:
                build_result = await build_static_source_in_docker(self.project_id)
                if not build_result.get("ok"):
                    ensure_preview_index(self.project_id)
                    provider = "local"
                    add_log(
                        self.project_id,
                        "DeploymentAgent",
                        f"Static build in Docker sandbox failed: {build_result.get('error')}. Using local preview fallback.",
                        "warn",
                    )
                else:
                    add_log(
                        self.project_id,
                        "DeploymentAgent",
                        f"Static build completed. Using {build_result.get('output_dir')} for deployment bundle.",
                        "info",
                    )

        add_log(
            self.project_id,
            "DeploymentAgent",
            f"[V2] Detected '{app_kind}' application → deploying via {provider}",
            "info",
        )

        # Record pending deployment in DB
        deploy_id = add_deployment(
            project_id=self.project_id,
            provider=provider,
            status="deploying",
        )

        if provider == "local" and app_kind == "static":
            local_url = get_local_preview_url(self.project_id)
            local_result = {
                "provider": "local",
                "deployment_url": local_url,
                "status": "success",
                "details": {
                    "mode": "local_static_fallback",
                    "project_name": project_name,
                    "note": "Provider deployment skipped. Static source served through local preview.",
                },
            }

            update_deployment(deploy_id, {
                "status": "success",
                "deployment_url": local_url,
                "details": local_result["details"],
            })
            update_project(self.project_id, {
                "deployment": local_result,
                "public_url": local_url,
                "status": "live",
            })

            add_log(
                self.project_id,
                "DeploymentAgent",
                f"Local preview deployment ready: {local_url}",
                "info",
            )

            return DeploymentResult(
                app_kind=app_kind,
                provider="local",
                deployment_url=local_url,
                status="success",
                details=local_result["details"],
            )

        try:
            result = await execute_deployment(
                project_id=self.project_id,
                project_name=project_name,
                app_kind=app_kind,
                preferred_provider=provider,
                github_url=github_url,
                env_template=env_template,
            )

            update_deployment(deploy_id, {
                "status": result.get("status", "success"),
                "deployment_url": result.get("deployment_url"),
                "details": result.get("details", {}),
            })

            result_status = str(result.get("status") or "unknown").lower()
            if result_status == "success" and result.get("deployment_url"):
                add_log(
                    self.project_id,
                    "DeploymentAgent",
                    f"Deployment successful via {provider}: {result.get('deployment_url', 'pending')}",
                    "info",
                )
            elif result_status == "blocked":
                details = result.get("details") if isinstance(result.get("details"), dict) else {}
                add_log(
                    self.project_id,
                    "DeploymentAgent",
                    f"Deployment blocked before provider rollout: {details.get('reason') or 'Missing deployment prerequisites.'}",
                    "warn",
                )
            else:
                details = result.get("details") if isinstance(result.get("details"), dict) else {}
                add_log(
                    self.project_id,
                    "DeploymentAgent",
                    f"Deployment failed via {provider}: {details.get('reason') or 'Provider error'}",
                    "error",
                )

            return DeploymentResult(
                app_kind=app_kind,
                provider=result["provider"],
                deployment_url=result.get("deployment_url"),
                status=result.get("status", "success"),
                details=result.get("details", {}),
            )

        except Exception as error:
            update_deployment(deploy_id, {"status": "failed"})
            add_log(self.project_id, "DeploymentAgent", f"Deployment failed: {error}", "error")
            raise