"""Unified agentic LLM client with provider fallback and usage metadata."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from app.agentic.llm_router import call_agentic_llm, provider_health


@dataclass(slots=True)
class AgenticLLMResult:
    text: str
    provider: str
    model: str
    tokens_used: int


class AgenticLLMClient:
    """Compatibility wrapper expected by spec-facing modules."""

    async def complete(
        self,
        messages: list[dict[str, str]],
        max_tokens: int = 4096,
        temperature: float = 0.1,
    ) -> tuple[str, dict[str, Any]]:
        result = await call_agentic_llm(
            messages,
            {
                "max_tokens": max_tokens,
                "temperature": temperature,
                "task_weight": "heavy",
            },
        )

        model = str(result.get("model") or "unknown")
        provider = model.split("/", 1)[0] if "/" in model else "fallback"
        usage = {
            "provider": provider,
            "model": model,
            "tokens_used": int(result.get("tokens_used") or 0),
            "provider_health": provider_health(),
        }
        return str(result.get("content") or ""), usage

    def get_langchain_llm(self) -> Any:
        """Return a CrewAI-compatible placeholder while preserving fallback behavior.

        Existing Nestify agent wrappers use async completion via complete().
        """

        class _CompatLLM:
            async def ainvoke(self, prompt: str) -> str:
                content, _ = await AgenticLLMClient().complete([
                    {"role": "user", "content": prompt},
                ])
                return content

        return _CompatLLM()
