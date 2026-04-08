"""Load testing tool with safe limits and fallback behavior."""

from __future__ import annotations

import asyncio
import ipaddress
import json
import time
from urllib.parse import urlparse

import httpx

from app.core.config import settings


class LoadTesterTool:
    name: str = "Load Test Application"
    description: str = "Run bounded HTTP load tests and return p50/p95/p99 and error rate"

    @staticmethod
    def _bounded_int(value: object, *, default: int, minimum: int, maximum: int) -> int:
        try:
            parsed = int(value) if value is not None else default
        except (TypeError, ValueError):
            parsed = default
        return max(minimum, min(maximum, parsed))

    @staticmethod
    def _validate_target_url(target_url: str) -> str | None:
        parsed = urlparse(target_url)
        if parsed.scheme not in {"http", "https"}:
            return "target_url must use http or https"

        host = (parsed.hostname or "").strip().lower()
        if not host:
            return "target_url must include a hostname"

        if host in {"localhost", "127.0.0.1", "::1"}:
            return "localhost targets are not allowed"

        try:
            ip = ipaddress.ip_address(host)
            if ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_multicast or ip.is_reserved:
                return "private or local network targets are not allowed"
        except ValueError:
            # Host is a DNS name; we only block obvious local hostnames at this layer.
            pass

        return None

    @staticmethod
    def _percentile(sorted_values: list[float], pct: float) -> float:
        index = int(pct * (len(sorted_values) - 1))
        return sorted_values[index]

    def _run(self, payload: str) -> str:
        return asyncio.run(self._arun(payload))

    async def _arun(self, payload: str) -> str:
        if not settings.load_test_enabled:
            return json.dumps({"ok": False, "error": "load testing is disabled by configuration"})

        try:
            data = json.loads(payload)
        except json.JSONDecodeError:
            return json.dumps({"ok": False, "error": "payload must be JSON"})

        if not isinstance(data, dict):
            return json.dumps({"ok": False, "error": "payload must be a JSON object"})

        target_url = str(data.get("target_url") or "")
        duration_seconds = self._bounded_int(
            data.get("duration_seconds"),
            default=settings.load_test_duration_seconds,
            minimum=1,
            maximum=120,
        )
        rps = self._bounded_int(
            data.get("rps"),
            default=settings.load_test_target_rps,
            minimum=1,
            maximum=250,
        )

        max_requests_raw = data.get("max_requests")
        max_requests = None
        if max_requests_raw is not None:
            max_requests = self._bounded_int(max_requests_raw, default=1000, minimum=1, maximum=5000)

        if not target_url:
            return json.dumps({"ok": False, "error": "target_url required"})

        target_error = self._validate_target_url(target_url)
        if target_error:
            return json.dumps({"ok": False, "error": target_error})

        latencies: list[float] = []
        errors = 0
        total = 0
        lock = asyncio.Lock()

        worker_count = min(20, rps)
        worker_interval_seconds = max(0.001, worker_count / float(rps))

        deadline = time.monotonic() + duration_seconds

        async def worker() -> None:
            nonlocal errors, total
            async with httpx.AsyncClient(timeout=10, follow_redirects=True) as client:
                while time.monotonic() < deadline:
                    async with lock:
                        if max_requests is not None and total >= max_requests:
                            break
                        total += 1

                    start = time.perf_counter()
                    request_error = 0
                    try:
                        response = await client.get(target_url)
                        if response.status_code >= 400:
                            request_error = 1
                    except Exception:
                        request_error = 1
                    elapsed_ms = (time.perf_counter() - start) * 1000.0

                    async with lock:
                        latencies.append(elapsed_ms)
                        errors += request_error

                    await asyncio.sleep(worker_interval_seconds)

        tasks = [asyncio.create_task(worker()) for _ in range(worker_count)]
        await asyncio.gather(*tasks)

        if not latencies:
            return json.dumps({"ok": False, "error": "no samples collected"})

        latencies.sort()
        p50 = self._percentile(latencies, 0.50)
        p95 = self._percentile(latencies, 0.95)
        p99 = self._percentile(latencies, 0.99)
        success_rate = max(0.0, 1.0 - (errors / max(1, total)))

        return json.dumps(
            {
                "ok": True,
                "duration_seconds": duration_seconds,
                "target_rps": rps,
                "sample_count": total,
                "worker_count": worker_count,
                "p50_ms": round(p50, 2),
                "p95_ms": round(p95, 2),
                "p99_ms": round(p99, 2),
                "success_rate": round(success_rate, 4),
            }
        )
