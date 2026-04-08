"""Security scoring helpers for the DevSecOps pipeline."""

from __future__ import annotations

from typing import Any, Mapping, Sequence


def calculate_security_score(report: Mapping[str, Sequence[object]]) -> int:
    """
    Calculate a 0–100 security score from a scan report.

    Formula: 100 - (30 × critical) - (15 × high) - (5 × medium)
    """
    score = 100
    score -= 30 * len(report.get("critical", []))
    score -= 15 * len(report.get("high", []))
    score -= 5 * len(report.get("medium", []))
    return max(score, 0)


def summarize_severity_counts(report: Mapping[str, Sequence[object]]) -> dict[str, int]:
    """Return a count of findings per severity level."""
    return {
        "critical": len(report.get("critical", [])),
        "high": len(report.get("high", [])),
        "medium": len(report.get("medium", [])),
        "info": len(report.get("info", [])),
    }


def build_score_metadata(
    report: Mapping[str, Sequence[object]],
    files_scanned: int = 0,
) -> dict[str, Any]:
    """Build a complete security score metadata object."""
    score = calculate_security_score(report)
    summary = summarize_severity_counts(report)
    total_issues = sum(summary.values())

    return {
        "security_score": score,
        "severity_counts": summary,
        "total_issues": total_issues,
        "files_scanned": files_scanned,
    }