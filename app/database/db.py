"""SQLite persistence layer for the Nestify DevSecOps pipeline."""

from __future__ import annotations

import json
import os
import sqlite3
import time
from datetime import date
from typing import Any


DB_PATH = os.path.join(os.path.dirname(os.path.dirname(__file__)), "nestify.db")
SCHEMA_PATH = os.path.join(os.path.dirname(os.path.dirname(__file__)), "schema.sql")
SQLITE_TIMEOUT_SECONDS = 30
SQLITE_BUSY_TIMEOUT_MS = SQLITE_TIMEOUT_SECONDS * 1000


def _with_locked_db_retry(write_fn, retries: int = 3) -> Any:
    """Retry write operations when SQLite reports a transient lock."""
    last_error: sqlite3.OperationalError | None = None
    for _ in range(retries):
        conn = get_connection()
        try:
            result = write_fn(conn)
            conn.commit()
            return result
        except sqlite3.OperationalError as error:
            last_error = error
            if "database is locked" not in str(error).lower():
                raise
            time.sleep(0.15)
        finally:
            conn.close()
    if last_error:
        raise last_error
    return None


# ─── Connection ──────────────────────────────────────────────────


def get_connection() -> sqlite3.Connection:
    """Return a new SQLite connection with WAL mode and foreign keys enabled."""
    conn = sqlite3.connect(DB_PATH, timeout=SQLITE_TIMEOUT_SECONDS)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode = WAL")
    conn.execute(f"PRAGMA busy_timeout = {SQLITE_BUSY_TIMEOUT_MS}")
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def init_db() -> None:
    """Create all tables from schema.sql if they don't exist."""
    conn = get_connection()
    with open(SCHEMA_PATH, "r", encoding="utf-8") as handle:
        conn.executescript(handle.read())

    # Additive, backward-compatible migrations for existing local DBs.
    project_columns = {
        row[1]
        for row in conn.execute("PRAGMA table_info(projects)").fetchall()
    }
    if "agentic_insights" not in project_columns:
        conn.execute("ALTER TABLE projects ADD COLUMN agentic_insights TEXT")
    if "learning_opt_out" not in project_columns:
        conn.execute("ALTER TABLE projects ADD COLUMN learning_opt_out INTEGER DEFAULT 0")
    if "security_report_pdf" not in project_columns:
        conn.execute("ALTER TABLE projects ADD COLUMN security_report_pdf TEXT")

    conn.commit()
    conn.close()


# ─── Projects ────────────────────────────────────────────────────


def create_project(
    name: str,
    input_type: str,
    source_payload: dict[str, Any] | None = None,
    preferred_provider: str | None = None,
) -> int:
    """Insert a new project and return its ID."""
    pipeline_state = json.dumps({
        "security_agent": "pending",
        "fix_agent": "pending",
        "deployment_agent": "pending",
    })
    conn = get_connection()
    cursor = conn.execute(
        """
        INSERT INTO projects (name, input_type, source_payload, pipeline_state, preferred_provider)
        VALUES (?, ?, ?, ?, ?)
        """,
        (name, input_type, json.dumps(source_payload or {}), pipeline_state, preferred_provider),
    )
    project_id = cursor.lastrowid
    conn.commit()
    conn.close()
    return int(project_id)


def get_project(project_id: int) -> dict[str, Any] | None:
    """Fetch a single project by ID."""
    conn = get_connection()
    row = conn.execute("SELECT * FROM projects WHERE id = ?", (project_id,)).fetchone()
    conn.close()
    return dict(row) if row else None


def list_projects() -> list[dict[str, Any]]:
    """List all projects ordered by creation time."""
    conn = get_connection()
    rows = conn.execute("SELECT * FROM projects ORDER BY created_at ASC").fetchall()
    conn.close()
    return [dict(row) for row in rows]


def update_project(project_id: int, fields: dict[str, Any]) -> None:
    """Update allowed fields on a project row."""
    allowed = {
        "name", "status", "source_payload", "stack_info",
        "security_report", "security_score", "fix_report",
        "deployment", "public_url", "preferred_provider",
        "pipeline_state", "agentic_insights", "learning_opt_out", "security_report_pdf",
    }
    sets: list[str] = []
    values: list[Any] = []
    for key, value in fields.items():
        if key not in allowed:
            continue
        sets.append(f"{key} = ?")
        values.append(json.dumps(value) if isinstance(value, (dict, list)) else value)

    if not sets:
        return

    sets.append("updated_at = CURRENT_TIMESTAMP")
    values.append(project_id)

    _with_locked_db_retry(
        lambda conn: conn.execute(f"UPDATE projects SET {', '.join(sets)} WHERE id = ?", values)
    )


# ─── Scan Results ────────────────────────────────────────────────


