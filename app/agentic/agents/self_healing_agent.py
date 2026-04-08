"""Agent 5: Self-Healing Deployment Engineer."""

from __future__ import annotations

import asyncio
from typing import Any

from app.agents.deployment_agent import DeploymentAgent


class SelfHealingDeploymentEngineer:
    """Deploy with retries, provider switching, and basic autonomous remediation."""

    def _suggest_fix(self, error_text: str) -> str:
        msg = error_text.lower()
        if "port" in msg:
            return "add_or_override_port_env"
        if "environment" in msg or "env" in msg:
            return "inject_safe_env_defaults"
        if "build" in msg:
            return "adjust_build_command"
        if "memory" in msg or "resource" in msg:
            return "increase_resource_limits"
        if "api" in msg or "429" in msg or "timeout" in msg:
            return "retry_with_backoff"
        return "retry_generic"

    def _provider_sequence(self, preferred: str | None, app_type: str) -> list[str]:
        seq: list[str] = []

        if app_type in {"static", "frontend"}:
            defaults = ["vercel", "netlify", "local"]
        else:
            defaults = ["railway"]

        normalized_preferred = str(preferred or "").strip().lower()
        if normalized_preferred and normalized_preferred in defaults:
            seq.append(normalized_preferred)

        for item in defaults:
            if item not in seq:
                seq.append(item)

        return seq

    async def deploy_with_self_heal(
        self,
        project_id: int,
        project_name: str,
        files: list[dict[str, str]],
        stack_info: dict[str, Any],
        preferred_provider: str | None,
        github_url: str | None,
        env_template: str,
        app_type: str,
        max_attempts: int = 4,
    ) -> dict[str, Any]:
        provider_order = self._provider_sequence(preferred_provider, app_type)
        attempts: list[dict[str, Any]] = []

        deployment_agent = DeploymentAgent(project_id)
        env_current = env_template or ""

        for attempt_index in range(max_attempts):
            provider = provider_order[min(attempt_index, len(provider_order) - 1)]
            try:
                result = await deployment_agent.deploy(
                    project_name=project_name,
                    files=files,
                    stack_info=stack_info,
                    preferred_provider=provider,
                    github_url=github_url,
                    env_template=env_current,
                )
                attempts.append(
                    {
                        "attempt": attempt_index + 1,
                        "provider": provider,
                        "status": result.status,
                        "deployment_url": result.deployment_url,
                        "fix_applied": "none",
                    }
                )

                return {
                    "status": "success",
                    "result": {
                        "provider": result.provider,
                        "deployment_url": result.deployment_url,
                        "details": result.details,
                        "app_kind": result.app_kind,
                    },
                    "attempts": attempts,
                }
            except Exception as exc:
                error_text = str(exc)
                fix = self._suggest_fix(error_text)

                if fix == "add_or_override_port_env" and "PORT=" not in env_current:
                    env_current = (env_current + "\nPORT=8000\n").strip() + "\n"
                elif fix == "inject_safe_env_defaults" and "PYTHONUNBUFFERED=" not in env_current:
                    env_current = (env_current + "\nPYTHONUNBUFFERED=1\n").strip() + "\n"

                attempts.append(
                    {
                        "attempt": attempt_index + 1,
                        "provider": provider,
                        "status": "failed",
                        "error": error_text,
                        "fix_applied": fix,
                    }
                )
                await asyncio.sleep(min(8, 2 * (attempt_index + 1)))

        return {
            "status": "failed",
            "attempts": attempts,
            "escalation": {
                "recommended": True,
                "reason": "Autonomous retry/fix attempts exhausted.",
            },
        }
