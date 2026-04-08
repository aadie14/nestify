"""Orchestrator compatibility layer backed by the central execution engine."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from enum import Enum
from typing import Any, Callable

from app.core.execution_engine import ExecutionEngine

logger = logging.getLogger(__name__)

ProgressCallback = Callable[[dict[str, Any]], None]


class PipelineState(str, Enum):
    """Legacy pipeline state constants kept for API compatibility."""

    IDLE = "idle"
    SCANNING = "scanning"
    ANALYZING = "analyzing"
    IMPACT_ANALYSIS = "impact_analysis"
    SIMULATION = "simulation"
    FIXING = "fixing"
    DEPLOYING = "deploying"
    MONITORING = "monitoring"
    COMPLETED = "completed"
    FAILED = "failed"


@dataclass(slots=True)
class OrchestratorResult:
    """Backwards-compatible orchestrator result envelope."""

    security_report: dict[str, Any]
    security_score: int
    risk_report: dict[str, Any]
    fix_report: dict[str, Any]
    deployment: dict[str, Any] | None
    graph_stats: dict[str, Any]
    status: str
    pipeline_states: dict[str, str]


class AgentOrchestrator:
    """Legacy orchestrator entrypoint that delegates to the execution engine."""

    def __init__(self, project_id: int, progress_callback: ProgressCallback | None = None) -> None:
        self.project_id = project_id
        self.on_progress = progress_callback or (lambda _: None)

    async def run(self, parsed_input: dict[str, Any]) -> OrchestratorResult:
        """Execute the full workflow using the central execution engine."""

        engine = ExecutionEngine(project_id=self.project_id, progress_callback=self.on_progress)
        result = await engine.run(parsed_input)

        logger.info("Execution engine finished for project %s with status=%s", self.project_id, result.status)

        return OrchestratorResult(
            security_report=result.security_report,
            security_score=result.security_score,
            risk_report=result.risk_report,
            fix_report=result.fix_report,
            deployment=result.deployment,
            graph_stats=result.graph_stats,
            status=result.status,
            pipeline_states=result.pipeline_states,
        )
