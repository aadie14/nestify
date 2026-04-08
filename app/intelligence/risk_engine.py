"""Risk Engine — Multi-factor vulnerability risk scoring.

Replaces the simple ``100 - (30×critical) - (15×high) - (5×medium)`` formula
with a graph-aware, context-sensitive risk model:

    Risk Score = Exploitability × Impact × Reachability × Sensitivity

Each factor is normalized to 0.0–1.0 and computed from the code graph,
vulnerability metadata, and environment context.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from enum import Enum
from typing import Any

from app.intelligence.graph_builder import CodeGraph, NodeType, RelationType

logger = logging.getLogger(__name__)


# ─── Enums & Constants ───────────────────────────────────────────────────

class RiskLevel(str, Enum):
    """Qualitative risk tiers derived from the composite score."""
    CRITICAL = "critical"
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"
    INFO = "info"


# Weights for the composite score  (sum = 1.0)
FACTOR_WEIGHTS = {
    "exploitability": 0.30,
    "impact": 0.30,
    "reachability": 0.25,
    "sensitivity": 0.15,
}

# Exploitability base scores by vulnerability type
_EXPLOITABILITY_MAP: dict[str, float] = {
    "hardcoded_secret": 0.95,
    "sql_injection": 0.90,
    "xss": 0.80,
    "command_injection": 0.90,
    "path_traversal": 0.75,
    "ssrf": 0.70,
    "insecure_deserialization": 0.85,
    "dependency_vuln": 0.60,
    "env_exposure": 0.70,
    "weak_crypto": 0.50,
    "missing_auth": 0.80,
    "insecure_header": 0.40,
    "debug_enabled": 0.55,
    "insecure_pattern": 0.45,
}

# Impact base scores by vulnerability type
_IMPACT_MAP: dict[str, float] = {
    "hardcoded_secret": 0.90,
    "sql_injection": 0.95,
    "xss": 0.65,
    "command_injection": 0.95,
    "path_traversal": 0.70,
    "ssrf": 0.80,
    "insecure_deserialization": 0.85,
    "dependency_vuln": 0.50,
    "env_exposure": 0.60,
    "weak_crypto": 0.55,
    "missing_auth": 0.85,
    "insecure_header": 0.30,
    "debug_enabled": 0.40,
    "insecure_pattern": 0.35,
}

# Sensitivity keywords — files matching these are treated as high-sensitivity
_SENSITIVE_PATHS = (
    "auth", "login", "password", "secret", "credential",
    "payment", "billing", "admin", "config", "database",
    ".env", "key", "token", "session", "middleware",
)


# ─── Data Models ──────────────────────────────────────────────────────────

@dataclass(slots=True)
class RiskFactor:
    """Individual risk factor with its raw and weighted values."""
    name: str
    raw_score: float         # 0.0 – 1.0
    weight: float            # from FACTOR_WEIGHTS
    weighted_score: float    # raw × weight
    reasoning: str = ""


@dataclass(slots=True)
class VulnerabilityRisk:
    """Complete risk assessment for a single vulnerability."""
    vuln_type: str
    file: str
    line: int | None
    factors: list[RiskFactor]
    composite_score: float       # 0.0 – 1.0
    risk_level: RiskLevel
    risk_score_100: int          # 0 – 100 for display
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class ProjectRiskReport:
    """Aggregated risk report for the entire project."""
    vulnerabilities: list[VulnerabilityRisk]
    overall_score: float         # 0.0 – 1.0
    overall_level: RiskLevel
    overall_score_100: int       # 0 – 100 (inverted: 100 = safe, 0 = critical)
    stats: dict[str, int] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        """Serialize for API responses."""
        return {
            "overall_score": self.overall_score_100,
            "overall_level": self.overall_level.value,
            "stats": self.stats,
            "vulnerabilities": [
                {
                    "type": v.vuln_type,
                    "file": v.file,
                    "line": v.line,
                    "composite_score": round(v.composite_score, 3),
                    "risk_level": v.risk_level.value,
                    "risk_score": v.risk_score_100,
                    "factors": [
                        {
                            "name": f.name,
                            "raw": round(f.raw_score, 3),
                            "weighted": round(f.weighted_score, 3),
                            "reasoning": f.reasoning,
                        }
                        for f in v.factors
                    ],
                }
                for v in self.vulnerabilities
            ],
        }


# ─── Factor Calculators ──────────────────────────────────────────────────

def _calc_exploitability(vuln: dict[str, Any]) -> RiskFactor:
    """How easy is it to exploit this vulnerability?

    Considers the vulnerability type, whether credentials are needed,
    and the attack vector (network vs local).
    """
    vuln_type = vuln.get("type", "unknown")
    base = _EXPLOITABILITY_MAP.get(vuln_type, 0.40)

    # Adjust for attack vector
    desc = (vuln.get("description") or "").lower()
    if "remote" in desc or "network" in desc:
        base = min(base + 0.10, 1.0)
    if "authenticated" in desc:
        base = max(base - 0.15, 0.1)

    return RiskFactor(
        name="exploitability",
        raw_score=base,
        weight=FACTOR_WEIGHTS["exploitability"],
        weighted_score=base * FACTOR_WEIGHTS["exploitability"],
        reasoning=f"Type '{vuln_type}' base exploitability: {base:.2f}",
    )


def _calc_impact(vuln: dict[str, Any]) -> RiskFactor:
    """What is the damage if this vulnerability is exploited?

    Considers affected data types, system access level, and blast radius.
    """
    vuln_type = vuln.get("type", "unknown")
    base = _IMPACT_MAP.get(vuln_type, 0.30)

    desc = (vuln.get("description") or "").lower()
    # Escalate for RCE or data exfiltration indicators
    if any(kw in desc for kw in ("remote code", "rce", "arbitrary code")):
        base = min(base + 0.15, 1.0)
    if any(kw in desc for kw in ("data leak", "exfiltration", "pii", "personal")):
        base = min(base + 0.10, 1.0)

    return RiskFactor(
        name="impact",
        raw_score=base,
        weight=FACTOR_WEIGHTS["impact"],
        weighted_score=base * FACTOR_WEIGHTS["impact"],
        reasoning=f"Type '{vuln_type}' base impact: {base:.2f}",
    )


def _calc_reachability(
    vuln: dict[str, Any],
    graph: CodeGraph | None,
) -> RiskFactor:
    """Is this vulnerable code actually reachable in the call graph?

    If graph data is available, traverse callers to determine whether
    the vulnerable function is invoked from an entry point.
    """
    file_path = vuln.get("file", "")
    score = 0.50  # default: unknown reachability

    if graph and file_path:
        # Find nodes in the vulnerable file
        file_nodes = [
            n for n in graph.nodes
            if n.file_path == file_path and n.type in (NodeType.FUNCTION, NodeType.CLASS)
        ]

        if file_nodes:
            # Check if any of these have callers
            max_caller_count = 0
            for node in file_nodes:
                callers = graph.get_callers(node.id)
                max_caller_count = max(max_caller_count, len(callers))

            if max_caller_count == 0:
                score = 0.20  # dead code — low reachability
                reasoning = "No callers found in graph — likely dead code"
            elif max_caller_count <= 2:
                score = 0.50
                reasoning = f"Limited reachability ({max_caller_count} caller(s))"
            elif max_caller_count <= 5:
                score = 0.75
                reasoning = f"Moderate reachability ({max_caller_count} callers)"
            else:
                score = 0.95
                reasoning = f"Highly reachable ({max_caller_count} callers)"
        else:
            reasoning = "No parseable definitions in file"
    else:
        reasoning = "Graph unavailable — assuming moderate reachability"

    return RiskFactor(
        name="reachability",
        raw_score=score,
        weight=FACTOR_WEIGHTS["reachability"],
        weighted_score=score * FACTOR_WEIGHTS["reachability"],
        reasoning=reasoning,
    )


def _calc_sensitivity(vuln: dict[str, Any], env: str = "production") -> RiskFactor:
    """Does the vulnerable code handle sensitive data or run in a sensitive environment?"""
    file_path = (vuln.get("file") or "").lower()
    score = 0.30  # base

    # Path-based sensitivity
    matches = [kw for kw in _SENSITIVE_PATHS if kw in file_path]
    if matches:
        score = min(0.30 + 0.15 * len(matches), 1.0)
        reasoning = f"Sensitive path keywords: {', '.join(matches)}"
    else:
        reasoning = "No sensitive path indicators detected"

    # Environment multiplier
    if env == "production":
        score = min(score + 0.20, 1.0)
        reasoning += " | production environment (+0.20)"
    elif env == "staging":
        score = min(score + 0.10, 1.0)
        reasoning += " | staging environment (+0.10)"

    return RiskFactor(
        name="sensitivity",
        raw_score=score,
        weight=FACTOR_WEIGHTS["sensitivity"],
        weighted_score=score * FACTOR_WEIGHTS["sensitivity"],
        reasoning=reasoning,
    )


# ─── Score Classification ────────────────────────────────────────────────

def _classify_risk(composite: float) -> RiskLevel:
    """Map a 0.0–1.0 composite score to a qualitative risk level."""
    if composite >= 0.80:
        return RiskLevel.CRITICAL
    if composite >= 0.60:
        return RiskLevel.HIGH
    if composite >= 0.35:
        return RiskLevel.MEDIUM
    if composite >= 0.15:
        return RiskLevel.LOW
    return RiskLevel.INFO


# ─── Public API ───────────────────────────────────────────────────────────

def assess_vulnerability(
    vuln: dict[str, Any],
    graph: CodeGraph | None = None,
    env: str = "production",
) -> VulnerabilityRisk:
    """Compute the full multi-factor risk score for a single vulnerability.

    Args:
        vuln: Vulnerability dict with ``type``, ``file``, ``line``, ``description``.
        graph: Optional code graph for reachability analysis.
        env: Deployment environment (``production``, ``staging``, ``development``).

    Returns:
        A ``VulnerabilityRisk`` with composite score and per-factor breakdown.
    """
    factors = [
        _calc_exploitability(vuln),
        _calc_impact(vuln),
        _calc_reachability(vuln, graph),
        _calc_sensitivity(vuln, env),
    ]

    composite = sum(f.weighted_score for f in factors)
    risk_level = _classify_risk(composite)

    return VulnerabilityRisk(
        vuln_type=vuln.get("type", "unknown"),
        file=vuln.get("file", "unknown"),
        line=vuln.get("line"),
        factors=factors,
        composite_score=composite,
        risk_level=risk_level,
        risk_score_100=int(round(composite * 100)),
    )


def assess_project(
    security_report: dict[str, list[dict[str, Any]]],
    graph: CodeGraph | None = None,
    env: str = "production",
) -> ProjectRiskReport:
    """Compute risk scores for all vulnerabilities in a project.

    Args:
        security_report: Output from SecurityAgent (``{severity: [findings]}``)
        graph: Optional code graph for reachability-aware scoring.
        env: Target deployment environment.

    Returns:
        A ``ProjectRiskReport`` with per-vulnerability and overall scores.
    """
    vuln_risks: list[VulnerabilityRisk] = []

    for severity, findings in security_report.items():
        if severity in ("info", "metadata"):
            continue
        for finding in findings:
            risk = assess_vulnerability(finding, graph, env)
            vuln_risks.append(risk)

    # Sort: highest risk first
    vuln_risks.sort(key=lambda v: v.composite_score, reverse=True)

    # Overall score: safety-oriented (100 = safe, 0 = critical risk)
    if vuln_risks:
        max_risk = max(v.composite_score for v in vuln_risks)
        avg_risk = sum(v.composite_score for v in vuln_risks) / len(vuln_risks)
        # Weight towards the worst finding
        blended = 0.60 * max_risk + 0.40 * avg_risk
        overall_safety = max(0, 1.0 - blended)
    else:
        overall_safety = 1.0
        blended = 0.0

    stats = {
        "total": len(vuln_risks),
        "critical": sum(1 for v in vuln_risks if v.risk_level == RiskLevel.CRITICAL),
        "high": sum(1 for v in vuln_risks if v.risk_level == RiskLevel.HIGH),
        "medium": sum(1 for v in vuln_risks if v.risk_level == RiskLevel.MEDIUM),
        "low": sum(1 for v in vuln_risks if v.risk_level == RiskLevel.LOW),
    }

    report = ProjectRiskReport(
        vulnerabilities=vuln_risks,
        overall_score=blended,
        overall_level=_classify_risk(blended),
        overall_score_100=int(round(overall_safety * 100)),
        stats=stats,
    )

    logger.info(
        "Risk assessment: %d vulns scored, overall safety: %d/100 (%s)",
        len(vuln_risks), report.overall_score_100, report.overall_level.value,
    )

    return report
