"""Feed formatter for deterministic, high-signal agent events."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any


_AGENT_LABELS: dict[str, str] = {
    "executionengine": "system",
    "metaagent": "meta",
    "meta-agent": "meta",
    "codeanalyzer": "code",
    "securityagent": "security",
    "fixagent": "fix",
    "simulationagent": "simulation",
    "deploymentagent": "deployment",
    "monitoringagent": "monitoring",
}


def _normalize_agent(agent: str) -> str:
    key = str(agent or "").strip().lower().replace(" ", "")
    return _AGENT_LABELS.get(key, str(agent or "system").strip().lower() or "system")


def _trim_line(text: str, max_len: int = 160) -> str:
    one_line = " ".join(str(text or "").split())
    if len(one_line) <= max_len:
        return one_line
    return f"{one_line[: max_len - 3].rstrip()}..."


def format_feed_event(
    *,
    agent: str,
    event_type: str,
    title: str,
    message: str,
    severity: str = "info",
    action: str | None = None,
    confidence: float | None = None,
    data: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Convert agent output into a deterministic UI feed payload."""

    normalized_agent = _normalize_agent(agent)
    bounded_confidence = None
    if confidence is not None:
        bounded_confidence = max(0.0, min(1.0, float(confidence)))

    payload: dict[str, Any] = {
        "agent": normalized_agent,
        "type": str(event_type or "status").strip().lower() or "status",
        "title": _trim_line(title, max_len=90),
        "severity": str(severity or "info").strip().lower() or "info",
        "message": _trim_line(message, max_len=160),
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }
    if action:
        payload["action"] = _trim_line(action, max_len=70)
    if bounded_confidence is not None:
        payload["confidence"] = bounded_confidence
    if data:
        payload["data"] = data

    return payload


def standard_agent_output(
    *,
    agent: str,
    status: str,
    data: dict[str, Any],
    confidence: float,
    risk: str,
) -> dict[str, Any]:
    """Return standardized agent output envelope."""

    return {
        "agent": str(agent),
        "status": "success" if str(status).lower() == "success" else "failed",
        "data": data if isinstance(data, dict) else {},
        "confidence": max(0.0, min(1.0, float(confidence))),
        "risk": str(risk or "medium").strip().lower() or "medium",
    }


def standard_agent_event(
    *,
    agent: str,
    event: str,
    details: str,
    confidence: float,
) -> dict[str, Any]:
    """Return short, user-facing event payload for agent execution feed."""

    return {
        "agent": str(agent or "system"),
        "event": _trim_line(event, max_len=70),
        "details": _trim_line(details, max_len=140),
        "confidence": max(0.0, min(1.0, float(confidence))),
    }
