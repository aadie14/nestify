"""SecurityAgent — Graph-aware autonomous security analysis.

Scans project files for hardcoded secrets, dependency vulnerabilities,
insecure code patterns, and missing protections.  Uses the code graph
for reachability analysis and feeds findings through the Risk Engine
for multi-factor scoring.
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass, field
from typing import Any

from app.database import add_log, add_scan_result, clear_scan_results
from app.intelligence.graph_builder import CodeGraph, build_project_graph
from app.intelligence.risk_engine import ProjectRiskReport, assess_project
from app.services.scan_service import enrich_with_llm, run_static_source_scan

logger = logging.getLogger(__name__)


@dataclass(slots=True)
class SecurityScanResult:
    """Structured output from a security scan."""
    report: dict[str, list[dict[str, Any]]]
    score: int
    summary: dict[str, int]
    metadata: dict[str, int] = field(default_factory=dict)
    graph: CodeGraph | None = None
    risk_report: ProjectRiskReport | None = None


class SecurityAgent:
    """Graph-aware security scanner with multi-factor risk scoring.

    V2 Enhancements over V1:
      - Builds a code graph and uses it for reachability analysis
      - Replaces simple scoring with the Risk Engine (Exploitability × Impact × Reachability × Sensitivity)
      - Passes graph context to downstream agents (ImpactAgent, FixAgent)
    """

    def __init__(self, project_id: int) -> None:
        self.project_id = project_id
        self._graph: CodeGraph | None = None

    @property
    def graph(self) -> CodeGraph | None:
        """The code graph from the last scan — used by downstream agents."""
        return self._graph

    def _detect_stack(self, files: list[dict[str, str]]) -> dict[str, Any]:
        """Lightweight project stack detection from file names and content."""
        names = [f.get("name", "") for f in files]
        stack_info: dict[str, Any] = {
            "framework": "unknown",
            "runtime": "unknown",
            "security_flags": [],
        }

        # Runtime detection
        if any(n.endswith("requirements.txt") or n.endswith(".py") for n in names):
            stack_info["runtime"] = "python"
        elif any(n.endswith("package.json") for n in names):
            stack_info["runtime"] = "node"
        elif any(n.endswith("go.mod") for n in names):
            stack_info["runtime"] = "go"

        # Framework detection
        for f in files:
            if f.get("name", "").endswith("package.json"):
                content = f.get("content", "")
                if '"react"' in content:
                    stack_info["framework"] = "react"
                elif '"vue"' in content:
                    stack_info["framework"] = "vue"
                elif '"svelte"' in content:
                    stack_info["framework"] = "svelte"
                elif '"next"' in content:
                    stack_info["framework"] = "next"
                elif '"express"' in content:
                    stack_info["framework"] = "express"
            if f.get("name", "").endswith(".py"):
                content = f.get("content", "")
                if "fastapi" in content.lower():
                    stack_info["framework"] = "fastapi"
                elif "flask" in content.lower():
                    stack_info["framework"] = "flask"
                elif "django" in content.lower():
                    stack_info["framework"] = "django"

        return stack_info

    async def scan(
        self,
        files: list[dict[str, str]],
        stack_info: dict[str, Any] | None = None,
    ) -> SecurityScanResult:
        """Run a full graph-aware security scan.

        Args:
            files: List of {"name": str, "content": str} file objects.
            stack_info: Optional pre-computed stack analysis.

        Returns:
            SecurityScanResult with report, risk-engine score, graph, and risk report.
        """
        add_log(self.project_id, "SecurityAgent", "Starting graph-aware security scan", "info")
        # Emit initial progress so UI shows scanning has started
        try:
            from app.routes.upload import _append_progress
            _append_progress(self.project_id, {"agent": "SecurityAgent", "phase": "scanning", "message": "Starting graph-aware security scan", "progress": 0})
        except Exception:
            pass

        # ── Step 1: Build the code graph ────────────────────────────────
        try:
            self._graph = build_project_graph(files)
            graph_stats = self._graph.to_dict().get("stats", {})
            add_log(
                self.project_id, "SecurityAgent",
                f"Code graph built: {graph_stats.get('functions', 0)} functions, "
                f"{graph_stats.get('classes', 0)} classes, "
                f"{graph_stats.get('imports', 0)} imports",
                "info",
            )
            try:
                from app.routes.upload import _append_progress
                _append_progress(self.project_id, {"agent": "SecurityAgent", "phase": "scanning", "message": "Code graph built", "progress": 5})
            except Exception:
                pass
        except Exception as exc:
            add_log(self.project_id, "SecurityAgent", f"Graph build failed: {exc}", "warn")
            self._graph = None

        # ── Step 2: Detect stack ────────────────────────────────────────
        if stack_info is None:
            stack_info = self._detect_stack(files)

        # ── Step 3: Run deterministic pattern scan ──────────────────────
        # Emit incremental progress while scanning files so frontend shows real-time coverage.
        report = {}
        try:
            total = max(1, len(files))
            # Process files in batches to avoid flooding progress messages.
            batch = 50
            for i in range(0, total, batch):
                chunk = files[i : i + batch]
                # Let the existing deterministic scanner handle the chunk; it's fast and synchronous.
                partial = run_static_source_scan(chunk, stack_info)
                # Merge partial report into overall report structure
                for k, v in (partial or {}).items():
                    report.setdefault(k, []).extend(v if isinstance(v, list) else [v])
                # Emit progress
                try:
                    from app.routes.upload import _append_progress
                    pct = int(min(90, ((i + len(chunk)) / total) * 80) + 5)
                    _append_progress(self.project_id, {"agent": "SecurityAgent", "phase": "scanning", "message": f"Scanned {i + len(chunk)}/{total} files", "progress": pct})
                except Exception:
                    pass
        except Exception:
            # Fallback: run whole-scan if batch scanning failed
            report = run_static_source_scan(files, stack_info)

        # ── Step 4: LLM enrichment ──────────────────────────────────────
        try:
            # Keep analysis deterministic: skip LLM enrichment when providers are slow.
            report = await asyncio.wait_for(
                enrich_with_llm(report, files, stack_info),
                timeout=20,
            )
            try:
                from app.routes.upload import _append_progress
                _append_progress(self.project_id, {"agent": "SecurityAgent", "phase": "scanning", "message": "LLM enrichment completed", "progress": 92})
            except Exception:
                pass
        except Exception as error:
            add_log(self.project_id, "SecurityAgent", f"LLM enrichment skipped: {error}", "warn")

        # ── Step 5: Multi-factor risk scoring ───────────────────────────
        risk_report = assess_project(report, self._graph)
        score = risk_report.overall_score_100

        summary = risk_report.stats

        # Count total issues and metadata
        total_issues = sum(len(findings) for findings in report.values())
        dep_files = sum(
            1 for f in files
            if f.get("name", "").endswith(("package.json", "requirements.txt", "go.mod", "Gemfile", "Cargo.toml"))
        )
        metadata = {
            "files_scanned": len(files),
            "dependencies_scanned": dep_files,
            "issues_found": total_issues,
            "graph_nodes": len(self._graph.nodes) if self._graph else 0,
            "graph_edges": len(self._graph.edges) if self._graph else 0,
        }

        # ── Step 6: Persist findings to database ───────────────────────
        clear_scan_results(self.project_id)
        for severity, findings in report.items():
            for finding in findings:
                add_scan_result(
                    project_id=self.project_id,
                    severity=severity,
                    issue_type=finding.get("type", "unknown"),
                    description=finding.get("description", ""),
                    file=finding.get("file"),
                    line=finding.get("line"),
                    recommendation=finding.get("recommendation"),
                    source=finding.get("source", "pattern_scan"),
                )

        add_log(
            self.project_id,
            "SecurityAgent",
            f"Scan complete: {summary.get('critical', 0)} critical, "
            f"{summary.get('high', 0)} high, {summary.get('medium', 0)} medium "
            f"— safety score {score}/100 (risk engine)",
            "info",
        )

        return SecurityScanResult(
            report=report,
            score=score,
            summary=summary,
            metadata=metadata,
            graph=self._graph,
            risk_report=risk_report,
        )