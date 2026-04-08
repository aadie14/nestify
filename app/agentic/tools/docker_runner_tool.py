"""Secure Docker runner utility for internal, resource-limited execution."""

from __future__ import annotations

import json
import time
from typing import Any

from app.core.config import settings


class DockerRunnerTool:
    name: str = "Run Isolated Docker Task"
    description: str = "Run a container with strict resource limits and guaranteed cleanup"

    def _run(self, payload: str) -> str:
        try:
            data = json.loads(payload)
        except json.JSONDecodeError:
            return json.dumps({"ok": False, "error": "payload must be JSON"})

        image = str(data.get("image") or "")
        command = data.get("command")
        timeout_seconds = max(5, min(settings.docker_timeout_seconds, int(data.get("timeout_seconds") or settings.docker_timeout_seconds)))

        if not image:
            return json.dumps({"ok": False, "error": "image required"})

        try:
            import docker  # type: ignore[import-untyped]
            client = docker.from_env()
        except Exception as exc:
            return json.dumps({"ok": False, "error": f"docker unavailable: {exc}"})

        container = None
        started = time.time()
        try:
            cpu_period = 100000
            cpu_quota = int(cpu_period * max(0.1, min(settings.docker_max_cpu, 1.0)))

            container = client.containers.run(
                image=image,
                command=command,
                detach=True,
                mem_limit=settings.docker_max_memory,
                cpu_period=cpu_period,
                cpu_quota=cpu_quota,
                network_disabled=True,
                read_only=True,
                security_opt=["no-new-privileges"],
                pids_limit=256,
            )
            result = container.wait(timeout=timeout_seconds)
            logs = container.logs(stdout=True, stderr=True).decode("utf-8", errors="ignore")

            return json.dumps(
                {
                    "ok": True,
                    "status_code": int(result.get("StatusCode", -1)),
                    "elapsed_seconds": round(time.time() - started, 2),
                    "logs": logs[-8000:],
                }
            )
        except Exception as exc:
            return json.dumps({"ok": False, "error": str(exc)})
        finally:
            try:
                if container is not None:
                    container.remove(force=True)
            except Exception:
                pass