def add_scan_result(
    project_id: int,
    severity: str,
    issue_type: str,
    description: str,
    file: str | None = None,
    line: int | None = None,
    recommendation: str | None = None,
    source: str = "pattern_scan",
) -> None:
    """Insert a single scan finding."""
    conn = get_connection()
    conn.execute(
        """
        INSERT INTO scan_results (project_id, severity, type, file, line, description, recommendation, source)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (project_id, severity, issue_type, file, line, description, recommendation, source),
    )
    conn.commit()
    conn.close()


def get_scan_results(project_id: int) -> list[dict[str, Any]]:
    """Fetch all scan findings for a project."""
    conn = get_connection()
    rows = conn.execute(
        "SELECT * FROM scan_results WHERE project_id = ? ORDER BY created_at ASC",
        (project_id,),
    ).fetchall()
    conn.close()
    return [dict(row) for row in rows]


def clear_scan_results(project_id: int) -> None:
    """Remove all scan results for a project (used before rescan)."""
    conn = get_connection()
    conn.execute("DELETE FROM scan_results WHERE project_id = ?", (project_id,))
    conn.commit()
    conn.close()


# ─── Fix Logs ────────────────────────────────────────────────────


def add_fix_log(
    project_id: int,
    file: str,
    fix_type: str,
    status: str,
    note: str | None = None,
) -> None:
    """Record a fix action."""
    if status == "simulation_failed":
        status = "failed"

    conn = get_connection()
    conn.execute(
        "INSERT INTO fix_logs (project_id, file, fix_type, status, note) VALUES (?, ?, ?, ?, ?)",
        (project_id, file, fix_type, status, note),
    )
    conn.commit()
    conn.close()


def get_fix_logs(project_id: int) -> list[dict[str, Any]]:
    """Fetch all fix log entries for a project."""
    conn = get_connection()
    rows = conn.execute(
        "SELECT * FROM fix_logs WHERE project_id = ? ORDER BY created_at ASC",
        (project_id,),
    ).fetchall()
    conn.close()
    return [dict(row) for row in rows]


# ─── Deployments ─────────────────────────────────────────────────


def add_deployment(
    project_id: int,
    provider: str,
    status: str = "pending",
    deployment_url: str | None = None,
    details: dict[str, Any] | None = None,
) -> int:
    """Record a deployment attempt and return its ID."""
    deploy_id = _with_locked_db_retry(
        lambda conn: conn.execute(
            "INSERT INTO deployments (project_id, provider, status, deployment_url, details) VALUES (?, ?, ?, ?, ?)",
            (project_id, provider, status, deployment_url, json.dumps(details or {})),
        ).lastrowid
    )
    return int(deploy_id)


def update_deployment(deploy_id: int, fields: dict[str, Any]) -> None:
    """Update a deployment record."""
    allowed = {"status", "deployment_url", "details"}
    sets: list[str] = []
    values: list[Any] = []
    for key, value in fields.items():
        if key not in allowed:
            continue
        sets.append(f"{key} = ?")
        values.append(json.dumps(value) if isinstance(value, (dict, list)) else value)
    if not sets:
        return
    values.append(deploy_id)
    _with_locked_db_retry(
        lambda conn: conn.execute(f"UPDATE deployments SET {', '.join(sets)} WHERE id = ?", values)
    )


def get_deployment(project_id: int) -> dict[str, Any] | None:
    """Fetch the latest deployment for a project."""
    conn = get_connection()
    row = conn.execute(
        "SELECT * FROM deployments WHERE project_id = ? ORDER BY created_at DESC LIMIT 1",
        (project_id,),
    ).fetchone()
    conn.close()
    return dict(row) if row else None


# ─── Logs ────────────────────────────────────────────────────────


def add_log(project_id: int, stage: str, message: str, level: str = "info") -> None:
    """Append a structured log entry."""
    last_error: sqlite3.OperationalError | None = None
    for _ in range(3):
        conn = get_connection()
        try:
            conn.execute(
                "INSERT INTO logs (project_id, stage, level, message) VALUES (?, ?, ?, ?)",
                (project_id, stage, level, message),
            )
            conn.commit()
            return
        except sqlite3.OperationalError as error:
            last_error = error
            if "database is locked" not in str(error).lower():
                raise
            time.sleep(0.15)
        finally:
            conn.close()

    if last_error:
        raise last_error


def get_project_logs(project_id: int) -> list[dict[str, Any]]:
    """Fetch all log entries for a project."""
    conn = get_connection()
    rows = conn.execute(
        "SELECT * FROM logs WHERE project_id = ? ORDER BY created_at ASC",
        (project_id,),
    ).fetchall()
    conn.close()
    return [dict(row) for row in rows]


# ─── Token Usage ─────────────────────────────────────────────────


def record_token_usage(model: str, tokens_used: int) -> None:
    """Track daily token consumption per model."""
    today = date.today().isoformat()
    conn = get_connection()
    conn.execute(
        """
        INSERT INTO token_usage (date, model, tokens_used, requests_made)
        VALUES (?, ?, ?, 1)
        ON CONFLICT(date, model) DO UPDATE SET
          tokens_used = tokens_used + excluded.tokens_used,
          requests_made = requests_made + 1
        """,
        (today, model, tokens_used),
    )
    conn.commit()
    conn.close()


def get_today_token_usage() -> dict[str, Any]:
    """Get today's token usage breakdown across all models."""
    today = date.today().isoformat()
    conn = get_connection()
    rows = conn.execute("SELECT * FROM token_usage WHERE date = ?", (today,)).fetchall()
    conn.close()
    breakdown = [dict(row) for row in rows]
    totals = {"tokens": 0, "requests": 0}
    for row in breakdown:
        totals["tokens"] += row["tokens_used"]
        totals["requests"] += row["requests_made"]
    return {"breakdown": breakdown, "totals": totals}


# ─── Agentic Learning Patterns ──────────────────────────────────


def add_deployment_pattern(
    pattern_id: str,
    pattern_payload: dict[str, Any],
    project_id: int | None = None,
    outcome: str | None = None,
) -> int:
    """Insert or replace a learned deployment pattern."""
    conn = get_connection()
    cursor = conn.execute(
        """
        INSERT INTO deployment_patterns (project_id, pattern_id, pattern_payload, outcome)
        VALUES (?, ?, ?, ?)
        ON CONFLICT(pattern_id) DO UPDATE SET
            pattern_payload = excluded.pattern_payload,
            outcome = excluded.outcome,
            created_at = CURRENT_TIMESTAMP
        """,
        (project_id, pattern_id, json.dumps(pattern_payload), outcome),
    )
    pattern_row_id = cursor.lastrowid
    conn.commit()
    conn.close()
    return int(pattern_row_id or 0)


def list_deployment_patterns(limit: int = 200) -> list[dict[str, Any]]:
    """Return recent learned deployment patterns."""
    conn = get_connection()
    rows = conn.execute(
        """
        SELECT * FROM deployment_patterns
        ORDER BY created_at DESC
        LIMIT ?
        """,
        (limit,),
    ).fetchall()
    conn.close()

    parsed: list[dict[str, Any]] = []
    for row in rows:
        item = dict(row)
        payload = item.get("pattern_payload")
        if isinstance(payload, str):
            try:
                item["pattern_payload"] = json.loads(payload)
            except json.JSONDecodeError:
                pass
        parsed.append(item)
    return parsed


def add_deployment_outcome(
    project_id: int,
    framework: str | None,
    platform: str | None,
    success: bool,
    duration_seconds: int | None,
    cost_per_month: float | None,
    fixes_applied: list[str] | None = None,
    debate_transcript: dict[str, Any] | list[dict[str, Any]] | None = None,
    learnings: list[str] | None = None,
    agentic_enabled: bool = True,
) -> int:
    """Persist a deployment outcome row for analytics and learning feedback loops."""
    conn = get_connection()
    cursor = conn.execute(
        """
        INSERT INTO deployment_outcomes (
            project_id, framework, platform, success, duration_seconds,
            cost_per_month, fixes_applied, debate_transcript, learnings, agentic_enabled
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            project_id,
            framework,
            platform,
            1 if success else 0,
            duration_seconds,
            cost_per_month,
            json.dumps(fixes_applied or []),
            json.dumps(debate_transcript or {}),
            json.dumps(learnings or []),
            1 if agentic_enabled else 0,
        ),
    )
    outcome_id = cursor.lastrowid
    conn.commit()
    conn.close()
    return int(outcome_id or 0)


def list_deployment_outcomes(limit: int = 1000) -> list[dict[str, Any]]:
    """Return recent deployment outcomes for trend analytics."""
    conn = get_connection()
    rows = conn.execute(
        """
        SELECT * FROM deployment_outcomes
        ORDER BY created_at DESC
        LIMIT ?
        """,
        (max(1, limit),),
    ).fetchall()
    conn.close()

    parsed: list[dict[str, Any]] = []
    for row in rows:
        item = dict(row)
        for key in ("fixes_applied", "debate_transcript", "learnings"):
            raw = item.get(key)
            if isinstance(raw, str):
                try:
                    item[key] = json.loads(raw)
                except json.JSONDecodeError:
                    item[key] = [] if key != "debate_transcript" else {}
        item["success"] = bool(item.get("success"))
        item["agentic_enabled"] = bool(item.get("agentic_enabled"))
        parsed.append(item)
    return parsed