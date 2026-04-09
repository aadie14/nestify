"""Central execution engine for deterministic autonomous deployment workflows."""

from __future__ import annotations

import asyncio
import logging
import re
import time
from dataclasses import asdict, dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any, Callable

import httpx

from app.agentic.agent_debate import AgentDebate
from app.agentic.agents.cost_optimization_agent import CostOptimizationSpecialist
from app.agentic.agents.production_monitoring_agent import ProductionMonitoringAnalyst
from app.agentic.agents.self_healing_agent import SelfHealingDeploymentEngineer
from app.agentic.coordinator import AgenticCoordinator
from app.agentic.models import AgenticInsights
from app.agents.deployment_agent import DeploymentAgent
from app.agents.fix_agent import FixAgent
from app.agents.security_agent import SecurityAgent
from app.agents.simulation_agent import PatchSpec, SimulationAgent
from app.database import add_log, update_project
from app.core.feed_formatter import format_feed_event, standard_agent_output
from app.runtime.metrics_analyzer import MetricsAnalyzer
from app.runtime.provider_metrics import ProviderMetricsCollector
from app.services.project_source_service import get_project_source_dir, load_source_text_map

logger = logging.getLogger(__name__)

ProgressCallback = Callable[[dict[str, Any]], None]


class ExecutionStep(str, Enum):
    """Deterministic workflow steps used by the central execution engine."""

    INPUT = "input"
    CODE_ANALYSIS = "code_analysis"
    EXECUTION_TEST = "execution_test"
    AGENT_DEBATE = "agent_debate"
    SECURITY_AUDIT = "security_audit"
    AUTO_FIXES = "auto_fixes"
    COST_ANALYSIS = "cost_analysis"
    DEPLOYMENT = "deployment"
    VERIFICATION = "verification"
    RETRY_LOOP = "retry_loop"
    MONITORING = "monitoring"
    SELF_HEALING_LOOP = "self_healing_loop"
    COMPLETED = "completed"
    FAILED = "failed"


@dataclass(slots=True)
class ExecutionState:
    """Public execution state contract exposed to clients and persisted in DB."""

    status: str = "pending"
    step: str = ExecutionStep.INPUT.value
    attempts: int = 0
    errors: list[str] = field(default_factory=list)
    deployment_url: str = ""


@dataclass(slots=True)
class ExecutionResult:
    """Final result emitted by the central execution engine."""

    security_report: dict[str, Any]
    security_score: int
    risk_report: dict[str, Any]
    fix_report: dict[str, Any]
    deployment: dict[str, Any] | None
    graph_stats: dict[str, Any]
    status: str
    pipeline_states: dict[str, str]
    execution_state: dict[str, Any]
    cost_analysis: dict[str, Any] | None = None
    monitoring: dict[str, Any] | None = None
    agent_actions: list[dict[str, Any]] = field(default_factory=list)
    security_report_pdf: str | None = None
    agentic_insights: dict[str, Any] | None = None


