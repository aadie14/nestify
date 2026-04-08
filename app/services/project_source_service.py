"""
Project source persistence helpers.

Handles on-disk storage and retrieval of uploaded project files
for scanning, fixing, and deployment packaging.
"""

import io
import json
import os
import shutil
import asyncio
import zipfile
from pathlib import Path, PurePosixPath

from app.core.config import settings

SOURCE_ROOT = Path(__file__).resolve().parent.parent / "project_sources"
TEXT_EXTENSIONS = {
    ".txt", ".md", ".py", ".js", ".ts", ".jsx", ".tsx", ".json", ".html",
    ".css", ".yml", ".yaml", ".toml", ".env", ".sql", ".sh", ".mjs", ".cjs",
}
IGNORE_DIRS = [
    "node_modules", ".git", "__pycache__", ".venv", "venv", "env", ".next",
    "dist", "build", ".cache", "coverage", ".idea", ".vscode",
]
FRONTEND_BUILD_FRAMEWORKS = {"react", "vue", "next", "static", "vite", "svelte", "astro"}


def _project_dir(project_id: int) -> Path:
    return SOURCE_ROOT / str(project_id)


def get_project_source_dir(project_id: int) -> str:
    """Return the on-disk source directory for a project."""
    return str(_project_dir(project_id))


def _ensure_clean_dir(project_id: int) -> Path:
    project_dir = _project_dir(project_id)
    if project_dir.exists():
        shutil.rmtree(project_dir)
    project_dir.mkdir(parents=True, exist_ok=True)
    return project_dir


def _is_safe_relative_path(rel_path: str) -> bool:
    path = PurePosixPath(rel_path)
    return not path.is_absolute() and ".." not in path.parts


def _is_ignored_path(rel_path: str) -> bool:
    normalized = rel_path.replace("\\", "/").strip("/")
    parts = normalized.split("/") if normalized else []
    return any(part in IGNORE_DIRS for part in parts)


def _write_metadata(project_dir: Path, metadata: dict) -> None:
    (project_dir / ".nestify-source.json").write_text(
        json.dumps(metadata, indent=2),
        encoding="utf-8",
    )


def persist_uploaded_source(
    project_id: int,
    *,
    input_type: str,
    original_name: str | None = None,
    file_bytes: bytes | None = None,
    text_content: str | None = None,
    text_filename: str | None = None,
    github_url: str | None = None,
    description: str | None = None,
) -> None:
    """Persist raw project input to disk for later scanning and deployment."""
    project_dir = _ensure_clean_dir(project_id)
    source_dir = project_dir / "source"
    source_dir.mkdir(parents=True, exist_ok=True)

    metadata = {
        "input_type": input_type,
        "original_name": original_name,
        "github_url": github_url,
        "description": description,
    }
    _write_metadata(project_dir, metadata)

    if input_type == "zip" and file_bytes is not None:
        (project_dir / (original_name or "upload.zip")).write_bytes(file_bytes)
        with zipfile.ZipFile(io.BytesIO(file_bytes), "r") as archive:
            for info in archive.infolist():
                rel_path = info.filename.replace("\\", "/")
                if info.is_dir() or not _is_safe_relative_path(rel_path) or _is_ignored_path(rel_path):
                    continue
                target = source_dir / rel_path
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_bytes(archive.read(info))
        return

    if input_type == "text" and text_content is not None:
        filename = (text_filename or original_name or "input.txt").replace("\\", "/")
        if not _is_safe_relative_path(filename):
            filename = "input.txt"
        target = source_dir / filename
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(text_content, encoding="utf-8")


def materialize_generated_files(
    project_id: int,
    files: list[dict],
    preserve_existing: bool = False,
) -> None:
    """Write generated files into the project source tree."""
    source_dir = Path(get_project_source_dir(project_id)) / "source"
    source_dir.mkdir(parents=True, exist_ok=True)

    for file_info in files:
        rel_path = file_info.get("name", "").replace("\\", "/")
        content = file_info.get("content", "")
        if not rel_path or not _is_safe_relative_path(rel_path):
            continue

        target = source_dir / rel_path
        if preserve_existing and target.exists():
            continue

        target.parent.mkdir(parents=True, exist_ok=True)
        if isinstance(content, bytes):
            target.write_bytes(content)
        else:
            target.write_text(content, encoding="utf-8")


def load_source_file_map(project_id: int, *, include_hidden: bool = True) -> dict[str, bytes]:
    """Load all persisted source files as a path → bytes mapping."""
    source_dir = Path(get_project_source_dir(project_id)) / "source"
    if not source_dir.exists():
        return {}

    file_map: dict[str, bytes] = {}
    for path in source_dir.rglob("*"):
        if not path.is_file():
            continue
        rel_path = path.relative_to(source_dir).as_posix()
        if not include_hidden and any(part.startswith(".") for part in rel_path.split("/")):
            continue
        file_map[rel_path] = path.read_bytes()
    return file_map


def load_source_text_map(project_id: int) -> dict[str, str]:
    """Load persisted source files that are likely text files."""
    text_map = {}
    for path, content in load_source_file_map(project_id).items():
        ext = os.path.splitext(path)[1].lower()
        if ext and ext not in TEXT_EXTENSIONS and not path.endswith(("Dockerfile", ".dockerignore")):
            continue
        try:
            text_map[path] = content.decode("utf-8")
        except UnicodeDecodeError:
            continue
    return text_map


