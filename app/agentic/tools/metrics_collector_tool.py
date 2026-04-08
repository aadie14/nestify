"""Metrics collector tool that samples runtime health using existing analyzer."""

from __future__ import annotations

import asyncio
import json

from app.runtime.metrics_analyzer import MetricsAnalyzer


class MetricsCollectorTool:
    name: str = "Collect Runtime Metrics"
    description: str = "Run health checks and summarize runtime anomalies"

    def _run(self, payload: str) -> str:
        return asyncio.run(self._arun(payload))

    async def _arun(self, payload: str) -> str:
        try:
            data = json.loads(payload)
        except json.JSONDecodeError:
            return json.dumps({"ok": False, "error": "payload must be JSON"})

        deployment_url = str(data.get("deployment_url") or "")
        samples = max(1, min(60, int(data.get("samples") or 10)))
        interval_ms = max(100, int(data.get("interval_ms") or 1000))

        if not deployment_url:
            return json.dumps({"ok": False, "error": "deployment_url required"})

        analyzer = MetricsAnalyzer(deployment_url)
        for _ in range(samples):
            await analyzer.health_check()
            await asyncio.sleep(interval_ms / 1000.0)

        status = analyzer.analyze().to_dict()
        return json.dumps({"ok": True, "metrics": status})
