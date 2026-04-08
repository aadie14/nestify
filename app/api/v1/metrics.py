"""Metrics endpoints that demonstrate learning improvement over time."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter

from app.database import list_deployment_outcomes, list_deployment_patterns

router = APIRouter()


def _build_batches(rows: list[dict[str, Any]], size: int = 10) -> list[dict[str, Any]]:
    ordered = sorted(rows, key=lambda item: int(item.get("id") or 0))
    batches: list[dict[str, Any]] = []
    for index in range(0, len(ordered), size):
        chunk = ordered[index:index + size]
        if not chunk:
            continue
        success_values = [1.0 if bool(item.get("success")) else 0.0 for item in chunk]
        durations = [float(item.get("duration_seconds") or 0.0) for item in chunk]
        batch_start = int(chunk[0].get("id") or 0)
        batch_end = int(chunk[-1].get("id") or 0)
        batches.append(
            {
                "batch": f"{batch_start}-{batch_end}",
                "deployments": len(chunk),
                "success_rate": round(sum(success_values) / max(1, len(success_values)), 3),
                "avg_time_seconds": round(sum(durations) / max(1, len(durations)), 1),
            }
        )
    return batches


@router.get("/metrics/learning-proof")
async def get_learning_proof() -> dict[str, Any]:
    """Return measurable evidence of learning-driven improvement."""

    rows = [row for row in list_deployment_outcomes(limit=5000) if bool(row.get("agentic_enabled"))]
    batches = _build_batches(rows, size=10)

    improvement = None
    if len(batches) >= 2:
        first = batches[0]
        last = batches[-1]
        improvement = {
            "success_rate_increase": round(float(last["success_rate"]) - float(first["success_rate"]), 3),
            "time_reduction": round(float(first["avg_time_seconds"]) - float(last["avg_time_seconds"]), 1),
            "total_deployments": sum(int(item["deployments"]) for item in batches),
        }

    pattern_count = len(list_deployment_patterns(limit=100000))

    return {
        "success_rate_by_batch": batches,
        "improvement": improvement,
        "patterns_discovered": pattern_count,
        "proof_statement": (
            f"System has learned from {sum(item['deployments'] for item in batches)} deployments. "
            f"Success rate improved by {improvement['success_rate_increase']:.1%} over time."
            if improvement
            else "Need more deployments to establish an improvement trend"
        ),
    }
