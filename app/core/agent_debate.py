"""Multi-agent debate utilities for critical deployment decisions."""

from __future__ import annotations

import json
from typing import Any

from app.services.llm_service import call_llm


class _DebateAgent:
    def __init__(self, name: str, priority: str) -> None:
        self.name = name
        self.priority = priority

    async def propose_solution(self, code_profile: dict[str, Any], context: dict[str, Any]) -> dict[str, Any]:
        prompt = f"""
        You are {self.name} focused on {self.priority}.
        Code profile: {json.dumps(code_profile, ensure_ascii=True)}
        Context: {json.dumps(context, ensure_ascii=True)}

        Propose best deployment platform among: railway, vercel, netlify.
        Return JSON with keys: platform, reasoning, priority.
        """
        raw = await call_llm(
            [
                {"role": "system", "content": "Return strict JSON only."},
                {"role": "user", "content": prompt},
            ],
            {"task_weight": "lite", "json_mode": True, "temperature": 0.1, "max_tokens": 500},
        )
        try:
            parsed = json.loads(raw["content"])
        except json.JSONDecodeError:
            parsed = {}

        platform = str(parsed.get("platform") or context.get("preferred_provider") or "railway").lower()
        return {
            "platform": platform,
            "reasoning": str(parsed.get("reasoning") or f"{self.name} selected {platform}"),
            "priority": self.priority,
        }

    async def challenge_proposals(
        self,
        own_proposal: dict[str, Any],
        other_proposals: list[dict[str, Any]],
        code_profile: dict[str, Any],
    ) -> dict[str, Any]:
        prompt = f"""
        You are {self.name} focused on {self.priority}.
        Own proposal: {json.dumps(own_proposal, ensure_ascii=True)}
        Other proposals: {json.dumps(other_proposals, ensure_ascii=True)}
        Code profile: {json.dumps(code_profile, ensure_ascii=True)}

        Return JSON with keys: objections (list), concessions (list).
        """
        raw = await call_llm(
            [
                {"role": "system", "content": "Return strict JSON only."},
                {"role": "user", "content": prompt},
            ],
            {"task_weight": "lite", "json_mode": True, "temperature": 0.2, "max_tokens": 500},
        )
        try:
            parsed = json.loads(raw["content"])
        except json.JSONDecodeError:
            parsed = {}

        objections = parsed.get("objections") if isinstance(parsed.get("objections"), list) else []
        concessions = parsed.get("concessions") if isinstance(parsed.get("concessions"), list) else []
        return {"objections": objections[:5], "concessions": concessions[:5]}


class AgentDebate:
    """Coordinates proposal/challenge/consensus rounds across specialist agents."""

    def __init__(self) -> None:
        self.participants = [
            _DebateAgent("Cost Agent", "cost"),
            _DebateAgent("Security Agent", "security"),
            _DebateAgent("Platform Agent", "capability"),
        ]

    async def debate_platform_choice(self, code_profile: dict[str, Any], context: dict[str, Any]) -> dict[str, Any]:
        proposals: list[dict[str, Any]] = []
        for agent in self.participants:
            proposal = await agent.propose_solution(code_profile, context)
            proposals.append({"agent": agent.name, **proposal})

        challenges: list[dict[str, Any]] = []
        for index, agent in enumerate(self.participants):
            others = [item for i, item in enumerate(proposals) if i != index]
            challenge = await agent.challenge_proposals(proposals[index], others, code_profile)
            challenges.append({"agent": agent.name, "challenges": challenge["objections"], "concessions": challenge["concessions"]})

        consensus_prompt = f"""
        Proposals: {json.dumps(proposals, ensure_ascii=True)}
        Challenges: {json.dumps(challenges, ensure_ascii=True)}
        Code profile: {json.dumps(code_profile, ensure_ascii=True)}

        Pick best platform. Return JSON with: decision, reasoning, compromises, agreements.
        """
        raw = await call_llm(
            [
                {"role": "system", "content": "You mediate deployment decisions. Return strict JSON."},
                {"role": "user", "content": consensus_prompt},
            ],
            {"task_weight": "heavy", "json_mode": True, "temperature": 0.1, "max_tokens": 800},
        )
        try:
            consensus = json.loads(raw["content"])
        except json.JSONDecodeError:
            fallback = max(proposals, key=lambda item: 1 if item.get("priority") == "security" else 0)
            consensus = {
                "decision": fallback.get("platform", "railway"),
                "reasoning": "Fallback consensus selected based on proposal priorities",
                "compromises": [],
                "agreements": [],
            }

        transcript = [
            {"round": 1, "type": "proposals", "statements": proposals},
            {"round": 2, "type": "challenges", "statements": challenges},
            {"round": 3, "type": "consensus", "decision": consensus},
        ]

        return {
            "platform": str(consensus.get("decision") or "railway").lower(),
            "reasoning": str(consensus.get("reasoning") or "Consensus selected"),
            "debate_transcript": transcript,
            "confidence": self._calculate_confidence(transcript),
        }

    def _calculate_confidence(self, rounds: list[dict[str, Any]]) -> float:
        statements = rounds[0].get("statements", []) if rounds else []
        proposals = {item.get("platform") for item in statements}
        if len(proposals) <= 1:
            return 0.95

        challenge_count = sum(len(item.get("challenges", [])) for item in rounds[1].get("statements", [])) if len(rounds) > 1 else 0
        if challenge_count == 0:
            return 0.9
        if challenge_count < 3:
            return 0.75
        return 0.6
