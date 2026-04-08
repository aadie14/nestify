"""Embeddings Engine — Semantic vectors for code entities.

Primary path uses the LLM service to generate embedding vectors.
If the LLM path fails, a TF-IDF fallback is used for deterministic
semantic search support.
"""

from __future__ import annotations

import hashlib
import json
import logging
from dataclasses import dataclass
from typing import Any

from app.services.llm_service import call_llm
from app.storage.qdrant_client import VectorSearchResult, get_qdrant_client

logger = logging.getLogger(__name__)

EMBED_DIMENSION = 128


@dataclass(slots=True)
class CodeEmbeddingItem:
    """Code snippet ready for embedding."""

    item_id: str
    text: str
    metadata: dict[str, Any]


class EmbeddingService:
    """Embedding orchestration with LLM-first and TF-IDF fallback."""

    def __init__(self, collection: str = "code_embeddings") -> None:
        self.collection = collection

    async def index_items(self, items: list[CodeEmbeddingItem]) -> int:
        """Generate and store embeddings for all items."""

        if not items:
            return 0

        texts = [item.text for item in items]

        vectors = await self._try_llm_embeddings(items)
        if vectors is None:
            vectors = self._tfidf_embeddings(texts)

        qdrant = await get_qdrant_client()
        stored = 0
        for item, vector in zip(items, vectors):
            await qdrant.upsert_embedding(
                collection=self.collection,
                item_id=item.item_id,
                vector=vector,
                payload=item.metadata,
            )
            stored += 1

        return stored

    async def search(self, query: str, limit: int = 10) -> list[VectorSearchResult]:
        """Semantic search over embedded code entities."""

        query_vector = await self._embed_query(query)
        qdrant = await get_qdrant_client()
        return await qdrant.search_similar(self.collection, query_vector, limit=limit)

    async def _embed_query(self, query: str) -> list[float]:
        """Embed a query string, preferring LLM output."""

        llm = await self._embed_with_llm(query)
        if llm is not None:
            return llm

        # Deterministic fallback for one-off query embedding.
        return _hash_embedding(query, EMBED_DIMENSION)

    async def _try_llm_embeddings(self, items: list[CodeEmbeddingItem]) -> list[list[float]] | None:
        """Attempt batch-like embedding generation through LLM JSON output."""

        vectors: list[list[float]] = []
        for item in items:
            vector = await self._embed_with_llm(item.text)
            if vector is None:
                return None
            vectors.append(vector)
        return vectors

    async def _embed_with_llm(self, text: str) -> list[float] | None:
        """Generate one embedding vector via LLM response."""

        prompt = (
            "Return a compact embedding vector as JSON with key 'vector'. "
            f"The vector must contain exactly {EMBED_DIMENSION} float values in [-1, 1]. "
            "Do not add extra keys.\n\n"
            f"TEXT:\n{text[:3000]}"
        )

        try:
            response = await call_llm(
                [
                    {"role": "system", "content": "You generate strict JSON embeddings."},
                    {"role": "user", "content": prompt},
                ],
                {"task_weight": "lite", "json_mode": True, "temperature": 0.0, "max_tokens": 1200},
            )
            parsed = json.loads(response["content"])
            raw = parsed.get("vector")
            if not isinstance(raw, list):
                return None

            vector: list[float] = []
            for value in raw[:EMBED_DIMENSION]:
                try:
                    vector.append(float(value))
                except (TypeError, ValueError):
                    vector.append(0.0)

            if len(vector) < EMBED_DIMENSION:
                vector.extend([0.0] * (EMBED_DIMENSION - len(vector)))

            return vector
        except Exception as exc:
            logger.warning("LLM embedding unavailable, falling back to TF-IDF/hash: %s", exc)
            return None

    def _tfidf_embeddings(self, texts: list[str]) -> list[list[float]]:
        """Generate TF-IDF vectors and normalize/pad to fixed dimension."""

        if not texts:
            return []

        try:
            from sklearn.feature_extraction.text import TfidfVectorizer  # type: ignore[import-untyped]

            vectorizer = TfidfVectorizer(max_features=EMBED_DIMENSION)
            matrix = vectorizer.fit_transform(texts).toarray()
        except Exception:
            return [_hash_embedding(text, EMBED_DIMENSION) for text in texts]

        vectors: list[list[float]] = []
        for row in matrix:
            current = [float(v) for v in row[:EMBED_DIMENSION]]
            if len(current) < EMBED_DIMENSION:
                current.extend([0.0] * (EMBED_DIMENSION - len(current)))
            vectors.append(current)

        return vectors


def _hash_embedding(text: str, dimension: int) -> list[float]:
    """Deterministic fallback embedding when no model/vectorizer is available."""

    vector = [0.0] * dimension
    tokens = [token for token in text.lower().split() if token]
    if not tokens:
        return vector

    for token in tokens:
        digest = hashlib.sha256(token.encode("utf-8")).hexdigest()
        index = int(digest[:8], 16) % dimension
        sign = 1.0 if int(digest[8:10], 16) % 2 == 0 else -1.0
        vector[index] += sign

    norm = sum(abs(v) for v in vector) or 1.0
    return [v / norm for v in vector]
