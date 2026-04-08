import json
import unittest
from unittest.mock import AsyncMock, patch

from app.agentic.tools.load_tester_tool import LoadTesterTool
from app.core.config import settings


class _DummyResponse:
    def __init__(self, status_code: int):
        self.status_code = status_code


class _DummyClient:
    def __init__(self, sequence):
        self._sequence = list(sequence)

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        return False

    async def get(self, _url: str):
        if not self._sequence:
            return _DummyResponse(200)
        item = self._sequence.pop(0)
        if isinstance(item, Exception):
            raise item
        return _DummyResponse(item)


class TestLoadTesterTool(unittest.IsolatedAsyncioTestCase):
    async def test_rejects_localhost_targets(self):
        tool = LoadTesterTool()
        payload = json.dumps({"target_url": "http://localhost:8000", "duration_seconds": 1, "rps": 1})

        result = json.loads(await tool._arun(payload))

        self.assertFalse(result["ok"])
        self.assertIn("localhost", result["error"])

    async def test_returns_disabled_when_feature_flag_off(self):
        tool = LoadTesterTool()
        payload = json.dumps({"target_url": "https://example.com", "duration_seconds": 1, "rps": 1})

        with patch.object(settings, "load_test_enabled", False):
            result = json.loads(await tool._arun(payload))

        self.assertFalse(result["ok"])
        self.assertIn("disabled", result["error"])

    async def test_collects_percentiles_and_success_rate_with_request_cap(self):
        tool = LoadTesterTool()
        payload = json.dumps(
            {
                "target_url": "https://example.com/health",
                "duration_seconds": 1,
                "rps": 1,
                "max_requests": 4,
            }
        )

        sequence = [200, 500, RuntimeError("timeout"), 200]

        with patch.object(settings, "load_test_enabled", True), patch(
            "app.agentic.tools.load_tester_tool.httpx.AsyncClient",
            return_value=_DummyClient(sequence),
        ), patch("app.agentic.tools.load_tester_tool.asyncio.sleep", new=AsyncMock(return_value=None)):
            result = json.loads(await tool._arun(payload))

        self.assertTrue(result["ok"])
        self.assertEqual(result["sample_count"], 4)
        self.assertEqual(result["worker_count"], 1)
        self.assertAlmostEqual(result["success_rate"], 0.5, places=4)
        self.assertGreaterEqual(result["p50_ms"], 0.0)
        self.assertGreaterEqual(result["p95_ms"], 0.0)
        self.assertGreaterEqual(result["p99_ms"], 0.0)


if __name__ == "__main__":
    unittest.main()
