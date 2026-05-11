"""Secrets API endpoints for project-scoped secret management."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from app.core.secrets import get_secret_store
from app.database import get_project

router = APIRouter()


class SecretCreateRequest(BaseModel):
    key: str = Field(..., min_length=1)
    value: str = Field(..., min_length=1)


@router.post("/projects/{project_id}/secrets")
async def set_secret(project_id: int, payload: SecretCreateRequest) -> dict[str, Any]:
    project = get_project(project_id)
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")
    store = get_secret_store()
    store.set(str(project_id), payload.key, payload.value, agent_name="SecretsAPI")
    return {"status": "stored", "key": payload.key}


@router.get("/projects/{project_id}/secrets")
async def list_secrets(project_id: int) -> dict[str, Any]:
    project = get_project(project_id)
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")
    store = get_secret_store()
    keys = store.list_keys(str(project_id), agent_name="SecretsAPI")
    return {"project_id": project_id, "keys": keys}


@router.delete("/projects/{project_id}/secrets/{key}")
async def delete_secret(project_id: int, key: str) -> dict[str, Any]:
    project = get_project(project_id)
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")
    store = get_secret_store()
    store.delete(str(project_id), key, agent_name="SecretsAPI")
    return {"status": "deleted", "key": key}
