"""Spec-aligned agentic orchestrator facade over the existing coordinator."""

from __future__ import annotations

from typing import Any

from app.agentic.coordinator import AgenticCoordinator
from app.agentic.models import AgenticInsights


class AgenticOrchestrator:
    """Compatibility orchestrator exposing spec method names additively."""

    def __init__(self, existing_orchestrator: Any | None = None, project_id: int | None = None) -> None:
        self.existing_orchestrator = existing_orchestrator
        self.project_id = int(project_id or 0)
        self._coordinator = AgenticCoordinator(project_id=self.project_id)

    async def enhance_analysis(self, project_id: int, code_graph: Any, files: list[dict[str, str]] | None = None) -> dict[str, Any]:
        insights = AgenticInsights()
        analyzed = await self._coordinator.run_analyzing_phase(files=files or [], graph=code_graph, insights=insights)
        return analyzed.code_profile or {}

    async def enhance_security(
        self,
        project_id: int,
        findings: dict[str, Any],
        risk_report: dict[str, Any] | None = None,
        graph_stats: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        insights = AgenticInsights()
        enriched = await self._coordinator.run_scanning_completion_phase(
            security_report=findings,
            risk_report=risk_report or {},
            graph_stats=graph_stats or {},
            insights=insights,
        )
        return enriched.security_reasoning or {}

    async def intelligent_deployment(
        self,
        project_id: int,
        code_profile: dict[str, Any],
        preferred_provider: str | None = None,
    ) -> dict[str, Any]:
        insights = AgenticInsights(code_profile=code_profile)
        insights = await self._coordinator.run_deploying_entry_phase(insights)
        insights = await self._coordinator.run_deployment_planning_phase(insights, preferred_provider)
        return {
            "deployment_intelligence": insights.deployment_intelligence,
            "cost_optimization": insights.cost_optimization,
            "similar_deployments": insights.similar_deployments,
            "proactive_actions": insights.proactive_actions,
        }

    async def self_healing_deploy(
        self,
        project_id: int,
        plan: dict[str, Any],
        project_name: str,
        files: list[dict[str, str]],
        stack_info: dict[str, Any],
        github_url: str | None,
        env_template: str,
    ) -> dict[str, Any]:
        insights = AgenticInsights(
            code_profile=plan.get("code_profile") or {},
            deployment_intelligence=plan.get("deployment_intelligence") or {},
        )
        return await self._coordinator.execute_self_healing_deployment(
            project_name=project_name,
            files=files,
            stack_info=stack_info,
            preferred_provider=plan.get("preferred_provider"),
            github_url=github_url,
            env_template=env_template,
            insights=insights,
        )

    async def monitor_production(self, project_id: int, deployment_url: str) -> dict[str, Any]:
        insights = AgenticInsights()
        insights = await self._coordinator.run_monitoring_phase(insights, deployment_url)
        return insights.production_insights or {}

    async def learn_from_deployment(
        self,
        project_id: int,
        code_profile: dict[str, Any],
        result: dict[str, Any],
    ) -> dict[str, Any]:
        insights = AgenticInsights(
            code_profile=code_profile,
            security_reasoning=result.get("security_reasoning"),
            cost_optimization=result.get("cost_optimization"),
            production_insights=result.get("production_insights"),
        )

        await self._coordinator.record_learning(
            insights=insights,
            outcome=str(result.get("outcome") or "unknown"),
            platform_choice=str(result.get("platform_choice") or "unknown"),
            deployment_attempts=result.get("deployment_attempts") or [],
            fixes_applied=result.get("fixes_applied") or [],
            project_id=project_id,
        )

        return {
            "learning_recorded": insights.learning_recorded,
            "project_id": project_id,
        }
