"""Upload API — accepts ZIP, GitHub URL, text, or description and starts the pipeline."""

from __future__ import annotations

import asyncio
import re
import time
from datetime import datetime
from typing import Any
from typing import Optional

from fastapi import APIRouter, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import JSONResponse

from app.core.orchestrator import AgentOrchestrator
from app.database import add_log, create_project, update_project
from app.services.project_source_service import materialize_generated_files, persist_uploaded_source
from app.utils.repo_parser import parse_github, parse_natural_language, parse_text, parse_zip

router = APIRouter()

ALLOWED_PROVIDERS = {"auto", "netlify", "vercel", "railway"}

# In-memory progress storage for WebSocket streaming
pipeline_progress: dict[int, list[dict]] = {}


def cleanup_pipeline_progress() -> None:
    """Remove stale progress entries older than 1 hour."""
    now = time.time()
    stale = [
        pid for pid, entries in pipeline_progress.items()
        if not entries or now - entries[-1].get("timestamp", now) > 3600
    ]
    for pid in stale:
        del pipeline_progress[pid]


def _append_progress(project_id: int, payload: dict) -> None:
    """Thread-safe progress append."""
    pipeline_progress.setdefault(project_id, []).append(
        payload if "timestamp" in payload else {**payload, "timestamp": time.time()}
    )


async def emit_agent_reasoning(
    project_id: int,
    agent: str,
    thought: str,
    decision: str,
    confidence: float,
    evidence: list[str] | None = None,
    data: dict[str, Any] | None = None,
) -> None:
    """Emit a detailed agent reasoning event to progress stream consumers."""

    message = {
        "type": "agent_reasoning",
        "timestamp": datetime.utcnow().isoformat(),
        "agent": agent,
        "thought": thought,
        "decision": decision,
        "confidence": max(0.0, min(1.0, float(confidence))),
        "evidence": evidence or [],
        "data": data or {},
    }
    _append_progress(project_id, message)


def _project_name_from_description(description: str) -> str:
    words = re.findall(r"[a-z0-9]+", description.lower())[:6]
    return "-".join(words) if words else "custom-project"


async def _parse_input(
    file: UploadFile | None,
    github_url: str | None,
    text: str | None,
    filename: str | None,
    description: str | None,
) -> tuple[dict, str, str, bytes | None, str | None]:
    """Parse user input into a standard project format."""
    if file is not None:
        file_bytes = await file.read()
        original_name = file.filename or "uploaded_file"
        if original_name.endswith(".zip"):
            return parse_zip(file_bytes), "zip", original_name.replace(".zip", ""), file_bytes, original_name
        return parse_text(file_bytes.decode("utf-8"), original_name), "text", original_name, file_bytes, original_name
    if github_url:
        try:
            parsed = await parse_github(github_url)
        except ValueError as error:
            raise HTTPException(status_code=400, detail=str(error)) from error
        except RuntimeError as error:
            raise HTTPException(status_code=502, detail=str(error)) from error
        parsed["github_url"] = github_url
        return parsed, "github", github_url.rstrip("/").split("/")[-1].replace(".git", ""), None, None
    if text:
        return parse_text(text, filename or "pasted_code.txt"), "text", filename or "pasted-code", None, None
    if description:
        return parse_natural_language(description), "natural_language", _project_name_from_description(description), None, None
    raise HTTPException(status_code=400, detail="No input provided. Upload a file, paste a GitHub URL, text, or a description.")


@router.post("/")
async def upload(
    request: Request,
    file: Optional[UploadFile] = File(None),
    github_url: Optional[str] = Form(None),
    text: Optional[str] = Form(None),
    filename: Optional[str] = Form(None),
    description: Optional[str] = Form(None),
    provider: Optional[str] = Form("auto"),
    require_fix_approval: Optional[bool] = Form(False),
    agentic: Optional[bool] = Form(True),
):
    """Upload a project and start the autonomous DevSecOps pipeline."""
    provider = (provider or "auto").strip().lower()
    if provider not in ALLOWED_PROVIDERS:
        raise HTTPException(status_code=400, detail="Unsupported deployment provider selected.")
    preferred_provider = None if provider == "auto" else provider

    parsed_input, input_type, project_name, raw_file_bytes, raw_original_name = await _parse_input(
        file, github_url, text, filename, description
    )
    parsed_input["require_fix_approval"] = bool(require_fix_approval)
    parsed_input["agentic_enabled"] = True
    parsed_input["analysis_only"] = True
    cleanup_pipeline_progress()

    project_id = create_project(
        name=project_name,
        input_type=input_type,
        source_payload=parsed_input,
        preferred_provider=preferred_provider,
    )
    persist_uploaded_source(
        project_id,
        input_type=input_type,
        original_name=raw_original_name,
        file_bytes=raw_file_bytes,
        text_content=text if text else (
            raw_file_bytes.decode("utf-8")
            if raw_file_bytes and not (raw_original_name or "").endswith(".zip")
            else None
        ),
        text_filename=filename or raw_original_name,
        github_url=github_url,
        description=description,
    )
    if input_type == "github" and parsed_input.get("files"):
        materialize_generated_files(project_id, parsed_input["files"], preserve_existing=True)

    pipeline_progress[project_id] = []

    async def run_in_background() -> None:
        orchestrator = AgentOrchestrator(
            project_id,
            progress_callback=lambda payload: _append_progress(project_id, payload),
        )
        try:
            await orchestrator.run(parsed_input)
        except Exception as error:
            add_log(project_id, "Orchestrator", f"Pipeline failed: {error}", "error")
            update_project(project_id, {"status": "failed"})
            _append_progress(project_id, {"agent": "Orchestrator", "phase": "error", "message": str(error)})

    asyncio.create_task(run_in_background())

    return JSONResponse({
        "project_id": project_id,
        "name": project_name,
        "input_type": input_type,
        "preferred_provider": preferred_provider,
        "require_fix_approval": bool(require_fix_approval),
        "agentic": True,
        "file_count": len(parsed_input.get("files", [])),
        "message": f"Pipeline started. Poll /api/status/{project_id} for progress.",
    })
