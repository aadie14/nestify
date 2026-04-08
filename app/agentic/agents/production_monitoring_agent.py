"""Agent 6: Production Monitoring Analyst."""

from __future__ import annotations

import asyncio
import statistics
import time
from typing import Any

import httpx

from app.core.config import settings


class ProductionMonitoringAnalyst:
    """Collect early post-deployment telemetry and recommend optimizations."""

    async def _sample_url(self, url: str, sample_count: int = 12) -> dict[str, Any]:
        latencies: list[float] = []
        errors = 0

        async with httpx.AsyncClient(timeout=10, follow_redirects=True) as client:
            for _ in range(sample_count):
                start = time.perf_counter()
                try:
                    resp = await client.get(url)
                    if resp.status_code >= 400:
                        errors += 1
                except Exception:
                    errors += 1
                finally:
                    latencies.append((time.perf_counter() - start) * 1000.0)
                await asyncio.sleep(1.0)

        latencies_sorted = sorted(latencies)
        p50 = latencies_sorted[int(0.50 * (len(latencies_sorted) - 1))] if latencies_sorted else 0.0
        p95 = latencies_sorted[int(0.95 * (len(latencies_sorted) - 1))] if latencies_sorted else 0.0
        p99 = latencies_sorted[int(0.99 * (len(latencies_sorted) - 1))] if latencies_sorted else 0.0
        error_rate = errors / max(1, len(latencies_sorted))

        return {
            "p50_ms": round(p50, 2),
            "p95_ms": round(p95, 2),
            "p99_ms": round(p99, 2),
            "error_rate": round(error_rate, 4),
            "sample_count": len(latencies_sorted),
        }

    def _optimize(self, metrics: dict[str, Any], allocated_memory_mb: int | None) -> list[dict[str, Any]]:
        recommendations: list[dict[str, Any]] = []

        if metrics.get("error_rate", 0.0) > 0.01:
            recommendations.append(
                {
                    "action": "investigate_failing_endpoint",
                    "reason": "Error rate exceeded 1% threshold.",
                    "priority": "high",
                }
            )

        if metrics.get("p95_ms", 0.0) > 500:
            recommendations.append(
                {
                    "action": "profile_slow_path",
                    "reason": "p95 latency exceeded 500ms.",
                    "priority": "high",
                }
            )

        if allocated_memory_mb and allocated_memory_mb >= 512 and metrics.get("p95_ms", 0.0) < 180:
            recommendations.append(
                {
                    "action": "consider_downsize",
                    "reason": "Performance headroom suggests potential over-provisioning.",
                    "priority": "medium",
                }
            )

        if not recommendations:
            recommendations.append(
                {
                    "action": "no_change",
                    "reason": "No immediate optimization trigger detected.",
                    "priority": "low",
                }
            )

        return recommendations

    async def monitor(
        self,
        deployment_url: str,
        allocated_memory_mb: int | None = None,
    ) -> dict[str, Any]:
        metrics = await self._sample_url(deployment_url, sample_count=12)
        recommendations = self._optimize(metrics, allocated_memory_mb)
        return {
            "duration_hours": settings.monitor_duration_hours,
            "metrics": metrics,
            "recommendations": recommendations,
            "auto_applied": [],
        }
