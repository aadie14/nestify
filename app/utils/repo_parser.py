"""Repository parsing for ZIP uploads, GitHub repositories, text, and descriptions."""

from __future__ import annotations

import io
import ipaddress
import os
import re
import zipfile
from urllib.parse import urlparse

import httpx

SUPPORTED_FILES = [
    "package.json", "requirements.txt", "go.mod", "composer.json", "Gemfile",
    "pom.xml", "build.gradle", "Cargo.toml", "Dockerfile", "docker-compose.yml",
    "docker-compose.yaml", ".env", ".env.example", ".env.sample", "Procfile",
    "app.json", "railway.json", "render.yaml",
]
SUPPORTED_EXTENSIONS = [
    ".js", ".mjs", ".cjs", ".ts", ".jsx", ".tsx", ".py", ".go", ".rb", ".php",
    ".java", ".rs", ".json", ".yml", ".yaml", ".toml", ".cfg", ".env", ".sql",
    ".sh", ".md", ".html", ".css", ".svg", ".txt", ".xml",
]
IGNORE_DIRS = [
    "node_modules", ".git", "__pycache__", ".venv", "venv", "env", ".next",
    "dist", "build", ".cache", "coverage", ".idea", ".vscode",
]
BLOCKED_IP_RANGES = [
    ipaddress.ip_network("127.0.0.0/8"),
    ipaddress.ip_network("10.0.0.0/8"),
    ipaddress.ip_network("172.16.0.0/12"),
    ipaddress.ip_network("192.168.0.0/16"),
    ipaddress.ip_network("169.254.0.0/16"),
    ipaddress.ip_network("0.0.0.0/8"),
    ipaddress.ip_network("::1/128"),
]
GITHUB_URL_PATTERN = re.compile(r"^https://github\.com/([A-Za-z0-9_.-]+)/([A-Za-z0-9_.-]+)/?$")


def _validate_github_url(url: str) -> tuple[str, str]:
    url = url.strip().rstrip("/")
    match = GITHUB_URL_PATTERN.match(url)
    if not match:
        raise ValueError("Invalid GitHub URL. Expected format: https://github.com/user/repo")

    owner, repo = match.groups()
    clean_repo = repo.replace(".git", "")
    parsed = urlparse(url)
    hostname = parsed.hostname or ""

    try:
        import socket
        resolved_ips = socket.getaddrinfo(hostname, None)
        for _, _, _, _, sockaddr in resolved_ips:
            ip = ipaddress.ip_address(sockaddr[0])
            if any(ip in blocked for blocked in BLOCKED_IP_RANGES):
                raise ValueError(f"Blocked: URL resolves to private IP range ({ip})")
    except (socket.gaierror, ValueError) as error:
        if "Blocked" in str(error):
            raise

    return owner, clean_repo


def parse_zip(zip_bytes: bytes) -> dict:
    """Parse a ZIP archive into a list of files and structure."""
    zip_buffer = io.BytesIO(zip_bytes)
    files: list[dict[str, str]] = []
    structure: list[str] = []

    with zipfile.ZipFile(zip_buffer, "r") as archive:
        for entry in archive.namelist():
            normalized = entry.replace("\\", "/")
            if any(f"/{name}/" in normalized or normalized.startswith(f"{name}/") for name in IGNORE_DIRS):
                continue
            structure.append(normalized)
            if normalized.endswith("/"):
                continue

            ext = os.path.splitext(normalized)[1].lower()
            base_name = os.path.basename(normalized)
            if base_name not in SUPPORTED_FILES and ext not in SUPPORTED_EXTENSIONS:
                continue

            info = archive.getinfo(entry)
            if info.file_size > 100 * 1024:
                continue

            try:
                files.append({"name": normalized, "content": archive.read(entry).decode("utf-8")})
            except (UnicodeDecodeError, KeyError):
                continue

    return {"files": files, "structure": structure}


async def parse_github(github_url: str) -> dict:
    """Fetch and parse a GitHub repository's files."""
    owner, clean_repo = _validate_github_url(github_url)
    github_token = os.getenv("GITHUB_TOKEN", "").strip()
    headers = {
        "User-Agent": "Nestify/2.0",
        "Accept": "application/vnd.github.v3+json",
    }
    if github_token:
        headers["Authorization"] = f"Bearer {github_token}"

    async with httpx.AsyncClient(timeout=30, headers=headers) as client:
        repo_meta = await client.get(f"https://api.github.com/repos/{owner}/{clean_repo}")
        default_branch = None
        if repo_meta.status_code == 200:
            default_branch = (repo_meta.json() or {}).get("default_branch")

        branches = [
            branch
            for branch in [default_branch, "main", "master", "canary", "dev", "trunk"]
            if isinstance(branch, str) and branch.strip()
        ]
        # Preserve order while removing duplicates.
        branches = list(dict.fromkeys(branches))

        tree: list[dict] = []
        last_error: str | None = None
        for branch in branches:
            response = await client.get(f"https://api.github.com/repos/{owner}/{clean_repo}/git/trees/{branch}?recursive=1")
            if response.status_code == 200:
                tree = response.json().get("tree", [])
                break
            if response.status_code in {401, 403}:
                last_error = "GitHub API rate limit reached or unauthorized request. Add GITHUB_TOKEN and try again."
            elif response.status_code == 404:
                last_error = f"Branch '{branch}' not found."
            else:
                last_error = f"GitHub API error ({response.status_code}) while reading branch '{branch}'."
        if not tree:
            attempted = ", ".join(branches) if branches else "(none)"
            raise RuntimeError(
                last_error
                or f"Could not fetch repository tree. Tried branches: {attempted}."
            )

        relevant_entries = [
            entry
            for entry in tree
            if entry.get("type") == "blob"
            and not any(f"{ignored}/" in entry["path"] for ignored in IGNORE_DIRS)
            and entry.get("size", 0) <= 100 * 1024
            and (
                os.path.basename(entry["path"]) in SUPPORTED_FILES
                or os.path.splitext(entry["path"])[1].lower() in SUPPORTED_EXTENSIONS
            )
        ]

        files: list[dict[str, str]] = []
        for entry in relevant_entries[:40]:
            for branch in branches:
                raw = await client.get(f"https://raw.githubusercontent.com/{owner}/{clean_repo}/{branch}/{entry['path']}")
                if raw.status_code == 200:
                    files.append({"name": entry["path"], "content": raw.text})
                    break

        if not files:
            raise RuntimeError("Repository parsed but no readable source files were found.")

    return {"files": files, "structure": [entry["path"] for entry in tree]}


def parse_text(text: str, filename: str = "pasted_code.txt") -> dict:
    """Parse pasted text into a single-file project."""
    # Only auto-detect filename when the user didn't provide one
    if filename == "pasted_code.txt":
        if '"name"' in text and '"dependencies"' in text:
            filename = "package.json"
        elif "<!doctype html" in text.lower() or "<html" in text.lower():
            filename = "index.html"
        elif "from fastapi" in text.lower() or "import flask" in text.lower():
            filename = "app.py"
        elif "require(" in text or "express" in text.lower():
            filename = "index.js"
    return {"files": [{"name": filename, "content": text}], "structure": [filename]}


def parse_natural_language(description: str) -> dict:
    """Create an empty project structure from a natural language description."""
    return {"files": [], "structure": [], "description": description}