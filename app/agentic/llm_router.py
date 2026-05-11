"""Unified LLM router for agentic tasks using the project fallback chain.

Anthropic is intentionally disabled in this runtime. Agentic requests are routed
through the shared LLM fallback service (Groq/Gemini) for consistency.
"""

from __future__ import annotations

import logging
import time
from typing import Any

from app.services.llm_service import call_llm

logger = logging.getLogger(__name__)

_provider_health: dict[str, dict[str, Any]] = {
    "fallback": {"ok": True, "last_error": "", "last_failure_ts": 0.0},
}


def _mark_failed(provider: str, error: str) -> None:
    state = _provider_health.setdefault(provider, {"ok": True, "last_error": "", "last_failure_ts": 0.0})
    state["ok"] = False
    state["last_error"] = error
    state["last_failure_ts"] = time.time()


def _mark_ok(provider: str) -> None:
    state = _provider_health.setdefault(provider, {"ok": True, "last_error": "", "last_failure_ts": 0.0})
    state["ok"] = True
    state["last_error"] = ""


async def call_agentic_llm(messages: list[dict[str, str]], options: dict[str, Any] | None = None) -> dict[str, Any]:
    """Call agentic LLM through the shared multi-provider fallback chain."""

    options = options or {}

    try:
        # Reuse existing fallback chain (Groq/Gemini) for resilience.
        fallback = await call_llm(messages, {**options, "task_weight": options.get("task_weight", "heavy")})
        _mark_ok("fallback")
        return fallback
    except Exception as exc:
        _mark_failed("fallback", str(exc))
        logger.warning("[AgenticLLM] Fallback chain failed: %s", exc)
        raise RuntimeError("All LLM providers failed for agentic task") from exc


def provider_health() -> dict[str, dict[str, Any]]:
    """Expose provider health for diagnostics and status reporting."""
    return dict(_provider_health)
