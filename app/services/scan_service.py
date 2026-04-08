"""Security scanning tools with line-level detection and result normalization."""

from __future__ import annotations

import json
import re
from typing import Any

from app.services.llm_service import call_llm

SEVERITY_BUCKETS = ("critical", "high", "medium", "info")

# ─── Detection Patterns ─────────────────────────────────────────

SECRET_PATTERNS: list[tuple[re.Pattern, str, str]] = [
    (re.compile(r"""(?:openai[_-]?api[_-]?key|OPENAI_API_KEY)\s*[:=]\s*['"][^'"]{10,}['"]""", re.IGNORECASE), "Hardcoded OpenAI API key", "hardcoded_secret"),
    (re.compile(r"""(?:aws[_-]?secret|AWS_SECRET_ACCESS_KEY)\s*[:=]\s*['"][^'"]{10,}['"]""", re.IGNORECASE), "Hardcoded AWS secret", "hardcoded_secret"),
    (re.compile(r"""(?:api[_-]?key|apikey|API_KEY)\s*[:=]\s*['"][^'"]{10,}['"]""", re.IGNORECASE), "Hardcoded API key", "hardcoded_secret"),
    (re.compile(r"""(?:secret|password|passwd|token)\s*[:=]\s*['"][^'"]{8,}['"]""", re.IGNORECASE), "Hardcoded secret or password", "hardcoded_secret"),
    (re.compile(r"""(?:sk-[a-zA-Z0-9]{20,}|ghp_[a-zA-Z0-9]{36,}|glpat-[a-zA-Z0-9-]{20,})"""), "Leaked credential token", "hardcoded_secret"),
]

INSECURE_PATTERNS: list[tuple[re.Pattern, str, str, str]] = [
    (re.compile(r"""eval\s*\("""), "Use of eval()", "insecure_pattern", "high"),
    (re.compile(r"""innerHTML\s*="""), "Direct innerHTML assignment (XSS risk)", "insecure_pattern", "medium"),
    (re.compile(r"""document\.write\s*\("""), "Use of document.write()", "insecure_pattern", "medium"),
    (re.compile(r"""subprocess\.call\(.*shell\s*=\s*True""", re.IGNORECASE), "Shell injection risk via subprocess", "insecure_pattern", "high"),
    (re.compile(r"""CORS\s*\(\s*\*\s*\)|allow_origins\s*=\s*\[\s*['\"]?\*['\"]?\s*\]""", re.IGNORECASE), "Wildcard CORS policy", "insecure_pattern", "medium"),
]

CSRF_PATTERNS = [
    re.compile(r"""app\.post\(""", re.IGNORECASE),
    re.compile(r"""@app\.post""", re.IGNORECASE),
]


# ─── Helpers ─────────────────────────────────────────────────────


def empty_security_report() -> dict[str, list[dict[str, Any]]]:
    """Return a blank security report structure."""
    return {bucket: [] for bucket in SEVERITY_BUCKETS}


def _push(
    report: dict[str, list[dict[str, Any]]],
    severity: str,
    finding: dict[str, Any],
) -> None:
    """Append a finding to the appropriate severity bucket."""
    report.setdefault(severity, []).append(finding)


def _find_line_number(content: str, pattern: re.Pattern) -> int | None:
    """Find the 1-based line number of the first match."""
    match = pattern.search(content)
    if not match:
        return None
    return content[:match.start()].count("\n") + 1


# ─── Core Scanner ────────────────────────────────────────────────


