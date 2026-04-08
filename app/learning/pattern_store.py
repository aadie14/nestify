"""Pattern store backed by existing DB + embedding infrastructure."""

from __future__ import annotations

import json
from collections import Counter
from datetime import datetime, timezone
from typing import Any

from app.database import add_deployment_pattern, list_deployment_patterns
from app.intelligence.embeddings import EmbeddingService
from app.storage.qdrant_client import get_qdrant_client


class PatternStore:
    """Stores anonymized deployment metadata and supports similarity search."""

    COLLECTION_NAME = "deployment_patterns"

    def __init__(self) -> None:
        self.embedding = EmbeddingService(collection=self.COLLECTION_NAME)

    async def ensure_collection_exists(self) -> None:
        """No-op for compatibility; Qdrant wrapper creates collections on demand."""
        await get_qdrant_client()

    async def store_deployment_pattern(
        self,
        project_id: int,
        code_profile: dict[str, Any],
        platform_choice: str,
        outcome: str,
        fixes_applied: list[str],
        deployment_time_seconds: float,
        cost_per_month: float | None = None,
    ) -> dict[str, Any]:
        """Store deployment outcome in SQLite and vector index."""

        await self.ensure_collection_exists()
        timestamp = datetime.now(timezone.utc).isoformat()
        framework = str(code_profile.get("framework") or "unknown")
        runtime = str(code_profile.get("runtime") or "unknown")
        dependencies = code_profile.get("dependencies") if isinstance(code_profile.get("dependencies"), list) else []
        dependencies = [str(item) for item in dependencies[:20]]

        embedding_text = " ".join([framework, runtime, *dependencies]).strip()
        vector = await self.embedding._embed_query(embedding_text)

        point_id = f"dp_{project_id}_{int(datetime.now(timezone.utc).timestamp() * 1000)}"
        pattern_payload = {
            "project_id": project_id,
            "framework": framework,
            "runtime": runtime,
            "dependencies": dependencies,
            "platform_choice": platform_choice,
            "outcome": outcome,
            "success": str(outcome).lower() in {"success", "completed", "live"},
            "fixes_applied": fixes_applied,
            "deployment_time_seconds": float(deployment_time_seconds),
            "cost_per_month": cost_per_month,
            "timestamp": timestamp,
            "code_profile": code_profile,
        }

        add_deployment_pattern(
            pattern_id=point_id,
            pattern_payload={"pattern": pattern_payload, "timestamp": timestamp},
            project_id=project_id,
            outcome=outcome,
        )

        qdrant = await get_qdrant_client()
        await qdrant.upsert_embedding(
            collection=self.COLLECTION_NAME,
            item_id=point_id,
            vector=vector,
            payload={
                "framework": framework,
                "runtime": runtime,
                "platform_choice": platform_choice,
                "success": pattern_payload["success"],
                "fixes_applied": fixes_applied,
                "deployment_time_seconds": float(deployment_time_seconds),
                "cost_per_month": cost_per_month,
                "pattern": json.dumps(pattern_payload, ensure_ascii=True)[:12000],
            },
        )

        return {"stored": True, "point_id": point_id, "collection": self.COLLECTION_NAME}

    async def find_similar_deployments(self, code_profile: dict[str, Any], limit: int = 10) -> list[dict[str, Any]]:
        """Find similar historical deployments using vector similarity."""

        framework = str(code_profile.get("framework") or "unknown")
        runtime = str(code_profile.get("runtime") or "unknown")
        dependencies = code_profile.get("dependencies") if isinstance(code_profile.get("dependencies"), list) else []
        dependencies = [str(item) for item in dependencies[:20]]
        query_text = " ".join([framework, runtime, *dependencies]).strip()

        query_vector = await self.embedding._embed_query(query_text)
        qdrant = await get_qdrant_client()
        hits = await qdrant.search_similar(self.COLLECTION_NAME, query_vector, limit=limit)

        similar_deployments: list[dict[str, Any]] = []
        for hit in hits:
            payload = hit.payload or {}
            similar_deployments.append(
                {
                    "similarity_score": round(float(hit.score), 4),
                    "framework": payload.get("framework"),
                    "runtime": payload.get("runtime"),
                    "platform_choice": payload.get("platform_choice"),
                    "success": payload.get("success"),
                    "fixes_applied": payload.get("fixes_applied", []),
                    "deployment_time_seconds": payload.get("deployment_time_seconds"),
                    "cost_per_month": payload.get("cost_per_month"),
                }
            )

        return similar_deployments

    async def extract_actionable_patterns(self, similar_deployments: list[dict[str, Any]]) -> dict[str, Any]:
        """Summarize similar deployments into proactive recommendations."""

        if len(similar_deployments) < 3:
            return {
                "confidence": "low",
                "sample_size": len(similar_deployments),
                "recommendations": [],
                "note": "Need more similar deployments for high-confidence recommendations",
            }

        platform_stats: dict[str, dict[str, int]] = {}
        all_fixes: list[str] = []
        success_count = 0

        for dep in similar_deployments:
            platform = str(dep.get("platform_choice") or "unknown")
            success = bool(dep.get("success"))
            platform_stats.setdefault(platform, {"total": 0, "success": 0})
            platform_stats[platform]["total"] += 1
            if success:
                platform_stats[platform]["success"] += 1
                success_count += 1

            fixes = dep.get("fixes_applied") if isinstance(dep.get("fixes_applied"), list) else []
            all_fixes.extend(str(item) for item in fixes)

        fix_frequency = Counter(all_fixes)
        common_fixes = []
        for fix, count in fix_frequency.most_common(5):
            frequency = count / max(1, len(similar_deployments))
            common_fixes.append(
                {
                    "fix": fix,
                    "frequency": round(frequency, 3),
                    "recommendation": "apply_proactively" if frequency > 0.7 else "monitor",
                }
            )

        platform_rankings = []
        for platform, stats in platform_stats.items():
            rate = stats["success"] / max(1, stats["total"])
            platform_rankings.append(
                {
                    "platform": platform,
                    "success_rate": round(rate, 3),
                    "sample_size": stats["total"],
                    "recommended": rate > 0.85,
                }
            )
        platform_rankings.sort(key=lambda item: item["success_rate"], reverse=True)

        recommendations: list[dict[str, Any]] = []
        for fix in common_fixes:
            if fix["recommendation"] == "apply_proactively":
                recommendations.append(
                    {
                        "type": "proactive_fix",
                        "action": fix["fix"],
                        "reasoning": f"{int(fix['frequency'] * 100)}% of similar deployments needed this",
                        "confidence": fix["frequency"],
                    }
                )

        if platform_rankings:
            best = platform_rankings[0]
            if best["success_rate"] > 0.9:
                recommendations.append(
                    {
                        "type": "platform_choice",
                        "action": f"use_{best['platform']}",
                        "reasoning": f"{int(best['success_rate'] * 100)}% success rate for similar apps",
                        "confidence": best["success_rate"],
                    }
                )

        return {
            "confidence": "high" if len(similar_deployments) >= 10 else "medium",
            "sample_size": len(similar_deployments),
            "success_rate": round(success_count / max(1, len(similar_deployments)), 3),
            "common_fixes": common_fixes,
            "platform_recommendations": platform_rankings,
            "recommendations": recommendations,
        }

    async def store_pattern(self, pattern_id: str, pattern_payload: dict[str, Any], outcome: str, project_id: int | None = None) -> dict[str, Any]:
        code_profile = pattern_payload.get("code_profile", {}) if isinstance(pattern_payload, dict) else {}
        platform = str(pattern_payload.get("platform_choice") or "unknown") if isinstance(pattern_payload, dict) else "unknown"
        fixes = pattern_payload.get("fixes_applied") if isinstance(pattern_payload, dict) and isinstance(pattern_payload.get("fixes_applied"), list) else []
        time_seconds = 0.0
        if isinstance(pattern_payload, dict):
            attempts = pattern_payload.get("deployment_attempts")
            if isinstance(attempts, list) and attempts:
                time_seconds = float(len(attempts) * 30)

        result = await self.store_deployment_pattern(
            project_id=int(project_id or 0),
            code_profile=code_profile if isinstance(code_profile, dict) else {},
            platform_choice=platform,
            outcome=outcome,
            fixes_applied=[str(item) for item in fixes],
            deployment_time_seconds=time_seconds,
            cost_per_month=(pattern_payload.get("cost_analysis", {}) or {}).get("recommended", {}).get("monthly_cost_usd")
            if isinstance(pattern_payload, dict)
            else None,
        )
        return {"pattern_id": pattern_id, "stored": bool(result.get("stored"))}

    async def find_similar(self, code_profile: dict[str, Any], limit: int = 10) -> list[dict[str, Any]]:
        rows = await self.find_similar_deployments(code_profile=code_profile, limit=limit)
        return [
            {
                "pattern_id": f"sim_{idx}",
                "score": row.get("similarity_score", 0.0),
                "framework": row.get("framework"),
                "runtime": row.get("runtime"),
                "platform": row.get("platform_choice"),
                "success": row.get("success"),
                "fixes_applied": row.get("fixes_applied", []),
                "payload": row,
            }
            for idx, row in enumerate(rows)
        ]

    def recent_patterns(self, limit: int = 200) -> list[dict[str, Any]]:
        return list_deployment_patterns(limit=limit)
