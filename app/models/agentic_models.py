"""Agentic response models (additive compatibility models)."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(slots=True)
class CodeProfileModel:
    framework: str = "unknown"
    language: str = "unknown"
    app_type: str = "unknown"
    dependencies: list[str] = field(default_factory=list)
    predicted_memory_mb: int = 512
    predicted_cpu: float = 0.5
    has_database: bool = False
    has_cache: bool = False
    has_websockets: bool = False


@dataclass(slots=True)
class PlatformDecisionModel:
    chosen: str = "railway"
    reasoning: str = ""
    alternatives: list[dict[str, Any]] = field(default_factory=list)


@dataclass(slots=True)
class CostOptimizationModel:
    recommended_memory_mb: int = 512
    recommended_cpu: float = 0.5
    estimated_monthly_cost_usd: float = 0.0
    method: str = "synthetic_predeploy"


@dataclass(slots=True)
class SelfHealingModel:
    status: str = "unknown"
    attempts: int = 0
    fixes_applied: list[str] = field(default_factory=list)


@dataclass(slots=True)
class AgenticResponseModel:
    code_profile: dict[str, Any] | None = None
    platform_decision: dict[str, Any] | None = None
    cost_optimization: dict[str, Any] | None = None
    self_healing: dict[str, Any] | None = None
    production_monitoring: dict[str, Any] | None = None
    learning_context: dict[str, Any] | None = None
