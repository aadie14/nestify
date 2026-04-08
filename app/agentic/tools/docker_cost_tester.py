"""Docker-backed cost benchmarking for deployment planning.

Runs lightweight HTTP probes against containers launched with bounded resources.
Falls back gracefully when Docker or image build/run is unavailable.
"""

from __future__ import annotations

import asyncio
import time
import uuid
from pathlib import Path
from typing import Any

import httpx


class DockerCostTester:
    """Test candidate runtime tiers with Docker and pick the cheapest SLA-safe option."""

    _CANDIDATES = [
        {"memory": "256m", "memory_mb": 256, "cpu_quota": 25000, "cpu": 0.25, "label": "minimal"},
        {"memory": "512m", "memory_mb": 512, "cpu_quota": 50000, "cpu": 0.5, "label": "recommended"},
        {"memory": "1g", "memory_mb": 1024, "cpu_quota": 100000, "cpu": 1.0, "label": "generous"},
    ]

    def __init__(self) -> None:
        self.docker_client = self._load_client()

    @property
    def is_available(self) -> bool:
        return self.docker_client is not None

    def _load_client(self) -> Any | None:
        try:
            import docker  # type: ignore[import-untyped]

            client = docker.from_env()
            client.ping()
            return client
        except Exception:
            return None

    async def test_configs(self, project_path: str, app_type: str, provider: str) -> dict[str, Any]:
        if not self.docker_client:
            return self._fallback(provider=provider, reason="Docker unavailable")

        build_path = self._resolve_build_path(project_path)
        if build_path is None:
            return self._fallback(provider=provider, reason="No buildable project path found")

        results: list[dict[str, Any]] = []
        for config in self._CANDIDATES:
            try:
                probe = await self._test_single_config(build_path=build_path, config=config, app_type=app_type)
                monthly_cost = self._estimate_cost(provider, int(config["memory_mb"]))
                results.append(
                    {
                        "config": {"memory_mb": config["memory_mb"], "cpu": config["cpu"], "label": config["label"]},
                        "benchmark": probe,
                        "monthly_cost_usd": monthly_cost,
                    }
                )
            except Exception as exc:
                results.append(
                    {
                        "config": {"memory_mb": config["memory_mb"], "cpu": config["cpu"], "label": config["label"]},
                        "benchmark": {
                            "p50_ms": 0.0,
                            "p95_ms": 99999.0,
                            "p99_ms": 99999.0,
                            "success_rate": 0.0,
                            "meets_sla": False,
                            "error": str(exc),
                        },
                        "monthly_cost_usd": self._estimate_cost(provider, int(config["memory_mb"])),
                    }
                )

        valid = [item for item in results if item["benchmark"].get("meets_sla")]
        if valid:
            recommended = sorted(valid, key=lambda item: (item["config"]["memory_mb"], item["monthly_cost_usd"]))[0]
        else:
            recommended = sorted(results, key=lambda item: item["benchmark"].get("p95_ms", 99999.0))[0]

        return {
            "method": "docker_load_testing",
            "tested": True,
            "comparison_matrix": results,
            "recommended": recommended,
            "sla": {"p95_ms_lt": 500, "success_rate_gte": 0.99},
            "note": "Docker benchmarks executed with bounded local load",
        }

    async def _test_single_config(self, build_path: Path, config: dict[str, Any], app_type: str) -> dict[str, Any]:
        image_tag = f"nestify-cost-{config['label']}-{uuid.uuid4().hex[:8]}"
        image = await asyncio.to_thread(self._build_image, build_path, image_tag)
        container = await asyncio.to_thread(self._run_container, image.id, config, app_type)
        try:
            host_port = await self._wait_for_container_port(container)
            target_url = f"http://127.0.0.1:{host_port}"
            await self._wait_until_ready(target_url)
            metrics = await self._send_load(target_url=target_url, rps=8, duration=15)
            stats = await asyncio.to_thread(container.stats, False)
            memory_used_bytes = (
                ((stats or {}).get("memory_stats") or {}).get("usage")
                or 0
            )
            memory_used_mb = round(memory_used_bytes / 1024 / 1024, 2)

            return {
                **metrics,
                "memory_used_mb": memory_used_mb,
                "memory_allocated_mb": int(config["memory_mb"]),
                "memory_utilization": round((memory_used_mb / max(1.0, float(config["memory_mb"]))) * 100, 1),
                "meets_sla": metrics.get("p95_ms", 99999.0) <= 500 and metrics.get("success_rate", 0.0) >= 0.99,
            }
        finally:
            await asyncio.to_thread(self._cleanup_container, container)
            await asyncio.to_thread(self._cleanup_image, image_tag)

    def _build_image(self, build_path: Path, image_tag: str):
        image, _logs = self.docker_client.images.build(path=str(build_path), tag=image_tag, rm=True)
        return image

    def _run_container(self, image_id: str, config: dict[str, Any], app_type: str):
        env = {"PORT": "8000"}
        if app_type.lower() == "backend":
            env["HOST"] = "0.0.0.0"

        return self.docker_client.containers.run(
            image=image_id,
            detach=True,
            mem_limit=config["memory"],
            cpu_period=100000,
            cpu_quota=int(config["cpu_quota"]),
            ports={"8000/tcp": None},
            environment=env,
        )

    async def _wait_for_container_port(self, container: Any, timeout: float = 20.0) -> str:
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            await asyncio.to_thread(container.reload)
            ports = (((container.attrs or {}).get("NetworkSettings") or {}).get("Ports") or {})
            binding = ports.get("8000/tcp") or []
            if binding and isinstance(binding, list) and binding[0].get("HostPort"):
                return str(binding[0]["HostPort"])
            await asyncio.sleep(0.5)
        raise RuntimeError("Container did not expose port 8000 in time")

    async def _wait_until_ready(self, base_url: str, timeout: float = 20.0) -> None:
        probes = ["/health", "/api/health", "/", "/docs"]
        deadline = time.monotonic() + timeout
        async with httpx.AsyncClient(timeout=2.5, follow_redirects=True) as client:
            while time.monotonic() < deadline:
                for suffix in probes:
                    try:
                        response = await client.get(f"{base_url}{suffix}")
                        if response.status_code < 500:
                            return
                    except Exception:
                        continue
                await asyncio.sleep(0.5)
        raise RuntimeError("Container did not become ready in time")

    async def _send_load(self, target_url: str, rps: int, duration: int) -> dict[str, Any]:
        latencies: list[float] = []
        errors = 0
        total = 0
        interval = max(0.01, 1.0 / max(1, rps))
        deadline = time.monotonic() + max(1, duration)

        async with httpx.AsyncClient(timeout=5.0, follow_redirects=True) as client:
            while time.monotonic() < deadline:
                start = time.perf_counter()
                try:
                    response = await client.get(target_url)
                    if response.status_code >= 400:
                        errors += 1
                except Exception:
                    errors += 1
                finally:
                    total += 1
                    latencies.append((time.perf_counter() - start) * 1000.0)
                await asyncio.sleep(interval)

        if not latencies:
            return {"p50_ms": 0.0, "p95_ms": 0.0, "p99_ms": 0.0, "success_rate": 0.0, "sample_count": 0}

        latencies.sort()
        p50 = latencies[int(0.50 * (len(latencies) - 1))]
        p95 = latencies[int(0.95 * (len(latencies) - 1))]
        p99 = latencies[int(0.99 * (len(latencies) - 1))]
        success_rate = max(0.0, 1.0 - (errors / max(1, total)))

        return {
            "p50_ms": round(p50, 2),
            "p95_ms": round(p95, 2),
            "p99_ms": round(p99, 2),
            "success_rate": round(success_rate, 4),
            "sample_count": total,
            "error_rate": round(1.0 - success_rate, 4),
        }

    def _cleanup_container(self, container: Any) -> None:
        try:
            container.stop(timeout=5)
        except Exception:
            pass
        try:
            container.remove(force=True)
        except Exception:
            pass

    def _cleanup_image(self, image_tag: str) -> None:
        try:
            self.docker_client.images.remove(image=image_tag, force=True)
        except Exception:
            pass

    def _resolve_build_path(self, project_path: str) -> Path | None:
        root = Path(project_path)
        candidates = [root, root / "source"]
        for candidate in candidates:
            if not candidate.exists() or not candidate.is_dir():
                continue
            dockerfile = candidate / "Dockerfile"
            if dockerfile.exists():
                return candidate
        for candidate in candidates:
            if candidate.exists() and candidate.is_dir():
                return candidate
        return None

    def _fallback(self, provider: str, reason: str) -> dict[str, Any]:
        monthly = self._estimate_cost(provider, 512)
        recommended = {
            "config": {"memory_mb": 512, "cpu": 0.5, "label": "recommended"},
            "benchmark": {
                "p50_ms": 0.0,
                "p95_ms": 0.0,
                "p99_ms": 0.0,
                "success_rate": 0.0,
                "meets_sla": False,
            },
            "monthly_cost_usd": monthly,
        }
        return {
            "method": "heuristic_estimation",
            "tested": False,
            "comparison_matrix": [recommended],
            "recommended": recommended,
            "sla": {"p95_ms_lt": 500, "success_rate_gte": 0.99},
            "note": f"{reason}; using heuristic estimation",
        }

    def _estimate_cost(self, provider: str, memory_mb: int) -> float:
        provider_key = provider.lower().strip()
        per_256 = {
            "railway": 1.6,
            "render": 1.9,
            "vercel": 1.5,
            "netlify": 1.4,
        }.get(provider_key, 1.6)
        return round((memory_mb / 256.0) * per_256, 2)