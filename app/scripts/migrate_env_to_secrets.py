"""One-time migration: import .env values into SecretStore and remove the file."""

from __future__ import annotations

import argparse
import os
from pathlib import Path

from app.core.secrets import get_secret_store
from app.services.project_source_service import get_project_source_dir


def _parse_env_file(path: Path) -> dict[str, str]:
    entries: dict[str, str] = {}
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        if "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip().strip("\"")
        if key:
            entries[key] = value
    return entries


def _ensure_gitignore(root: Path) -> None:
    gitignore = root / ".gitignore"
    if not gitignore.exists():
        gitignore.write_text(".env\n", encoding="utf-8")
        return

    content = gitignore.read_text(encoding="utf-8")
    if ".env" not in content:
        gitignore.write_text(content.rstrip() + "\n.env\n", encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser(description="Migrate .env secrets into SecretStore.")
    parser.add_argument("--project-id", required=True, help="Nestify project id")
    parser.add_argument("--env-path", default="", help="Optional path to .env file")
    args = parser.parse_args()

    project_id = str(args.project_id)
    env_path = Path(args.env_path) if args.env_path else Path(get_project_source_dir(int(project_id))) / "source" / ".env"

    if not env_path.exists():
        raise SystemExit(f"No .env file found at {env_path}")

    entries = _parse_env_file(env_path)
    if not entries:
        raise SystemExit("No secrets found in .env file.")

    store = get_secret_store()
    for key, value in entries.items():
        store.set(project_id, key, value, agent_name="EnvMigration")

    env_path.unlink(missing_ok=True)
    _ensure_gitignore(Path.cwd())

    print(f"Migrated {len(entries)} secrets into SecretStore and removed {env_path}.")


if __name__ == "__main__":
    main()
