import unittest
from unittest.mock import patch
from unittest.mock import AsyncMock

from app.agentic.coordinator import AgenticCoordinator
from app.agentic.models import AgenticInsights


class TestAgenticCoordinator(unittest.IsolatedAsyncioTestCase):
    async def test_deployment_planning_populates_cost_and_platform(self):
        coordinator = AgenticCoordinator(project_id=1)
        insights = AgenticInsights(code_profile={"app_type": "backend", "framework": "fastapi", "runtime": "python"})

        coordinator.cost_agent.optimize = AsyncMock(return_value={
            "provider": "railway",
            "recommended": {"config": {"memory_mb": 512}, "monthly_cost_usd": 12.5},
            "comparison_matrix": [],
        })
        with patch("app.agentic.agent_debate.AgentDebate.debate_platform_choice", new=AsyncMock(return_value={
            "chosen_platform": "railway",
            "reasoning": "debate consensus",
            "confidence": 0.91,
            "debate_transcript": [
                {"round": 1, "type": "proposals", "statements": []},
                {"round": 2, "type": "challenges", "statements": []},
                {"round": 3, "type": "consensus", "decision": {"platform": "railway"}},
            ],
            "alternatives_considered": ["railway", "vercel"],
        })):
            updated = await coordinator.run_deployment_planning_phase(insights=insights, preferred_provider=None)

        self.assertIsNotNone(updated.cost_optimization)
        self.assertEqual(updated.cost_optimization["provider"], "railway")
        self.assertIsNotNone(updated.deployment_intelligence)
        self.assertEqual(updated.deployment_intelligence["chosen_platform"], "railway")
        self.assertEqual(len(updated.deployment_intelligence["debate_transcript"]), 3)

    async def test_execute_self_healing_sets_report(self):
        coordinator = AgenticCoordinator(project_id=2)
        insights = AgenticInsights(code_profile={"app_type": "backend"})

        coordinator.self_heal_agent.deploy_with_self_heal = AsyncMock(return_value={
            "status": "success",
            "attempts": [{"attempt": 1, "provider": "railway", "status": "success"}],
            "result": {"provider": "railway", "deployment_url": "https://example.test"},
        })

        result = await coordinator.execute_self_healing_deployment(
            project_name="demo",
            files=[{"name": "main.py", "content": "print('x')"}],
            stack_info={"runtime": "python", "framework": "fastapi"},
            preferred_provider="railway",
            github_url="https://github.com/acme/demo",
            env_template="",
            insights=insights,
        )

        self.assertEqual(result["status"], "success")
        self.assertIsNotNone(insights.self_healing_report)
        self.assertEqual(insights.self_healing_report["status"], "success")


if __name__ == "__main__":
    unittest.main()
