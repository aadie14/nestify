"""Cost calculator tool using existing optimization specialist pricing logic."""

from __future__ import annotations

import json

from app.agentic.agents.cost_optimization_agent import CostOptimizationSpecialist


class CostCalculatorTool:
    name: str = "Calculate Deployment Cost"
    description: str = "Estimate monthly cost for provider + resource config"

    def __init__(self) -> None:
        self._optimizer = CostOptimizationSpecialist()

    def _run(self, payload: str) -> str:
        try:
            data = json.loads(payload)
        except json.JSONDecodeError:
            return json.dumps({"ok": False, "error": "payload must be JSON"})

        provider = str(data.get("provider") or "railway").lower()
        memory_mb = int(data.get("memory_mb") or 512)
        requests_per_month = int(data.get("requests_per_month") or 100000)

        monthly = self._optimizer._estimate_monthly_cost(provider, memory_mb, requests_per_month)
        return json.dumps(
            {
                "ok": True,
                "provider": provider,
                "memory_mb": memory_mb,
                "requests_per_month": requests_per_month,
                "estimated_monthly_cost_usd": monthly,
            }
        )
