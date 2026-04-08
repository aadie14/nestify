"""Agent 7: Knowledge Curation Engine.

Stores and retrieves anonymized deployment patterns for similarity-based guidance.
"""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from typing import Any

from app.agentic.models import RecommendedAction
from app.database import add_deployment_pattern
from app.intelligence.embeddings import EmbeddingService
from app.storage.qdrant_client import get_qdrant_client

_PATTERN_COLLECTION = "deployment_patterns"


class KnowledgeCurationAgent:
    """Learn from deployment outcomes and recommend proactive actions."""

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
        """Persist structured pattern in SQLite and vector index."""

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
        """Find similar historical patterns and derive proactive recommendations."""

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
