"""Multi-agent debate system for collaborative platform decisions."""

from __future__ import annotations

import json
from collections import Counter
from typing import Any

from app.agentic.llm_router import call_agentic_llm

_SUPPORTED_DEPLOYMENT_PLATFORMS = {"railway", "vercel", "netlify", "gcp_cloud_run"}


def _normalize_platform(platform: str | None, fallback: str = "railway") -> str:
    normalized = str(platform or "").strip().lower()
    return normalized if normalized in _SUPPORTED_DEPLOYMENT_PLATFORMS else fallback


def _safe_json_object(raw_content: str) -> dict[str, Any]:
    """Parse model output into an object with fence handling and safe fallback."""
    cleaned = raw_content.strip().replace("```json", "").replace("```", "").strip()
    try:
        parsed = json.loads(cleaned)
        return parsed if isinstance(parsed, dict) else {}
    except Exception:
        return {}


class AgentDebate:
    """Facilitates proposal, challenge, and consensus rounds across agents."""

    async def debate_platform_choice(
        self,
        code_profile: dict[str, Any],
        cost_analysis: dict[str, Any],
        similar_deployments: list[dict[str, Any]],
    ) -> dict[str, Any]:
        proposals = await self._round_1_proposals(code_profile, cost_analysis, similar_deployments)
        challenges = await self._round_2_challenges(proposals, code_profile)
        consensus = await self._round_3_consensus(proposals, challenges, code_profile)

        transcript = [
            {"round": 1, "type": "proposals", "statements": proposals},
            {"round": 2, "type": "challenges", "statements": challenges},
            {"round": 3, "type": "consensus", "decision": consensus},
        ]

        return {
            "chosen_platform": _normalize_platform(consensus.get("platform"), "railway"),
            "reasoning": consensus.get("reasoning", "Consensus based on specialist debate."),
            "confidence": float(consensus.get("confidence", 0.7)),
            "debate_transcript": transcript,
            "alternatives_considered": [_normalize_platform(item.get("platform"), "railway") for item in proposals],
        }

    async def _round_1_proposals(
        self,
        code_profile: dict[str, Any],
        cost_analysis: dict[str, Any],
        similar_deployments: list[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        prompts = [
            (
                "cost_agent",
                f"""
You are the Cost Optimization Agent. Prioritize monthly cost and avoid over-provisioning.
Code Profile: {json.dumps(code_profile, ensure_ascii=True)}
Cost Analysis: {json.dumps(cost_analysis, ensure_ascii=True)}
Respond in JSON with keys: platform, reasoning, priority, estimated_monthly_cost.
""",
            ),
            (
                "security_agent",
                f"""
You are the Security Agent. Prioritize secure defaults and reliability.
Code Profile: {json.dumps(code_profile, ensure_ascii=True)}
Respond in JSON with keys: platform, reasoning, priority, security_concerns.
""",
            ),
            (
                "platform_agent",
                f"""
You are the Platform Selection Agent. Prioritize technical fit and historical outcomes.
Code Profile: {json.dumps(code_profile, ensure_ascii=True)}
Similar Deployments: {json.dumps(similar_deployments[:5], ensure_ascii=True)}
Respond in JSON with keys: platform, reasoning, priority, historical_success_rate.
""",
            ),
        ]

        proposals: list[dict[str, Any]] = []
        for agent_name, prompt in prompts:
            try:
                result = await call_agentic_llm(
                    [{"role": "user", "content": prompt}],
                    {"temperature": 0.3, "max_tokens": 350, "task_weight": "heavy"},
                )
                proposal = _safe_json_object(str(result.get("content") or "{}"))
            except Exception:
                proposal = {}

            fallback_platform = _normalize_platform(str(cost_analysis.get("provider") or "railway"), "railway")
            proposals.append(
                {
                    "agent": agent_name,
                    "platform": _normalize_platform(str(proposal.get("platform") or fallback_platform), fallback_platform),
                    "reasoning": str(proposal.get("reasoning") or "fallback recommendation"),
                    "priority": str(proposal.get("priority") or agent_name.replace("_agent", "")),
                    "estimated_monthly_cost": proposal.get("estimated_monthly_cost"),
                    "historical_success_rate": proposal.get("historical_success_rate"),
                }
            )

        return proposals

    async def _round_2_challenges(
        self,
        proposals: list[dict[str, Any]],
        code_profile: dict[str, Any],
    ) -> list[dict[str, Any]]:
        challenges: list[dict[str, Any]] = []

        for idx, proposal in enumerate(proposals):
            others = [item for item_idx, item in enumerate(proposals) if item_idx != idx]
            prompt = f"""
You are {proposal.get('agent', 'an agent')}.
Your proposal: {json.dumps(proposal, ensure_ascii=True)}
Other proposals: {json.dumps(others, ensure_ascii=True)}
Code profile: {json.dumps(code_profile, ensure_ascii=True)}
Respond in JSON with keys: objections, deal_breakers, concessions.
"""

            try:
                result = await call_agentic_llm(
                    [{"role": "user", "content": prompt}],
                    {"temperature": 0.35, "max_tokens": 350, "task_weight": "heavy"},
                )
                parsed = _safe_json_object(str(result.get("content") or "{}"))
            except Exception:
                parsed = {}

            challenges.append(
                {
                    "agent": proposal.get("agent"),
                    "objections": parsed.get("objections") if isinstance(parsed.get("objections"), list) else [],
                    "deal_breakers": parsed.get("deal_breakers") if isinstance(parsed.get("deal_breakers"), list) else [],
                    "concessions": parsed.get("concessions") if isinstance(parsed.get("concessions"), list) else [],
                }
            )

        return challenges

    async def _round_3_consensus(
        self,
        proposals: list[dict[str, Any]],
        challenges: list[dict[str, Any]],
        code_profile: dict[str, Any],
    ) -> dict[str, Any]:
        prompt = f"""
You are a neutral mediator.
PROPOSALS: {json.dumps(proposals, ensure_ascii=True)}
CHALLENGES: {json.dumps(challenges, ensure_ascii=True)}
CODE PROFILE: {json.dumps(code_profile, ensure_ascii=True)}
Respond in JSON with keys: platform, reasoning, confidence, tradeoffs.
"""

        try:
            result = await call_agentic_llm(
                [{"role": "user", "content": prompt}],
                {"temperature": 0.2, "max_tokens": 500, "task_weight": "heavy"},
            )
            consensus = _safe_json_object(str(result.get("content") or "{}"))
        except Exception:
            consensus = {}

        if not consensus.get("platform"):
            vote = Counter(str(item.get("platform") or "railway") for item in proposals)
            platform = _normalize_platform(vote.most_common(1)[0][0] if vote else "railway", "railway")
            return {
                "platform": platform,
                "reasoning": "Consensus based on majority vote fallback.",
                "confidence": 0.7,
                "tradeoffs": [],
            }

        return {
            "platform": _normalize_platform(consensus.get("platform"), "railway"),
            "reasoning": str(consensus.get("reasoning") or "Consensus selected."),
            "confidence": float(consensus.get("confidence") or 0.7),
            "tradeoffs": consensus.get("tradeoffs") if isinstance(consensus.get("tradeoffs"), list) else [],
        }