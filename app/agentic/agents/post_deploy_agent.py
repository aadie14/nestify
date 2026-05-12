"""Merged post-deploy agent for monitoring and knowledge curation."""

from __future__ import annotations

import asyncio
import hashlib
import json
import time
from datetime import datetime, timezone
from typing import Any

import httpx

from app.agentic.models import RecommendedAction
from app.core.config import settings
from app.database import add_deployment_pattern
from app.intelligence.embeddings import EmbeddingService
from app.storage.qdrant_client import get_qdrant_client

_PATTERN_COLLECTION = "deployment_patterns"


class PostDeployAgent:
    """Collect post-deploy telemetry and learn from outcomes."""

    def __init__(self) -> None:
        self.embedding_service = EmbeddingService(collection=_PATTERN_COLLECTION)

    def _pattern_text(self, pattern: dict[str, Any]) -> str:
        parts = [
            f"app_type={pattern.get('code_profile', {}).get('app_type', 'unknown')}",
            f"framework={pattern.get('code_profile', {}).get('framework', 'unknown')}",
            f"runtime={pattern.get('code_profile', {}).get('runtime', 'unknown')}",
            f"platform={pattern.get('platform_choice', 'unknown')}",
            f"outcome={pattern.get('outcome', 'unknown')}",
            f"fixes={pattern.get('fixes_applied', [])}",
            f"failures={pattern.get('deployment_attempts', [])}",
        ]
        return "\n".join(parts)

    def _pattern_id(self, pattern_text: str) -> str:
        digest = hashlib.sha256(pattern_text.encode("utf-8")).hexdigest()[:16]
        return f"pattern_{digest}"

    async def store_pattern(self, pattern: dict[str, Any], project_id: int | None = None) -> str:
        serialized = self._pattern_text(pattern)
        pattern_id = self._pattern_id(serialized)

        payload = {
            "pattern_id": pattern_id,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "pattern": pattern,
        }

        add_deployment_pattern(
            pattern_id=pattern_id,
            pattern_payload=payload,
            project_id=project_id,
            outcome=str(pattern.get("outcome", "unknown")),
        )

        qdrant = await get_qdrant_client()
        vector = await self.embedding_service._embed_query(serialized)
        await qdrant.upsert_embedding(
            collection=_PATTERN_COLLECTION,
            item_id=pattern_id,
            vector=vector,
            payload={
                "project_hash": hashlib.sha256(str(project_id or 0).encode("utf-8")).hexdigest()[:12],
                "outcome": str(pattern.get("outcome", "unknown")),
                "pattern": json.dumps(pattern, ensure_ascii=True)[:12000],
            },
        )

        return pattern_id

    async def recommend(self, code_profile: dict[str, Any], limit: int = 10) -> tuple[list[dict[str, Any]], list[RecommendedAction]]:
        query_text = self._pattern_text(
            {
                "code_profile": code_profile,
                "platform_choice": "unknown",
                "outcome": "unknown",
                "fixes_applied": [],
                "deployment_attempts": [],
            }
        )
        query_vector = await self.embedding_service._embed_query(query_text)

        qdrant = await get_qdrant_client()
        hits = await qdrant.search_similar(_PATTERN_COLLECTION, query_vector, limit=limit)

        similar: list[dict[str, Any]] = []
        action_votes: dict[str, int] = {}
        for hit in hits:
            payload = hit.payload or {}
            pattern_raw = payload.get("pattern", "")
            parsed: dict[str, Any] = {}
            if isinstance(pattern_raw, str) and pattern_raw:
                try:
                    parsed = json.loads(pattern_raw)
                except json.JSONDecodeError:
                    parsed = {}

            record = {
                "pattern_id": hit.item_id,
                "score": round(float(hit.score), 4),
                "outcome": payload.get("outcome", "unknown"),
                "pattern": parsed,
            }
            similar.append(record)

            fixes = parsed.get("fixes_applied", []) if isinstance(parsed, dict) else []
            for fix in fixes:
                action = str(fix).strip().lower()
                if action:
                    action_votes[action] = action_votes.get(action, 0) + 1

        recommendations: list[RecommendedAction] = []
        total_hits = max(1, len(similar))
        for action, votes in sorted(action_votes.items(), key=lambda item: item[1], reverse=True)[:5]:
            recommendations.append(
                RecommendedAction(
                    action=action,
                    confidence=round(votes / total_hits, 3),
                    evidence_count=votes,
                    rationale=f"Observed in {votes} similar deployment pattern(s)",
                )
            )

        return similar, recommendations

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
                {"action": "investigate_failing_endpoint", "reason": "Error rate exceeded 1% threshold.", "priority": "high"}
            )

        if metrics.get("p95_ms", 0.0) > 500:
            recommendations.append(
                {"action": "profile_slow_path", "reason": "p95 latency exceeded 500ms.", "priority": "high"}
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
                {"action": "no_change", "reason": "No immediate optimization trigger detected.", "priority": "low"}
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


ProductionMonitoringAnalyst = PostDeployAgent
KnowledgeCurationAgent = PostDeployAgent
