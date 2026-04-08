"""Learning engine for storing and extracting deployment outcome patterns."""

from __future__ import annotations

import json
from collections import Counter
from typing import Any

from app.database import add_deployment_outcome, list_deployment_outcomes
from app.intelligence.embeddings import EmbeddingService
from app.storage.qdrant_client import get_qdrant_client


class LearningEngine:
    """Persist and retrieve deployment learnings across runs."""

    def __init__(self) -> None:
        self.embedding = EmbeddingService(collection="deployments")

    async def store_deployment_outcome(self, deployment_data: dict[str, Any]) -> dict[str, Any]:
        project_id = int(deployment_data.get("project_id") or 0)
        code_profile = deployment_data.get("code_profile") or {}
        framework = str(code_profile.get("framework") or "unknown")
        platform = str(deployment_data.get("platform") or "unknown")
        success = str(deployment_data.get("outcome") or "failed").lower() in {"success", "live", "completed"}

        add_deployment_outcome(
            project_id=project_id,
            framework=framework,
            platform=platform,
            success=success,
            duration_seconds=int(deployment_data.get("duration") or 0),
            cost_per_month=float(deployment_data.get("cost") or 0.0),
            fixes_applied=[str(item) for item in deployment_data.get("fixes", [])],
            debate_transcript=deployment_data.get("debate_transcript") or {},
            learnings=[str(item) for item in deployment_data.get("learnings", [])],
            agentic_enabled=bool(deployment_data.get("agentic_enabled", True)),
        )

        text = self._create_embedding_text(deployment_data)
        vector = await self.embedding._embed_query(text)
        qdrant = await get_qdrant_client()
        await qdrant.upsert_embedding(
            collection="deployments",
            item_id=str(project_id),
            vector=vector,
            payload={
                "framework": framework,
                "platform_chosen": platform,
                "success": success,
                "fixes_applied": deployment_data.get("fixes", []),
                "cost_per_month": deployment_data.get("cost"),
                "code_profile": json.dumps(code_profile, ensure_ascii=True)[:12000],
            },
        )
        return {"stored": True, "project_id": project_id}

    async def find_similar_deployments(self, code_profile: dict[str, Any], limit: int = 10) -> list[dict[str, Any]]:
        text = self._create_embedding_text({"code_profile": code_profile})
        vector = await self.embedding._embed_query(text)
        qdrant = await get_qdrant_client()
        hits = await qdrant.search_similar("deployments", vector, limit=max(1, limit))

        similar = []
        for hit in hits:
            payload = hit.payload or {}
            similar.append(
                {
                    "similarity": round(float(hit.score), 4),
                    "framework": payload.get("framework"),
                    "platform": payload.get("platform_chosen"),
                    "success": bool(payload.get("success")),
                    "fixes_applied": payload.get("fixes_applied", []),
                    "cost": payload.get("cost_per_month"),
                }
            )
        return similar

    async def extract_patterns(self, similar_deployments: list[dict[str, Any]]) -> dict[str, Any]:
        if len(similar_deployments) < 3:
            return {"confidence": "low", "patterns": [], "sample_size": len(similar_deployments)}

        fixes = Counter()
        platform = Counter()
        successes = Counter()
        costs = []

        for item in similar_deployments:
            for fix in item.get("fixes_applied", []):
                fixes[str(fix)] += 1
            platform_name = str(item.get("platform") or "unknown")
            platform[platform_name] += 1
            if item.get("success"):
                successes[platform_name] += 1
            if item.get("cost") is not None:
                try:
                    costs.append(float(item.get("cost")))
                except (TypeError, ValueError):
                    pass

        recommendations = []
        for platform_name, count in platform.items():
            recommendations.append(
                {
                    "platform": platform_name,
                    "success_rate": round(successes[platform_name] / max(1, count), 3),
                    "sample_size": count,
                }
            )
        recommendations.sort(key=lambda item: item["success_rate"], reverse=True)

        common_fixes = []
        for name, count in fixes.most_common(5):
            frequency = count / max(1, len(similar_deployments))
            common_fixes.append(
                {
                    "fix": name,
                    "frequency": round(frequency, 3),
                    "recommendation": "apply_proactively" if frequency >= 0.8 else "monitor",
                }
            )

        avg_cost = round(sum(costs) / max(1, len(costs)), 2) if costs else 0.0
        return {
            "confidence": "high" if len(similar_deployments) >= 10 else "medium",
            "sample_size": len(similar_deployments),
            "common_fixes": common_fixes,
            "platform_recommendations": recommendations,
            "typical_cost": avg_cost,
            "insights": self._generate_insights(similar_deployments),
        }

    def learning_stats(self, limit: int = 2000) -> dict[str, Any]:
        rows = list_deployment_outcomes(limit=max(1, limit))
        total = len(rows)
        success_count = sum(1 for row in rows if row.get("success"))

        return {
            "total_deployments": total,
            "success_rate": round(success_count / max(1, total), 4),
            "first_attempt_success_rate": round(success_count / max(1, total), 4),
            "average_duration_seconds": round(
                sum(int(row.get("duration_seconds") or 0) for row in rows) / max(1, total),
                2,
            ),
            "records": rows[:100],
        }

    def _create_embedding_text(self, data: dict[str, Any]) -> str:
        profile = data.get("code_profile") or {}
        framework = str(profile.get("framework") or "unknown")
        runtime = str(profile.get("runtime") or "unknown")
        deps = profile.get("dependencies") or []
        platform = str(data.get("platform") or "unknown")
        return f"framework={framework}\nruntime={runtime}\nplatform={platform}\ndeps={' '.join(map(str, deps[:20]))}"

    def _generate_insights(self, deployments: list[dict[str, Any]]) -> list[str]:
        insights: list[str] = []
        total = len(deployments)
        success_rate = sum(1 for item in deployments if item.get("success")) / max(1, total)
        if success_rate >= 0.9:
            insights.append(f"Similar cases show {success_rate:.0%} success rate; confidence is strong.")
        elif success_rate < 0.6:
            insights.append(f"Warning: Similar cases only succeed {success_rate:.0%} of the time.")

        fixes = Counter()
        for item in deployments:
            for fix in item.get("fixes_applied", []):
                fixes[str(fix)] += 1
        if fixes:
            top_fix, top_count = fixes.most_common(1)[0]
            insights.append(f"Most common remediation: {top_fix} ({top_count} occurrences).")

        return insights
