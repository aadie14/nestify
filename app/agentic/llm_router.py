"""Unified LLM router for agentic tasks with provider fallback.

Priority: Claude -> Groq/Gemini existing chain.
"""

from __future__ import annotations

import logging
import time
from typing import Any

import httpx

from app.core.config import settings
from app.database import record_token_usage
from app.services.llm_service import call_llm

logger = logging.getLogger(__name__)

ANTHROPIC_MODEL = "claude-3-5-sonnet-20241022"

_provider_health: dict[str, dict[str, Any]] = {
    "anthropic": {"ok": True, "last_error": "", "last_failure_ts": 0.0},
    "fallback": {"ok": True, "last_error": "", "last_failure_ts": 0.0},
}


async def _call_anthropic(messages: list[dict[str, str]], options: dict[str, Any]) -> dict[str, Any]:
    api_key = settings.anthropic_api_key
    if not api_key:
        raise RuntimeError("ANTHROPIC_API_KEY not set")

    system_parts = [m["content"] for m in messages if m.get("role") == "system"]
    non_system = [m for m in messages if m.get("role") != "system"]
    system_prompt = "\n\n".join(system_parts).strip()

    body: dict[str, Any] = {
        "model": ANTHROPIC_MODEL,
        "max_tokens": options.get("max_tokens", 2000),
        "temperature": options.get("temperature", 0.2),
        "messages": [
            {"role": "assistant" if m.get("role") == "assistant" else "user", "content": m.get("content", "")}
            for m in non_system
        ],
    }
    if system_prompt:
        body["system"] = system_prompt

    headers = {
        "x-api-key": api_key,
        "anthropic-version": "2023-06-01",
        "content-type": "application/json",
    }

    async with httpx.AsyncClient(timeout=60) as client:
        response = await client.post("https://api.anthropic.com/v1/messages", headers=headers, json=body)

    if response.status_code >= 400:
        raise RuntimeError(f"Anthropic API error ({response.status_code}): {response.text[:300]}")

    payload = response.json()
    content_blocks = payload.get("content", [])
    text = "\n".join(block.get("text", "") for block in content_blocks if isinstance(block, dict)).strip()
    if not text:
        raise RuntimeError("Anthropic returned empty response")

    usage = payload.get("usage", {})
    tokens_used = int(usage.get("input_tokens", 0)) + int(usage.get("output_tokens", 0))
    return {"content": text, "tokens_used": tokens_used, "model": f"anthropic/{ANTHROPIC_MODEL}"}


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
    """Call primary/secondary LLM providers with graceful fallback."""

    options = options or {}

    try:
        result = await _call_anthropic(messages, options)
        record_token_usage(result["model"], int(result.get("tokens_used", 0)))
        _mark_ok("anthropic")
        return result
    except Exception as exc:
        _mark_failed("anthropic", str(exc))
        logger.warning("[AgenticLLM] Anthropic failed, falling back: %s", exc)

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
