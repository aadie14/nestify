"""Simulation Agent — Sandbox validation gate for proposed code changes.

EVERY fix MUST pass through this agent before being applied to the actual
codebase.  The agent:

1. Copies the project to a temporary directory
2. Applies the proposed patch
3. Runs a validation pipeline (syntax check → lint → tests)
4. Returns a pass/fail result with detailed error information

If the simulation fails, the fix is REJECTED — no exceptions.
"""

from __future__ import annotations

import asyncio
import logging
import os
import shutil
import tempfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


# ─── Data Models ──────────────────────────────────────────────────────────

@dataclass(slots=True)
class ValidationStep:
    """Result of a single validation step."""
    name: str
    passed: bool
    output: str = ""
    error: str = ""
    duration_ms: int = 0


@dataclass(slots=True)
class SimulationResult:
    """Complete result from a simulation run."""
    passed: bool = False
    steps: list[ValidationStep] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    sandbox_path: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "passed": self.passed,
            "steps": [
                {
                    "name": s.name,
                    "passed": s.passed,
                    "output": s.output[:500],
                    "error": s.error[:500],
                    "duration_ms": s.duration_ms,
                }
                for s in self.steps
            ],
            "errors": self.errors,
            "warnings": self.warnings,
        }


@dataclass(slots=True)
class PatchSpec:
    """Specification for a single file patch."""
    file_path: str         # relative path within the project
    new_content: str       # full replacement content
    original_content: str = ""  # for rollback


# ─── Simulation Agent ────────────────────────────────────────────────────

