"""Extract high-level recommendations from similar deployment patterns."""

from __future__ import annotations

from collections import Counter
from typing import Any


class InsightExtractor:
    """Deterministic insight extractor for transparent recommendations."""

    def extract_insights(self, patterns: list[dict[str, Any]]) -> dict[str, Any]:
        if not patterns:
            return {
                "summary": "No similar historical deployment patterns were found.",
                "recommendations": [],
            }

        outcome_counter: Counter[str] = Counter()
        platform_counter: Counter[str] = Counter()

        for item in patterns:
            payload = item.get("payload") or {}
            outcome = str(payload.get("outcome") or "unknown").lower()
            outcome_counter[outcome] += 1

            raw_pattern = str(payload.get("pattern") or "").lower()
            for platform in ("railway", "vercel", "netlify"):
                if platform in raw_pattern:
                    platform_counter[platform] += 1

        top_outcome = outcome_counter.most_common(1)[0][0] if outcome_counter else "unknown"
        top_platforms = [name for name, _ in platform_counter.most_common(2)]

        recommendations = []
        if top_platforms:
            recommendations.append(f"Prioritize platform shortlist: {', '.join(top_platforms)}")
        if top_outcome in {"failed", "error"}:
            recommendations.append("Enable conservative resource allocation and self-healing retries")
        else:
            recommendations.append("Use recommended minimal SLA-safe resource tier to reduce cost")

        return {
            "summary": f"Analyzed {len(patterns)} similar patterns; dominant outcome: {top_outcome}.",
            "top_platforms": top_platforms,
            "recommendations": recommendations,
        }
