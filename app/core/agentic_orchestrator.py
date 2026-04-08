"""ReAct-style agentic orchestrator for adaptive deployment reasoning loops."""

from __future__ import annotations

import json
from typing import Any, Protocol

from app.core.agent_debate import AgentDebate
from app.core.learning_engine import LearningEngine
from app.services.llm_service import call_llm


class ToolProtocol(Protocol):
    async def execute(self, params: dict[str, Any], context: dict[str, Any]) -> dict[str, Any]:
        ...


class AgenticOrchestrator:
    """Reason-Act-Observe loop that adapts strategy from intermediate outcomes."""

    def __init__(self, tools: dict[str, ToolProtocol], max_iterations: int = 10) -> None:
        self.tools = tools
        self.max_iterations = max_iterations
        self.learning = LearningEngine()
        self.debate = AgentDebate()

    async def deploy_project(
        self,
        project_id: int,
        code: bytes | None = None,
        github_url: str | None = None,
    ) -> dict[str, Any]:
        goal = "Analyze code, generate security report, and prepare autonomous deployment plan"
        context: dict[str, Any] = {
            "project_id": project_id,
            "code_available": code is not None,
            "github_url": github_url,
            "iteration": 0,
            "observations": [],
            "actions_taken": [],
            "learnings": [],
            "outcome": "in_progress",
        }

        similar = await self.learning.find_similar_deployments({"raw": "byte_upload"}, limit=10)
        if similar:
            context["similar_cases"] = similar
            context["learned_patterns"] = await self.learning.extract_patterns(similar)

        while context["iteration"] < self.max_iterations:
            thought = await self._reason(goal, context)
            action = str(thought.get("action") or "goal_achieved")

            if action == "goal_achieved":
                context["outcome"] = "success"
                break

            params = thought.get("params") if isinstance(thought.get("params"), dict) else {}
            observation = await self._act(action, params, context)
            context["observations"].append(observation)
            context["actions_taken"].append(
                {
                    "action": action,
                    "reasoning": thought.get("reasoning", ""),
                    "result": observation.get("outcome"),
                }
            )

            if observation.get("lesson_learned"):
                context["learnings"].append(observation["lesson_learned"])

            if observation.get("outcome") == "failure":
                context["last_failure"] = observation
            context["iteration"] += 1

        if context.get("outcome") != "success":
            context["outcome"] = "failed"

        await self.learning.store_deployment_outcome(
            {
                "project_id": project_id,
                "code_profile": context.get("code_profile", {}),
                "platform": context.get("chosen_platform", "unknown"),
                "outcome": context.get("outcome"),
                "duration": context.get("iteration", 0),
                "fixes": context.get("fixes", []),
                "learnings": context.get("learnings", []),
                "agentic_enabled": True,
                "debate_transcript": context.get("debate_transcript", []),
                "cost": context.get("estimated_cost"),
            }
        )
        return context

    async def _reason(self, goal: str, context: dict[str, Any]) -> dict[str, Any]:
        prompt = f"""
        Goal: {goal}
        Iteration: {context.get('iteration')}/{self.max_iterations}
        Last observation: {json.dumps((context.get('observations') or [None])[-1], ensure_ascii=True)}
        Available tools: {list(self.tools.keys())}
        Learned patterns: {json.dumps(context.get('learned_patterns', {}), ensure_ascii=True)}

        Decide the next action as JSON:
        {{
          "reasoning": "your concise reasoning",
          "action": "tool_name or goal_achieved",
          "params": {{"k": "v"}},
          "confidence": 0.0
        }}
        """
        raw = await call_llm(
            [
                {"role": "system", "content": "You are an autonomous deployment planner. Output strict JSON."},
                {"role": "user", "content": prompt},
            ],
            {"task_weight": "heavy", "json_mode": True, "temperature": 0.1, "max_tokens": 800},
        )
        try:
            parsed = json.loads(raw["content"])
            if not isinstance(parsed, dict):
                raise ValueError("reasoning response must be object")
            return parsed
        except Exception:
            # Safe fallback when model output is malformed.
            if not context.get("code_profile"):
                return {
                    "reasoning": "No code profile yet; starting with structural analysis",
                    "action": "analyze_code_structure",
                    "params": {},
                    "confidence": 0.5,
                }
            return {
                "reasoning": "No further mandatory actions detected",
                "action": "goal_achieved",
                "params": {},
                "confidence": 0.5,
            }

    async def _act(self, action: str, params: dict[str, Any], context: dict[str, Any]) -> dict[str, Any]:
        if action == "debate_platform_choice":
            debate = await self.debate.debate_platform_choice(context.get("code_profile", {}), context)
            context["chosen_platform"] = debate["platform"]
            context["debate_transcript"] = debate["debate_transcript"]
            return {
                "action": action,
                "outcome": "success",
                "data": debate,
                "lesson_learned": None,
            }

        tool = self.tools.get(action)
        if tool is None:
            return {
                "action": action,
                "outcome": "failure",
                "data": {"error": f"Unknown tool: {action}"},
                "lesson_learned": f"Tool mapping missing for {action}",
            }

        try:
            result = await tool.execute(params, context)
            if isinstance(result, dict):
                if result.get("code_profile"):
                    context["code_profile"] = result["code_profile"]
                if result.get("estimated_cost") is not None:
                    context["estimated_cost"] = result["estimated_cost"]
                if result.get("fixes"):
                    context["fixes"] = result["fixes"]
                if result.get("platform"):
                    context["chosen_platform"] = result["platform"]

            return {
                "action": action,
                "outcome": "success" if bool(result.get("success", True)) else "failure",
                "data": result,
                "lesson_learned": result.get("lesson") if isinstance(result, dict) else None,
            }
        except Exception as exc:
            return {
                "action": action,
                "outcome": "failure",
                "data": {"error": str(exc)},
                "lesson_learned": f"{action} failed: {exc}",
            }
