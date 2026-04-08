"""CrewAI integration shell.

This module keeps CrewAI optional so existing deployments continue to run
without the dependency installed. It enables phased rollout of the agentic
team orchestration layer.
"""

from __future__ import annotations

from typing import Any


def crewai_available() -> bool:
    try:
        import crewai  # type: ignore[import-untyped] # noqa: F401

        return True
    except Exception:
        return False


def build_phase1_team() -> dict[str, Any]:
    """Return metadata describing the current phase-1 agent team."""
    return {
        "enabled": crewai_available(),
        "agents": ["CodeIntelligenceAnalyst", "KnowledgeCurationAgent"],
        "phase": "phase_1_foundation",
    }
