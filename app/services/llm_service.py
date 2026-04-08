"""LLM service with multi-provider fallback, cooldown, and budget tracking.

Supports Groq (OpenAI-compatible) and Google Gemini. Automatically routes
requests through a fallback chain when a model is rate-limited or exhausted.
"""

from __future__ import annotations

import asyncio
import logging
import os
import time
from datetime import date
from typing import Any

import httpx

from app.database import get_today_token_usage, record_token_usage

logger = logging.getLogger(__name__)

# ─── Model Configuration ────────────────────────────────────────

MODEL_LIMITS: dict[str, dict[str, int]] = {
    # Groq — free tier
    "groq/llama-3.3-70b-versatile":  {"daily_tokens": 50_000, "daily_requests": 200, "cooldown_ms": 1500},
    "groq/llama-3.1-8b-instant":     {"daily_tokens": 80_000, "daily_requests": 300, "cooldown_ms": 500},
    # Gemini — free tier
    "gemini/gemini-2.0-flash":       {"daily_tokens": 100_000, "daily_requests": 1500, "cooldown_ms": 200},
    "gemini/gemini-2.5-flash":       {"daily_tokens": 100_000, "daily_requests": 1000, "cooldown_ms": 300},
}

FALLBACK_CHAIN = [
    "groq/llama-3.1-8b-instant",
    "gemini/gemini-2.0-flash",
    "gemini/gemini-2.5-flash",
    "groq/llama-3.3-70b-versatile",
]

TASK_ROUTES: dict[str, list[str]] = {
    "lite":  ["groq/llama-3.1-8b-instant", "gemini/gemini-2.0-flash"],
    "heavy": ["groq/llama-3.3-70b-versatile", "gemini/gemini-2.5-flash", "gemini/gemini-2.0-flash"],
}

_last_call_timestamp: dict[str, float] = {}
_disabled_models: set[str] = set()


# ─── Budget Checks ──────────────────────────────────────────────


def _has_model_budget(model: str) -> bool:
    """Check if a model still has budget remaining today."""
    limits = MODEL_LIMITS.get(model)
    if not limits:
        return False
    usage = get_today_token_usage()
    model_usage = next(
        (r for r in usage["breakdown"] if r["model"] == model),
        None,
    )
    if model_usage is None:
        return True
    return (
        model_usage["tokens_used"] < limits["daily_tokens"]
        and model_usage["requests_made"] < limits["daily_requests"]
    )


async def _enforce_cooldown(model: str) -> None:
    """Wait if the per-model cooldown hasn't elapsed."""
    limits = MODEL_LIMITS.get(model)
    if not limits:
        return
    last_call = _last_call_timestamp.get(model, 0)
    elapsed_ms = (time.time() - last_call) * 1000
    if elapsed_ms < limits["cooldown_ms"]:
        wait_s = (limits["cooldown_ms"] - elapsed_ms) / 1000
        await asyncio.sleep(wait_s)
    _last_call_timestamp[model] = time.time()


def _select_model(task_weight: str, exclude: set[str]) -> str | None:
    """Select the best available model, skipping excluded ones."""
    preferred = TASK_ROUTES.get(task_weight, TASK_ROUTES["lite"])
    for model in preferred:
        if model not in exclude and model not in _disabled_models and _has_model_budget(model):
            return model
    for model in FALLBACK_CHAIN:
        if model not in exclude and model not in _disabled_models and _has_model_budget(model):
            return model
    return None


# ─── Provider Callers ────────────────────────────────────────────


async def _call_groq(model: str, messages: list[dict], options: dict) -> dict:
    """Call the Groq API (OpenAI-compatible)."""
    api_key = os.getenv("GROQ_API_KEY")
    if not api_key:
        raise RuntimeError("GROQ_API_KEY not set")

    body: dict[str, Any] = {
        "model": model.replace("groq/", ""),
        "messages": messages,
        "temperature": options.get("temperature", 0.3),
        "max_tokens": min(int(options.get("max_tokens", 1024)), 2048),
    }
    if options.get("json_mode"):
        body["response_format"] = {"type": "json_object"}

    async with httpx.AsyncClient(timeout=60) as client:
        resp = await client.post(
            "https://api.groq.com/openai/v1/chat/completions",
            headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
            json=body,
        )

    if resp.status_code != 200:
        raise RuntimeError(f"Groq API error ({resp.status_code}): {resp.text[:300]}")

    data = resp.json()
    content = data.get("choices", [{}])[0].get("message", {}).get("content", "")
    if not content or not content.strip():
        raise RuntimeError(f"Groq returned empty response for {model}")

    return {
        "content": content,
        "tokens_used": data.get("usage", {}).get("total_tokens", 0),
        "model": model,
    }


