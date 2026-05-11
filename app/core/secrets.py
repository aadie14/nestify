"""Secret management abstraction with provider backends and audit logging."""

from __future__ import annotations

import base64
import json
import os
import re
import sqlite3
import time
from dataclasses import dataclass
from typing import Any, List, Optional, Protocol

import httpx
from cryptography.fernet import Fernet
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC
import google.auth
from google.auth.transport.requests import Request
import boto3

from app.database import add_log


class SecretStore(Protocol):
    def set(self, project_id: str, key: str, value: str) -> None: ...
    def get(self, project_id: str, key: str) -> Optional[str]: ...
    def list_keys(self, project_id: str) -> List[str]: ...
    def delete(self, project_id: str, key: str) -> None: ...
    def exists(self, project_id: str, key: str) -> bool: ...


@dataclass(slots=True)
class AuditEntry:
    project_id: str
    key_name: str
    operation: str
    agent_name: str
    timestamp: float


def _audit(entry: AuditEntry) -> None:
    payload = {
        "timestamp": entry.timestamp,
        "project_id": entry.project_id,
        "key_name": entry.key_name,
        "operation": entry.operation,
        "agent_name": entry.agent_name,
    }
    try:
        project_id = int(entry.project_id)
    except (TypeError, ValueError):
        project_id = 0
    add_log(project_id, "SecretStore", json.dumps(payload), "info")


class SecretManager:
    """Wrapper that adds audit logging to secret operations."""

    def __init__(self, store: SecretStore) -> None:
        self.store = store

    def set(self, project_id: str, key: str, value: str, *, agent_name: str = "system") -> None:
        self.store.set(project_id, key, value)
        _audit(AuditEntry(project_id, key, "write", agent_name, time.time()))

    def get(self, project_id: str, key: str, *, agent_name: str = "system") -> Optional[str]:
        value = self.store.get(project_id, key)
        _audit(AuditEntry(project_id, key, "read", agent_name, time.time()))
        return value

    def list_keys(self, project_id: str, *, agent_name: str = "system") -> List[str]:
        keys = self.store.list_keys(project_id)
        _audit(AuditEntry(project_id, "*", "list", agent_name, time.time()))
        return keys

    def delete(self, project_id: str, key: str, *, agent_name: str = "system") -> None:
        self.store.delete(project_id, key)
        _audit(AuditEntry(project_id, key, "delete", agent_name, time.time()))

    def exists(self, project_id: str, key: str, *, agent_name: str = "system") -> bool:
        found = self.store.exists(project_id, key)
        _audit(AuditEntry(project_id, key, "exists", agent_name, time.time()))
        return found


class VaultSecretStore:
    def __init__(self, addr: str, token: str, kv_path: str = "secret") -> None:
        self.addr = addr.rstrip("/")
        self.token = token
        self.kv_path = kv_path.strip("/")

    def _headers(self) -> dict[str, str]:
        return {"X-Vault-Token": self.token}

    def _path(self, project_id: str, key: str) -> str:
        return f"{self.addr}/v1/{self.kv_path}/data/nestify/{project_id}/{key}"

    def _metadata_path(self, project_id: str) -> str:
        return f"{self.addr}/v1/{self.kv_path}/metadata/nestify/{project_id}"

    def set(self, project_id: str, key: str, value: str) -> None:
        payload = {"data": {"value": value}}
        resp = httpx.post(self._path(project_id, key), headers=self._headers(), json=payload, timeout=10)
        if resp.status_code >= 400:
            raise RuntimeError(f"Vault write failed: {resp.text[:200]}")

    def get(self, project_id: str, key: str) -> Optional[str]:
        resp = httpx.get(self._path(project_id, key), headers=self._headers(), timeout=10)
        if resp.status_code == 404:
            return None
        if resp.status_code >= 400:
            raise RuntimeError(f"Vault read failed: {resp.text[:200]}")
        payload = resp.json() if resp.content else {}
        return (payload.get("data") or {}).get("data", {}).get("value")

    def list_keys(self, project_id: str) -> List[str]:
        resp = httpx.get(self._metadata_path(project_id), headers=self._headers(), timeout=10)
        if resp.status_code == 404:
            return []
        if resp.status_code >= 400:
            raise RuntimeError(f"Vault list failed: {resp.text[:200]}")
        payload = resp.json() if resp.content else {}
        return (payload.get("data") or {}).get("keys", [])

    def delete(self, project_id: str, key: str) -> None:
        resp = httpx.delete(self._path(project_id, key), headers=self._headers(), timeout=10)
        if resp.status_code not in {200, 204, 404}:
            raise RuntimeError(f"Vault delete failed: {resp.text[:200]}")

    def exists(self, project_id: str, key: str) -> bool:
        resp = httpx.get(self._path(project_id, key), headers=self._headers(), timeout=10)
        return resp.status_code < 400