def run_static_source_scan(
    files: list[dict[str, str]],
    stack_info: dict[str, Any] | None = None,
) -> dict[str, list[dict[str, Any]]]:
    """
    Run deterministic pattern-based security scanning across all project files.

    Returns a structured report with findings grouped by severity.
    """
    report = empty_security_report()
    stack_info = stack_info or {}

    for file_info in files:
        name = file_info.get("name", "unknown")
        content = file_info.get("content", "")

        # Secret detection
        for pattern, title, issue_type in SECRET_PATTERNS:
            if pattern.search(content):
                line = _find_line_number(content, pattern)
                _push(report, "critical", {
                    "type": issue_type,
                    "title": title,
                    "file": name,
                    "line": line,
                    "severity": "critical",
                    "description": f"{title} detected in {name}.",
                    "recommendation": "Move the secret to an environment variable and load it at runtime.",
                    "source": "pattern_scan",
                })
                break  # One secret finding per file

        # Insecure code patterns
        for pattern, title, issue_type, severity in INSECURE_PATTERNS:
            if pattern.search(content):
                line = _find_line_number(content, pattern)
                _push(report, severity, {
                    "type": issue_type,
                    "title": title,
                    "file": name,
                    "line": line,
                    "severity": severity,
                    "description": f"{title} found in {name}.",
                    "recommendation": "Review and replace with a secure alternative.",
                    "source": "pattern_scan",
                })

        # CSRF check
        if any(p.search(content) for p in CSRF_PATTERNS):
            if "csrf" not in content.lower() and "xsrf" not in content.lower():
                _push(report, "high", {
                    "type": "missing_csrf",
                    "title": "Missing CSRF protection on POST endpoint",
                    "file": name,
                    "line": None,
                    "severity": "high",
                    "description": f"POST handlers found in {name} without CSRF protection.",
                    "recommendation": "Add CSRF middleware or token validation.",
                    "source": "pattern_scan",
                })

        # Dependency checks
        if name.endswith("package.json"):
            _scan_package_json(content, name, report)

        if name.endswith("requirements.txt"):
            _scan_requirements_txt(content, name, report)

        # .env file exposure
        if name == ".env" or name.endswith("/.env"):
            _push(report, "critical", {
                "type": "env_exposure",
                "title": "Environment file included in project",
                "file": name,
                "line": None,
                "severity": "critical",
                "description": "A .env file with potential secrets is included in the deployed project.",
                "recommendation": "Add .env to .gitignore and remove from repository.",
                "source": "pattern_scan",
            })

    # Stack-level security flags
    for flag in stack_info.get("security_flags", []):
        _push(report, flag.get("severity", "high"), {
            "type": "stack_flag",
            "title": flag.get("issue", "Security finding"),
            "file": flag.get("file", "unknown"),
            "line": None,
            "severity": flag.get("severity", "high"),
            "description": flag.get("issue", "Security finding detected by stack analysis."),
            "recommendation": "Review the flagged file and move sensitive values into managed configuration.",
            "source": "stack_analysis",
        })

    return report


def _scan_package_json(content: str, name: str, report: dict) -> None:
    """Check package.json for outdated or vulnerable dependencies."""
    if '"react": "17' in content or '"react": "16' in content:
        _push(report, "medium", {
            "type": "dependency_vuln",
            "title": "Outdated React major version",
            "file": name,
            "line": None,
            "severity": "medium",
            "description": "An outdated React version was detected. Upgrade is recommended.",
            "recommendation": "Upgrade React and react-dom to a maintained 18.x release.",
            "source": "dependency_hint",
        })


def _scan_requirements_txt(content: str, name: str, report: dict) -> None:
    """Check requirements.txt for known vulnerable packages."""
    vulnerable_packages = {
        "flask": ("1.", "Outdated Flask version detected"),
        "django": ("1.", "Outdated Django version (1.x) detected"),
        "requests": ("2.19", "Outdated requests version with known CVEs"),
    }
    for line in content.splitlines():
        line = line.strip().lower()
        if not line or line.startswith("#"):
            continue
        for pkg, (version_prefix, description) in vulnerable_packages.items():
            if line.startswith(pkg) and f"=={version_prefix}" in line:
                _push(report, "medium", {
                    "type": "dependency_vuln",
                    "title": description,
                    "file": name,
                    "line": None,
                    "severity": "medium",
                    "description": f"{description} in {name}.",
                    "recommendation": f"Upgrade {pkg} to the latest stable version.",
                    "source": "dependency_hint",
                })


# ─── LLM Enrichment ─────────────────────────────────────────────


async def enrich_with_llm(
    report: dict[str, list[dict[str, Any]]],
    files: list[dict[str, str]],
    stack_info: dict[str, Any] | None = None,
) -> dict[str, list[dict[str, Any]]]:
    """Use an LLM to identify additional security findings beyond pattern matching."""
    source_context = "\n\n".join(
        f"--- {f['name']} ---\n{f['content'][:1500]}"
        for f in files[:6]
    )
    prompt = f"""You are a senior application security engineer. Review the project snippets and extend the existing structured report only when you find clear additional risks.

STACK INFO:
{json.dumps(stack_info or {}, indent=2)}

CURRENT REPORT:
{json.dumps(report, indent=2)}

SOURCE SNIPPETS:
{source_context or '(none)'}

Return only valid JSON in this shape:
{{
  "critical": [],
  "high": [],
  "medium": [],
  "info": []
}}

Each item must include: type, title, file, line (int or null), severity, description, recommendation, source.
Avoid duplicates with the current report.
"""

    result = await call_llm(
        [
            {"role": "system", "content": "You are a precise application security reviewer. Return only JSON."},
            {"role": "user", "content": prompt},
        ],
        {"task_weight": "heavy", "json_mode": True, "temperature": 0.1, "max_tokens": 2500},
    )

    llm_report = json.loads(result["content"])
    for severity in SEVERITY_BUCKETS:
        existing_keys = {
            (finding.get("file"), finding.get("title"))
            for finding in report.get(severity, [])
        }
        for finding in llm_report.get(severity, []):
            key = (finding.get("file"), finding.get("title"))
            if key not in existing_keys:
                finding.setdefault("source", "llm_analysis")
                _push(report, severity, finding)

    return report