"""Qdrant Client — Vector store adapter with in-memory fallback.

Provides embedding upsert/search operations for semantic code intelligence.
If Qdrant is unreachable, a local in-memory collection is used so core
pipeline behavior continues without hard infrastructure dependencies.
"""

from __future__ import annotations

import logging
import math
from dataclasses import dataclass
from typing import Any

from app.core.config import settings

logger = logging.getLogger(__name__)


@dataclass(slots=True)
class VectorSearchResult:
    """Single vector search hit."""

    item_id: str
    score: float
    payload: dict[str, Any]


class QdrantStore:
    """Qdrant wrapper with graceful fallback to in-memory vectors."""

    def __init__(self, host: str, port: int) -> None:
        self._host = host
        self._port = port
        self._client: Any = None
        self._connected = False
        self._memory: dict[str, dict[str, tuple[list[float], dict[str, Any]]]] = {}

    @property
    def is_connected(self) -> bool:
        return self._connected

    async def connect(self) -> bool:
        """Connect to Qdrant if available; keep fallback mode otherwise."""

        try:
            from qdrant_client import QdrantClient  # type: ignore[import-untyped]

            self._client = QdrantClient(host=self._host, port=self._port, timeout=5)
            self._client.get_collections()
            self._connected = True
            logger.info("Connected to Qdrant at %s:%s", self._host, self._port)
        except Exception as exc:
            self._connected = False
            logger.warning("Qdrant unavailable (%s) — using in-memory vector fallback", exc)

        return self._connected

    async def upsert_embedding(
        self,
        collection: str,
        item_id: str,
        vector: list[float],
        payload: dict[str, Any] | None = None,
    ) -> None:
        """Insert or update an embedding vector."""

        payload = payload or {}

        if self._connected:
            await self._upsert_qdrant(collection, item_id, vector, payload)
            return

        bucket = self._memory.setdefault(collection, {})
        bucket[item_id] = (vector, payload)

    async def search_similar(
        self,
        collection: str,
        vector: list[float],
        limit: int = 10,
    ) -> list[VectorSearchResult]:
        """Search for nearest vectors by cosine similarity."""

        if self._connected:
            return await self._search_qdrant(collection, vector, limit)
        return self._search_memory(collection, vector, limit)

    async def delete_collection(self, collection: str) -> None:
        """Delete a collection and all vectors in it."""

        if self._connected:
            try:
                self._client.delete_collection(collection_name=collection)
            except Exception:
                pass
        self._memory.pop(collection, None)

    async def _upsert_qdrant(
        self,
        collection: str,
        item_id: str,
        vector: list[float],
        payload: dict[str, Any],
    ) -> None:
        """Qdrant-backed upsert path."""

        from qdrant_client import models  # type: ignore[import-untyped]

        try:
            collections = self._client.get_collections().collections
            exists = any(c.name == collection for c in collections)
            if not exists:
                self._client.create_collection(
                    collection_name=collection,
                    vectors_config=models.VectorParams(size=len(vector), distance=models.Distance.COSINE),
                )

            self._client.upsert(
                collection_name=collection,
                points=[
                    models.PointStruct(
                        id=item_id,
                        vector=vector,
                        payload=payload,
                    ),
                ],
            )
        except Exception as exc:
            logger.warning("Qdrant upsert failed (%s) — storing in-memory", exc)
            self._connected = False
            bucket = self._memory.setdefault(collection, {})
            bucket[item_id] = (vector, payload)

    async def _search_qdrant(
        self,
        collection: str,
        vector: list[float],
        limit: int,
    ) -> list[VectorSearchResult]:
        """Qdrant-backed search path."""

        try:
            hits = self._client.search(
                collection_name=collection,
                query_vector=vector,
                limit=limit,
            )
            return [
                VectorSearchResult(
                    item_id=str(hit.id),
                    score=float(hit.score),
                    payload=(hit.payload or {}),
                )
                for hit in hits
            ]
        except Exception as exc:
            logger.warning("Qdrant search failed (%s) — using fallback search", exc)
            self._connected = False
            return self._search_memory(collection, vector, limit)

    def _search_memory(
        self,
        collection: str,
        query_vector: list[float],
        limit: int,
    ) -> list[VectorSearchResult]:
        """In-memory cosine search fallback."""

        bucket = self._memory.get(collection, {})
        scored: list[VectorSearchResult] = []

        for item_id, (candidate, payload) in bucket.items():
            score = _cosine_similarity(query_vector, candidate)
            scored.append(VectorSearchResult(item_id=item_id, score=score, payload=payload))

        scored.sort(key=lambda item: item.score, reverse=True)
        return scored[:limit]


_client: QdrantStore | None = None


async def get_qdrant_client() -> QdrantStore:
    """Get shared Qdrant client instance."""

    global _client
    if _client is None:
        _client = QdrantStore(settings.qdrant_host, settings.qdrant_port)
        await _client.connect()
    return _client


def _cosine_similarity(left: list[float], right: list[float]) -> float:
    """Compute cosine similarity for two vectors."""

    if not left or not right or len(left) != len(right):
        return 0.0

    dot = sum(a * b for a, b in zip(left, right))
    left_norm = math.sqrt(sum(a * a for a in left))
    right_norm = math.sqrt(sum(b * b for b in right))
    if left_norm == 0 or right_norm == 0:
        return 0.0
    return dot / (left_norm * right_norm)
