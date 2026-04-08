import unittest
from unittest.mock import patch

from app.runtime.provider_metrics import ProviderMetricsCollector, _find_numeric_by_keys


class TestProviderMetricParsing(unittest.TestCase):
    def test_find_numeric_by_keys_nested(self):
        payload = {
            "outer": {
                "nodes": [
                    {"label": "a"},
                    {"cpuPercent": "42.5", "memoryUsageMb": 256},
                ]
            }
        }
        cpu = _find_numeric_by_keys(payload, {"cpupercent"})
        mem = _find_numeric_by_keys(payload, {"memoryusagemb"})
        self.assertEqual(cpu, 42.5)
        self.assertEqual(mem, 256.0)


class TestProviderMetricsCollector(unittest.IsolatedAsyncioTestCase):
    async def test_collect_railway_unavailable_without_project_id(self):
        collector = ProviderMetricsCollector()
        with patch("app.runtime.provider_metrics.settings.railway_api_key", "token"):
            result = await collector.collect("railway", details={})
        self.assertEqual(result["provider"], "railway")
        self.assertEqual(result["status"], "unavailable")

    async def test_collect_unsupported_provider(self):
        collector = ProviderMetricsCollector()
        result = await collector.collect("vercel", details={})
        self.assertEqual(result["status"], "unsupported")


if __name__ == "__main__":
    unittest.main()
