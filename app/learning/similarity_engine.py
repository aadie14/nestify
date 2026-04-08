"""Similarity filtering/ranking over stored deployment patterns."""

from __future__ import annotations

from typing import Any


class SimilarityEngine:
    """Applies relevance filters on top of vector similarity results."""

    def rank(self, matches: list[dict[str, Any]], code_profile: dict[str, Any], limit: int = 10) -> list[dict[str, Any]]:
        framework = str(code_profile.get("framework") or "").lower()
        runtime = str(code_profile.get("runtime") or "").lower()

        scored: list[dict[str, Any]] = []
        for item in matches:
            score = float(item.get("score") or 0.0)
            payload = item.get("payload") or {}
            pattern_raw = payload.get("pattern")

            bonus = 0.0
            if isinstance(pattern_raw, str):
                text = pattern_raw.lower()
                if framework and framework in text:
                    bonus += 0.08
                if runtime and runtime in text:
                    bonus += 0.06

            scored.append({**item, "rank_score": round(score + bonus, 4)})

        scored.sort(key=lambda x: x.get("rank_score", 0.0), reverse=True)
        return scored[: max(1, limit)]