class GcpSecretStore:
    def __init__(self, project: str) -> None:
        self.project = project
        self._creds, _ = google.auth.default(scopes=["https://www.googleapis.com/auth/cloud-platform"])

    def _token(self) -> str:
        if not self._creds.valid:
            self._creds.refresh(Request())
        return str(self._creds.token)

    def _secret_name(self, project_id: str, key: str) -> str:
        return f"projects/{self.project}/secrets/nestify-{project_id}-{_sanitize(key)}"

    def _headers(self) -> dict[str, str]:
        return {"Authorization": f"Bearer {self._token()}"}

    def _create_if_missing(self, secret_name: str) -> None:
        url = f"https://secretmanager.googleapis.com/v1/{secret_name}"
        resp = httpx.get(url, headers=self._headers(), timeout=10)
        if resp.status_code == 404:
            create_url = f"https://secretmanager.googleapis.com/v1/projects/{self.project}/secrets?secretId={secret_name.split('/')[-1]}"
            payload = {"replication": {"automatic": {}}}
            create_resp = httpx.post(create_url, headers=self._headers(), json=payload, timeout=10)
            if create_resp.status_code >= 400:
                raise RuntimeError(f"GCP secret create failed: {create_resp.text[:200]}")
        elif resp.status_code >= 400:
            raise RuntimeError(f"GCP secret check failed: {resp.text[:200]}")

    def set(self, project_id: str, key: str, value: str) -> None:
        secret_name = self._secret_name(project_id, key)
        self._create_if_missing(secret_name)
        url = f"https://secretmanager.googleapis.com/v1/{secret_name}:addVersion"
        payload = {"payload": {"data": base64.b64encode(value.encode("utf-8")).decode("ascii")}}
        resp = httpx.post(url, headers=self._headers(), json=payload, timeout=10)
        if resp.status_code >= 400:
            raise RuntimeError(f"GCP secret write failed: {resp.text[:200]}")

    def get(self, project_id: str, key: str) -> Optional[str]:
        secret_name = self._secret_name(project_id, key)
        url = f"https://secretmanager.googleapis.com/v1/{secret_name}/versions/latest:access"
        resp = httpx.get(url, headers=self._headers(), timeout=10)
        if resp.status_code == 404:
            return None
        if resp.status_code >= 400:
            raise RuntimeError(f"GCP secret read failed: {resp.text[:200]}")
        payload = resp.json() if resp.content else {}
        data = (payload.get("payload") or {}).get("data")
        return base64.b64decode(data).decode("utf-8") if data else None

    def list_keys(self, project_id: str) -> List[str]:
        url = f"https://secretmanager.googleapis.com/v1/projects/{self.project}/secrets"
        resp = httpx.get(url, headers=self._headers(), timeout=10)
        if resp.status_code >= 400:
            raise RuntimeError(f"GCP secret list failed: {resp.text[:200]}")
        payload = resp.json() if resp.content else {}
        keys: list[str] = []
        prefix = f"projects/{self.project}/secrets/nestify-{project_id}-"
        for item in payload.get("secrets", []) or []:
            name = str(item.get("name") or "")
            if name.startswith(prefix):
                keys.append(name[len(prefix):])
        return sorted(set(keys))

    def delete(self, project_id: str, key: str) -> None:
        secret_name = self._secret_name(project_id, key)
        url = f"https://secretmanager.googleapis.com/v1/{secret_name}"
        resp = httpx.delete(url, headers=self._headers(), timeout=10)
        if resp.status_code not in {200, 204, 404}:
            raise RuntimeError(f"GCP secret delete failed: {resp.text[:200]}")

    def exists(self, project_id: str, key: str) -> bool:
        secret_name = self._secret_name(project_id, key)
        url = f"https://secretmanager.googleapis.com/v1/{secret_name}"
        resp = httpx.get(url, headers=self._headers(), timeout=10)
        return resp.status_code < 400


class AwsSecretStore:
    def __init__(self, region: str) -> None:
        self.client = boto3.client("secretsmanager", region_name=region)

    def _name(self, project_id: str, key: str) -> str:
        return f"nestify/{project_id}/{_sanitize(key)}"

    def set(self, project_id: str, key: str, value: str) -> None:
        name = self._name(project_id, key)
        try:
            self.client.create_secret(Name=name, SecretString=value)
        except self.client.exceptions.ResourceExistsException:
            self.client.put_secret_value(SecretId=name, SecretString=value)

    def get(self, project_id: str, key: str) -> Optional[str]:
        name = self._name(project_id, key)
        try:
            resp = self.client.get_secret_value(SecretId=name)
            return resp.get("SecretString")
        except self.client.exceptions.ResourceNotFoundException:
            return None

    def list_keys(self, project_id: str) -> List[str]:
        prefix = f"nestify/{project_id}/"
        keys: list[str] = []
        paginator = self.client.get_paginator("list_secrets")
        for page in paginator.paginate():
            for item in page.get("SecretList", []):
                name = str(item.get("Name") or "")
                if name.startswith(prefix):
                    keys.append(name.split(prefix)[-1])
        return sorted(set(keys))

    def delete(self, project_id: str, key: str) -> None:
        name = self._name(project_id, key)
        try:
            self.client.delete_secret(SecretId=name, ForceDeleteWithoutRecovery=True)
        except self.client.exceptions.ResourceNotFoundException:
            return

    def exists(self, project_id: str, key: str) -> bool:
        name = self._name(project_id, key)
        try:
            self.client.describe_secret(SecretId=name)
            return True
        except self.client.exceptions.ResourceNotFoundException:
            return False


