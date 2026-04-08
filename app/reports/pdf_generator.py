"""Professional PDF security report generation using ReportLab with fallback output."""

from __future__ import annotations

import io
import os
from datetime import datetime
from pathlib import Path
from typing import Any


class SecurityReportGenerator:
    """Generate a branded, multi-section PDF report and optionally persist to disk."""

    def __init__(self) -> None:
        self._styles = None

    def generate_report(
        self,
        project_id: int,
        project_name: str,
        findings: list[dict[str, Any]],
        code_profile: dict[str, Any],
        deployment_plan: dict[str, Any],
        similar_deployments: list[dict[str, Any]],
        output_dir: str | None = None,
    ) -> str:
        """Generate report file and return absolute path."""

        output_root = Path(output_dir or os.getenv("NESTIFY_REPORT_DIR") or "app/outputs/reports")
        output_root.mkdir(parents=True, exist_ok=True)
        safe_name = "".join(ch for ch in project_name if ch.isalnum() or ch in {"-", "_"}).strip("-_") or f"project-{project_id}"
        stamp = datetime.utcnow().strftime("%Y%m%d_%H%M%S")
        filepath = output_root / f"security_report_{safe_name}_{stamp}.pdf"

        report_bytes = self.build_bytes(
            {
                "id": project_id,
                "name": project_name,
            },
            {
                "findings": findings,
                "code_profile": code_profile,
                "deployment_plan": deployment_plan,
                "similar_deployments": similar_deployments,
            },
        )

        filepath.write_bytes(report_bytes)
        return str(filepath.resolve())

    def build_bytes(self, project: dict[str, Any], report: dict[str, Any]) -> bytes:
        """Build report bytes for API streaming or persistence."""

        try:
            return self._build_pdf(project, report)
        except Exception:
            # Graceful fallback if reportlab is unavailable.
            lines: list[str] = []
            lines.append("Nestify Security Report")
            lines.append(f"Project: {project.get('name', 'Unknown')}")
            lines.append(f"Generated: {datetime.utcnow().isoformat()}Z")
            lines.append("")
            findings = report.get("findings") or {}
            for severity in ("critical", "high", "medium", "info", "low"):
                items = findings.get(severity) if isinstance(findings, dict) else []
                if items:
                    lines.append(f"{severity.upper()}: {len(items)}")
            lines.append("")
            lines.append("Deployment Intelligence")
            plan = report.get("deployment_plan") or {}
            lines.append(f"Chosen platform: {plan.get('chosen_platform', 'unknown')}")
            lines.append(f"Confidence: {int(float(plan.get('confidence') or 0.0) * 100)}%")
            return "\n".join(lines).encode("utf-8")

    def _build_pdf(self, project: dict[str, Any], report: dict[str, Any]) -> bytes:
        from reportlab.lib import colors
        from reportlab.lib.pagesizes import A4
        from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
        from reportlab.lib.units import inch
        from reportlab.platypus import PageBreak, Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

        styles = getSampleStyleSheet()
        styles.add(
            ParagraphStyle(
                "TitlePrimary",
                parent=styles["Heading1"],
                fontName="Helvetica-Bold",
                fontSize=24,
                textColor=colors.HexColor("#6D28D9"),
                spaceAfter=10,
            )
        )
        styles.add(
            ParagraphStyle(
                "Section",
                parent=styles["Heading2"],
                fontName="Helvetica-Bold",
                fontSize=15,
                textColor=colors.HexColor("#111827"),
                spaceBefore=12,
                spaceAfter=8,
            )
        )
        styles.add(
            ParagraphStyle(
                "Body",
                parent=styles["BodyText"],
                fontName="Helvetica",
                fontSize=10,
                leading=14,
            )
        )

        buffer = io.BytesIO()
        doc = SimpleDocTemplate(
            buffer,
            pagesize=A4,
            leftMargin=50,
            rightMargin=50,
            topMargin=45,
            bottomMargin=40,
        )

        findings_grouped = report.get("findings") or {}
        if isinstance(findings_grouped, list):
            grouped = {"critical": [], "high": [], "medium": [], "low": [], "info": []}
            for item in findings_grouped:
                sev = str((item or {}).get("severity") or "info").lower()
                if sev not in grouped:
                    sev = "info"
                grouped[sev].append(item)
            findings_grouped = grouped

        critical = len(findings_grouped.get("critical") or [])
        high = len(findings_grouped.get("high") or [])
        medium = len(findings_grouped.get("medium") or [])
        low = len(findings_grouped.get("low") or [])
        info = len(findings_grouped.get("info") or [])
        total = critical + high + medium + low + info

        plan = report.get("deployment_plan") or {}
        chosen_platform = plan.get("chosen_platform") or "unknown"
        confidence = int(float(plan.get("confidence") or 0.0) * 100)
        estimated_cost = plan.get("estimated_cost")

        story: list[Any] = []
        story.append(Spacer(1, 0.35 * inch))
        story.append(Paragraph("SECURITY ANALYSIS REPORT", styles["TitlePrimary"]))
        story.append(Paragraph(f"Project: <b>{project.get('name', 'Unknown')}</b>", styles["Body"]))
        story.append(Paragraph(f"Generated: {datetime.utcnow().strftime('%Y-%m-%d %H:%M:%S')} UTC", styles["Body"]))
        story.append(Spacer(1, 0.15 * inch))

        summary_table = Table(
            [
                ["Total Findings", str(total), "Chosen Platform", str(chosen_platform)],
                ["Critical", str(critical), "Confidence", f"{confidence}%"],
                ["High", str(high), "Estimated Cost", f"${estimated_cost}" if estimated_cost is not None else "n/a"],
                ["Medium", str(medium), "Low", str(low)],
            ],
            colWidths=[100, 90, 130, 120],
        )
        summary_table.setStyle(
            TableStyle(
                [
                    ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#EDE9FE")),
                    ("GRID", (0, 0), (-1, -1), 0.5, colors.HexColor("#D1D5DB")),
                    ("FONTNAME", (0, 0), (-1, -1), "Helvetica"),
                    ("FONTSIZE", (0, 0), (-1, -1), 10),
                    ("LEFTPADDING", (0, 0), (-1, -1), 6),
                    ("RIGHTPADDING", (0, 0), (-1, -1), 6),
                ]
            )
        )
        story.append(summary_table)

        story.append(Spacer(1, 0.2 * inch))
        story.append(Paragraph("Executive Summary", styles["Section"]))
        story.append(
            Paragraph(
                (
                    f"Nestify identified <b>{total}</b> findings with severity distribution: "
                    f"critical={critical}, high={high}, medium={medium}, low={low}, info={info}. "
                    "Agentic deployment planning evaluated cost, security, and technical fit before platform selection."
                ),
                styles["Body"],
            )
        )

        audit_overview = report.get("project_overview") or {}
        detected_stack = audit_overview.get("detected_stack") if isinstance(audit_overview, dict) else {}
        dependencies = audit_overview.get("dependencies") if isinstance(audit_overview, dict) else []
        entry_points = audit_overview.get("entry_points") if isinstance(audit_overview, dict) else []
        if isinstance(detected_stack, dict) and (detected_stack or dependencies or entry_points):
            story.append(Spacer(1, 0.15 * inch))
            story.append(Paragraph("Project Overview", styles["Section"]))
            story.append(
                Paragraph(
                    f"Detected stack: framework=<b>{detected_stack.get('framework', 'unknown')}</b>, runtime=<b>{detected_stack.get('runtime', 'unknown')}</b>",
                    styles["Body"],
                )
            )
            if isinstance(dependencies, list) and dependencies:
                dep_preview = ", ".join(str(dep) for dep in dependencies[:20])
                story.append(Paragraph(f"Dependencies: {dep_preview}", styles["Body"]))
            if isinstance(entry_points, list) and entry_points:
                story.append(Paragraph(f"Entry points: {', '.join(str(ep) for ep in entry_points[:10])}", styles["Body"]))

        story.append(PageBreak())
        story.append(Paragraph("Detailed Findings", styles["Section"]))

        severity_order = ["critical", "high", "medium", "low", "info"]
        severity_color = {
            "critical": "#DC2626",
            "high": "#EA580C",
            "medium": "#CA8A04",
            "low": "#2563EB",
            "info": "#4B5563",
        }
        finding_index = 1
        for severity in severity_order:
            for item in findings_grouped.get(severity) or []:
                title = item.get("title") or item.get("description") or "Security finding"
                location = item.get("file") or item.get("file_path") or "unknown file"
                line = item.get("line") or item.get("line_number") or "?"
                recommendation = item.get("recommendation") or "Review and remediate manually."

                story.append(
                    Paragraph(
                        f"<font color='{severity_color[severity]}'><b>{severity.upper()} #{finding_index}</b></font> - {title}",
                        styles["Body"],
                    )
                )
                story.append(Paragraph(f"Location: {location}:{line}", styles["Body"]))
                story.append(Paragraph(f"Recommendation: {recommendation}", styles["Body"]))
                why_it_matters = item.get("why_it_matters") or item.get("impact")
                if why_it_matters:
                    story.append(Paragraph(f"Why it matters: {why_it_matters}", styles["Body"]))
                story.append(Spacer(1, 0.08 * inch))
                finding_index += 1

        vuln = report.get("vulnerability_analysis") or {}
        if isinstance(vuln, dict) and any(isinstance(vuln.get(level), list) and vuln.get(level) for level in ("critical", "high", "medium")):
            story.append(PageBreak())
            story.append(Paragraph("Vulnerability Analysis (Audit View)", styles["Section"]))
            for severity in ("critical", "high", "medium"):
                issues = vuln.get(severity) if isinstance(vuln.get(severity), list) else []
                if not issues:
                    continue
                story.append(Paragraph(f"<b>{severity.upper()}</b> ({len(issues)})", styles["Body"]))
                for issue in issues[:20]:
                    story.append(Paragraph(f"Description: {issue.get('description')}", styles["Body"]))
                    story.append(Paragraph(f"Location: {issue.get('location')}", styles["Body"]))
                    story.append(Paragraph(f"Why it matters: {issue.get('why_it_matters')}", styles["Body"]))
                    story.append(Spacer(1, 0.06 * inch))

        story.append(PageBreak())
        story.append(Paragraph("Deployment Intelligence", styles["Section"]))
        story.append(Paragraph(f"Chosen Platform: <b>{chosen_platform}</b>", styles["Body"]))
        story.append(Paragraph(f"Confidence: <b>{confidence}%</b>", styles["Body"]))
        if estimated_cost is not None:
            story.append(Paragraph(f"Estimated Monthly Cost: <b>${estimated_cost}</b>", styles["Body"]))
        if plan.get("reasoning"):
            story.append(Paragraph(f"Reasoning: {plan.get('reasoning')}", styles["Body"]))

        alternatives = plan.get("alternatives_considered") or []
        if alternatives:
            story.append(Paragraph(f"Alternatives Considered: {', '.join(str(x) for x in alternatives)}", styles["Body"]))

        cost_alternatives = plan.get("cost_alternatives") or []
        if cost_alternatives:
            story.append(Spacer(1, 0.12 * inch))
            story.append(Paragraph("Cost Alternatives", styles["Section"]))
            alt_rows = [["Option", "Resources", "Monthly Cost", "P95", "Success"]]
            for alt in cost_alternatives[:8]:
                resources = f"{alt.get('memory_mb') or '?'}MB / {alt.get('cpu') or '?'} vCPU"
                alt_rows.append(
                    [
                        str(alt.get("label") or "option"),
                        resources,
                        f"${alt.get('monthly_cost_usd')}" if alt.get("monthly_cost_usd") is not None else "unknown",
                        f"{alt.get('p95_ms')} ms" if alt.get("p95_ms") is not None else "-",
                        f"{round(float(alt.get('success_rate') or 0.0) * 100, 1)}%" if alt.get("success_rate") is not None else "-",
                    ]
                )
            alt_table = Table(alt_rows, colWidths=[90, 140, 90, 70, 70])
            alt_table.setStyle(
                TableStyle(
                    [
                        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#DCFCE7")),
                        ("GRID", (0, 0), (-1, -1), 0.5, colors.HexColor("#D1D5DB")),
                        ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
                        ("FONTSIZE", (0, 0), (-1, -1), 9),
                    ]
                )
            )
            story.append(alt_table)

        if plan.get("failure_reason"):
            story.append(Spacer(1, 0.12 * inch))
            story.append(Paragraph("Failure Analysis & Recovery", styles["Section"]))
            story.append(Paragraph(f"Failure Reason: {plan.get('failure_reason')}", styles["Body"]))
            if plan.get("recovery_plan"):
                story.append(Paragraph(f"Nestify Recovery Plan: {plan.get('recovery_plan')}", styles["Body"]))

        fix_recommendations = report.get("fix_recommendations") or {}
        if isinstance(fix_recommendations, dict):
            exact_steps = fix_recommendations.get("exact_fix_steps") if isinstance(fix_recommendations.get("exact_fix_steps"), list) else []
            code_suggestions = fix_recommendations.get("code_level_suggestions") if isinstance(fix_recommendations.get("code_level_suggestions"), list) else []
            config_changes = fix_recommendations.get("config_changes") if isinstance(fix_recommendations.get("config_changes"), list) else []
            if exact_steps or code_suggestions or config_changes:
                story.append(PageBreak())
                story.append(Paragraph("Fix Recommendations", styles["Section"]))
                for step in exact_steps[:15]:
                    story.append(Paragraph(f"Step {step.get('step')}: {step.get('action')}", styles["Body"]))
                    story.append(Paragraph(f"Location: {step.get('location')}", styles["Body"]))
                if code_suggestions:
                    story.append(Spacer(1, 0.08 * inch))
                    story.append(Paragraph("Code-Level Suggestions", styles["Section"]))
                    for suggestion in code_suggestions[:10]:
                        story.append(Paragraph(f"- {suggestion.get('action')} ({suggestion.get('location')})", styles["Body"]))
                if config_changes:
                    story.append(Spacer(1, 0.08 * inch))
                    story.append(Paragraph("Configuration Changes", styles["Section"]))
                    for change in config_changes[:10]:
                        story.append(Paragraph(f"- {change.get('action')} ({change.get('location')})", styles["Body"]))

        applied_fixes = report.get("applied_fixes") if isinstance(report.get("applied_fixes"), list) else []
        if applied_fixes:
            story.append(PageBreak())
            story.append(Paragraph("Applied Fixes", styles["Section"]))
            for item in applied_fixes[:20]:
                story.append(Paragraph(f"Change: {item.get('change')}", styles["Body"]))
                story.append(Paragraph(f"Location: {item.get('location')}", styles["Body"]))
                story.append(Paragraph(f"Before → After: {item.get('before_after')}", styles["Body"]))
                story.append(Spacer(1, 0.05 * inch))

        readiness = report.get("deployment_readiness") or {}
        if isinstance(readiness, dict) and readiness:
            story.append(Spacer(1, 0.12 * inch))
            story.append(Paragraph("Deployment Readiness", styles["Section"]))
            story.append(Paragraph(f"Score: <b>{readiness.get('score', 'n/a')}</b>", styles["Body"]))
            story.append(Paragraph(f"Safe to deploy: <b>{readiness.get('safe_to_deploy', 'No')}</b>", styles["Body"]))
            blockers = readiness.get("blocking_issues") if isinstance(readiness.get("blocking_issues"), list) else []
            if blockers:
                story.append(Paragraph("Blocking issues:", styles["Body"]))
                for blocker in blockers[:10]:
                    story.append(Paragraph(f"- {blocker}", styles["Body"]))

        strategy = report.get("deployment_strategy") or {}
        if isinstance(strategy, dict) and strategy:
            story.append(Spacer(1, 0.12 * inch))
            story.append(Paragraph("Deployment Strategy", styles["Section"]))
            story.append(Paragraph(f"Selected platform: <b>{strategy.get('selected_platform', 'unknown')}</b>", styles["Body"]))
            story.append(Paragraph(f"Why chosen: {strategy.get('why_chosen', 'Not provided')}", styles["Body"]))

        remediation_steps = report.get("remediation_steps") or []
        if remediation_steps:
            story.append(PageBreak())
            story.append(Paragraph("Detailed Remediation Steps", styles["Section"]))
            for idx, step in enumerate(remediation_steps[:30], start=1):
                story.append(
                    Paragraph(
                        f"<b>Step {idx} [{str(step.get('severity') or 'info').upper()}]</b> - {step.get('title')}",
                        styles["Body"],
                    )
                )
                story.append(Paragraph(f"Location: {step.get('location')}", styles["Body"]))
                story.append(Paragraph(f"Action: {step.get('recommendation')}", styles["Body"]))
                story.append(Spacer(1, 0.06 * inch))

        similar = report.get("similar_deployments") or []
        if similar:
            story.append(Spacer(1, 0.12 * inch))
            story.append(Paragraph("Top Similar Deployments", styles["Section"]))
            rows = [["Platform", "Similarity", "Success", "Cost"]]
            for dep in similar[:8]:
                rows.append(
                    [
                        str(dep.get("platform_choice") or dep.get("platform") or "unknown"),
                        str(dep.get("similarity_score") or dep.get("similarity") or "n/a"),
                        "yes" if dep.get("success") else "no",
                        str(dep.get("cost_per_month") or dep.get("cost") or "n/a"),
                    ]
                )
            table = Table(rows, colWidths=[110, 110, 90, 90])
            table.setStyle(
                TableStyle(
                    [
                        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#DDD6FE")),
                        ("GRID", (0, 0), (-1, -1), 0.5, colors.HexColor("#D1D5DB")),
                        ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
                        ("FONTSIZE", (0, 0), (-1, -1), 9),
                    ]
                )
            )
            story.append(table)

        doc.build(story)
        return buffer.getvalue()


class SecurityPdfGenerator:
    """Backward-compatible adapter used by existing endpoints."""

    def __init__(self) -> None:
        self._generator = SecurityReportGenerator()

    def build(self, project: dict[str, Any], report: dict[str, Any]) -> bytes:
        return self._generator.build_bytes(project, report)
