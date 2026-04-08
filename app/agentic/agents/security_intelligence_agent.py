"""Agent 2: Security Intelligence Expert.

Enriches deterministic findings with exploit scenarios and business context.
"""

from __future__ import annotations

from typing import Any

from app.agentic.llm_router import call_agentic_llm


class SecurityIntelligenceExpert:
    """Adds reasoning layer on top of existing SecurityAgent and RiskEngine outputs."""

    def _top_findings(self, report: dict[str, Any], max_items: int = 8) -> list[dict[str, Any]]:
        ordered: list[dict[str, Any]] = []
        for sev in ("critical", "high", "medium"):
            for finding in report.get(sev, []) or []:
                item = dict(finding)
                item["severity"] = sev
                ordered.append(item)
        return ordered[:max_items]

    async def enrich(
        self,
        security_report: dict[str, Any],
        risk_report: dict[str, Any],
        graph_stats: dict[str, Any],
    ) -> dict[str, Any]:
        top_findings = self._top_findings(security_report)
        if not top_findings:
            return {
                "summary": "No high-priority findings requiring business-context enrichment.",
                "prioritized_findings": [],
                "business_impact_summary": "Low immediate risk based on current report.",
            }

        prompt = (
            "You are an application security engineer. For each finding, provide:\n"
            "1) plausible exploit scenario\n"
            "2) business impact\n"
            "3) remediation priority (P0-P3)\n"
            "Return strict JSON with keys: summary, prioritized_findings, business_impact_summary.\n\n"
            f"risk_report={risk_report}\n"
            f"graph_stats={graph_stats}\n"
            f"findings={top_findings}\n"
        )

        try:
            response = await call_agentic_llm(
                [
                    {"role": "system", "content": "You produce strict JSON for security triage."},
                    {"role": "user", "content": prompt},
                ],
                {"json_mode": True, "temperature": 0.1, "max_tokens": 1500, "task_weight": "heavy"},
            )
            import json

            parsed = json.loads(response.get("content", "{}"))
            if isinstance(parsed, dict):
                return {
                    "summary": parsed.get("summary", "Security enrichment completed."),
                    "prioritized_findings": parsed.get("prioritized_findings", []),
                    "business_impact_summary": parsed.get("business_impact_summary", ""),
                }
        except Exception:
            pass

        enriched = []
        for finding in top_findings:
            sev = str(finding.get("severity", "medium")).lower()
            priority = "P2"
            if sev == "critical":
                priority = "P0"
            elif sev == "high":
                priority = "P1"

            enriched.append(
                {
                    "type": finding.get("type", "unknown"),
                    "file": finding.get("file"),
                    "priority": priority,
                    "exploit_scenario": "Attacker reaches vulnerable path via exposed endpoint and abuses insufficient validation.",
                    "business_impact": "Potential service disruption or data exposure if left unresolved.",
                }
            )

        return {
            "summary": "Security enrichment generated using deterministic fallback.",
            "prioritized_findings": enriched,
            "business_impact_summary": "Prioritize externally reachable findings before deployment.",
        }
