import unittest
from unittest.mock import AsyncMock, patch

from app.agentic.agents.self_healing_agent import SelfHealingDeploymentEngineer


class TestSelfHealingDeploymentEngineer(unittest.IsolatedAsyncioTestCase):
    async def test_retries_and_recovers_after_env_fix(self):
        agent = SelfHealingDeploymentEngineer()

        class DummyResult:
            def __init__(self):
                self.provider = "railway"
                self.deployment_url = "https://live.example"
                self.status = "success"
                self.details = {"id": "dep_1"}
                self.app_kind = "backend"

        with patch("app.agentic.agents.self_healing_agent.DeploymentAgent") as mocked_deployment:
            instance = mocked_deployment.return_value
            instance.deploy = AsyncMock(side_effect=[
                RuntimeError("Missing environment variable DATABASE_URL"),
                DummyResult(),
            ])

            result = await agent.deploy_with_self_heal(
                project_id=99,
                project_name="demo",
                files=[{"name": "app.py", "content": "print('ok')"}],
                stack_info={"runtime": "python", "framework": "fastapi"},
                preferred_provider="railway",
                github_url="https://github.com/acme/demo",
                env_template="",
                app_type="backend",
                max_attempts=3,
            )

        self.assertEqual(result["status"], "success")
        self.assertEqual(len(result["attempts"]), 2)
        self.assertEqual(result["attempts"][0]["fix_applied"], "inject_safe_env_defaults")
        self.assertEqual(result["result"]["provider"], "railway")

    async def test_returns_escalation_when_all_attempts_fail(self):
        agent = SelfHealingDeploymentEngineer()

        with patch("app.agentic.agents.self_healing_agent.DeploymentAgent") as mocked_deployment:
            instance = mocked_deployment.return_value
            instance.deploy = AsyncMock(side_effect=RuntimeError("Provider API timeout"))

            result = await agent.deploy_with_self_heal(
                project_id=100,
                project_name="demo",
                files=[{"name": "app.py", "content": "print('ok')"}],
                stack_info={"runtime": "python", "framework": "fastapi"},
                preferred_provider="railway",
                github_url="https://github.com/acme/demo",
                env_template="",
                app_type="backend",
                max_attempts=2,
            )

        self.assertEqual(result["status"], "failed")
        self.assertTrue(result["escalation"]["recommended"])
        self.assertEqual(len(result["attempts"]), 2)


if __name__ == "__main__":
    unittest.main()
