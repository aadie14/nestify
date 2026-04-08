import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from app.core.execution_engine import ExecutionEngine
from app.database import create_project, init_db


class _DummyDeployResult:
    def __init__(self, *, provider: str = "railway", url: str = "https://example.live") -> None:
        self.provider = provider
        self.deployment_url = url
        self.status = "success"
        self.details = {"id": "dep_1"}
        self.app_kind = "backend"


class _DummyFixResult:
    applied = []
    manual_review = []
    env_vars_detected = []
    simulation_blocked = []


class TestExecutionEngine(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        init_db()

    async def test_run_success_updates_execution_state(self):
        project_id = create_project(
            name="engine-success",
            input_type="github",
            source_payload={"github_url": "https://github.com/acme/demo"},
            preferred_provider="railway",
        )
        engine = ExecutionEngine(project_id)

        scan = SimpleNamespace(
            report={"critical": [], "high": [], "medium": [], "info": []},
            score=96,
            metadata={"framework": "fastapi", "runtime": "python"},
            risk_report=SimpleNamespace(to_dict=lambda: {"overall_level": "low"}),
            graph=SimpleNamespace(),
        )

        parsed_input = {
            "github_url": "https://github.com/acme/demo",
            "files": [{"name": "main.py", "content": "print('ok')"}],
        }

        with patch("app.core.execution_engine.SecurityAgent.scan", new=AsyncMock(return_value=scan)), patch(
            "app.core.execution_engine.AgenticCoordinator.run_analyzing_phase",
            new=AsyncMock(side_effect=lambda files, graph, insights: self._with_profile(insights)),
        ), patch(
            "app.core.execution_engine.AgenticCoordinator.run_scanning_completion_phase",
            new=AsyncMock(side_effect=lambda **kwargs: kwargs["insights"]),
        ), patch(
            "app.core.execution_engine.AgenticCoordinator.generate_security_pdf",
            new=AsyncMock(return_value="app/outputs/reports/mock.pdf"),
        ), patch(
            "app.core.execution_engine.AgenticCoordinator.to_dict",
            return_value={},
        ), patch(
            "app.core.execution_engine.CostOptimizationSpecialist.optimize",
            new=AsyncMock(return_value={"provider": "railway", "recommended": {"monthly_cost_usd": 12.0}}),
        ), patch(
            "app.core.execution_engine.AgentDebate.debate_platform_choice",
            new=AsyncMock(return_value={"chosen_platform": "railway", "confidence": 0.9, "reasoning": "fit", "debate_transcript": []}),
        ), patch(
            "app.core.execution_engine.FixAgent.generate_and_apply",
            new=AsyncMock(return_value=_DummyFixResult()),
        ), patch(
            "app.core.execution_engine.DeploymentAgent.deploy",
            new=AsyncMock(return_value=_DummyDeployResult()),
        ), patch(
            "app.core.execution_engine.ExecutionEngine._run_execution_test",
            new=AsyncMock(return_value={"success": True}),
        ), patch(
            "app.core.execution_engine.ExecutionEngine._verify_live_url",
            new=AsyncMock(return_value=(True, {"checks": []})),
        ), patch(
            "app.core.execution_engine.ExecutionEngine._collect_monitoring",
            new=AsyncMock(return_value={"runtime": {"anomalies": []}}),
        ):
            result = await engine.run(parsed_input)

        self.assertEqual(result.status, "live")
        self.assertEqual(result.execution_state.get("status"), "success")
        self.assertEqual(result.execution_state.get("deployment_url"), "https://example.live")
        self.assertEqual(result.pipeline_states.get("retry_loop"), "done")

    async def test_run_retries_three_times_on_deploy_failure(self):
        project_id = create_project(
            name="engine-retry",
            input_type="github",
            source_payload={"github_url": "https://github.com/acme/demo"},
            preferred_provider="railway",
        )
        engine = ExecutionEngine(project_id)

        scan = SimpleNamespace(
            report={"critical": [], "high": [], "medium": [], "info": []},
            score=81,
            metadata={"framework": "fastapi", "runtime": "python"},
            risk_report=SimpleNamespace(to_dict=lambda: {"overall_level": "medium"}),
            graph=SimpleNamespace(),
        )

        parsed_input = {
            "github_url": "https://github.com/acme/demo",
            "files": [{"name": "main.py", "content": "print('ok')"}],
        }

        with patch("app.core.execution_engine.SecurityAgent.scan", new=AsyncMock(return_value=scan)), patch(
            "app.core.execution_engine.AgenticCoordinator.run_analyzing_phase",
            new=AsyncMock(side_effect=lambda files, graph, insights: self._with_profile(insights)),
        ), patch(
            "app.core.execution_engine.AgenticCoordinator.run_scanning_completion_phase",
            new=AsyncMock(side_effect=lambda **kwargs: kwargs["insights"]),
        ), patch(
            "app.core.execution_engine.AgenticCoordinator.generate_security_pdf",
            new=AsyncMock(return_value="app/outputs/reports/mock.pdf"),
        ), patch(
            "app.core.execution_engine.AgenticCoordinator.to_dict",
            return_value={},
        ), patch(
            "app.core.execution_engine.CostOptimizationSpecialist.optimize",
            new=AsyncMock(return_value={"provider": "railway", "recommended": {"monthly_cost_usd": 12.0}}),
        ), patch(
            "app.core.execution_engine.AgentDebate.debate_platform_choice",
            new=AsyncMock(return_value={"chosen_platform": "railway", "confidence": 0.9, "reasoning": "fit", "debate_transcript": []}),
        ), patch(
            "app.core.execution_engine.FixAgent.generate_and_apply",
            new=AsyncMock(return_value=_DummyFixResult()),
        ), patch(
            "app.core.execution_engine.DeploymentAgent.deploy",
            new=AsyncMock(side_effect=[RuntimeError("attempt-1"), RuntimeError("attempt-2"), RuntimeError("attempt-3")]),
        ), patch(
            "app.core.execution_engine.ExecutionEngine._run_execution_test",
            new=AsyncMock(return_value={"success": True}),
        ):
            result = await engine.run(parsed_input)

        self.assertEqual(result.status, "failed")
        self.assertEqual(result.execution_state.get("status"), "failed")
        self.assertEqual(result.execution_state.get("attempts"), 3)
        self.assertEqual(len(result.execution_state.get("errors", [])), 4)

    @staticmethod
    def _with_profile(insights):
        insights.code_profile = {
            "app_type": "backend",
            "framework": "fastapi",
            "runtime": "python",
            "resource_prediction": {"memory_mb": 512},
            "deployment_complexity_score": 42,
            "dependencies": ["fastapi", "uvicorn"],
        }
        return insights


if __name__ == "__main__":
    unittest.main()
