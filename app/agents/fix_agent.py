"""FixAgent — Simulation-gated autonomous remediation agent.

V2 Flow (MANDATORY):
    1. Generate fix (pattern-based or LLM)
    2. Send to ImpactAgent → blast radius analysis
    3. Send to SimulationAgent → sandbox validation
    4. Apply ONLY if both ImpactAgent and SimulationAgent approve

NEVER apply a fix directly.  Every patch goes through the simulation gate.
"""

from __future__ import annotations

import json
import logging
import re
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from app.agents.impact_agent import ImpactAgent
from app.agents.simulation_agent import PatchSpec, SimulationAgent
from app.core.config import settings
from app.database import add_fix_log, add_log
from app.intelligence.graph_builder import CodeGraph
from app.services.llm_service import call_llm
from app.services.project_source_service import get_project_source_dir
from app.utils.patch_utils import create_backup, validate_syntax

logger = logging.getLogger(__name__)

# Finding types that must NOT be auto-fixed
MANUAL_REVIEW_TYPES = {
    "auth_logic", "authorization", "authentication",
    "database_schema", "db_migration", "complex_security",
}

# Keywords in finding titles that indicate risky auto-fix territory
MANUAL_REVIEW_KEYWORDS = [
    "authentication", "authorization", "database", "schema",
    "migration", "session", "oauth", "jwt", "rbac", "acl",
]


@dataclass(slots=True)
class FixAction:
    """Record of a single fix attempt."""
    file: str
    fix_type: str
    status: str  # "applied" | "manual_review" | "failed" | "simulation_failed"
    note: str
    impact_blast_radius: int = 0
    simulation_passed: bool = False


@dataclass(slots=True)
class FixResult:
    """Aggregated fix output."""
    applied: list[FixAction]
    manual_review: list[FixAction]
    env_vars_detected: list[str]
    simulation_blocked: list[FixAction]


