"""Agent 1: Code Intelligence Analyst.

Wraps existing graph output and augments it with semantic profiling.
"""

from __future__ import annotations

import asyncio
from collections import Counter
from typing import Any

from app.agentic.llm_router import call_agentic_llm
from app.agentic.models import CodeProfile
from app.intelligence.graph_builder import CodeGraph, NodeType


class CodeIntelligenceAnalyst:
    """Generate a semantic code profile from existing intelligence artifacts."""

    def _infer_runtime_framework(self, files: list[dict[str, str]]) -> tuple[str, str]:
        runtime = "unknown"
        framework = "unknown"

        for file in files:
            name = file.get("name", "")
            content = file.get("content", "")
            if name.endswith("requirements.txt") or name.endswith(".py"):
                runtime = "python"
            if name.endswith("package.json"):
                runtime = "node"
                package_blob = content.lower()
                if '"next"' in package_blob:
                    framework = "nextjs"
                elif '"react"' in package_blob:
                    framework = "react"
                elif '"vue"' in package_blob:
                    framework = "vue"
                elif '"svelte"' in package_blob:
                    framework = "svelte"

            lowered = content.lower()
            if "fastapi" in lowered:
                framework = "fastapi"
            elif "flask" in lowered:
                framework = "flask"
            elif "django" in lowered:
                framework = "django"

        return runtime, framework

    def _extract_dependencies(self, files: list[dict[str, str]], graph: CodeGraph | None) -> list[str]:
        deps: set[str] = set()

        for file in files:
            name = file.get("name", "")
            content = file.get("content", "")
            if name.endswith("requirements.txt"):
                for raw in content.splitlines():
                    line = raw.strip()
                    if not line or line.startswith("#"):
                        continue
                    deps.add(line.split("==", 1)[0].split(">=", 1)[0].strip())
            if name.endswith("package.json"):
                for marker in ["\"dependencies\"", "\"devDependencies\""]:
                    if marker in content:
                        deps.add("package.json:declared")

        if graph:
            for node in graph.get_nodes_by_type(NodeType.IMPORT):
                top = node.name.split(".", 1)[0]
                if top:
                    deps.add(top)

        return sorted(dep for dep in deps if dep)

    def _detect_external_services(self, dependencies: list[str]) -> list[str]:
        service_markers = {
            "postgres": "postgresql",
            "psycopg2": "postgresql",
            "redis": "redis",
            "pymongo": "mongodb",
            "mysql": "mysql",
            "boto3": "aws",
            "stripe": "stripe",
            "openai": "llm_api",
            "httpx": "external_http",
            "requests": "external_http",
            "qdrant": "vector_db",
            "neo4j": "graph_db",
        }
        services: set[str] = set()
        for dep in dependencies:
            marker = service_markers.get(dep.lower())
            if marker:
                services.add(marker)
        return sorted(services)

    def _predict_resources(self, graph: CodeGraph | None, dependencies: list[str]) -> dict[str, Any]:
        function_count = len(graph.get_nodes_by_type(NodeType.FUNCTION)) if graph else 0
        class_count = len(graph.get_nodes_by_type(NodeType.CLASS)) if graph else 0

        complexity = function_count + class_count * 2 + len(dependencies)
        if complexity < 40:
            return {"cpu": "0.25", "memory_mb": 256, "confidence": 0.65}
        if complexity < 120:
            return {"cpu": "0.5", "memory_mb": 512, "confidence": 0.75}
        return {"cpu": "1.0", "memory_mb": 1024, "confidence": 0.8}

    async def analyze(self, files: list[dict[str, str]], graph: CodeGraph | None) -> CodeProfile:
        runtime, framework = self._infer_runtime_framework(files)
        dependencies = self._extract_dependencies(files, graph)
        services = self._detect_external_services(dependencies)
        resource_prediction = self._predict_resources(graph, dependencies)

        node_count = len(graph.nodes) if graph else 0
        edge_count = len(graph.edges) if graph else 0
        complexity_score = min(100, int((node_count * 0.4) + (edge_count * 0.2) + (len(dependencies) * 1.5)))

        app_type = "backend"
        if framework in {"react", "nextjs", "vue", "svelte"}:
            app_type = "frontend"
        if any(f.get("name", "").endswith("index.html") for f in files) and runtime != "python":
            app_type = "static"

        likely_failure_modes = [
            "missing_environment_variables",
            "provider_runtime_mismatch",
        ]
        if "postgresql" in services and "redis" not in services:
            likely_failure_modes.append("database_connection_retries_needed")
        if runtime == "unknown":
            likely_failure_modes.append("stack_detection_uncertain")

        architecture_hint = self._infer_architecture(graph)
        llm_reasoning = await self._build_reasoning(app_type, framework, architecture_hint, dependencies, services)

        return CodeProfile(
            app_type=app_type,
            framework=framework,
            runtime=runtime,
            dependencies=dependencies[:60],
            external_services=services,
            resource_prediction=resource_prediction,
            deployment_complexity_score=complexity_score,
            likely_failure_modes=likely_failure_modes,
            reasoning=llm_reasoning,
        )

    def _infer_architecture(self, graph: CodeGraph | None) -> str:
        if not graph:
            return "unknown"

        file_nodes = graph.get_nodes_by_type(NodeType.FILE)
        files_by_dir = Counter(node.file_path.split("/", 1)[0] for node in file_nodes if "/" in node.file_path)
        if len(files_by_dir) >= 5 and any(count > 3 for count in files_by_dir.values()):
            return "modular_monolith"
        if len(file_nodes) <= 4:
            return "small_service"
        return "monolith"

    async def _build_reasoning(
        self,
        app_type: str,
        framework: str,
        architecture_hint: str,
        dependencies: list[str],
        services: list[str],
    ) -> str:
        prompt = (
            "Summarize deployment architecture risk in 4 concise bullet points. "
            "Focus on runtime fit, dependency risk, and likely deployment failure modes.\n\n"
            f"app_type={app_type}\n"
            f"framework={framework}\n"
            f"architecture={architecture_hint}\n"
            f"dependencies={dependencies[:20]}\n"
            f"services={services}\n"
        )
        try:
            response = await asyncio.wait_for(
                call_agentic_llm(
                    [
                        {"role": "system", "content": "You are a senior software architect producing concise deployment analysis."},
                        {"role": "user", "content": prompt},
                    ],
                    {"temperature": 0.1, "max_tokens": 400, "task_weight": "heavy"},
                ),
                timeout=20,
            )
            return response.get("content", "").strip()[:1500]
        except Exception:
            return (
                f"Architecture hint: {architecture_hint}. "
                f"Framework/runtime: {framework}/{app_type}. "
                f"Dependencies observed: {len(dependencies)}. "
                "Use simulation-gated remediation before production deployment."
            )