class ExecutionEngine:
    """Single source of truth for autonomous execution workflows.

    CrewAI/agent debate is used only for decisioning. All execution control remains
    deterministic and state-driven inside this engine.
    """

    def __init__(self, project_id: int, progress_callback: ProgressCallback | None = None) -> None:
        self.project_id = project_id
        self.on_progress = progress_callback or (lambda _: None)
        self.state = ExecutionState()
        self.pipeline_states: dict[str, str] = {}
        self.agent_actions: list[dict[str, Any]] = []
        self._cycle = 0

    @staticmethod
    def _confidence_language(confidence: float) -> str:
        score = max(0.0, min(1.0, float(confidence)))
        if score >= 0.85:
            return "I am highly confident this path will work."
        if score >= 0.7:
            return "I am reasonably confident this is the best next step."
        if score >= 0.5:
            return "Confidence is moderate, so I will validate results before committing further."
        return "Confidence is low, so I am prioritizing safe checks and reversible actions."

    def _pattern_hint(self, context: dict[str, Any], action: str) -> str:
        failures = context.get("failures") or []
        stack_info = context.get("stack_info") or {}
        runtime = str(stack_info.get("runtime") or "").lower()

        if action in {"attempt_deploy", "retry_with_modification"} and failures:
            last = failures[-1] if isinstance(failures[-1], dict) else {}
            last_error = str(last.get("error") or "").lower()
            if "env" in last_error or "token" in last_error or "auth" in last_error:
                return "Pattern detected: previous attempts often fail due to missing environment variables or provider credentials."
            if "build" in last_error or "output" in last_error:
                return "Pattern detected: prior attempts indicate missing build artifacts, so deployability checks are prioritized."
            return "Pattern detected: the previous deployment strategy failed, so this attempt uses a modified approach."

        if action == "change_platform" and runtime:
            if runtime == "python":
                return "Pattern detected: backend-heavy Python services usually deploy more reliably on Railway-style runtimes."
            if runtime == "node":
                return "Pattern detected: Node workloads vary by artifact type, so provider fit is being adjusted."

        if action == "run_security_scan":
            return "Pattern detected: unresolved critical findings are a common source of rollout failures."

        if action == "apply_fix":
            return "Pattern detected: deterministic remediations usually improve deployment success after failed verification."

        return ""

    def _compose_reasoned_message(
        self,
        base: str,
        reasoning: str | None,
        confidence: float | None,
        pattern: str | None,
    ) -> str:
        # Keep operator feed concise and deterministic (no raw reasoning text).
        return " ".join(str(base or "").split())

    def _emit(
        self,
        agent: str,
        phase: str,
        message: str,
        data: dict[str, Any] | None = None,
        reasoning: str | None = None,
        confidence: float | None = None,
        pattern: str | None = None,
    ) -> None:
        composed_message = self._compose_reasoned_message(message, reasoning, confidence, pattern)
        feed_event = format_feed_event(
            agent=agent,
            event_type="status",
            title=phase,
            message=composed_message,
            severity="info",
            action=data.get("action") if isinstance(data, dict) else None,
            confidence=confidence,
            data=data if isinstance(data, dict) else None,
        )
        payload: dict[str, Any] = {
            "agent": agent,
            "phase": phase,
            "message": str(feed_event.get("message") or composed_message),
            "timestamp": time.time(),
            "cycle": int(getattr(self, "_cycle", 0)),
            "execution_step": self.state.step,
            "execution_state": asdict(self.state),
            "feed": feed_event,
        }
        if confidence is not None:
            payload["confidence"] = max(0.0, min(1.0, float(confidence)))
        if data is not None:
            payload["data"] = data
        self.on_progress(payload)

    def _emit_action(
        self,
        agent: str,
        user_message: str,
        action: str,
        confidence: float,
        evidence: list[str] | None = None,
        data: dict[str, Any] | None = None,
    ) -> None:
        feed_event = format_feed_event(
            agent=agent,
            event_type="decision",
            title="decision",
            message=user_message,
            severity="info",
            action=action,
            confidence=confidence,
            data=data if isinstance(data, dict) else None,
        )
        item = {
            "agent": agent,
            "user_message": str(feed_event.get("message") or user_message),
            "action": action,
            "confidence": max(0.0, min(1.0, float(confidence))),
            "evidence": evidence or [],
            "data": data or {},
            "timestamp": time.time(),
        }
        self.agent_actions.append(item)
        self.on_progress({
            "type": "argument",
            "timestamp": item["timestamp"],
            "cycle": int(getattr(self, "_cycle", 0)),
            "agent": agent,
            "user_message": item["user_message"],
            "decision": item["user_message"],
            "action": action,
            "confidence": item["confidence"],
            "evidence": item["evidence"],
            "data": item["data"],
            "feed": feed_event,
        })

    @staticmethod
    def _classify_failure(error: str) -> str:
        text = str(error or "").lower()
        if any(token in text for token in ["env", "environment variable", "token", "credential", "apikey", "api key"]):
            return "missing_env"
        if any(token in text for token in ["module not found", "no module named", "cannot find module", "dependency", "package"]):
            return "dependency_issue"
        if any(token in text for token in ["build", "compile", "syntax", "output directory", "dist/"]):
            return "build_error"
        if any(token in text for token in ["timeout", "dns", "network", "rate limit", "gateway", "infra", "unavailable"]):
            return "infra_issue"
        return "unknown"

    def _set_step(self, step: ExecutionStep, status: str = "running") -> None:
        self.state.step = step.value
        self.state.status = status
        update_project(
            self.project_id,
            {
                "pipeline_state": {
                    "execution_state": asdict(self.state),
                    "pipeline_states": self.pipeline_states,
                }
            },
        )

    def _record_error(self, error: Exception | str) -> None:
        message = str(error)
        self.state.errors.append(message)
        add_log(self.project_id, "ExecutionEngine", message, "error")

    def _emit_stage_log(self, stage: str, status: str, start_ts: float) -> None:
        latency_ms = int(max(0.0, (time.perf_counter() - start_ts) * 1000.0))
        payload = {
            "stage": str(stage),
            "status": str(status),
            "latency_ms": latency_ms,
        }
        add_log(self.project_id, "ExecutionEngine", str(payload), "info")

    def _build_plan(self, files: list[dict[str, str]]) -> dict[str, Any]:
        file_count = len(files)
        risk = "low"
        if file_count > 30:
            risk = "medium"
        if file_count > 120:
            risk = "high"
        return {
            "tasks": [
                "code_analysis",
                "security_analysis",
                "cost_estimation",
                "platform_selection",
            ],
            "parallel": ["code_analysis", "security_analysis"],
            "risk_level": risk,
        }

    def _derive_memory_signals(self, similar_deployments: list[dict[str, Any]]) -> dict[str, Any]:
        rows = similar_deployments if isinstance(similar_deployments, list) else []
        if not rows:
            return {
                "historical_success_rate": 0.0,
                "common_failures": [],
                "recommended_actions": [],
            }

        total = len(rows)
        success = 0
        failure_buckets: dict[str, int] = {}
        for row in rows:
            if bool(row.get("success")):
                success += 1
            for fix in (row.get("fixes_applied") or []):
                key = str(fix or "unknown").strip().lower()
                if key:
                    failure_buckets[key] = int(failure_buckets.get(key, 0)) + 1

        common_failures = [
            item for item, _ in sorted(failure_buckets.items(), key=lambda kv: kv[1], reverse=True)[:5]
        ]
        recommended_actions = []
        if common_failures:
            recommended_actions = [f"preempt_{item}" for item in common_failures[:3]]

        return {
            "historical_success_rate": round(success / max(1, total), 2),
            "common_failures": common_failures,
            "recommended_actions": recommended_actions,
        }

    @staticmethod
    def _detect_entry_points(files: list[dict[str, str]]) -> list[str]:
        names = [str(item.get("name", "")) for item in files]
        candidates = [
            "main.py",
            "app.py",
            "server.py",
            "index.js",
            "server.js",
            "main.ts",
            "index.ts",
            "Dockerfile",
            "docker-compose.yml",
            "docker-compose.yaml",
            "package.json",
        ]
        found: list[str] = []
        lower_names = {name.lower(): name for name in names}
        for candidate in candidates:
            if candidate.lower() in lower_names:
                found.append(lower_names[candidate.lower()])

        if not found:
            for name in names:
                lowered = name.lower()
                if lowered.endswith("/main.py") or lowered.endswith("/server.py"):
                    found.append(name)
                if len(found) >= 5:
                    break

        return found[:6]

    async def _run_execution_test(
        self,
        files: list[dict[str, str]],
        code_profile: dict[str, Any] | None,
    ) -> dict[str, Any]:
        """Attempt to run or validate project locally using sandbox-friendly checks."""

        entry_points = self._detect_entry_points(files)
        source_dir = Path(get_project_source_dir(self.project_id)) / "source"
        execution_report: dict[str, Any] = {
            "entry_points": entry_points,
            "sandbox": "none",
            "success": False,
            "details": [],
        }

        # If Dockerfile exists, try bounded Docker-backed runtime probe via cost tester.
        try:
            from app.agentic.tools.docker_cost_tester import DockerCostTester

            tester = DockerCostTester()
            if tester.is_available and source_dir.exists() and (source_dir / "Dockerfile").exists():
                app_type = "backend"
                if isinstance(code_profile, dict):
                    app_type = str(code_profile.get("app_type") or "backend")

                docker_probe = await tester.test_configs(
                    project_path=str(source_dir),
                    app_type=app_type,
                    provider="railway",
                )
                execution_report["sandbox"] = "docker"
                execution_report["details"].append(docker_probe)
                execution_report["success"] = bool(docker_probe.get("tested"))
                return execution_report
        except Exception as exc:
            execution_report["details"].append({"docker_error": str(exc)})

        # Fallback sandbox check: parse/compile python entry files.
        parse_ok = 0
        parse_fail = 0
        for item in files[:200]:
            file_name = str(item.get("name") or "")
            if not file_name.endswith(".py"):
                continue
            content = str(item.get("content") or "")
            try:
                compile(content, file_name, "exec")
                parse_ok += 1
            except Exception:
                parse_fail += 1

        execution_report["sandbox"] = "python_compile_fallback"
        execution_report["details"].append({
            "parsed_ok": parse_ok,
            "parsed_failed": parse_fail,
            "entry_points": entry_points,
        })
        execution_report["success"] = parse_ok > 0 and parse_fail == 0
        return execution_report

    def _maybe_generate_dockerfile(self, files: list[dict[str, str]], stack_info: dict[str, Any]) -> bool:
        """Create a minimal Dockerfile when missing to improve deployability."""

        file_names = {str(item.get("name") or "") for item in files}
        if any(name.lower().endswith("dockerfile") or name.lower() == "dockerfile" for name in file_names):
            return False

        runtime = str(stack_info.get("runtime") or "unknown").lower()
        source_dir = Path(get_project_source_dir(self.project_id)) / "source"
        source_dir.mkdir(parents=True, exist_ok=True)

        if runtime == "python":
            dockerfile = (
                "FROM python:3.11-slim\n"
                "WORKDIR /app\n"
                "COPY requirements.txt ./\n"
                "RUN pip install --no-cache-dir -r requirements.txt\n"
                "COPY . .\n"
                "ENV PORT=8000\n"
                "EXPOSE 8000\n"
                "CMD [\"python\", \"-m\", \"uvicorn\", \"app.main:app\", \"--host\", \"0.0.0.0\", \"--port\", \"8000\"]\n"
            )
        elif runtime == "node":
            dockerfile = (
                "FROM node:20-alpine\n"
                "WORKDIR /app\n"
                "COPY package*.json ./\n"
                "RUN npm ci || npm install\n"
                "COPY . .\n"
                "ENV PORT=8000\n"
                "EXPOSE 8000\n"
                "CMD [\"npm\", \"start\"]\n"
            )
        else:
            return False

        target = source_dir / "Dockerfile"
        target.write_text(dockerfile, encoding="utf-8")
        add_log(self.project_id, "ExecutionEngine", "Generated baseline Dockerfile for deployability.", "info")
        return True

    async def _verify_live_url(self, deployment_url: str | None) -> tuple[bool, dict[str, Any]]:
        if not deployment_url:
            return False, {"reason": "deployment_url_missing"}

        checks: list[dict[str, Any]] = []
        async with httpx.AsyncClient(timeout=10, follow_redirects=True) as client:
            for attempt in range(1, 6):
                try:
                    response = await client.get(deployment_url)
                    ok = 200 <= response.status_code < 500
                    checks.append({"attempt": attempt, "status_code": response.status_code, "ok": ok})
                    if ok:
                        return True, {"checks": checks}
                except Exception as exc:
                    checks.append({"attempt": attempt, "error": str(exc), "ok": False})
                await asyncio.sleep(2)

        return False, {"checks": checks}

    async def _collect_monitoring(
        self,
        deployment_url: str,
        provider: str | None,
        deployment_details: dict[str, Any] | None,
    ) -> dict[str, Any]:
        analyzer = MetricsAnalyzer(deployment_url)
        for _ in range(8):
            await analyzer.health_check()
            await asyncio.sleep(0.5)
        runtime = analyzer.analyze().to_dict()

        provider_metrics = await ProviderMetricsCollector().collect(provider=provider, details=deployment_details or {})

        # Preserve prior frontend compatibility by mirroring provider metrics into runtime when available.
        if provider_metrics.get("cpu_percent") is not None:
            runtime["cpu_percent"] = provider_metrics.get("cpu_percent")
        if provider_metrics.get("memory_mb") is not None:
            runtime["memory_mb"] = provider_metrics.get("memory_mb")

        monitor_agent = ProductionMonitoringAnalyst()
        enrichment = await monitor_agent.monitor(deployment_url=deployment_url, allocated_memory_mb=None)

        monitor_metrics = {
            "p50": runtime.get("p50_ms"),
            "p95": runtime.get("p95_ms"),
            "p99": runtime.get("p99_ms"),
            "error_rate": runtime.get("error_rate"),
        }
        status = "healthy" if float(runtime.get("error_rate") or 0.0) <= 0.01 else "degraded"
        recommendations = []
        if isinstance(enrichment.get("recommendations"), list):
            recommendations = [
                str(item.get("action") or item) if isinstance(item, dict) else str(item)
                for item in enrichment.get("recommendations")[:8]
            ]

        return {
            "metrics": monitor_metrics,
            "status": status,
            "recommendations": recommendations,
            "runtime": runtime,
            "agent_report": enrichment,
            "provider_metrics": provider_metrics,
            "cpu": {
                "status": "ok" if provider_metrics.get("cpu_percent") is not None else "provider_managed",
                "value": provider_metrics.get("cpu_percent"),
                "note": provider_metrics.get("note"),
            },
            "ram": {
                "status": "ok" if provider_metrics.get("memory_mb") is not None else "provider_managed",
                "value": provider_metrics.get("memory_mb"),
                "note": provider_metrics.get("note"),
            },
        }

    async def run(self, parsed_input: dict[str, Any]) -> ExecutionResult:
        from app.database import get_project

        project = get_project(self.project_id)
        if not project:
            raise RuntimeError("Project not found")

        files = parsed_input.get("files") or [
            {"name": path, "content": content}
            for path, content in load_source_text_map(self.project_id).items()
        ]

        security_agent = SecurityAgent(self.project_id)
        coordinator = AgenticCoordinator(self.project_id)
        insights = AgenticInsights()

        fix_report: dict[str, Any] = {
            "applied": [],
            "manual_review": [],
            "env_vars_detected": [],
            "simulation_blocked": [],
        }
        deployment_payload: dict[str, Any] | None = None
        monitoring_payload: dict[str, Any] | None = None
        debate_result: dict[str, Any] = {}
        cost_analysis: dict[str, Any] | None = None
        risk_dict: dict[str, Any] = {}
        graph_stats: dict[str, Any] = {}
        final_scan = None
        final_status = "failed"
        pdf_path: str | None = None
        source_payload = project.get("source_payload") if isinstance(project.get("source_payload"), dict) else parsed_input
        analysis_only = bool(parsed_input.get("analysis_only"))
        execution_plan = self._build_plan(files)

        # Shared context for meta-agent control loop.
        context: dict[str, Any] = {
            "goal": "Secure, fix, and deploy the application successfully",
            "current_state": "input_ready",
            "analysis": {},
            "failures": [],
            "actions_taken": [],
            "confidence": 0.65,
            "goal_achieved": False,
            "decision_log": [],
            "security_scanned": False,
            "fixes_applied": False,
            "deployment_attempted": False,
            "deploy_attempts": 0,
            "provider_attempts": {},
            "providers_tried": [],
            "platform_changes": 0,
            "retry_modifications": [],
            "retry_exhausted": False,
            "fatal_blocker": None,
            "preferred_provider": str(project.get("preferred_provider") or "").strip().lower() or None,
            "stack_info": {},
            "self_heal_attempts": [],
            "fixes_applied": [],
            "simulation_validated": False,
            "last_failure_type": None,
            "failure_type_counts": {},
            "last_action": None,
            "last_outcome": None,
            "result_classification": "partial",
            "analysis_only": analysis_only,
            "plan": execution_plan,
            "plan_applied": False,
            "agent_outputs": {},
            "memory_signals": {
                "historical_success_rate": 0.0,
                "common_failures": [],
                "recommended_actions": [],
            },
        }

        def _decision_entry(thought: str, action: str, reason: str, confidence: float) -> dict[str, Any]:
            return {
                "thought": thought,
                "action": action,
                "reason": reason,
                "confidence": max(0.0, min(1.0, float(confidence))),
            }

        def _severity_count(report: dict[str, Any], severity: str) -> int:
            bucket = report.get(severity)
            if isinstance(bucket, list):
                return len(bucket)
            return 0

        def _decide_action() -> dict[str, Any]:
            if context.get("goal_achieved"):
                return _decision_entry(
                    "Goal achieved and live deployment verified.",
                    "stop_with_explanation",
                    "No additional execution needed.",
                    context["confidence"],
                )

            if not context.get("plan_applied"):
                plan = context.get("plan") or {}
                return _decision_entry(
                    "Applying deterministic execution plan.",
                    "analyze_code",
                    f"Plan tasks={plan.get('tasks', [])}; parallel={plan.get('parallel', [])}",
                    context["confidence"],
                )

            if context.get("analysis_only"):
                if not context.get("analysis"):
                    return _decision_entry(
                        "Running controlled analysis workflow for stack and risk context.",
                        "analyze_code",
                        "Analyze mode is restricted to code/security analysis and platform debate.",
                        context["confidence"],
                    )
                if not context.get("security_scanned"):
                    return _decision_entry(
                        "Completing security enrichment before closing controlled analysis.",
                        "run_security_scan",
                        "Security context must be finalized before handoff.",
                        context["confidence"],
                    )
                return _decision_entry(
                    "Controlled analysis workflow is complete.",
                    "stop_with_explanation",
                    "Analyze mode intentionally excludes auto-fix and deployment execution.",
                    context["confidence"],
                )

            if context.get("fatal_blocker"):
                blocker = str(context.get("fatal_blocker") or "fatal deployment blocker")
                if context.get("last_failure_type") == "missing_env":
                    return _decision_entry(
                        f"A credential blocker was detected: {blocker}",
                        "request_user_input",
                        "Credentials are required before any further safe deployment action.",
                        context["confidence"],
                    )
                return _decision_entry(
                    f"Stopping because a fatal blocker was detected: {blocker}",
                    "fallback_local",
                    "Continuing retries would repeat the same failure without new deploy prerequisites.",
                    context["confidence"],
                )

            if context.get("retry_exhausted"):
                return _decision_entry(
                    "Stopping because all retry modifications have been exhausted.",
                    "fallback_local",
                    "No distinct remediation remains, so local fallback keeps the app available.",
                    context["confidence"],
                )

            has_analysis = bool(context.get("analysis"))
            if not has_analysis:
                return _decision_entry(
                    "I need an architecture and risk baseline before making high-impact deployment decisions.",
                    "analyze_code",
                    "Security and stack analysis provide the baseline for all adaptive actions.",
                    context["confidence"],
                )

            if not context.get("security_scanned"):
                return _decision_entry(
                    "I will run security enrichment before deployment to avoid preventable production failures.",
                    "run_security_scan",
                    "Risk context is needed for acceptable security goal.",
                    context["confidence"],
                )

            if context.get("fixes_applied") and not context.get("simulation_validated"):
                return _decision_entry(
                    "Fixes were applied and must be validated before deployment.",
                    "run_simulation",
                    "Simulation gate is mandatory before deploy retries.",
                    context["confidence"],
                )

            if context.get("failures"):
                last = context["failures"][-1]
                failure_type = str(last.get("failure_type") or context.get("last_failure_type") or "unknown")
                provider = str(last.get("provider") or context.get("preferred_provider") or "auto")
                provider_attempts = int((context.get("provider_attempts") or {}).get(provider, 0))
                repeated_failure = int((context.get("failure_type_counts") or {}).get(failure_type, 0)) >= 2
                memory_signals = context.get("memory_signals") or {}
                recommended_actions = memory_signals.get("recommended_actions") or []
                if any("provider" in str(item).lower() for item in recommended_actions) and failure_type in {"infra_issue", "unknown"}:
                    return _decision_entry(
                        "Historical signals indicate provider mismatch risk.",
                        "switch_provider",
                        "Learning signals recommend provider adaptation for this failure profile.",
                        context["confidence"],
                    )

                if provider_attempts >= 2:
                    return _decision_entry(
                        f"Provider {provider} already failed twice.",
                        "switch_provider",
                        "Provider retry cap reached; switching strategy avoids blind repetition.",
                        context["confidence"],
                    )

                if failure_type == "missing_env":
                    if not context.get("fixes_applied"):
                        return _decision_entry(
                            "Deployment failed due to missing environment variables; attempting safe config remediation.",
                            "fix_code",
                            "Generate safe env/config defaults before asking for manual credentials.",
                            context["confidence"],
                        )
                    return _decision_entry(
                        "Environment credentials are still unresolved.",
                        "request_user_input",
                        "User credentials are required to continue safely.",
                        context["confidence"],
                    )

                if failure_type == "dependency_issue":
                    return _decision_entry(
                        "Deployment failed due to dependency mismatch.",
                        "fix_dependencies",
                        "Dependencies must be corrected before retry.",
                        context["confidence"],
                    )

                if failure_type == "build_error":
                    return _decision_entry(
                        "Build failure detected.",
                        "fix_code",
                        "Code/build fix is required before deployment.",
                        context["confidence"],
                    )

                if failure_type == "infra_issue" or repeated_failure:
                    return _decision_entry(
                        "Infrastructure instability or repeated failure detected.",
                        "switch_provider",
                        "A new deployment strategy is required.",
                        context["confidence"],
                    )

                if context.get("deploy_attempts", 0) < 3:
                    return _decision_entry(
                        "Unknown failure; applying conservative remediation before next deployment.",
                        "fix_code",
                        "Avoid immediate blind retry; remediate first.",
                        context["confidence"],
                    )

                return _decision_entry(
                    "Failure budget exhausted.",
                    "fallback_local",
                    "Fallback keeps execution resilient when cloud retries are exhausted.",
                    context["confidence"],
                )

            return _decision_entry(
                "Current signals look stable enough to proceed with deployment under the active strategy.",
                "deploy",
                "Goal requires reaching verified live state.",
                context["confidence"],
            )

        def _reflect(action: str, result: dict[str, Any] | None, error: str | None = None) -> dict[str, Any]:
            confidence = float(context.get("confidence", 0.5))
            if error:
                root_cause = self._classify_failure(error)

                confidence = max(0.15, confidence - 0.12)
                strategy_update = f"Adjust strategy after {root_cause}: avoid repeating unchanged action."
                return {
                    "root_cause": root_cause,
                    "strategy_update": strategy_update,
                    "confidence": confidence,
                }

            if result and result.get("outcome") == "success":
                confidence = min(0.98, confidence + 0.06)
            else:
                confidence = max(0.2, confidence - 0.04)
            return {
                "root_cause": "none",
                "strategy_update": "Continue current strategy with updated confidence.",
                "confidence": confidence,
            }

        async def _action_analyze_code() -> dict[str, Any]:
            nonlocal final_scan, risk_dict, graph_stats, cost_analysis, debate_result, insights
            self._set_step(ExecutionStep.CODE_ANALYSIS)
            started_at = time.perf_counter()
            self._emit(
                "CodeAnalyzer",
                "analyzing",
                "Analyzing code and security in controlled parallel mode.",
                confidence=context.get("confidence"),
            )

            async def _security_task():
                return await security_agent.scan(files)

            async def _code_task():
                profile = await coordinator.code_agent.analyze(files=files, graph=None)
                return profile.to_dict()

            initial_scan, code_profile = await asyncio.gather(_security_task(), _code_task())
            final_scan = initial_scan
            risk_dict = initial_scan.risk_report.to_dict() if initial_scan.risk_report else {}
            graph_stats = dict(initial_scan.metadata or {})
            insights.code_profile = code_profile

            # Derive memory signals for deterministic strategy hints.
            insights = await coordinator.run_deploying_entry_phase(insights)
            context["memory_signals"] = self._derive_memory_signals(insights.similar_deployments or [])

            execution_test = await self._run_execution_test(files, insights.code_profile)
            self.pipeline_states["execution_test"] = "done" if execution_test.get("success") else "failed"

            cost_agent = CostOptimizationSpecialist()
            cost_analysis = await cost_agent.optimize(
                code_profile=insights.code_profile or {},
                preferred_provider=context.get("preferred_provider") or project.get("preferred_provider"),
                project_path=str(Path(get_project_source_dir(self.project_id)) / "source"),
            )

            debate = AgentDebate()
            debate_result = await debate.debate_platform_choice(
                code_profile=insights.code_profile or {},
                cost_analysis=cost_analysis,
                similar_deployments=insights.similar_deployments,
            )

            context["agent_outputs"]["cost_estimation"] = standard_agent_output(
                agent="CostOptimizationSpecialist",
                status="success",
                data=cost_analysis if isinstance(cost_analysis, dict) else {},
                confidence=float((cost_analysis or {}).get("recommended", {}).get("benchmark", {}).get("success_rate") or 0.7),
                risk="medium",
            )
            context["agent_outputs"]["platform_selection"] = standard_agent_output(
                agent="PlatformSelectionStrategist",
                status="success",
                data={
                    "chosen_platform": debate_result.get("chosen_platform"),
                    "confidence": debate_result.get("confidence"),
                },
                confidence=float(debate_result.get("confidence") or 0.7),
                risk="medium",
            )

            chosen_platform = str(debate_result.get("chosen_platform") or cost_analysis.get("provider") or "railway").lower()
            memory_rate = float((context.get("memory_signals") or {}).get("historical_success_rate") or 0.0)
            if memory_rate >= 0.8:
                learned_candidates = insights.similar_deployments or []
                if learned_candidates:
                    top = learned_candidates[0]
                    learned_provider = str(top.get("platform_choice") or "").strip().lower()
                    if learned_provider:
                        chosen_platform = learned_provider
            context["preferred_provider"] = chosen_platform
            context["analysis"] = {
                "stack": initial_scan.metadata or {},
                "entry_points": self._detect_entry_points(files),
                "execution_test": execution_test,
                "chosen_platform": chosen_platform,
            }
            context["stack_info"] = security_agent._detect_stack(files)
            context["security_scanned"] = True
            context["plan_applied"] = True

            code_output = standard_agent_output(
                agent="CodeIntelligenceAnalyst",
                status="success",
                data={
                    "profile": insights.code_profile or {},
                    "entry_points": self._detect_entry_points(files),
                },
                confidence=float(context.get("confidence") or 0.65),
                risk=str(execution_plan.get("risk_level") or "medium"),
            )
            security_output = standard_agent_output(
                agent="SecurityIntelligenceExpert",
                status="success",
                data={
                    "summary": initial_scan.report,
                    "risk_report": risk_dict,
                },
                confidence=float(context.get("confidence") or 0.65),
                risk="high" if int(initial_scan.score or 0) < 60 else "medium",
            )
            context["agent_outputs"]["code_analysis"] = code_output
            context["agent_outputs"]["security_analysis"] = security_output

            update_project(
                self.project_id,
                {
                    "stack_info": {
                        **(initial_scan.metadata or {}),
                        "entry_points": self._detect_entry_points(files),
                    },
                    "security_report": initial_scan.report,
                    "security_score": initial_scan.score,
                    "status": "scanning",
                },
            )

            self.pipeline_states["code_analysis"] = "done"
            self.pipeline_states["security_agent"] = "done"
            self.pipeline_states["agent_debate"] = "done"
            self.pipeline_states["agentic_platform_strategist"] = "done"
            self.pipeline_states["cost_analysis"] = "done"
            self.pipeline_states["agentic_cost_optimizer"] = "done"
            self._emit_stage_log("analysis", "success", started_at)
            self._emit(
                "CodeAnalyzer",
                "complete",
                "Analysis complete and deployment strategy selected.",
                {
                    "chosen_platform": chosen_platform,
                    "risk_level": execution_plan.get("risk_level"),
                },
                confidence=context.get("confidence"),
            )

            return {"outcome": "success", "data": context["analysis"]}

        async def _action_run_security_scan() -> dict[str, Any]:
            nonlocal insights
            if final_scan is None:
                return await _action_analyze_code()

            self._set_step(ExecutionStep.SECURITY_AUDIT)
            insights = await coordinator.run_scanning_completion_phase(
                security_report=final_scan.report,
                risk_report=risk_dict,
                graph_stats=graph_stats,
                insights=insights,
            )
            context["security_scanned"] = True
            context["agent_outputs"]["security_analysis"] = standard_agent_output(
                agent="SecurityIntelligenceExpert",
                status="success",
                data={
                    "summary": final_scan.report,
                    "risk_report": risk_dict,
                },
                confidence=float(context.get("confidence") or 0.7),
                risk="high" if int(final_scan.score or 0) < 60 else "medium",
            )
            self.pipeline_states["security_audit"] = "done"
            self._emit(
                "SecurityAgent",
                "complete",
                "Security enrichment completed with updated risk context.",
                reasoning="This reduces rollout risk by surfacing issues that commonly cause failed deploys or unsafe releases.",
                confidence=context.get("confidence"),
                pattern=self._pattern_hint(context, "run_security_scan"),
            )
            return {"outcome": "success", "data": {"security_scanned": True}}

        async def _action_rescan() -> dict[str, Any]:
            # Reuse scan path to refresh risk posture before deployment decisions.
            context["security_scanned"] = False
            result = await _action_run_security_scan()
            self.pipeline_states["re_scan"] = "done"
            self._emit(
                "SecurityAgent",
                "complete",
                "Security re-scan completed and state refreshed.",
                reasoning="Re-scan validates that post-fix state is still deployable and secure.",
                confidence=context.get("confidence"),
            )
            return {"outcome": "success", "data": {"rescan": True, **(result.get("data") or {})}}

        async def _action_apply_fix() -> dict[str, Any]:
            nonlocal fix_report
            if final_scan is None:
                await _action_analyze_code()

            self._set_step(ExecutionStep.AUTO_FIXES)
            stack_info = context.get("stack_info") or security_agent._detect_stack(files)
            docker_generated = self._maybe_generate_dockerfile(files, stack_info)
            fix_agent = FixAgent(self.project_id, graph=final_scan.graph if final_scan else None)
            fix_result = await fix_agent.generate_and_apply(files, final_scan.report if final_scan else {})

            fix_report = {
                "applied": [asdict(item) for item in fix_result.applied],
                "manual_review": [asdict(item) for item in fix_result.manual_review],
                "env_vars_detected": fix_result.env_vars_detected,
                "simulation_blocked": [asdict(item) for item in fix_result.simulation_blocked],
                "dockerfile_generated": docker_generated,
            }
            update_project(self.project_id, {"fix_report": fix_report, "status": "fixing"})
            context["fixes_applied"] = [
                {
                    "fix_type": item.get("fix_type"),
                    "file": item.get("file"),
                    "status": item.get("status"),
                }
                for item in fix_report.get("applied", [])
            ]
            context["simulation_validated"] = len(fix_report.get("simulation_blocked", [])) == 0
            context["agent_outputs"]["fixes"] = standard_agent_output(
                agent="SelfHealingDeploymentEngineer",
                status="success",
                data={
                    "applied": fix_report.get("applied", []),
                    "manual_review": fix_report.get("manual_review", []),
                },
                confidence=float(context.get("confidence") or 0.7),
                risk="medium",
            )
            self.pipeline_states["auto_fixes"] = "done"
            self.pipeline_states["fix_agent"] = "done"
            self._emit(
                "FixAgent",
                "complete",
                "Applied available remediations and prepared the codebase for safer deployment retries.",
                fix_report,
                reasoning="These fixes target common blockers such as missing configuration, risky code paths, and deployability gaps.",
                confidence=context.get("confidence"),
                pattern=self._pattern_hint(context, "apply_fix"),
            )
            return {"outcome": "success", "data": {"fixes_applied": len(fix_report.get('applied', []))}}

        async def _action_fix_dependencies() -> dict[str, Any]:
            source_dir = Path(get_project_source_dir(self.project_id)) / "source"
            req_path = source_dir / "requirements.txt"
            package_json = source_dir / "package.json"
            failure_text = str((context.get("failures") or [{}])[-1].get("error") or "")

            if req_path.exists():
                match = re.search(r"No module named ['\"]([a-zA-Z0-9_\-]+)['\"]", failure_text)
                module = match.group(1).replace("_", "-") if match else ""
                existing = req_path.read_text(encoding="utf-8")
                if module and module.lower() not in existing.lower():
                    patched = f"{existing.rstrip()}\n{module}\n"
                    simulator = SimulationAgent(source_dir)
                    sim = await simulator.simulate([PatchSpec(file_path="requirements.txt", new_content=patched, original_content=existing)])
                    if sim.passed:
                        req_path.write_text(patched, encoding="utf-8")
                        context["fixes_applied"].append({"fix_type": "dependency_fix", "file": "requirements.txt", "status": "applied"})
                        context["simulation_validated"] = True
                        self.pipeline_states["fix_dependencies"] = "done"
                        self._emit("FixAgent", "fixing", f"Dependency fix applied for {module}.", reasoning="Missing dependency was detected and validated in simulation.", confidence=context.get("confidence"))
                        return {"outcome": "success", "data": {"dependency": module}}
                    context["simulation_validated"] = False
                    raise RuntimeError(f"Dependency fix simulation failed: {sim.errors[:2]}")

            if package_json.exists():
                self._emit("FixAgent", "fixing", "Dependency issue detected for Node project; manual package reconciliation required.", reasoning="Automated dependency patch is not safe without lockfile-aware rewrite.", confidence=context.get("confidence"))
                return {"outcome": "stopped", "data": {"reason": "dependency_manual_review_required"}}

            raise RuntimeError("Dependency issue detected but no dependency manifest could be safely updated")

        async def _action_run_simulation() -> dict[str, Any]:
            blocked = len(fix_report.get("simulation_blocked", [])) if isinstance(fix_report, dict) else 0
            passed = blocked == 0
            context["simulation_validated"] = passed
            context["agent_outputs"]["simulation"] = standard_agent_output(
                agent="SelfHealingDeploymentEngineer",
                status="success" if passed else "failed",
                data={"blocked": blocked, "validated": passed},
                confidence=float(context.get("confidence") or 0.7),
                risk="low" if passed else "high",
            )
            self.pipeline_states["run_simulation"] = "done" if passed else "failed"
            self._emit(
                "SimulationAgent",
                "validating",
                "Simulation validation completed.",
                {
                    "blocked": blocked,
                    "validated": passed,
                },
                reasoning="Fixes must be validated before deployment retries.",
                confidence=context.get("confidence"),
            )
            if not passed:
                raise RuntimeError("Simulation failed for one or more fixes")
            return {"outcome": "success", "data": {"validated": True}}

        async def _action_choose_platform() -> dict[str, Any]:
            nonlocal debate_result, cost_analysis
            if not context.get("analysis"):
                await _action_analyze_code()

            self._set_step(ExecutionStep.AGENT_DEBATE)
            debate = AgentDebate()
            debate_result = await debate.debate_platform_choice(
                code_profile=insights.code_profile or context.get("analysis", {}).get("stack", {}),
                cost_analysis=cost_analysis,
                similar_deployments=insights.similar_deployments,
            )
            chosen_platform = str(debate_result.get("chosen_platform") or debate_result.get("platform") or context.get("preferred_provider") or "railway").lower()
            context["preferred_provider"] = chosen_platform
            context["platform_selected"] = True
            self.pipeline_states["choose_platform"] = "done"
            self.pipeline_states["agent_debate"] = "done"
            self._emit(
                "MetaAgent",
                "strategy",
                f"Selected {chosen_platform} as deployment platform.",
                reasoning=str(debate_result.get("reasoning") or "Platform chosen using debate and optimization signals."),
                confidence=float(debate_result.get("confidence") or context.get("confidence") or 0.6),
            )
            return {"outcome": "success", "data": {"platform": chosen_platform}}

        async def _action_change_platform() -> dict[str, Any]:
            stack_info = context.get("stack_info") or security_agent._detect_stack(files)
            runtime = str(stack_info.get("runtime") or "").lower()
            current = str(context.get("preferred_provider") or "").lower()
            attempts = context.get("provider_attempts") or {}

            candidates = ["netlify", "vercel", "local"] if runtime == "node" else ["railway", "local"]
            next_platform = next(
                (
                    item for item in candidates
                    if item != current and int(attempts.get(item, 0)) < 2
                ),
                "local",
            )

            context["preferred_provider"] = next_platform
            context["platform_changes"] = int(context.get("platform_changes", 0)) + 1
            self._emit(
                "MetaAgent",
                "strategy",
                f"I am switching deployment strategy to {next_platform} based on current runtime fit and failure history.",
                reasoning="Provider adaptation increases success odds when prior attempts indicate platform mismatch.",
                confidence=context.get("confidence"),
                pattern=self._pattern_hint(context, "change_platform"),
            )
            return {"outcome": "success", "data": {"preferred_provider": next_platform, "change": "platform_switch"}}

        async def _action_fallback_local() -> dict[str, Any]:
            from app.services.project_source_service import ensure_preview_index, get_local_preview_url

            ensure_preview_index(self.project_id)
            preview_url = get_local_preview_url(self.project_id)
            deployment = {
                "provider": "local",
                "deployment_url": preview_url,
                "status": "success",
                "details": {
                    "mode": "local_preview_fallback",
                    "reason": str(context.get("fatal_blocker") or "Cloud deployment retries exhausted"),
                },
                "app_kind": "static",
            }

            update_project(
                self.project_id,
                {
                    "deployment": deployment,
                    "public_url": preview_url,
                    "status": "live",
                },
            )
            self.state.deployment_url = preview_url
            context["goal_achieved"] = True
            context["current_state"] = "local_fallback_live"
            self.pipeline_states["fallback_local"] = "done"
            self._emit(
                "MetaAgent",
                "fallback",
                "Local preview started after cloud deployment failures.",
                {"deployment_url": preview_url},
                reasoning="Fallback preserves availability when external provider constraints block deployment.",
                confidence=context.get("confidence"),
            )
            return {"outcome": "success", "data": {"deployment": deployment}}

        async def _action_attempt_deploy(change_tag: str | None = None) -> dict[str, Any]:
            nonlocal deployment_payload, monitoring_payload, insights, pdf_path
            stack_info = context.get("stack_info") or security_agent._detect_stack(files)
            deploy_agent = DeploymentAgent(self.project_id)

            self._set_step(ExecutionStep.DEPLOYMENT)
            context["deployment_attempted"] = True
            context["deploy_attempts"] = int(context.get("deploy_attempts", 0)) + 1
            self.state.attempts = context["deploy_attempts"]

            provider = context.get("preferred_provider")
            provider_key = str(provider or "auto")
            provider_attempts = context.get("provider_attempts") or {}
            current_attempts = int(provider_attempts.get(provider_key, 0))
            if current_attempts >= 2:
                raise RuntimeError(f"Provider {provider_key} already failed twice; switch provider before retry")
            provider_attempts[provider_key] = current_attempts + 1
            context["provider_attempts"] = provider_attempts
            if provider_key not in context.get("providers_tried", []):
                context.setdefault("providers_tried", []).append(provider_key)

            deploy_reason = (
                f"Choosing {provider} because current stack signals and cost analysis suggest better backend compatibility and delivery reliability."
                if provider
                else "Choosing automatic provider selection to balance compatibility, reliability, and monthly cost."
            )
            self._emit(
                "DeploymentAgent",
                "deploying",
                f"Starting deployment attempt {context['deploy_attempts']} via {provider or 'auto'}.",
                {"change": change_tag},
                reasoning=deploy_reason,
                confidence=context.get("confidence"),
                pattern=self._pattern_hint(context, "attempt_deploy"),
            )

            deployed = await deploy_agent.deploy(
                project_name=project["name"],
                files=[{"name": path, "content": content} for path, content in load_source_text_map(self.project_id).items()] or files,
                stack_info=stack_info,
                preferred_provider=provider,
                github_url=source_payload.get("github_url") if isinstance(source_payload, dict) else None,
                env_template=project.get("env_template", "") or "",
            )

            deployment_payload = {
                "provider": deployed.provider,
                "deployment_url": deployed.deployment_url,
                "status": deployed.status,
                "details": deployed.details,
                "app_kind": deployed.app_kind,
            }

            deployment_details = deployed.details if isinstance(deployed.details, dict) else {}
            deployment_action = str(deployment_details.get("action") or "").strip().lower()
            deployment_reason = str(
                deployment_details.get("reason")
                or deployment_details.get("plain_english_error")
                or "Deployment could not produce a public URL."
            ).strip()
            deployment_next_action = str(deployment_details.get("next_action") or "").strip()

            if str(deployed.status).lower() == "blocked" or deployment_action in {"needs_credentials", "حتاج_credentials"}:
                context["fatal_blocker"] = (
                    f"{deployment_reason}"
                    + (f" Next action: {deployment_next_action}" if deployment_next_action else "")
                )
                raise RuntimeError(context["fatal_blocker"])

            if not deployed.deployment_url:
                raise RuntimeError(
                    deployment_reason
                    + (f" Next action: {deployment_next_action}" if deployment_next_action else "")
                )

            self._set_step(ExecutionStep.VERIFICATION)
            is_live, verification = await self._verify_live_url(deployed.deployment_url)
            if not is_live:
                raise RuntimeError(f"Verification failed: {verification}")

            deployment_payload.setdefault("details", {})["verification"] = verification
            self.state.deployment_url = str(deployed.deployment_url or "")
            self.pipeline_states["deployment"] = "done"
            self.pipeline_states["verification"] = "done"
            self.pipeline_states["deployment_agent"] = "done"

            self._set_step(ExecutionStep.MONITORING)
            monitoring_payload = await self._collect_monitoring(
                deployment_url=str(deployment_payload.get("deployment_url") or ""),
                provider=str(deployment_payload.get("provider") or ""),
                deployment_details=deployment_payload.get("details") if isinstance(deployment_payload.get("details"), dict) else {},
            )
            self.pipeline_states["monitoring"] = "done"
            self.pipeline_states["agentic_production_monitor"] = "done"

            self._set_step(ExecutionStep.SELF_HEALING_LOOP)
            self_healing = SelfHealingDeploymentEngineer()
            runtime = (monitoring_payload.get("runtime") or {}) if isinstance(monitoring_payload, dict) else {}
            critical_anomalies = [
                item for item in (runtime.get("anomalies") or [])
                if isinstance(item, dict) and str(item.get("severity") or "").lower() == "critical"
            ]
            self_heal_report: dict[str, Any] = {
                "status": "not_needed",
                "attempts": list(context.get("self_heal_attempts") or []),
                "incidents": [],
            }
            if critical_anomalies:
                heal_result = await self_healing.deploy_with_self_heal(
                    project_id=self.project_id,
                    project_name=project["name"],
                    files=[{"name": path, "content": content} for path, content in load_source_text_map(self.project_id).items()] or files,
                    stack_info=stack_info,
                    preferred_provider=context.get("preferred_provider"),
                    github_url=source_payload.get("github_url") if isinstance(source_payload, dict) else None,
                    env_template=project.get("env_template", "") or "",
                    app_type=str(deployment_payload.get("app_kind") or "backend"),
                    max_attempts=2,
                )
                self_heal_report["status"] = heal_result.get("status", "failed")
                self_heal_report["attempts"].extend(heal_result.get("attempts", []))

            insights.self_healing_report = self_heal_report
            self.pipeline_states["self_healing_loop"] = "done"
            self.pipeline_states["agentic_self_healer"] = "done"

            context["agent_outputs"]["deployment"] = standard_agent_output(
                agent="SelfHealingDeploymentEngineer",
                status="success",
                data={
                    "provider": deployed.provider,
                    "deployment_url": deployed.deployment_url,
                    "attempts": context.get("self_heal_attempts", []),
                },
                confidence=float(context.get("confidence") or 0.75),
                risk="low",
            )
            context["agent_outputs"]["monitoring"] = standard_agent_output(
                agent="ProductionMonitoringAnalyst",
                status="success",
                data=monitoring_payload if isinstance(monitoring_payload, dict) else {},
                confidence=0.8,
                risk="low" if (monitoring_payload or {}).get("status") == "healthy" else "medium",
            )
            context["agent_outputs"]["knowledge"] = standard_agent_output(
                agent="KnowledgeCurationAgent",
                status="success",
                data={"memory_signals": context.get("memory_signals", {})},
                confidence=0.75,
                risk="low",
            )

            context.setdefault("self_heal_attempts", []).append(
                {
                    "attempt": int(context.get("deploy_attempts") or 0),
                    "provider": str(deployed.provider or provider_key),
                    "status": "success",
                    "reason": "deployment_succeeded",
                    "fix_applied": (
                        context.get("fixes_applied", [{}])[-1].get("fix_type")
                        if context.get("fixes_applied")
                        else None
                    ),
                }
            )

            pdf_path = await coordinator.generate_security_pdf(
                project_id=self.project_id,
                project_name=str(project.get("name") or f"project-{self.project_id}"),
                insights=insights,
            )
            update_project(self.project_id, {"security_report_pdf": pdf_path})

            context["goal_achieved"] = True
            context["current_state"] = "deployed_live"
            return {"outcome": "success", "data": deployment_payload}

        async def _action_retry_with_modification() -> dict[str, Any]:
            stack_info = context.get("stack_info") or security_agent._detect_stack(files)
            runtime = str(stack_info.get("runtime") or "").lower()
            used = set(context.get("retry_modifications") or [])

            candidates = ["generate_dockerfile", "switch_provider", "force_local_preview"]
            selected: str | None = None
            for item in candidates:
                if item in used:
                    continue
                if item == "switch_provider" and runtime not in {"node", "unknown"}:
                    continue
                selected = item
                break

            if selected is None:
                context["retry_exhausted"] = True
                raise RuntimeError("No remaining retry modifications available")

            context["retry_modifications"].append(selected)
            if selected == "generate_dockerfile":
                self._maybe_generate_dockerfile(files, stack_info)
            elif selected == "switch_provider":
                await _action_change_platform()
            elif selected == "force_local_preview":
                context["preferred_provider"] = "local"

            result = await _action_attempt_deploy(change_tag=selected)
            result.setdefault("data", {})["modification"] = selected
            return result

        async def _execute_action(action: str) -> dict[str, Any]:
            if action == "analyze_code":
                return await _action_analyze_code()
            if action == "run_security_scan":
                return await _action_run_security_scan()
            if action == "fix_code":
                return await _action_apply_fix()
            if action == "fix_dependencies":
                return await _action_fix_dependencies()
            if action == "run_simulation":
                return await _action_run_simulation()
            if action == "deploy":
                return await _action_attempt_deploy()
            if action == "switch_provider":
                return await _action_change_platform()
            if action == "request_user_input":
                context["fatal_blocker"] = context.get("fatal_blocker") or "Missing required user credentials/configuration"
                return {"outcome": "stopped", "data": {"reason": context["fatal_blocker"]}}
            if action == "fallback_local":
                return await _action_fallback_local()
            if action == "stop_with_explanation":
                if context.get("analysis_only") and context.get("security_scanned"):
                    context["goal_achieved"] = True
                    context["current_state"] = "analysis_complete"
                    self.pipeline_states.setdefault("auto_fixes", "skipped")
                    self.pipeline_states.setdefault("deployment", "skipped")
                    self.pipeline_states.setdefault("verification", "skipped")
                    self.pipeline_states.setdefault("monitoring", "skipped")
                    return {
                        "outcome": "success",
                        "data": {"reason": "Analysis-only mode completed"},
                    }
                context["current_state"] = "stopped"
                stop_reason = (
                    str(context.get("fatal_blocker") or "").strip()
                    or "Meta-agent stop condition reached."
                )
                return {"outcome": "stopped", "data": {"reason": stop_reason}}

            raise RuntimeError(f"Unknown action: {action}")

        try:
            self._set_step(ExecutionStep.INPUT)
            self.pipeline_states["input"] = "done"
            self._emit(
                "ExecutionEngine",
                "input",
                "Input accepted and execution has started.",
                reasoning="I will iteratively decide, act, and reflect so each step adapts to findings instead of following a rigid pipeline.",
                confidence=context.get("confidence"),
            )

            max_iterations = 16
            iteration = 0

            while iteration < max_iterations and not context.get("goal_achieved"):
                self._cycle = iteration + 1
                decision = _decide_action()
                pattern_hint = self._pattern_hint(context, str(decision.get("action") or ""))
                reasoned_thought = self._compose_reasoned_message(
                    base=str(decision.get("thought") or "Preparing next action."),
                    reasoning=str(decision.get("reason") or ""),
                    confidence=float(decision.get("confidence") or 0.0),
                    pattern=pattern_hint or None,
                )
                decision["pattern"] = pattern_hint
                decision["thought"] = reasoned_thought
                context["decision_log"].append(decision)
                self._emit_action(
                    agent="meta_agent",
                    user_message=decision["thought"],
                    action=decision["action"],
                    confidence=decision["confidence"],
                    evidence=[decision["reason"]],
                    data={
                        "agent": "Meta-Agent",
                        "action": decision["action"],
                        "reason": decision["reason"],
                        "decision": {
                            "action": decision["action"],
                            "reason": decision["reason"],
                        },
                        "cycle": self._cycle,
                        "current_state": context.get("current_state"),
                    },
                )

                action = str(decision.get("action") or "stop_with_explanation")
                last_action = str(context.get("last_action") or "")
                if action == last_action and action not in {"fallback_local", "stop_with_explanation"}:
                    if action == "deploy":
                        action = "switch_provider"
                    elif action in {"fix_code", "fix_dependencies"}:
                        action = "run_simulation"
                    else:
                        action = "fallback_local"
                    decision["action"] = action
                    decision["reason"] = "Avoid repeating identical action twice; adapting strategy."
                error_text: str | None = None
                result: dict[str, Any] | None = None
                action_started_at = time.perf_counter()

                try:
                    result = await _execute_action(action)
                    self._emit_stage_log(action, "success", action_started_at)
                    context["actions_taken"].append({"action": action, "result": result})
                    context["current_state"] = "running" if not context.get("goal_achieved") else "goal_achieved"
                except Exception as exc:
                    error_text = str(exc)
                    self._emit_stage_log(action, "failed", action_started_at)
                    self._record_error(exc)
                    failure_type = self._classify_failure(error_text)
                    context["last_failure_type"] = failure_type
                    counts = context.get("failure_type_counts") or {}
                    counts[failure_type] = int(counts.get(failure_type, 0)) + 1
                    context["failure_type_counts"] = counts
                    current_provider = str(context.get("preferred_provider") or "auto")

                    lowered_error = error_text.lower()
                    if "backend deployments require a github repository url" in lowered_error:
                        context["fatal_blocker"] = (
                            "Backend deployment requires a GitHub repository URL or GITHUB_TOKEN "
                            "for temporary repository publishing. Configure GITHUB_TOKEN or provide github_url before redeploying."
                        )
                    elif "workspaceid" in lowered_error and "railway project creation failed" in lowered_error:
                        context["fatal_blocker"] = (
                            "Railway project creation requires workspace context. "
                            "Set RAILWAY_WORKSPACE_ID for automated backend deploys."
                        )

                    context["failures"].append(
                        {
                            "action": action,
                            "error": error_text,
                            "failure_type": failure_type,
                            "provider": current_provider,
                            "iteration": iteration + 1,
                            "cycle": self._cycle,
                        }
                    )
                    context["actions_taken"].append({"action": action, "result": {"outcome": "failure", "error": error_text}})
                    self._emit(
                        "MetaAgent",
                        "reflection",
                        f"Action {action} failed and I am revising strategy for the next step.",
                        reasoning=f"Failure classified as {failure_type}. Details: {error_text}",
                        confidence=context.get("confidence"),
                        pattern=self._pattern_hint(context, action),
                    )
                    if action == "deploy":
                        context["self_heal_attempts"].append(
                            {
                                "attempt": int(context.get("deploy_attempts") or 0),
                                "provider": str(context.get("preferred_provider") or "auto"),
                                "status": "failed",
                                "reason": error_text,
                                "failure_type": failure_type,
                                "fix_applied": (
                                    context.get("fixes_applied", [{}])[-1].get("fix_type")
                                    if context.get("fixes_applied")
                                    else None
                                ),
                            }
                        )
                    if action == "stop_with_explanation":
                        break

                reflection = _reflect(action=action, result=result, error=error_text)
                context["confidence"] = reflection["confidence"]
                context.setdefault("reflections", []).append(reflection)
                context["last_action"] = action
                if result:
                    context["last_outcome"] = result.get("outcome")
                    context["result_classification"] = (
                        "success" if result.get("outcome") == "success" and context.get("goal_achieved")
                        else "partial" if result.get("outcome") == "success"
                        else "failure"
                    )
                elif error_text:
                    context["last_outcome"] = "failure"
                    context["result_classification"] = "failure"

                if action == "stop_with_explanation":
                    break
                iteration += 1

            if not context.get("goal_achieved"):
                self.pipeline_states.setdefault("deployment", "failed")
                self.pipeline_states.setdefault("verification", "failed")
                self.pipeline_states.setdefault("deployment_agent", "failed")
                raise RuntimeError("Meta-agent stopped before goal was achieved")

            final_status = "completed" if context.get("analysis_only") else "live"
            self.state.status = "success"
            self._set_step(ExecutionStep.COMPLETED, status="success")

            chosen_platform = str(context.get("preferred_provider") or "railway")
            insights.deployment_intelligence = {
                **(insights.deployment_intelligence or {}),
                "chosen_platform": chosen_platform,
                "reasoning": debate_result.get("reasoning") if isinstance(debate_result, dict) else None,
                "confidence": context.get("confidence"),
                "debate_transcript": debate_result.get("debate_transcript", []) if isinstance(debate_result, dict) else [],
            }
            insights.cost_optimization = cost_analysis
            insights.production_insights = monitoring_payload

            insights_dict = coordinator.to_dict(insights)
            security_issues = []
            for severity in ("critical", "high", "medium"):
                for issue in ((final_scan.report or {}).get(severity, []) if final_scan else []):
                    if not isinstance(issue, dict):
                        continue
                    security_issues.append(
                        {
                            "severity": severity,
                            "title": issue.get("title") or issue.get("type") or "security_issue",
                            "message": issue.get("description") or issue.get("message") or "Issue detected",
                            "action": issue.get("recommendation") or "Review and remediate",
                        }
                    )

            consolidated_audit = {
                "summary": f"Execution finished with status {final_status}.",
                "security_issues": security_issues,
                "fixes": fix_report.get("applied", []) if isinstance(fix_report, dict) else [],
                "deployment_plan": {
                    "platform": chosen_platform,
                    "reason": (debate_result.get("reasoning") if isinstance(debate_result, dict) else "Deterministic policy selection"),
                    "confidence": float(context.get("confidence") or 0.0),
                },
                "cost_estimate": cost_analysis or {},
                "confidence_score": round(float(context.get("confidence") or 0.0), 2),
            }
            insights_dict["autonomous_audit"] = consolidated_audit
            insights_dict["meta_agent"] = {
                "goal": context.get("goal"),
                "current_state": context.get("current_state"),
                "confidence": context.get("confidence"),
                "decision_log": context.get("decision_log", []),
                "reflections": context.get("reflections", []),
                "actions_taken": context.get("actions_taken", []),
                "failures": context.get("failures", []),
                "fixes_applied": context.get("fixes_applied", []),
                "providers_tried": context.get("providers_tried", []),
                "provider_attempts": context.get("provider_attempts", {}),
                "last_failure_type": context.get("last_failure_type"),
                "self_heal_attempts": context.get("self_heal_attempts", []),
                "memory_signals": context.get("memory_signals", {}),
                "agent_outputs": context.get("agent_outputs", {}),
            }

            update_project(
                self.project_id,
                {
                    "status": final_status,
                    "public_url": deployment_payload.get("deployment_url") if isinstance(deployment_payload, dict) else None,
                    "agentic_insights": insights_dict,
                    "pipeline_state": {
                        "execution_state": asdict(self.state),
                        "pipeline_states": self.pipeline_states,
                    },
                },
            )

            return ExecutionResult(
                security_report=final_scan.report if final_scan else {},
                security_score=int(final_scan.score if final_scan else 0),
                risk_report=risk_dict,
                fix_report=fix_report,
                deployment=deployment_payload,
                graph_stats=graph_stats,
                status=final_status,
                pipeline_states=self.pipeline_states,
                execution_state=asdict(self.state),
                cost_analysis=cost_analysis,
                monitoring=monitoring_payload,
                agent_actions=self.agent_actions,
                security_report_pdf=pdf_path,
                agentic_insights=insights_dict,
            )

        except Exception as exc:
            self._record_error(exc)
            self.state.status = "failed"
            self._set_step(ExecutionStep.FAILED, status="failed")
            update_project(
                self.project_id,
                {
                    "status": "failed",
                    "pipeline_state": {
                        "execution_state": asdict(self.state),
                        "pipeline_states": self.pipeline_states,
                    },
                },
            )
            self._emit("ExecutionEngine", "error", f"Execution failed: {exc}")

            return ExecutionResult(
                security_report=final_scan.report if final_scan else {},
                security_score=int(final_scan.score if final_scan else 0),
                risk_report=risk_dict,
                fix_report=fix_report,
                deployment=deployment_payload,
                graph_stats=graph_stats,
                status="failed",
                pipeline_states=self.pipeline_states,
                execution_state=asdict(self.state),
                cost_analysis=cost_analysis,
                monitoring=monitoring_payload,
                agent_actions=self.agent_actions,
                security_report_pdf=pdf_path,
                agentic_insights={
                    "meta_agent": {
                        "goal": context.get("goal"),
                        "current_state": context.get("current_state"),
                        "confidence": context.get("confidence"),
                        "decision_log": context.get("decision_log", []),
                        "reflections": context.get("reflections", []),
                        "actions_taken": context.get("actions_taken", []),
                        "failures": context.get("failures", []),
                        "fixes_applied": context.get("fixes_applied", []),
                        "providers_tried": context.get("providers_tried", []),
                        "provider_attempts": context.get("provider_attempts", {}),
                        "last_failure_type": context.get("last_failure_type"),
                        "self_heal_attempts": context.get("self_heal_attempts", []),
                        "memory_signals": context.get("memory_signals", {}),
                        "agent_outputs": context.get("agent_outputs", {}),
                    }
                },
            )