async def _call_gemini(model: str, messages: list[dict], options: dict) -> dict:
    """Call the Google Gemini API."""
    api_key = os.getenv("GEMINI_API_KEY")
    if not api_key:
        raise RuntimeError("GEMINI_API_KEY not set")

    short_model = model.replace("gemini/", "")
    system_msg = next((m for m in messages if m["role"] == "system"), None)
    non_system = [m for m in messages if m["role"] != "system"]

    contents = []
    for m in non_system:
        role = "model" if m["role"] == "assistant" else "user"
        contents.append({"role": role, "parts": [{"text": m["content"]}]})

    body: dict[str, Any] = {
        "contents": contents,
        "generationConfig": {
            "temperature": options.get("temperature", 0.3),
            "maxOutputTokens": min(int(options.get("max_tokens", 1024)), 2048),
        },
    }
    if options.get("json_mode"):
        body["generationConfig"]["responseMimeType"] = "application/json"
    if system_msg:
        body["systemInstruction"] = {"parts": [{"text": system_msg["content"]}]}

    url = f"https://generativelanguage.googleapis.com/v1beta/models/{short_model}:generateContent?key={api_key}"

    async with httpx.AsyncClient(timeout=60) as client:
        resp = await client.post(url, json=body)

    if resp.status_code != 200:
        raise RuntimeError(f"Gemini API error ({resp.status_code}): {resp.text[:300]}")

    data = resp.json()
    content = ""
    candidates = data.get("candidates", [])
    if candidates:
        parts = candidates[0].get("content", {}).get("parts", [])
        if parts:
            content = parts[0].get("text", "")

    if not content or not content.strip():
        block_reason = ""
        if candidates and candidates[0].get("finishReason") == "SAFETY":
            block_reason = " (blocked by safety filter)"
        elif not candidates:
            block_reason = " (no candidates returned)"
        raise RuntimeError(f"Gemini returned empty response for {model}{block_reason}")

    usage_meta = data.get("usageMetadata", {})
    tokens_used = usage_meta.get("promptTokenCount", 0) + usage_meta.get("candidatesTokenCount", 0)

    return {"content": content, "tokens_used": tokens_used, "model": model}


# ─── Public API ──────────────────────────────────────────────────


async def call_llm(messages: list[dict], options: dict | None = None) -> dict:
    """
    Make an LLM call with automatic model selection, cooldown, and fallback.

    Args:
        messages: OpenAI-style messages [{"role": ..., "content": ...}]
        options: {
            "task_weight": "lite" | "heavy",
            "json_mode": bool,
            "temperature": float,
            "max_tokens": int,
        }

    Returns:
        {"content": str, "tokens_used": int, "model": str}
    """
    options = options or {}
    task_weight = options.get("task_weight", "lite")

    exhausted_models: set[str] = set()
    last_error: Exception | None = None
    max_attempts = len(FALLBACK_CHAIN) + 1

    for _ in range(max_attempts):
        model = _select_model(task_weight, exhausted_models)
        if not model:
            break

        try:
            await _enforce_cooldown(model)

            if model.startswith("groq/"):
                result = await _call_groq(model, messages, options)
            elif model.startswith("gemini/"):
                result = await _call_gemini(model, messages, options)
            else:
                raise RuntimeError(f"Unknown model provider for: {model}")

            record_token_usage(model, result["tokens_used"])
            return result

        except RuntimeError as err:
            error_str = str(err)
            last_error = err

            if "decommissioned" in error_str.lower() or "model_decommissioned" in error_str.lower():
                logger.warning("[LLM] Model unavailable permanently on %s, disabling for this runtime.", model)
                exhausted_models.add(model)
                _disabled_models.add(model)
                continue

            if "429" in error_str or "rate" in error_str.lower() or "quota" in error_str.lower():
                logger.warning("[LLM] Rate limited on %s, switching...", model)
                exhausted_models.add(model)
                await asyncio.sleep(2)
                continue

            logger.warning("[LLM] Error on %s: %s", model, err)
            exhausted_models.add(model)
            await asyncio.sleep(1)
            continue

        except Exception as err:
            last_error = err
            logger.warning("[LLM] Unexpected error on %s: %s", model, err)
            exhausted_models.add(model)
            await asyncio.sleep(1)
            continue

    if last_error:
        raise RuntimeError(
            f"All LLM models exhausted or failed. Last error: {last_error}. "
            f"Tried: {exhausted_models or 'none'}. Please try again later."
        )
    raise RuntimeError("No LLM models available. Please try again later.")
