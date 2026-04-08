"""GitHub Webhook API — Handles incoming GitHub events."""

from __future__ import annotations

import logging
from typing import Any

from fastapi import APIRouter, HTTPException, Header, Request

from app.integrations.github import (
    GitHubClient,
    format_pr_comment,
    parse_webhook_event,
    verify_webhook_signature,
)
from app.intelligence.graph_builder import build_project_graph
from app.intelligence.risk_engine import assess_project
from app.services.scan_service import run_static_source_scan

logger = logging.getLogger(__name__)
router = APIRouter()


def _build_stack_info(files: list[dict[str, str]]) -> dict[str, Any]:
    """Lightweight stack detection for webhook-triggered PR analysis."""
    names = [f.get("name", "") for f in files]

    runtime = "unknown"
    if any(name.endswith(".py") for name in names):
        runtime = "python"
    elif any(name.endswith("package.json") for name in names):
        runtime = "node"

    framework = "unknown"
    for file_info in files:
        name = file_info.get("name", "")
        content = (file_info.get("content", "") or "").lower()
        if name.endswith("package.json"):
            if '"react"' in content:
                framework = "react"
            elif '"next"' in content:
                framework = "next"
            elif '"express"' in content:
                framework = "express"
        elif name.endswith(".py"):
            if "fastapi" in content:
                framework = "fastapi"
            elif "flask" in content:
                framework = "flask"
            elif "django" in content:
                framework = "django"

    return {"runtime": runtime, "framework": framework, "security_flags": []}


def _extract_stats_from_risk(report: dict[str, Any]) -> dict[str, int]:
    """Normalize risk report stats for PR comment formatting."""
    stats = report.get("stats", {})
    return {
        "critical": int(stats.get("critical", 0)),
        "high": int(stats.get("high", 0)),
        "medium": int(stats.get("medium", 0)),
        "low": int(stats.get("low", 0)),
    }


async def _analyze_pr_files(github: GitHubClient, repo_full_name: str, pr_number: int) -> dict[str, Any]:
    """Fetch changed PR files and run graph-aware security analysis."""
    changed = await github.get_pr_files(repo_full_name, pr_number)

    files: list[dict[str, str]] = []
    for item in changed[:25]:
        status = (item.get("status") or "").lower()
        if status == "removed":
            continue

        file_path = item.get("filename") or ""
        if not file_path:
            continue
        if not file_path.endswith((".py", ".js", ".ts", ".tsx", ".jsx", ".json", ".txt")):
            continue

        try:
            content = await github.get_file_content(repo_full_name, file_path)
        except Exception:
            continue

        if not content:
            continue

        files.append({"name": file_path, "content": content})

    if not files:
        return {
            "scan_report": {"critical": [], "high": [], "medium": [], "info": []},
            "risk_score": 100,
            "risk_report": {"stats": {"critical": 0, "high": 0, "medium": 0, "low": 0}},
        }

    stack_info = _build_stack_info(files)
    scan_report = run_static_source_scan(files, stack_info)
    graph = build_project_graph(files)
    risk_report = assess_project(scan_report, graph).to_dict()

    return {
        "scan_report": scan_report,
        "risk_score": int(risk_report.get("overall_score", 100)),
        "risk_report": risk_report,
    }


@router.post("/github")
async def handle_github_webhook(
    request: Request,
    x_github_event: str = Header(default=""),
    x_hub_signature_256: str = Header(default=""),
):
    """Handle GitHub webhook events (push, pull_request).

    On pull_request events:
      1. Parses the PR metadata
      2. Triggers a Nestify scan (async)
      3. Posts analysis results as a PR comment
    """
    body = await request.body()

    # Verify signature
    if not verify_webhook_signature(body, x_hub_signature_256):
        raise HTTPException(status_code=401, detail="Invalid webhook signature")

    payload = await request.json()
    event = parse_webhook_event(x_github_event, payload)

    logger.info("GitHub webhook: %s / %s", event.event_type, event.action)

    if event.event_type == "pull_request" and event.action in ("opened", "synchronize"):
        # Handle PR analysis
        if event.pr and event.repo:
            logger.info(
                "Analyzing PR #%d on %s",
                event.pr.number, event.repo.full_name,
            )
            github = GitHubClient()

            if not github.is_configured:
                return {
                    "status": "accepted",
                    "event": event.event_type,
                    "pr_number": event.pr.number,
                    "message": "PR analysis skipped: GitHub token is not configured.",
                }

            analysis = await _analyze_pr_files(github, event.repo.full_name, event.pr.number)
            risk_score = int(analysis["risk_score"])

            comment_body = format_pr_comment(
                scan_result={"stats": _extract_stats_from_risk(analysis["risk_report"])},
                risk_score=risk_score,
            )

            try:
                await github.post_pr_comment(
                    repo_full_name=event.repo.full_name,
                    pr_number=event.pr.number,
                    body=comment_body,
                )
            except Exception as exc:
                logger.warning("Failed to post summary PR comment: %s", exc)

            # Inline comments for highest-severity findings with line metadata.
            critical_and_high = (
                analysis["scan_report"].get("critical", [])
                + analysis["scan_report"].get("high", [])
            )
            inline_posted = 0
            for finding in critical_and_high[:5]:
                file_path = finding.get("file")
                line = finding.get("line")
                if not file_path or not isinstance(line, int):
                    continue
                body = (
                    "Nestify detected a security issue here:\n\n"
                    f"- Type: {finding.get('type', 'unknown')}\n"
                    f"- Severity: {finding.get('severity', 'high')}\n"
                    f"- Recommendation: {finding.get('recommendation', 'Review this code path.') }"
                )
                try:
                    await github.post_review_comment(
                        repo_full_name=event.repo.full_name,
                        pr_number=event.pr.number,
                        commit_sha=event.pr.head_sha,
                        file_path=file_path,
                        line=line,
                        body=body,
                    )
                    inline_posted += 1
                except Exception as exc:
                    logger.debug("Inline PR comment failed for %s:%s (%s)", file_path, line, exc)

            return {
                "status": "accepted",
                "event": event.event_type,
                "pr_number": event.pr.number,
                "risk_score": risk_score,
                "inline_comments": inline_posted,
                "message": "PR analyzed and comments posted",
            }

    if event.event_type == "push":
        logger.info("Push event received for ref: %s", event.ref)
        return {
            "status": "accepted",
            "event": event.event_type,
            "ref": event.ref,
            "message": "Push event received",
        }

    return {"status": "ignored", "event": event.event_type, "action": event.action}
