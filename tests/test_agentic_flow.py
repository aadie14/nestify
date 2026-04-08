import unittest
from unittest.mock import AsyncMock, patch

from app.agentic.coordinator import AgenticCoordinator
from app.agentic.models import AgenticInsights


class TestAgenticFlow(unittest.IsolatedAsyncioTestCase):
    async def test_complete_agentic_flow(self):
        coordinator = AgenticCoordinator(project_id=999)
        insights = AgenticInsights(
            code_profile={"framework": "fastapi", "runtime": "python", "dependencies": ["fastapi", "uvicorn"]}
        )

        with patch(
            "app.learning.pattern_store.PatternStore.find_similar_deployments",
            new=AsyncMock(return_value=[
                {
                    "similarity_score": 0.92,
                    "framework": "fastapi",
                    "runtime": "python",
                    "platform_choice": "railway",
                    "success": True,
                    "fixes_applied": ["set_port"],
                    "deployment_time_seconds": 38,
                    "cost_per_month": 3.2,
                }
            ]),
        ), patch(
            "app.learning.pattern_store.PatternStore.extract_actionable_patterns",
            new=AsyncMock(return_value={"recommendations": [{"type": "platform_choice", "action": "use_railway"}]}),
        ), patch(
            "app.agentic.agent_debate.AgentDebate.debate_platform_choice",
            new=AsyncMock(return_value={
                "chosen_platform": "railway",
                "reasoning": "Most reliable for backend app profile.",
                "confidence": 0.9,
                "debate_transcript": [
                    {"round": 1, "type": "proposals", "statements": []},
                    {"round": 2, "type": "challenges", "statements": []},
                    {"round": 3, "type": "consensus", "decision": {"platform": "railway"}},
                ],
                "alternatives_considered": ["railway", "vercel"],
            }),
        ):
            coordinator.cost_agent.optimize = AsyncMock(
                return_value={
                    "provider": "railway",
                    "recommended": {
                        "config": {"memory_mb": 512, "cpu": 0.5, "label": "recommended"},
                        "monthly_cost_usd": 3.2,
                        "benchmark": {"p95_ms": 160, "success_rate": 0.999, "meets_sla": True},
                    },
                    "comparison_matrix": [
                        {
                            "config": {"memory_mb": 512, "cpu": 0.5, "label": "recommended"},
                            "benchmark": {"p95_ms": 160, "success_rate": 0.999, "meets_sla": True},
                            "monthly_cost_usd": 3.2,
                        }
                    ],
                    "method": "synthetic_predeploy",
                }
            )

            insights = await coordinator.run_deploying_entry_phase(insights)
            self.assertTrue(isinstance(insights.similar_deployments, list))

            insights = await coordinator.run_deployment_planning_phase(insights, preferred_provider=None)
            self.assertEqual(insights.deployment_intelligence.get("chosen_platform"), "railway")
            transcript = insights.deployment_intelligence.get("debate_transcript")
            self.assertEqual(len(transcript), 3)
            self.assertEqual(transcript[0]["type"], "proposals")
            self.assertEqual(transcript[1]["type"], "challenges")
            self.assertEqual(transcript[2]["type"], "consensus")


if __name__ == "__main__":
    unittest.main()