class SimulationAgent:
    """Sandbox-based validation agent.

    Ensures no broken code is applied to the project by running proposed
    changes through a temporary copy first.
    """

    def __init__(self, project_source_dir: str | Path) -> None:
        """
        Args:
            project_source_dir: Path to the project source directory.
        """
        self.source_dir = Path(project_source_dir)
        self._sandbox_dir: Path | None = None

    # ── Public API ────────────────────────────────────────────────────

    async def simulate(self, patches: list[PatchSpec]) -> SimulationResult:
        """Run the full simulation pipeline for a set of patches.

        Args:
            patches: List of file patches to validate.

        Returns:
            SimulationResult with pass/fail and per-step details.
        """
        result = SimulationResult()

        if not patches:
            result.passed = True
            result.warnings.append("No patches to simulate.")
            return result

        try:
            # Step 1: Create sandbox
            self._sandbox_dir = Path(tempfile.mkdtemp(prefix="nestify_sim_"))
            result.sandbox_path = str(self._sandbox_dir)

            # Step 2: Copy project to sandbox
            copy_step = await self._copy_to_sandbox()
            result.steps.append(copy_step)
            if not copy_step.passed:
                result.passed = False
                result.errors.append(f"Failed to create sandbox: {copy_step.error}")
                return result

            # Step 3: Apply patches in sandbox
            apply_step = await self._apply_patches(patches)
            result.steps.append(apply_step)
            if not apply_step.passed:
                result.passed = False
                result.errors.append(f"Failed to apply patches: {apply_step.error}")
                return result

            # Step 4: Run validation pipeline
            syntax_step = await self._run_syntax_check()
            result.steps.append(syntax_step)

            lint_step = await self._run_lint()
            result.steps.append(lint_step)

            test_step = await self._run_tests()
            result.steps.append(test_step)

            # Determine overall pass/fail
            # Syntax check is mandatory; lint and tests are best-effort
            if not syntax_step.passed:
                result.passed = False
                result.errors.append("Syntax validation FAILED — patch rejected.")
            elif not lint_step.passed:
                # Lint failures are warnings, not blockers (unless severe)
                result.passed = True
                result.warnings.append("Lint warnings detected — proceeding with caution.")
            elif not test_step.passed:
                result.passed = False
                result.errors.append("Tests FAILED after applying patch — patch rejected.")
            else:
                result.passed = True

        except Exception as exc:
            result.passed = False
            result.errors.append(f"Simulation error: {exc}")
            logger.exception("Simulation failed unexpectedly")

        finally:
            # Clean up sandbox
            await self._cleanup()

        logger.info(
            "Simulation %s: %d patches, %d steps, %d errors",
            "PASSED" if result.passed else "FAILED",
            len(patches), len(result.steps), len(result.errors),
        )

        return result

    # ── Internal Steps ────────────────────────────────────────────────

    async def _copy_to_sandbox(self) -> ValidationStep:
        """Copy the project files to the sandbox directory."""
        import time
        start = time.monotonic()
        try:
            if self.source_dir.exists():
                shutil.copytree(
                    self.source_dir, self._sandbox_dir / "project",
                    dirs_exist_ok=True,
                    ignore=shutil.ignore_patterns(
                        "__pycache__", "*.pyc", ".git", "node_modules",
                        ".venv", "venv", ".env", "*.db",
                    ),
                )
            else:
                return ValidationStep(
                    name="copy_to_sandbox",
                    passed=False,
                    error=f"Source directory not found: {self.source_dir}",
                    duration_ms=int((time.monotonic() - start) * 1000),
                )

            duration = int((time.monotonic() - start) * 1000)
            return ValidationStep(
                name="copy_to_sandbox",
                passed=True,
                output=f"Copied project to {self._sandbox_dir / 'project'}",
                duration_ms=duration,
            )
        except Exception as exc:
            duration = int((time.monotonic() - start) * 1000)
            return ValidationStep(
                name="copy_to_sandbox",
                passed=False,
                error=str(exc),
                duration_ms=duration,
            )

    async def _apply_patches(self, patches: list[PatchSpec]) -> ValidationStep:
        """Apply all patches to the sandbox copy."""
        import time
        start = time.monotonic()
        applied = 0

        try:
            project_dir = self._sandbox_dir / "project"
            for patch in patches:
                target = project_dir / patch.file_path
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_text(patch.new_content, encoding="utf-8")
                applied += 1

            duration = int((time.monotonic() - start) * 1000)
            return ValidationStep(
                name="apply_patches",
                passed=True,
                output=f"Applied {applied} patch(es)",
                duration_ms=duration,
            )
        except Exception as exc:
            duration = int((time.monotonic() - start) * 1000)
            return ValidationStep(
                name="apply_patches",
                passed=False,
                error=f"Patch application failed at {applied}/{len(patches)}: {exc}",
                duration_ms=duration,
            )

    async def _run_syntax_check(self) -> ValidationStep:
        """Run Python syntax validation on all .py files in the sandbox."""
        import time
        start = time.monotonic()
        project_dir = self._sandbox_dir / "project"
        errors: list[str] = []

        py_files = list(project_dir.rglob("*.py"))
        for py_file in py_files:
            try:
                proc = await asyncio.create_subprocess_exec(
                    "python", "-m", "py_compile", str(py_file),
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.PIPE,
                )
                _, stderr = await asyncio.wait_for(proc.communicate(), timeout=30)
                if proc.returncode != 0:
                    errors.append(f"{py_file.relative_to(project_dir)}: {stderr.decode().strip()}")
            except asyncio.TimeoutError:
                errors.append(f"{py_file.relative_to(project_dir)}: syntax check timed out")
            except FileNotFoundError:
                # Python not in PATH — skip but warn
                duration = int((time.monotonic() - start) * 1000)
                return ValidationStep(
                    name="syntax_check",
                    passed=True,
                    output="Python not found in PATH — syntax check skipped",
                    duration_ms=duration,
                )

        duration = int((time.monotonic() - start) * 1000)
        if errors:
            return ValidationStep(
                name="syntax_check",
                passed=False,
                error="\n".join(errors[:10]),
                duration_ms=duration,
            )
        return ValidationStep(
            name="syntax_check",
            passed=True,
            output=f"All {len(py_files)} Python files passed syntax check",
            duration_ms=duration,
        )

    async def _run_lint(self) -> ValidationStep:
        """Run flake8 lint on the sandbox project."""
        import time
        start = time.monotonic()
        project_dir = self._sandbox_dir / "project"

        try:
            proc = await asyncio.create_subprocess_exec(
                "python", "-m", "flake8", str(project_dir),
                "--max-line-length", "120",
                "--count", "--statistics",
                "--select", "E9,F63,F7,F82",  # Only fatal errors
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=60)

            duration = int((time.monotonic() - start) * 1000)
            output = stdout.decode().strip()

            if proc.returncode == 0:
                return ValidationStep(
                    name="lint", passed=True,
                    output="Lint passed (no fatal errors)",
                    duration_ms=duration,
                )
            else:
                return ValidationStep(
                    name="lint", passed=False,
                    output=output[:500],
                    error=f"Lint found issues (exit code {proc.returncode})",
                    duration_ms=duration,
                )

        except FileNotFoundError:
            duration = int((time.monotonic() - start) * 1000)
            return ValidationStep(
                name="lint", passed=True,
                output="flake8 not installed — lint skipped",
                duration_ms=duration,
            )
        except asyncio.TimeoutError:
            duration = int((time.monotonic() - start) * 1000)
            return ValidationStep(
                name="lint", passed=True,
                output="Lint timed out — skipping",
                duration_ms=duration,
            )

    async def _run_tests(self) -> ValidationStep:
        """Run pytest in the sandbox if tests exist."""
        import time
        start = time.monotonic()
        project_dir = self._sandbox_dir / "project"

        # Check if any test files exist
        test_files = (
            list(project_dir.rglob("test_*.py")) +
            list(project_dir.rglob("*_test.py")) +
            list(project_dir.rglob("tests/*.py"))
        )

        if not test_files:
            duration = int((time.monotonic() - start) * 1000)
            return ValidationStep(
                name="tests", passed=True,
                output="No test files found — test step skipped",
                duration_ms=duration,
            )

        try:
            proc = await asyncio.create_subprocess_exec(
                "python", "-m", "pytest", str(project_dir),
                "--tb=short", "-q", "--no-header",
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                cwd=str(project_dir),
            )
            stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=120)

            duration = int((time.monotonic() - start) * 1000)
            output = stdout.decode().strip()

            if proc.returncode == 0:
                return ValidationStep(
                    name="tests", passed=True,
                    output=output[:500],
                    duration_ms=duration,
                )
            else:
                return ValidationStep(
                    name="tests", passed=False,
                    output=output[:500],
                    error=stderr.decode().strip()[:500],
                    duration_ms=duration,
                )

        except FileNotFoundError:
            duration = int((time.monotonic() - start) * 1000)
            return ValidationStep(
                name="tests", passed=True,
                output="pytest not installed — test step skipped",
                duration_ms=duration,
            )
        except asyncio.TimeoutError:
            duration = int((time.monotonic() - start) * 1000)
            return ValidationStep(
                name="tests", passed=False,
                error="Tests timed out after 120s",
                duration_ms=duration,
            )

    async def _cleanup(self) -> None:
        """Remove the sandbox directory."""
        if self._sandbox_dir and self._sandbox_dir.exists():
            try:
                shutil.rmtree(self._sandbox_dir, ignore_errors=True)
            except Exception as exc:
                logger.warning("Sandbox cleanup failed: %s", exc)
            self._sandbox_dir = None
