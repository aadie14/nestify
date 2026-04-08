"""Patch utilities — backup, restore, and syntax validation helpers."""

from __future__ import annotations

import ast
import json
import logging
from pathlib import Path

logger = logging.getLogger(__name__)


def create_backup(target: Path) -> Path:
    """
    Create a .bak backup of the target file before modification.

    Returns the backup path.
    """
    backup_path = target.with_suffix(f"{target.suffix}.bak") if target.suffix else target.with_name(f"{target.name}.bak")
    if not backup_path.exists():
        backup_path.write_bytes(target.read_bytes())
        logger.debug("Created backup: %s", backup_path)
    return backup_path


def restore_from_backup(target: Path) -> bool:
    """
    Restore a file from its .bak backup.

    Returns True if the restore was successful.
    """
    backup_path = target.with_suffix(f"{target.suffix}.bak") if target.suffix else target.with_name(f"{target.name}.bak")
    if backup_path.exists():
        target.write_bytes(backup_path.read_bytes())
        logger.info("Restored from backup: %s", target)
        return True
    return False


def validate_syntax(content: str, file_path: str) -> tuple[bool, str | None]:
    """
    Validate syntax of generated code before applying.

    Args:
        content: The file content to validate.
        file_path: The file path (used to determine language from extension).

    Returns:
        (is_valid, error_message) — error_message is None if valid.
    """
    ext = Path(file_path).suffix.lower()

    if ext == ".py":
        return _validate_python(content)
    if ext == ".json":
        return _validate_json(content)

    # For other file types, basic non-empty check
    if not content or not content.strip():
        return False, "File content is empty"

    return True, None


def _validate_python(content: str) -> tuple[bool, str | None]:
    """Check Python syntax with ast.parse."""
    try:
        ast.parse(content)
        return True, None
    except SyntaxError as e:
        return False, f"Python syntax error at line {e.lineno}: {e.msg}"


def _validate_json(content: str) -> tuple[bool, str | None]:
    """Check JSON validity."""
    try:
        json.loads(content)
        return True, None
    except json.JSONDecodeError as e:
        return False, f"JSON parse error: {e.msg}"
