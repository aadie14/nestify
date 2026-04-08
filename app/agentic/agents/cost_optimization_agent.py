"""Agent 3: Cost Optimization Specialist.

Finds minimum viable resource recommendation with optional Docker/HTTP probing.
"""

from __future__ import annotations

import asyncio
import time
from typing import Any

import httpx

from app.core.config import settings
from app.agentic.tools.docker_cost_tester import DockerCostTester


class CostOptimizationSpecialist:
    """Estimate resource/cost profile and benchmark candidate configurations."""

    _PRICING = {
        "vercel": {"256": 5.0, "512": 10.0, "1024": 20.0},
        "railway": {"256": 6.0, "512": 12.0, "1024": 24.0},
        "render": {"256": 7.0, "512": 14.0, "1024": 28.0},
        "netlify": {"256": 4.0, "512": 8.0, "1024": 16.0},
    }

    def __init__(self) -> None:
        self.docker_tester = DockerCostTester()

    def _candidate_configs(self) -> list[dict[str, Any]]:
        return [
            {"memory_mb": 256, "cpu": 0.25, "label": "minimal"},
            {"memory_mb": 512, "cpu": 0.5, "label": "recommended"},
            {"memory_mb": 1024, "cpu": 1.0, "label": "generous"},
        ]

    def _synthetic_benchmark(self, complexity: int, config: dict[str, Any]) -> dict[str, Any]:
        mem = int(config["memory_mb"])
        cpu = float(config["cpu"])
        baseline = max(40.0, min(1200.0, complexity * 3.2))

        pressure_factor = (complexity / max(1.0, mem * cpu)) * 0.05
        p95 = baseline * (1.0 + pressure_factor)
        error_rate = max(0.0, min(0.05, pressure_factor / 8.0))

        return {
            "p50_ms": round(p95 * 0.65, 2),
            "p95_ms": round(p95, 2),
            "p99_ms": round(p95 * 1.45, 2),
            "success_rate": round(1.0 - error_rate, 4),
            "meets_sla": p95 < 200.0 and (1.0 - error_rate) >= 0.999,
        }

    async def _probe_url(self, url: str, seconds: int, target_rps: int) -> dict[str, Any]:
        latencies: list[float] = []
        errors = 0
        total = 0

        deadline = time.time() + max(5, seconds)
        async with httpx.AsyncClient(timeout=10, follow_redirects=True) as client:
            while time.time() < deadline:
                start = time.perf_counter()
                try:
                    response = await client.get(url)
                    if response.status_code >= 400:
                        errors += 1
                except Exception:
                    errors += 1
                finally:
                    total += 1
                    latencies.append((time.perf_counter() - start) * 1000.0)
                await asyncio.sleep(max(0.001, 1.0 / max(1, target_rps)))

        if not latencies:
            return {"p50_ms": 0.0, "p95_ms": 0.0, "p99_ms": 0.0, "success_rate": 0.0, "meets_sla": False}

        latencies_sorted = sorted(latencies)
        p50 = latencies_sorted[int(0.50 * (len(latencies_sorted) - 1))]
        p95 = latencies_sorted[int(0.95 * (len(latencies_sorted) - 1))]
        p99 = latencies_sorted[int(0.99 * (len(latencies_sorted) - 1))]
        success_rate = max(0.0, 1.0 - (errors / max(1, total)))
        return {
            "p50_ms": round(p50, 2),
            "p95_ms": round(p95, 2),
            "p99_ms": round(p99, 2),
            "success_rate": round(success_rate, 4),
            "meets_sla": p95 < 200.0 and success_rate >= 0.999,
            "sample_count": total,
        }

    def _estimate_monthly_cost(self, provider: str, memory_mb: int, requests_per_month: int = 100000) -> float:
        mem_key = str(memory_mb)
        base = self._PRICING.get(provider, self._PRICING["railway"]).get(mem_key, 12.0)
        bandwidth_component = requests_per_month * 0.0000025
        return round(base + bandwidth_component, 2)

    async def optimize(
        self,
        code_profile: dict[str, Any],
        preferred_provider: str | None,
        probe_url: str | None = None,
        project_path: str | None = None,
    ) -> dict[str, Any]:
        complexity = int(code_profile.get("deployment_complexity_score", 50))
        provider = (preferred_provider or "railway").lower()
        baseline_memory = int(code_profile.get("resource_prediction", {}).get("memory_mb") or 512)

        if project_path and self.docker_tester.is_available:
            docker_result = await self.docker_tester.test_configs(
                project_path=project_path,
                app_type=str(code_profile.get("app_type") or "backend"),
                provider=provider,
            )
            if docker_result.get("tested"):
                return {
                    "provider": provider,
                    **docker_result,
                }

        observed_probe: dict[str, Any] | None = None
        if probe_url:
            observed_probe = await self._probe_url(
                probe_url,
                seconds=min(30, settings.load_test_duration_seconds),
                target_rps=max(1, settings.load_test_target_rps),
            )

        matrix: list[dict[str, Any]] = []
        for config in self._candidate_configs():
            if observed_probe:
                benchmark = self._scaled_from_observed_probe(
                    observed_probe=observed_probe,
                    baseline_memory_mb=baseline_memory,
                    target_memory_mb=int(config["memory_mb"]),
                )
            else:
                benchmark = self._synthetic_benchmark(complexity, config)

            monthly_cost = self._estimate_monthly_cost(provider, int(config["memory_mb"]))
            matrix.append({
                "config": config,
                "benchmark": benchmark,
                "monthly_cost_usd": monthly_cost,
            })

        meeting = [m for m in matrix if m["benchmark"].get("meets_sla")]
        if meeting:
            recommended = sorted(meeting, key=lambda item: (item["config"]["memory_mb"], item["monthly_cost_usd"]))[0]
        else:
            recommended = sorted(matrix, key=lambda item: item["benchmark"].get("p95_ms", 99999))[0]

        return {
            "provider": provider,
            "recommended": recommended,
            "comparison_matrix": matrix,
            "sla": {"p95_ms_lt": 200, "success_rate_gte": 0.999},
            "method": "http_probe" if probe_url else "heuristic_estimation",
            "tested": bool(probe_url),
            "note": "Docker benchmark unavailable; using modeled estimates" if not probe_url else None,
            "observed_probe": observed_probe,
        }

    def _scaled_from_observed_probe(
        self,
        observed_probe: dict[str, Any],
        baseline_memory_mb: int,
        target_memory_mb: int,
    ) -> dict[str, Any]:
        """Scale a single observed probe to candidate resource tiers.

        This keeps measurement real (one live probe) while still producing
        actionable per-tier recommendations.
        """
        ratio = max(0.25, min(4.0, baseline_memory_mb / max(1.0, target_memory_mb)))

        p50 = float(observed_probe.get("p50_ms", 0.0)) * (0.85 + 0.25 * ratio)
        p95 = float(observed_probe.get("p95_ms", 0.0)) * (0.85 + 0.30 * ratio)
        p99 = float(observed_probe.get("p99_ms", 0.0)) * (0.85 + 0.35 * ratio)

        base_success = float(observed_probe.get("success_rate", 0.0))
        success_rate = max(0.0, min(1.0, base_success - max(0.0, ratio - 1.0) * 0.01))

        return {
            "p50_ms": round(p50, 2),
            "p95_ms": round(p95, 2),
            "p99_ms": round(p99, 2),
            "success_rate": round(success_rate, 4),
            "meets_sla": p95 < 200.0 and success_rate >= 0.999,
            "sample_count": int(observed_probe.get("sample_count", 0)),
        }