class LocalEncryptedSecretStore:
    def __init__(self, db_path: str, master_key: str) -> None:
        self.db_path = db_path
        self._init_db()
        self.fernet = Fernet(_derive_fernet_key(master_key, self._load_or_create_salt()))

    def _init_db(self) -> None:
        conn = sqlite3.connect(self.db_path)
        conn.execute(
            "CREATE TABLE IF NOT EXISTS secrets (project_id TEXT, key TEXT, value BLOB, PRIMARY KEY(project_id, key))"
        )
        conn.execute(
            "CREATE TABLE IF NOT EXISTS secret_meta (id INTEGER PRIMARY KEY, salt BLOB)"
        )
        conn.commit()
        conn.close()

    def _load_or_create_salt(self) -> bytes:
        conn = sqlite3.connect(self.db_path)
        row = conn.execute("SELECT salt FROM secret_meta WHERE id = 1").fetchone()
        if row and row[0]:
            conn.close()
            return row[0]
        salt = os.urandom(16)
        conn.execute("INSERT OR REPLACE INTO secret_meta (id, salt) VALUES (1, ?)", (salt,))
        conn.commit()
        conn.close()
        return salt

    def set(self, project_id: str, key: str, value: str) -> None:
        token = self.fernet.encrypt(value.encode("utf-8"))
        conn = sqlite3.connect(self.db_path)
        conn.execute(
            "INSERT OR REPLACE INTO secrets (project_id, key, value) VALUES (?, ?, ?)",
            (project_id, key, token),
        )
        conn.commit()
        conn.close()

    def get(self, project_id: str, key: str) -> Optional[str]:
        conn = sqlite3.connect(self.db_path)
        row = conn.execute(
            "SELECT value FROM secrets WHERE project_id = ? AND key = ?",
            (project_id, key),
        ).fetchone()
        conn.close()
        if not row or not row[0]:
            return None
        return self.fernet.decrypt(row[0]).decode("utf-8")

    def list_keys(self, project_id: str) -> List[str]:
        conn = sqlite3.connect(self.db_path)
        rows = conn.execute(
            "SELECT key FROM secrets WHERE project_id = ?",
            (project_id,),
        ).fetchall()
        conn.close()
        return [row[0] for row in rows]

    def delete(self, project_id: str, key: str) -> None:
        conn = sqlite3.connect(self.db_path)
        conn.execute(
            "DELETE FROM secrets WHERE project_id = ? AND key = ?",
            (project_id, key),
        )
        conn.commit()
        conn.close()

    def exists(self, project_id: str, key: str) -> bool:
        conn = sqlite3.connect(self.db_path)
        row = conn.execute(
            "SELECT 1 FROM secrets WHERE project_id = ? AND key = ?",
            (project_id, key),
        ).fetchone()
        conn.close()
        return bool(row)


def _sanitize(value: str) -> str:
    return re.sub(r"[^a-zA-Z0-9_-]+", "-", value).strip("-") or "secret"


def _derive_fernet_key(master_key: str, salt: bytes) -> bytes:
    kdf = PBKDF2HMAC(
        algorithm=hashes.SHA256(),
        length=32,
        salt=salt,
        iterations=200_000,
    )
    return base64.urlsafe_b64encode(kdf.derive(master_key.encode("utf-8")))


_STORE: SecretManager | None = None


def get_secret_store() -> SecretManager:
    global _STORE
    if _STORE is not None:
        return _STORE

    if os.getenv("VAULT_ADDR"):
        token = os.getenv("VAULT_TOKEN", "").strip()
        if not token:
            raise RuntimeError("VAULT_ADDR set but VAULT_TOKEN is missing.")
        kv_path = os.getenv("VAULT_KV_PATH", "secret")
        _STORE = SecretManager(VaultSecretStore(os.getenv("VAULT_ADDR", ""), token, kv_path))
        return _STORE

    if os.getenv("GOOGLE_CLOUD_PROJECT"):
        _STORE = SecretManager(GcpSecretStore(os.getenv("GOOGLE_CLOUD_PROJECT", "")))
        return _STORE

    if os.getenv("AWS_DEFAULT_REGION"):
        _STORE = SecretManager(AwsSecretStore(os.getenv("AWS_DEFAULT_REGION", "")))
        return _STORE

    master_key = os.getenv("NESTIFY_MASTER_KEY", "").strip()
    if not master_key:
        raise RuntimeError("NESTIFY_MASTER_KEY is required for local encrypted secret storage.")
    db_path = os.getenv("NESTIFY_SECRET_DB", "app/secrets.db")
    _STORE = SecretManager(LocalEncryptedSecretStore(db_path, master_key))
    return _STORE
