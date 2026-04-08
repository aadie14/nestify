"""GitHub Integration — Webhook listener, PR analysis, and automated responses.

Features:
  - Webhook endpoint to receive push/PR events
  - PR analyzer: clones branch, runs full Nestify pipeline
  - PR commenter: posts inline comments on vulnerable lines
  - Auto-PR creator: creates PRs with safe fixes
"""

from __future__ import annotations

import hashlib
import hmac
import json
import logging
from dataclasses import dataclass, field
from typing import Any

import httpx

from app.core.config import settings

logger = logging.getLogger(__name__)

# ─── GitHub API Constants ─────────────────────────────────────────────────

GITHUB_API = "https://api.github.com"
ACCEPT_HEADER = "application/vnd.github.v3+json"


# ─── Data Models ──────────────────────────────────────────────────────────

@dataclass(slots=True)
class GitHubRepo:
    """Parsed GitHub repository metadata."""
    owner: str
    name: str
    full_name: str
    clone_url: str
    default_branch: str = "main"


@dataclass(slots=True)
class PRInfo:
    """Pull request context for analysis."""
    number: int
    title: str
    head_branch: str
    base_branch: str
    head_sha: str
    repo: GitHubRepo
    changed_files: list[str] = field(default_factory=list)


@dataclass(slots=True)
class WebhookPayload:
    """Parsed webhook event."""
    event_type: str
    action: str
    repo: GitHubRepo | None
    pr: PRInfo | None
    ref: str  # branch ref for push events
    raw: dict[str, Any] = field(default_factory=dict)


# ─── Webhook Verification ────────────────────────────────────────────────

def verify_webhook_signature(payload_body: bytes, signature: str) -> bool:
    """Verify GitHub webhook signatures using HMAC SHA-256.

    Args:
        payload_body: Raw request body bytes.
        signature: The ``X-Hub-Signature-256`` header value.

    Returns:
        True if the signature matches the configured webhook secret.
    """
    if not settings.github_webhook_secret:
        logger.warning("GitHub webhook secret not configured — skipping verification")
        return True

    expected = "sha256=" + hmac.new(
        settings.github_webhook_secret.encode(),
        payload_body,
        hashlib.sha256,
    ).hexdigest()

    return hmac.compare_digest(expected, signature)


def parse_webhook_event(event_type: str, payload: dict[str, Any]) -> WebhookPayload:
    """Parse a raw GitHub webhook payload into structured data.

    Args:
        event_type: The ``X-GitHub-Event`` header value (e.g., 'push', 'pull_request').
        payload: Decoded JSON body.

    Returns:
        A structured ``WebhookPayload``.
    """
    repo = None
    pr = None
    ref = ""

    repo_data = payload.get("repository", {})
    if repo_data:
        repo = GitHubRepo(
            owner=repo_data.get("owner", {}).get("login", ""),
            name=repo_data.get("name", ""),
            full_name=repo_data.get("full_name", ""),
            clone_url=repo_data.get("clone_url", ""),
            default_branch=repo_data.get("default_branch", "main"),
        )

    if event_type == "pull_request":
        pr_data = payload.get("pull_request", {})
        pr = PRInfo(
            number=pr_data.get("number", 0),
            title=pr_data.get("title", ""),
            head_branch=pr_data.get("head", {}).get("ref", ""),
            base_branch=pr_data.get("base", {}).get("ref", ""),
            head_sha=pr_data.get("head", {}).get("sha", ""),
            repo=repo,
        )

    if event_type == "push":
        ref = payload.get("ref", "")

    return WebhookPayload(
        event_type=event_type,
        action=payload.get("action", ""),
        repo=repo,
        pr=pr,
        ref=ref,
        raw=payload,
    )


# ─── GitHub API Client ───────────────────────────────────────────────────

