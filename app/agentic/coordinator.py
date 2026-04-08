"""Agentic coordinator shell.

Phase 1 provides wrappers for Agent 1 and Agent 7 in an opt-in flow.
"""

from __future__ import annotations

import logging
from dataclasses import asdict
from pathlib import Path
from typing import Any

from app.agentic.agents import (
    CodeIntelligenceAnalyst,
    CostOptimizationSpecialist,
    KnowledgeCurationAgent,
    PlatformSelectionStrategist,
    ProductionMonitoringAnalyst,
    SecurityIntelligenceExpert,
    SelfHealingDeploymentEngineer,
)
from app.agentic.models import AgenticInsights
from app.services.project_source_service import get_project_source_dir

logger = logging.getLogger(__name__)


class AgenticCoordinator:
    """Thin orchestration layer that wraps existing Nestify pipeline artifacts."""

    def __init__(self, project_id: int) -> None:
        self.project_id = project_id
        self.code_agent = CodeIntelligenceAnalyst()
        self.security_agent = SecurityIntelligenceExpert()
        self.cost_agent = CostOptimizationSpecialist()
        self.platform_agent = PlatformSelectionStrategist()
        self.self_heal_agent = SelfHealingDeploymentEngineer()
        self.monitor_agent = ProductionMonitoringAnalyst()
        self.knowledge_agent = KnowledgeCurationAgent()

    async def run_scanning_completion_phase(
        self,
        security_report: dict[str, Any],
        risk_report: dict[str, Any],
        graph_stats: dict[str, Any],
        insights: AgenticInsights,
    ) -> AgenticInsights:
        insights.security_reasoning = await self.security_agent.enrich(
            security_report=security_report,
            risk_report=risk_report,
            graph_stats=graph_stats,
        )
        return insights

    async def run_analyzing_phase(
        self,
        files: list[dict[str, str]],
        graph: Any,
        insights: AgenticInsights,
    ) -> AgenticInsights:
        profile = await self.code_agent.analyze(files=files, graph=graph)
        insights.code_profile = profile.to_dict()
        return insights

    async def run_deploying_entry_phase(self, insights: AgenticInsights) -> AgenticInsights:
        if not insights.code_profile:
            return insights

        from app.learning.pattern_store import PatternStore

        pattern_store = PatternStore()
        similar = await pattern_store.find_similar_deployments(insights.code_profile, limit=10)

        if similar:
            patterns = await pattern_store.extract_actionable_patterns(similar)
            insights.similar_deployments = similar
            insights.proactive_actions = patterns.get("recommendations", [])
            logger.info(
                "Found %s similar deployments, success rate=%s",
                len(similar),
                patterns.get("success_rate", "n/a"),
            )
            return insights

        similar_fallback, recommendations = await self.knowledge_agent.recommend(insights.code_profile, limit=10)
        insights.similar_deployments = similar_fallback
        insights.proactive_actions = [item.to_dict() for item in recommendations]
        return insights

    async def run_deployment_planning_phase(
        self,
        insights: AgenticInsights,
        preferred_provider: str | None,
    ) -> AgenticInsights:
        if not insights.code_profile:
            return insights

        project_root = Path(get_project_source_dir(self.project_id))
        source_dir = project_root / "source"
        project_path = str(source_dir if source_dir.exists() else project_root)

        insights.cost_optimization = await self.cost_agent.optimize(
            code_profile=insights.code_profile,
            preferred_provider=preferred_provider,
            project_path=project_path,
        )

        from app.agentic.agent_debate import AgentDebate

        try:
            debate = AgentDebate()
            debate_result = await debate.debate_platform_choice(
                code_profile=insights.code_profile,
                cost_analysis=insights.cost_optimization,
                similar_deployments=insights.similar_deployments or [],
            )
            insights.deployment_intelligence = {
                "chosen_platform": debate_result["chosen_platform"],
                "reasoning": debate_result["reasoning"],
                "confidence": debate_result["confidence"],
                "debate_transcript": debate_result["debate_transcript"],
                "alternatives_considered": debate_result["alternatives_considered"],
                "estimated_monthly_cost_usd": (
                    insights.cost_optimization.get("recommended", {}).get("monthly_cost_usd")
                    if isinstance(insights.cost_optimization, dict)
                    else None
                ),
            }
        except Exception as exc:
            logger.warning("Agent debate failed, falling back to platform selector: %s", exc)
            insights.deployment_intelligence = self.platform_agent.choose(
                code_profile=insights.code_profile,
                cost_report=insights.cost_optimization,
                preferred_provider=preferred_provider,
                proactive_actions=insights.proactive_actions,
            )

        return insights

    async def execute_self_healing_deployment(
        self,
        project_name: str,
        files: list[dict[str, str]],
        stack_info: dict[str, Any],
        preferred_provider: str | None,
        github_url: str | None,
        env_template: str,
        insights: AgenticInsights,
    ) -> dict[str, Any]:
        app_type = "backend"
        if insights.code_profile:
            app_type = str(insights.code_profile.get("app_type", "backend"))

        planned_provider = preferred_provider
        if insights.deployment_intelligence and insights.deployment_intelligence.get("chosen_platform"):
            planned_provider = str(insights.deployment_intelligence.get("chosen_platform"))

        result = await self.self_heal_agent.deploy_with_self_heal(
            project_id=self.project_id,
            project_name=project_name,
            files=files,
            stack_info=stack_info,
            preferred_provider=planned_provider,
            github_url=github_url,
            env_template=env_template,
            app_type=app_type,
        )

        insights.self_healing_report = result
        return result

    async def run_monitoring_phase(
        self,
        insights: AgenticInsights,
        deployment_url: str | None,
    ) -> AgenticInsights:
        if not deployment_url:
            return insights

        allocated_memory_mb = None
        if insights.cost_optimization:
            allocated_memory_mb = (
                insights.cost_optimization
                .get("recommended", {})
                .get("config", {})
                .get("memory_mb")
            )

        insights.production_insights = await self.monitor_agent.monitor(
            deployment_url=deployment_url,
            allocated_memory_mb=allocated_memory_mb,
        )
        return insights

    async def generate_security_pdf(
        self,
        project_id: int,
        project_name: str,
        insights: AgenticInsights,
    ) -> str:
        """Generate and persist a project security PDF report."""

        from app.reports.pdf_generator import SecurityReportGenerator

        security = insights.security_reasoning if isinstance(insights.security_reasoning, dict) else {}
        findings = security.get("findings") if isinstance(security.get("findings"), list) else []

        deployment_plan = {
            "chosen_platform": (
                insights.deployment_intelligence.get("chosen_platform")
                if isinstance(insights.deployment_intelligence, dict)
                else "unknown"
            ),
            "reasoning": (
                insights.deployment_intelligence.get("reasoning")
                if isinstance(insights.deployment_intelligence, dict)
                else ""
            ),
            "confidence": (
                insights.deployment_intelligence.get("confidence")
                if isinstance(insights.deployment_intelligence, dict)
                else 0.0
            ),
            "alternatives_considered": (
                insights.deployment_intelligence.get("alternatives_considered")
                if isinstance(insights.deployment_intelligence, dict)
                else []
            ),
            "estimated_cost": (
                insights.cost_optimization.get("recommended", {}).get("monthly_cost_usd")
                if isinstance(insights.cost_optimization, dict)
                else None
            ),
        }

        generator = SecurityReportGenerator()
        pdf_path = generator.generate_report(
            project_id=project_id,
            project_name=project_name,
            findings=findings,
            code_profile=insights.code_profile or {},
            deployment_plan=deployment_plan,
            similar_deployments=insights.similar_deployments or [],
        )

        logger.info("Generated security PDF for project %s: %s", project_id, pdf_path)
        return pdf_path

    async def record_learning(
        self,
        insights: AgenticInsights,
        outcome: str,
        platform_choice: str,
        deployment_attempts: list[dict[str, Any]],
        fixes_applied: list[str],
        project_id: int,
    ) -> AgenticInsights:
        if not insights.code_profile:
            return insights

        pattern = {
            "code_profile": insights.code_profile,
            "security_findings": insights.security_reasoning,
            "cost_analysis": insights.cost_optimization,
            "platform_choice": platform_choice,
            "deployment_attempts": deployment_attempts,
            "production_metrics": insights.production_insights,
            "fixes_applied": fixes_applied,
            "outcome": outcome,
        }
        await self.knowledge_agent.store_pattern(pattern=pattern, project_id=project_id)
        insights.learning_recorded = True
        logger.info("Agentic learning pattern recorded for project %s", project_id)
        return insights

    @staticmethod
    def to_dict(insights: AgenticInsights) -> dict[str, Any]:
        return asdict(insights)
