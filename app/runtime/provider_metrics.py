"""Provider-specific runtime telemetry collection adapters.

These adapters fetch CPU/RAM telemetry when deployment providers expose it,
while degrading safely when metrics are unavailable.
"""

from __future__ import annotations

import time
from typing import Any

import httpx

from app.core.config import settings


def _find_numeric_by_keys(payload: Any, key_candidates: set[str]) -> float | None:
    """Recursively search payload for the first numeric value matching candidate keys."""
    if isinstance(payload, dict):
        for key, value in payload.items():
            normalized = str(key).replace("_", "").replace("-", "").lower()
            if normalized in key_candidates:
                try:
                    return float(value)
                except (TypeError, ValueError):
                    pass
            nested = _find_numeric_by_keys(value, key_candidates)
            if nested is not None:
                return nested
    elif isinstance(payload, list):
        for item in payload:
            nested = _find_numeric_by_keys(item, key_candidates)
            if nested is not None:
                return nested
    return None


class ProviderMetricsCollector:
    """Fetch telemetry from provider APIs when available."""

    async def collect(self, provider: str | None, details: dict[str, Any] | None = None) -> dict[str, Any]:
        normalized_provider = str(provider or "").strip().lower()
        details = details or {}

        if normalized_provider == "railway":
            return await self._collect_railway(details)

        return {
            "provider": normalized_provider or "unknown",
            "status": "unsupported",
            "cpu_percent": None,
            "memory_mb": None,
            "note": "Provider telemetry adapter is not configured for this provider.",
            "collected_at": time.time(),
        }

    async def _collect_render(self, details: dict[str, Any]) -> dict[str, Any]:
        api_key = settings.render_api_key
        service_id = str(details.get("service_id") or "").strip()

        if not api_key:
            return self._unavailable("render", "RENDER_API_KEY is not configured.")
        if not service_id:
            return self._unavailable("render", "Render service_id is missing from deployment details.")

        headers = {"Authorization": f"Bearer {api_key}"}

        try:
            async with httpx.AsyncClient(timeout=15) as client:
                # Service snapshot (always available if service exists).
                service_resp = await client.get(f"https://api.render.com/v1/services/{service_id}", headers=headers)
                service_payload = service_resp.json() if service_resp.content else {}

                # Metrics endpoint may not be enabled for all accounts/services.
                metrics_resp = await client.get(
                    f"https://api.render.com/v1/services/{service_id}/metrics",
                    headers=headers,
                )
                metrics_payload = metrics_resp.json() if metrics_resp.content else {}
        except Exception as exc:
            return self._unavailable("render", f"Render telemetry request failed: {exc}")

        merged = {"service": service_payload, "metrics": metrics_payload}
        cpu = _find_numeric_by_keys(merged, {"cpu", "cpupercent", "cpuusage", "avgcpu", "cpuutilization"})
        memory_mb = _find_numeric_by_keys(
            merged,
            {"memory", "memorymb", "memoryusage", "memoryusagemb", "avgmemory", "rssmb", "rammb"},
        )

        if memory_mb is None:
            memory_bytes = _find_numeric_by_keys(merged, {"memorybytes", "rssbytes", "memoryusagebytes"})
            if memory_bytes is not None:
                memory_mb = memory_bytes / 1024.0 / 1024.0

        if cpu is None and memory_mb is None:
            return self._unavailable(
                "render",
                "Render API reachable but did not return CPU/RAM metrics for this service.",
            )

        return {
            "provider": "render",
            "status": "ok",
            "cpu_percent": round(cpu, 2) if cpu is not None else None,
            "memory_mb": round(memory_mb, 2) if memory_mb is not None else None,
            "note": "Provider metrics collected from Render API.",
            "collected_at": time.time(),
        }

    async def _collect_railway(self, details: dict[str, Any]) -> dict[str, Any]:
        api_key = settings.railway_api_key
        project_id = str(details.get("railway_project_id") or "").strip()

        if not api_key:
            return self._unavailable("railway", "RAILWAY_API_KEY is not configured.")
        if not project_id:
            return self._unavailable("railway", "Railway project id is missing from deployment details.")

        headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}
        gql_url = "https://backboard.railway.app/graphql/v2"

        # Query intentionally includes stable project/service fields first.
        query = """
        query GetProjectTelemetry($id: String!) {
          project(id: $id) {
            id
            name
            services {
              edges {
                node {
                  id
                  name
                  domains {
                    serviceDomains {
                      domain
                    }
                  }
                }
              }
            }
          }
        }
        """

        try:
            async with httpx.AsyncClient(timeout=20) as client:
                response = await client.post(
                    gql_url,
                    headers=headers,
                    json={"query": query, "variables": {"id": project_id}},
                )
                payload = response.json() if response.content else {}
        except Exception as exc:
            return self._unavailable("railway", f"Railway telemetry request failed: {exc}")

        # Some Railway accounts expose metrics through additional fields. We parse opportunistically.
        cpu = _find_numeric_by_keys(payload, {"cpu", "cpupercent", "cpuusage", "avgcpu", "cpuutilization"})
        memory_mb = _find_numeric_by_keys(
            payload,
            {"memory", "memorymb", "memoryusage", "memoryusagemb", "avgmemory", "rssmb", "rammb"},
        )

        if memory_mb is None:
            memory_bytes = _find_numeric_by_keys(payload, {"memorybytes", "rssbytes", "memoryusagebytes"})
            if memory_bytes is not None:
                memory_mb = memory_bytes / 1024.0 / 1024.0

        if cpu is None and memory_mb is None:
            return self._unavailable(
                "railway",
                "Railway API reachable but no CPU/RAM telemetry fields were available for this project.",
            )

        return {
            "provider": "railway",
            "status": "ok",
            "cpu_percent": round(cpu, 2) if cpu is not None else None,
            "memory_mb": round(memory_mb, 2) if memory_mb is not None else None,
            "note": "Provider metrics collected from Railway API.",
            "collected_at": time.time(),
        }

    @staticmethod
    def _unavailable(provider: str, reason: str) -> dict[str, Any]:
        return {
            "provider": provider,
            "status": "unavailable",
            "cpu_percent": None,
            "memory_mb": None,
            "note": reason,
            "collected_at": time.time(),
        }
