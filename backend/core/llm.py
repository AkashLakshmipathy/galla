"""The one place a model is called.

Every model call in Galla goes through `ask()`. It builds a Strands `Agent`,
runs one turn, and returns parsed JSON plus token counts for the trace strip.
Which provider answers is `core.model`'s decision, not this file's — nothing
here names a vendor.

Two rules from CLAUDE.md are encoded here:

1. **Every model call has a deterministic fallback.** If no provider is
   configured, the call errors, or the output will not parse, `ask()` returns
   the caller's `fallback` and marks the result `ok=False`. The demo never
   shows an empty state because an API call failed.
2. **The model never decides money.** `ask()` returns data, never a verdict.
   Rules live in plain Python next to the agent that owns them.

WHY A THREAD AND A TIMEOUT

A model call that hangs is worse than one that fails, because the owner is
standing at the counter waiting. Strands' `Agent.__call__` is synchronous and
has no timeout of its own, so the call is handed to a worker thread and
abandoned if it overruns. Reading a photograph is slower than reading text and
the shop's connection may be poor, so vision gets appreciably longer before we
give up on it — falling back on a bill the model could have read is the worse
outcome.
"""
from __future__ import annotations

import concurrent.futures
import json
import re
from dataclasses import dataclass
from typing import Any, Iterable

from core import model as provider
from core.config import LLM_TIMEOUT_SECONDS, LLM_VISION_TIMEOUT_SECONDS

_JSON_BLOCK = re.compile(r"\{.*\}|\[.*\]", re.DOTALL)
# Bedrock and Gemini both take these four; anything else is converted upstream
# by `storage.for_model`, which already normalises phone photographs to JPEG.
_IMAGE_FORMATS = {"image/jpeg": "jpeg", "image/jpg": "jpeg", "image/png": "png",
                  "image/gif": "gif", "image/webp": "webp"}
_EXECUTOR = concurrent.futures.ThreadPoolExecutor(max_workers=4,
                                                  thread_name_prefix="galla-llm")


@dataclass
class Media:
    mime_type: str
    data: bytes


@dataclass
class LlmResult:
    data: Any
    ok: bool
    model: str = ""
    tokens_in: int = 0
    tokens_out: int = 0
    note: str | None = None          # why we fell back, for the trace
    raw: str = ""

    @property
    def source(self) -> str:
        return provider.provider() if self.ok else "fallback"


def parse_json(text: str) -> Any:
    """Models fence their JSON, prefix it with prose, or trail a period. Cope."""
    if not text:
        raise ValueError("empty model response")
    cleaned = text.strip()
    if cleaned.startswith("```"):
        cleaned = re.sub(r"^```[a-zA-Z]*\s*", "", cleaned)
        cleaned = re.sub(r"\s*```$", "", cleaned)
    try:
        return json.loads(cleaned)
    except json.JSONDecodeError:
        match = _JSON_BLOCK.search(cleaned)
        if not match:
            raise
        return json.loads(match.group(0))


def _content(prompt: str, media: list[Media]) -> list[dict]:
    """Text first, then each image as a Strands content block.

    An unrecognised mime type is dropped rather than guessed at: sending a PDF
    labelled as a JPEG fails the whole call, where dropping it still lets the
    model read the text and the line simply lands in the confirm queue.
    """
    blocks: list[dict] = [{"text": prompt}]
    for item in media:
        image_format = _IMAGE_FORMATS.get((item.mime_type or "").lower())
        if image_format:
            blocks.append({"image": {"format": image_format,
                                     "source": {"bytes": item.data}}})
    return blocks


def _text_of(message: Any) -> str:
    """Pull the assistant's text out of a Strands message."""
    if isinstance(message, str):
        return message
    parts = (message or {}).get("content") or []
    return "".join(p.get("text", "") for p in parts if isinstance(p, dict))


def _usage(result: Any) -> tuple[int, int]:
    try:
        used = (result.metrics.get_summary() or {}).get("accumulated_usage") or {}
        return int(used.get("inputTokens") or 0), int(used.get("outputTokens") or 0)
    except Exception:                                     # noqa: BLE001
        return 0, 0


def ask(name: str, instruction: str, prompt: str, *,
        media: Iterable[Media] | None = None,
        fallback: Any = None,
        fast: bool = False,
        timeout: float | None = None) -> LlmResult:
    """Run one Strands agent turn and return parsed JSON, or `fallback`.

    `name` labels the agent for the trace; `fast` picks the cheap high-volume
    model over the one that handles judgement.
    """
    from strands import Agent

    media = list(media or [])
    model_id = provider.model_id(fast=fast)
    llm = provider.model(fast=fast)
    if llm is None:
        return LlmResult(fallback, ok=False, model=model_id,
                         note="no model provider configured")

    budget = timeout or (LLM_VISION_TIMEOUT_SECONDS if media else LLM_TIMEOUT_SECONDS)
    try:
        agent = Agent(model=llm, system_prompt=instruction, name=name,
                      callback_handler=None)
        future = _EXECUTOR.submit(agent, _content(prompt, media))
        result = future.result(timeout=budget)
        raw = _text_of(result.message)
        tokens_in, tokens_out = _usage(result)
        return LlmResult(parse_json(raw), ok=True, model=model_id,
                         tokens_in=tokens_in, tokens_out=tokens_out, raw=raw)
    except concurrent.futures.TimeoutError:
        return LlmResult(fallback, ok=False, model=model_id,
                         note=f"model call exceeded {budget}s")
    except Exception as exc:                              # noqa: BLE001
        return LlmResult(fallback, ok=False, model=model_id,
                         note=f"{type(exc).__name__}: {exc}"[:180])
