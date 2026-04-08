"""Pattern matcher tool over existing embedding + Qdrant fallback stack."""

from __future__ import annotations

import asyncio
import json
from typing import Any

from app.intelligence.embeddings import EmbeddingService
from app.storage.qdrant_client import get_qdrant_client


class PatternMatcherTool:
    name: str = "Match Deployment Patterns"
    description: str = "Find similar historical deployment patterns by vector similarity"

    def _run(self, payload: str) -> str:
        return asyncio.run(self._arun(payload))

    async def _arun(self, payload: str) -> str:
        try:
            data = json.loads(payload)
        except json.JSONDecodeError:
            return json.dumps({"ok": False, "error": "payload must be JSON"})

        profile: dict[str, Any] = data.get("code_profile") or {}
        limit = int(data.get("limit") or 10)

        text = json.dumps(profile, sort_keys=True, ensure_ascii=True)
        embedding_service = EmbeddingService(collection="deployment_patterns")
        query_vector = await embedding_service._embed_query(text)

        qdrant = await get_qdrant_client()
        hits = await qdrant.search_similar("deployment_patterns", query_vector, limit=limit)
        result = [
            {
                "pattern_id": hit.item_id,
                "score": round(float(hit.score), 4),
                "payload": hit.payload,
            }
            for hit in hits
        ]
        return json.dumps({"ok": True, "count": len(result), "matches": result})