class GitHubClient:
    """Async GitHub API client for PR interactions.

    Requires a GitHub token (personal access or GitHub App installation token)
    configured via ``GITHUB_TOKEN`` environment variable.
    """

    def __init__(self, token: str | None = None) -> None:
        self._token = token or settings.github_token
        self._headers = {
            "Accept": ACCEPT_HEADER,
            "User-Agent": "Nestify-DevSecOps-Bot",
        }
        if self._token:
            self._headers["Authorization"] = f"Bearer {self._token}"

    @property
    def is_configured(self) -> bool:
        return bool(self._token)

    async def get_pr_files(self, repo_full_name: str, pr_number: int) -> list[dict[str, Any]]:
        """Fetch the list of changed files in a PR."""
        url = f"{GITHUB_API}/repos/{repo_full_name}/pulls/{pr_number}/files"
        async with httpx.AsyncClient() as client:
            resp = await client.get(url, headers=self._headers, timeout=30)
            resp.raise_for_status()
            return resp.json()

    async def post_pr_comment(
        self,
        repo_full_name: str,
        pr_number: int,
        body: str,
    ) -> dict[str, Any]:
        """Post a general comment on a PR."""
        url = f"{GITHUB_API}/repos/{repo_full_name}/issues/{pr_number}/comments"
        async with httpx.AsyncClient() as client:
            resp = await client.post(
                url, headers=self._headers,
                json={"body": body}, timeout=30,
            )
            resp.raise_for_status()
            return resp.json()

    async def post_review_comment(
        self,
        repo_full_name: str,
        pr_number: int,
        commit_sha: str,
        file_path: str,
        line: int,
        body: str,
    ) -> dict[str, Any]:
        """Post an inline review comment on a specific line in a PR."""
        url = f"{GITHUB_API}/repos/{repo_full_name}/pulls/{pr_number}/comments"
        async with httpx.AsyncClient() as client:
            resp = await client.post(
                url, headers=self._headers,
                json={
                    "body": body,
                    "commit_id": commit_sha,
                    "path": file_path,
                    "line": line,
                    "side": "RIGHT",
                },
                timeout=30,
            )
            resp.raise_for_status()
            return resp.json()

    async def create_pr(
        self,
        repo_full_name: str,
        title: str,
        body: str,
        head: str,
        base: str,
    ) -> dict[str, Any]:
        """Create a pull request."""
        url = f"{GITHUB_API}/repos/{repo_full_name}/pulls"
        async with httpx.AsyncClient() as client:
            resp = await client.post(
                url, headers=self._headers,
                json={
                    "title": title,
                    "body": body,
                    "head": head,
                    "base": base,
                },
                timeout=30,
            )
            resp.raise_for_status()
            return resp.json()

    async def get_repo_contents(
        self,
        repo_full_name: str,
        path: str = "",
        ref: str = "",
    ) -> list[dict[str, Any]]:
        """Fetch repository contents at a given path and ref."""
        url = f"{GITHUB_API}/repos/{repo_full_name}/contents/{path}"
        params: dict[str, str] = {}
        if ref:
            params["ref"] = ref

        async with httpx.AsyncClient() as client:
            resp = await client.get(
                url, headers=self._headers,
                params=params, timeout=30,
            )
            resp.raise_for_status()
            data = resp.json()
            return data if isinstance(data, list) else [data]

    async def get_file_content(
        self,
        repo_full_name: str,
        file_path: str,
        ref: str = "",
    ) -> str:
        """Download a single file's content from the repository."""
        import base64
        contents = await self.get_repo_contents(repo_full_name, file_path, ref)
        if contents and contents[0].get("content"):
            return base64.b64decode(contents[0]["content"]).decode("utf-8")
        return ""


# ─── Analysis Report Formatter ────────────────────────────────────────────

def format_pr_comment(
    scan_result: dict[str, Any],
    risk_score: int,
) -> str:
    """Format a Nestify analysis result as a GitHub PR comment.

    Returns a markdown-formatted string.
    """
    status_emoji = "🟢" if risk_score >= 80 else "🟡" if risk_score >= 60 else "🔴"

    lines = [
        "## 🪺 Nestify Security Analysis",
        "",
        f"**Security Score**: {status_emoji} **{risk_score}/100**",
        "",
    ]

    stats = scan_result.get("stats", {})
    if stats:
        lines.extend([
            "### Summary",
            f"- 🔴 Critical: **{stats.get('critical', 0)}**",
            f"- 🟠 High: **{stats.get('high', 0)}**",
            f"- 🟡 Medium: **{stats.get('medium', 0)}**",
            f"- ⚪ Low: **{stats.get('low', 0)}**",
            "",
        ])

    if risk_score < 70:
        lines.extend([
            "> ⚠️ **Deployment Blocked** — Score is below the safety threshold (70/100).",
            "> Please address the critical and high-severity issues before merging.",
            "",
        ])

    lines.extend([
        "---",
        "*Analyzed by [Nestify](https://github.com/nestify) — AI-Powered DevSecOps Autopilot*",
    ])

    return "\n".join(lines)