def normalize_framework_name(value: str | None) -> str:
    return str(value or "").strip().lower()


def is_frontend_build_framework(framework: str | None) -> bool:
    return normalize_framework_name(framework) in FRONTEND_BUILD_FRAMEWORKS


def project_has_package_json(project_id: int) -> bool:
    source_dir = Path(get_project_source_dir(project_id)) / "source"
    return (source_dir / "package.json").exists()


def get_local_preview_url(project_id: int) -> str:
    return f"http://127.0.0.1:{settings.port}/preview/{project_id}"


def ensure_preview_index(project_id: int) -> str:
    source_dir = Path(get_project_source_dir(project_id)) / "source"
    source_dir.mkdir(parents=True, exist_ok=True)
    index_file = source_dir / "index.html"
    if index_file.exists():
        return str(index_file)

    listing: list[str] = []
    for path in sorted(source_dir.rglob("*")):
        if not path.is_file():
            continue
        rel = path.relative_to(source_dir).as_posix()
        if rel == "index.html" or rel.startswith("."):
            continue
        listing.append(rel)
        if len(listing) >= 200:
            break

    list_items = "\n".join(
        f"<li><a href=\"/preview/{project_id}/{item}\">{item}</a></li>"
        for item in listing
    )
    html = (
        "<!doctype html>\n"
        "<html><head><meta charset=\"utf-8\"><title>Nestify Preview</title></head>\n"
        "<body>\n"
        f"<h1>Preview for project {project_id}</h1>\n"
        "<p>No index.html was found in source. Showing available files.</p>\n"
        "<ul>\n"
        f"{list_items}\n"
        "</ul>\n"
        "</body></html>\n"
    )
    index_file.write_text(html, encoding="utf-8")
    return str(index_file)


def _copy_tree_contents(src_dir: Path, dst_dir: Path) -> None:
    dst_dir.mkdir(parents=True, exist_ok=True)
    for item in src_dir.iterdir():
        target = dst_dir / item.name
        if item.is_dir():
            if target.exists():
                shutil.rmtree(target)
            shutil.copytree(item, target)
        else:
            shutil.copy2(item, target)


def _normalize_build_output_to_dist(source_dir: Path) -> Path | None:
    dist_dir = source_dir / "dist"
    candidates = [source_dir / "dist", source_dir / "build", source_dir / "out"]

    selected: Path | None = None
    for candidate in candidates:
        if candidate.exists() and candidate.is_dir() and (candidate / "index.html").exists():
            selected = candidate
            break

    if selected is None:
        return None

    if selected != dist_dir:
        if dist_dir.exists():
            shutil.rmtree(dist_dir)
        dist_dir.mkdir(parents=True, exist_ok=True)
        _copy_tree_contents(selected, dist_dir)

    if (dist_dir / "index.html").exists():
        return dist_dir
    return None


def _run_node_build_in_docker(source_dir: Path) -> dict[str, str | bool]:
    try:
        import docker  # type: ignore[import-untyped]
    except Exception as exc:
        return {"ok": False, "error": f"docker_sdk_unavailable: {exc}"}

    image = os.getenv("NESTIFY_NODE_BUILD_IMAGE", "node:20-alpine")
    command = "sh -lc \"npm install && npm run build\""
    container = None
    client = None

    try:
        client = docker.from_env()
        client.ping()

        cpu_period = 100000
        cpu_quota = int(cpu_period * max(0.2, min(settings.docker_max_cpu, 1.0)))

        container = client.containers.run(
            image=image,
            command=command,
            working_dir="/workspace",
            volumes={str(source_dir.resolve()): {"bind": "/workspace", "mode": "rw"}},
            detach=True,
            mem_limit=settings.docker_max_memory,
            cpu_period=cpu_period,
            cpu_quota=cpu_quota,
            network_disabled=False,
        )

        wait_result = container.wait(timeout=max(120, settings.docker_timeout_seconds))
        status_code = int(wait_result.get("StatusCode", -1))
        logs = container.logs(stdout=True, stderr=True).decode("utf-8", errors="ignore")
        if status_code != 0:
            return {
                "ok": False,
                "error": f"npm_build_failed_exit_{status_code}",
                "logs_tail": logs[-6000:],
            }

        return {"ok": True, "logs_tail": logs[-2000:]}
    except Exception as exc:
        return {"ok": False, "error": str(exc)}
    finally:
        try:
            if container is not None:
                container.remove(force=True)
        except Exception:
            pass
        try:
            if client is not None:
                client.close()
        except Exception:
            pass


async def build_static_source_in_docker(project_id: int) -> dict[str, str | bool]:
    source_dir = Path(get_project_source_dir(project_id)) / "source"
    package_json = source_dir / "package.json"
    if not package_json.exists():
        return {"ok": False, "error": "package_json_missing"}

    build_result = await asyncio.to_thread(_run_node_build_in_docker, source_dir)
    if not build_result.get("ok"):
        return build_result

    output = _normalize_build_output_to_dist(source_dir)
    if output is None:
        return {
            "ok": False,
            "error": "build_output_missing",
            "logs_tail": str(build_result.get("logs_tail") or ""),
        }

    return {
        "ok": True,
        "output_dir": output.as_posix(),
        "logs_tail": str(build_result.get("logs_tail") or ""),
    }