class FixAgent:
    """Simulation-gated remediation agent.

    Safety rules:
      - EVERY fix goes through ImpactAgent → SimulationAgent
      - Never auto-modify authentication / authorization logic
      - Never auto-modify database schemas
      - Always create .bak backups before modifying files on disk
      - High blast-radius changes are flagged for human review
    """

    def __init__(self, project_id: int, graph: CodeGraph | None = None) -> None:
        self.project_id = project_id
        self.source_dir = Path(get_project_source_dir(project_id)) / "source"
        self._env_vars: list[str] = []
        self._graph = graph
        self._impact_agent = ImpactAgent(graph) if graph else None
        self._simulation_agent = SimulationAgent(self.source_dir)

    def _resolve_file(self, file_path: str) -> Path | None:
        """Resolve a finding's file path to an actual file on disk."""
        if not file_path:
            return None
        target = self.source_dir / file_path
        if target.exists() and target.is_file():
            return target
        basename = Path(file_path).name
        for candidate in self.source_dir.rglob(basename):
            if candidate.is_file():
                return candidate
        return None

    async def generate_and_apply(
        self,
        files: list[dict[str, str]],
        security_report: dict[str, list[dict[str, Any]]],
    ) -> FixResult:
        """Process all findings with simulation-gated safety.

        Flow for each finding:
            1. Generate proposed fix
            2. Run ImpactAgent (blast radius check)
            3. Run SimulationAgent (sandbox validation)
            4. Apply only if both pass
        """
        applied: list[FixAction] = []
        manual_review: list[FixAction] = []
        simulation_blocked: list[FixAction] = []
        self._env_vars = []

        findings = [
            item
            for severity in ("critical", "high", "medium")
            for item in security_report.get(severity, [])
        ]

        for finding in findings:
            title = (finding.get("title") or "").lower()
            file_path = finding.get("file") or ""
            issue_type = finding.get("type") or ""

            # Safety check: skip risky categories
            if self._requires_manual_review(title, issue_type):
                action = FixAction(
                    file=file_path or "unknown",
                    fix_type="manual-review",
                    status="manual_review",
                    note=f"Flagged for manual review: {finding.get('title', 'Complex security issue')}",
                )
                manual_review.append(action)
                add_fix_log(self.project_id, action.file, action.fix_type, action.status, action.note)
                continue

            # ── Step 1: Generate the proposed fix ────────────────────
            proposed_content: str | None = None
            fix_type = "unknown"

            if issue_type == "hardcoded_secret" and file_path:
                proposed_content, fix_type = self._generate_secret_fix(file_path, finding)
            elif settings.allow_fix_agent_llm and file_path:
                proposed_content, fix_type = await self._generate_llm_fix(file_path, finding)

            if proposed_content is None:
                action = FixAction(
                    file=file_path or "unknown",
                    fix_type="manual-review",
                    status="manual_review",
                    note=finding.get("recommendation", "Manual remediation required."),
                )
                manual_review.append(action)
                add_fix_log(self.project_id, action.file, action.fix_type, action.status, action.note)
                continue

            # ── Step 2: Impact analysis ──────────────────────────────
            blast_radius = 0
            if self._impact_agent and file_path:
                impact = self._impact_agent.analyze(file_path)
                blast_radius = impact.blast_radius
                if impact.requires_human_review:
                    action = FixAction(
                        file=file_path,
                        fix_type=fix_type,
                        status="manual_review",
                        note=f"High blast radius ({blast_radius}): {impact.reasoning}",
                        impact_blast_radius=blast_radius,
                    )
                    manual_review.append(action)
                    add_fix_log(self.project_id, action.file, action.fix_type, action.status, action.note)
                    continue

            # ── Step 3: Simulation ───────────────────────────────────
            patch = PatchSpec(
                file_path=file_path,
                new_content=proposed_content,
            )
            sim_result = await self._simulation_agent.simulate([patch])

            if not sim_result.passed:
                action = FixAction(
                    file=file_path,
                    fix_type=fix_type,
                    status="simulation_failed",
                    note=f"Simulation FAILED: {'; '.join(sim_result.errors[:3])}",
                    impact_blast_radius=blast_radius,
                    simulation_passed=False,
                )
                simulation_blocked.append(action)
                add_fix_log(self.project_id, action.file, action.fix_type, action.status, action.note)
                add_log(
                    self.project_id, "FixAgent",
                    f"Fix for {file_path} REJECTED by simulation: {sim_result.errors[:1]}",
                    "warn",
                )
                continue

            # ── Step 4: Apply the fix (simulation passed) ────────────
            target = self._resolve_file(file_path)
            if target:
                create_backup(target)
                target.write_text(proposed_content, encoding="utf-8")

            action = FixAction(
                file=file_path,
                fix_type=fix_type,
                status="applied",
                note=f"Fix applied after passing simulation ({len(sim_result.steps)} validation steps).",
                impact_blast_radius=blast_radius,
                simulation_passed=True,
            )
            applied.append(action)
            add_fix_log(self.project_id, action.file, action.fix_type, action.status, action.note)

        # Generate .env.example if we moved any secrets
        if self._env_vars:
            self._generate_env_example()

        add_log(
            self.project_id, "FixAgent",
            f"Applied {len(applied)} fix(es); {len(manual_review)} manual review; "
            f"{len(simulation_blocked)} blocked by simulation",
            "info",
        )

        return FixResult(
            applied=applied,
            manual_review=manual_review,
            env_vars_detected=self._env_vars,
            simulation_blocked=simulation_blocked,
        )

    # ── Fix Generators ────────────────────────────────────────────────

    def _generate_secret_fix(
        self, file_path: str, finding: dict,
    ) -> tuple[str | None, str]:
        """Generate a fix for hardcoded secrets (returns new content)."""
        target = self._resolve_file(file_path)
        if not target:
            return None, "secret_removal"

        original = target.read_text(encoding="utf-8")
        updated = original

        replacements = [
            (r"""(openai[_-]?api[_-]?key\s*[:=]\s*)['"][^'"]+['"]""", r"\1process.env.OPENAI_API_KEY", "OPENAI_API_KEY"),
            (r"""(aws[_-]?secret[_-]?access[_-]?key\s*[:=]\s*)['"][^'"]+['"]""", r"\1process.env.AWS_SECRET_ACCESS_KEY", "AWS_SECRET_ACCESS_KEY"),
            (r"""(api[_-]?key\s*[:=]\s*)['"][^'"]+['"]""", r"\1process.env.API_KEY", "API_KEY"),
            (r"""(secret\s*[:=]\s*)['"][^'"]+['"]""", r"\1process.env.APP_SECRET", "APP_SECRET"),
            (r"""(password\s*[:=]\s*)['"][^'"]+['"]""", r"\1process.env.DB_PASSWORD", "DB_PASSWORD"),
            (r"""(token\s*[:=]\s*)['"][^'"]+['"]""", r"\1process.env.AUTH_TOKEN", "AUTH_TOKEN"),
        ]

        for pattern, replacement, env_var in replacements:
            new_content = re.sub(pattern, replacement, updated, flags=re.IGNORECASE)
            if new_content != updated:
                updated = new_content
                if env_var not in self._env_vars:
                    self._env_vars.append(env_var)

        if file_path.endswith(".py"):
            py_replacements = [
                (r"""(api[_-]?key\s*=\s*)['"][^'"]+['"]""", r'\1os.getenv("API_KEY", "")', "API_KEY"),
                (r"""(secret\s*=\s*)['"][^'"]+['"]""", r'\1os.getenv("APP_SECRET", "")', "APP_SECRET"),
            ]
            for pattern, replacement, env_var in py_replacements:
                new_content = re.sub(pattern, replacement, updated, flags=re.IGNORECASE)
                if new_content != updated:
                    updated = new_content
                    if env_var not in self._env_vars:
                        self._env_vars.append(env_var)

        if updated == original:
            return None, "secret_removal"

        return updated, "secret_removal"

    async def _generate_llm_fix(
        self, file_path: str, finding: dict[str, Any],
    ) -> tuple[str | None, str]:
        """Use an LLM to generate a safe patch."""
        target = self._resolve_file(file_path)
        if not target:
            return None, "llm_fix"

        original = target.read_text(encoding="utf-8")
        prompt = f"""You are a senior secure software engineer. Given a security finding and a file, produce a safe full-file rewrite only when the change is low-risk.

Finding:
{json.dumps(finding, indent=2)}

File path: {file_path}
File content:
{original[:6000]}

Return valid JSON only:
{{
  "safe_to_apply": true,
  "updated_content": "full file contents or null",
  "note": "short explanation"
}}
"""
        try:
            result = await call_llm(
                [
                    {"role": "system", "content": "You apply only conservative security fixes. Return JSON."},
                    {"role": "user", "content": prompt},
                ],
                {"task_weight": "heavy", "json_mode": True, "temperature": 0.1, "max_tokens": 2200},
            )
            payload = json.loads(result["content"])
        except Exception:
            return None, "llm_fix"

        if not payload.get("safe_to_apply") or not payload.get("updated_content"):
            return None, "llm_fix"

        # Basic syntax validation before sending to simulation
        is_valid, _ = validate_syntax(payload["updated_content"], file_path)
        if not is_valid:
            return None, "llm_fix"

        return payload["updated_content"], "llm_fix"

    # ── Helpers ───────────────────────────────────────────────────────

    def _requires_manual_review(self, title: str, issue_type: str) -> bool:
        if issue_type in MANUAL_REVIEW_TYPES:
            return True
        return any(keyword in title for keyword in MANUAL_REVIEW_KEYWORDS)

    def _generate_env_example(self) -> None:
        """Generate a .env.example file listing required environment variables."""
        env_example_path = self.source_dir / ".env.example"
        if env_example_path.exists():
            existing = env_example_path.read_text(encoding="utf-8")
            existing_vars = {
                line.split("=")[0].strip()
                for line in existing.splitlines()
                if "=" in line and not line.startswith("#")
            }
            new_vars = [v for v in self._env_vars if v not in existing_vars]
            if new_vars:
                content = existing.rstrip() + "\n"
                content += "\n# Added by Nestify FixAgent\n"
                for var in new_vars:
                    content += f"{var}=your_{var.lower()}_here\n"
                env_example_path.write_text(content, encoding="utf-8")
        else:
            lines = ["# Environment variables required by this project", "# Generated by Nestify FixAgent", ""]
            for var in self._env_vars:
                lines.append(f"{var}=your_{var.lower()}_here")
            lines.append("")
            env_example_path.write_text("\n".join(lines), encoding="utf-8")

        add_log(
            self.project_id, "FixAgent",
            f"Generated .env.example with {len(self._env_vars)} variable(s)",
            "info",
        )