"""Code Summarizer — Function/class/module summaries for graph metadata.

Uses LLM summarization when available and a deterministic structural fallback
when LLM calls fail.
"""

from __future__ import annotations

import ast
import json
import logging
from dataclasses import dataclass
from typing import Any

from app.services.llm_service import call_llm

logger = logging.getLogger(__name__)


@dataclass(slots=True)
class CodeSummary:
    """Summary output for a code entity."""

    kind: str
    name: str
    file_path: str
    summary: str
    metadata: dict[str, Any]


class CodeSummarizer:
    """Summarize module, class, and function behavior."""

    async def summarize_file(self, file_path: str, source: str) -> list[CodeSummary]:
        """Produce summaries for module + top-level classes/functions."""

        try:
            tree = ast.parse(source)
        except SyntaxError:
            return [
                CodeSummary(
                    kind="module",
                    name=file_path,
                    file_path=file_path,
                    summary="Module could not be parsed due to syntax errors.",
                    metadata={"parse_error": True},
                ),
            ]

        entities: list[tuple[str, str, str]] = []
        entities.append(("module", file_path, source[:6000]))

        for node in tree.body:
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                snippet = ast.get_source_segment(source, node) or f"def {node.name}(...):"
                entities.append(("function", node.name, snippet[:4000]))
            elif isinstance(node, ast.ClassDef):
                snippet = ast.get_source_segment(source, node) or f"class {node.name}:"
                entities.append(("class", node.name, snippet[:4000]))

        summaries: list[CodeSummary] = []
        for kind, name, snippet in entities:
            summary = await self._summarize_with_llm(kind, name, snippet)
            if not summary:
                summary = self._fallback_summary(kind, name, snippet)

            summaries.append(
                CodeSummary(
                    kind=kind,
                    name=name,
                    file_path=file_path,
                    summary=summary,
                    metadata={"source_length": len(snippet)},
                )
            )

        return summaries

    async def _summarize_with_llm(self, kind: str, name: str, snippet: str) -> str | None:
        """Try model-based summarization with strict JSON output."""

        prompt = (
            "Summarize this code entity in one concise sentence and return JSON: "
            "{\"summary\": \"...\"}."
            f"\nKIND: {kind}\nNAME: {name}\nCODE:\n{snippet}"
        )

        try:
            result = await call_llm(
                [
                    {"role": "system", "content": "You write concise technical summaries in strict JSON."},
                    {"role": "user", "content": prompt},
                ],
                {"task_weight": "lite", "json_mode": True, "temperature": 0.1, "max_tokens": 300},
            )
            parsed = json.loads(result["content"])
            summary = (parsed.get("summary") or "").strip()
            return summary or None
        except Exception as exc:
            logger.debug("LLM summarization unavailable for %s %s: %s", kind, name, exc)
            return None

    def _fallback_summary(self, kind: str, name: str, snippet: str) -> str:
        """Deterministic fallback summary if LLM is unavailable."""

        line_count = snippet.count("\n") + 1
        if kind == "module":
            return f"Module {name} contains approximately {line_count} lines of source code."
        if kind == "class":
            return f"Class {name} defines behavior and related methods across about {line_count} lines."
        return f"Function {name} implements logic in about {line_count} lines."
