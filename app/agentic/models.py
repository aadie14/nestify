"""Shared data models for the agentic intelligence extension."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any


@dataclass(slots=True)
class CodeProfile:
    """Structured architecture profile generated from existing graph intelligence."""

    app_type: str
    framework: str
    runtime: str
    dependencies: list[str]
    external_services: list[str]
    resource_prediction: dict[str, Any]
    deployment_complexity_score: int
    likely_failure_modes: list[str] = field(default_factory=list)
    reasoning: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(slots=True)
class RecommendedAction:
    """Action inferred from historical deployment similarity."""

    action: str
    confidence: float
    evidence_count: int
    rationale: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(slots=True)
class AgenticInsights:
    """Container for optional agentic output appended to project status responses."""

    code_profile: dict[str, Any] | None = None
    security_reasoning: dict[str, Any] | None = None
    cost_optimization: dict[str, Any] | None = None
    deployment_intelligence: dict[str, Any] | None = None
    self_healing_report: dict[str, Any] | None = None
    production_insights: dict[str, Any] | None = None
    similar_deployments: list[dict[str, Any]] = field(default_factory=list)
    proactive_actions: list[dict[str, Any]] = field(default_factory=list)
    learning_recorded: bool = False

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)
