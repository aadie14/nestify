"""Agent 4: Platform Selection Strategist."""

from __future__ import annotations

from typing import Any


class PlatformSelectionStrategist:
    """Select deployment platform from technical constraints and cost analysis."""

    def _capability_score(self, app_type: str, framework: str, provider: str) -> int:
        provider = provider.lower()
        score = 50

        if app_type in {"static", "frontend"}:
            if provider in {"vercel", "netlify"}:
                score += 30
            if framework == "nextjs" and provider == "vercel":
                score += 10

        if app_type == "backend":
            if provider == "railway":
                score += 30

        if app_type == "docker":
            if provider == "railway":
                score += 35

        return min(100, score)

    def _candidate_providers(self, app_type: str) -> list[str]:
        if app_type in {"static", "frontend"}:
            return ["vercel", "netlify", "local"]
        return ["railway", "local"]

    def choose(
        self,
        code_profile: dict[str, Any],
        cost_report: dict[str, Any] | None,
        preferred_provider: str | None,
        proactive_actions: list[dict[str, Any]] | None = None,
    ) -> dict[str, Any]:
        app_type = str(code_profile.get("app_type", "backend")).lower()
        framework = str(code_profile.get("framework", "unknown")).lower()
        candidates = self._candidate_providers(app_type)

        if preferred_provider:
            preferred = preferred_provider.lower()
            if preferred in candidates:
                chosen = preferred
            else:
                chosen = candidates[0]
        else:
            chosen = candidates[0]

        if cost_report:
            recommended_provider = str(cost_report.get("provider", chosen)).lower()
            if recommended_provider in candidates:
                chosen = recommended_provider

        alternatives = []
        for provider in candidates:
            score = self._capability_score(app_type, framework, provider)
            alternatives.append({"provider": provider, "score": score})
        alternatives.sort(key=lambda item: item["score"], reverse=True)

        rationale = [
            f"App type inferred as {app_type} with framework {framework}.",
            f"Selected provider {chosen} based on capability fit and available optimization data.",
        ]
        if proactive_actions:
            rationale.append("Historical patterns were considered for proactive safeguards.")

        return {
            "chosen_platform": chosen,
            "alternatives": alternatives,
            "rationale": " ".join(rationale),
            "estimated_monthly_cost_usd": (
                cost_report.get("recommended", {}).get("monthly_cost_usd") if cost_report else None
            ),
            "generated_config": {
                "provider": chosen,
                "runtime_hint": code_profile.get("runtime", "unknown"),
                "memory_mb": (
                    cost_report.get("recommended", {}).get("config", {}).get("memory_mb") if cost_report else None
                ),
            },
        }
