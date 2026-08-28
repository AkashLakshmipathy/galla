"""The Google ADK bridge.

Every model call in Galla goes through `ask()`. It builds a real
`google.adk.agents.LlmAgent`, runs it on an ADK `Runner`, and returns parsed
JSON plus token counts for the trace strip.

Two rules encoded here, both from CLAUDE.md:

1. **Every model call has a deterministic fallback.** If credentials are absent,
   the call errors, or the model returns unparseable output, `ask()` returns the
   caller's `fallback` and marks the result `ok=False`. The demo never shows an
   empty state because an API call failed.
2. **The model never decides money.** `ask()` returns data, never a verdict.
   Rules live in plain Python next to the agent that owns them.
"""
from __future__ import annotations

import asyncio
import json
import re
import threading
from dataclasses import dataclass, field
from typing import Any, Iterable, Sequence

from core.config import GEMINI_MODEL, LLM_AVAILABLE

_JSON_BLOCK = re.compile(r"\{.*\}|\[.*\]", re.DOTALL)


@dataclass
class Media:
    mime_type: str
    data: bytes


@dataclass
class LlmResult:
    data: Any
    ok: bool
    model: str = GEMINI_MODEL
    tokens_in: int = 0
    tokens_out: int = 0
    note: str | None = None          # why we fell back, for the trace
    raw: str = ""

    @property
    def source(self) -> str:
        return "gemini" if self.ok else "fallback"


# --------------------------------------------------------------- event loop
def _run_coro(coro):
    """Run a coroutine from sync code, safely, even under a live FastAPI loop.

    Always uses a dedicated thread with its own loop: `asyncio.run` would raise
    inside an already-running loop, and the agents are called from both sync
    scripts (seeding, tests) and async request handlers.
    """
    box: dict[str, Any] = {}

    def target():
        loop = asyncio.new_event_loop()
        try:
            box["value"] = loop.run_until_complete(coro)
        except BaseException as exc:                     # noqa: BLE001
            box["error"] = exc
        finally:
            loop.close()

    thread = threading.Thread(target=target, daemon=True)
    thread.start()
    thread.join()
    if "error" in box:
        raise box["error"]
    return box["value"]


# ------------------------------------------------------------------- parsing
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


# ----------------------------------------------------------------- the bridge
def _build_agent(name: str, instruction: str):
    from google.adk.agents import LlmAgent
    from google.genai import types

    return LlmAgent(
        name=name,
        model=GEMINI_MODEL,
        description=f"Galla {name} agent",
        instruction=instruction,
        generate_content_config=types.GenerateContentConfig(
            temperature=0.1,
            response_mime_type="application/json",
        ),
    )


async def _invoke(name: str, instruction: str, prompt: str,
                  media: Sequence[Media]) -> tuple[str, int, int]:
    from google.adk import Runner
    from google.adk.sessions import InMemorySessionService
    from google.genai import types

    agent = _build_agent(name, instruction)
    sessions = InMemorySessionService()
    app_name = f"galla-{name}"
    await sessions.create_session(app_name=app_name, user_id="shop-main",
                                  session_id="s1")
    runner = Runner(app_name=app_name, agent=agent, session_service=sessions)

    parts = [types.Part(text=prompt)]
    for item in media:
        parts.append(types.Part.from_bytes(data=item.data, mime_type=item.mime_type))
    message = types.Content(role="user", parts=parts)

    text_chunks: list[str] = []
    tokens_in = tokens_out = 0
    try:
        async for event in runner.run_async(user_id="shop-main", session_id="s1",
                                            new_message=message):
            usage = getattr(event, "usage_metadata", None)
            if usage is not None:
                tokens_in += getattr(usage, "prompt_token_count", 0) or 0
                tokens_out += getattr(usage, "candidates_token_count", 0) or 0
            content = getattr(event, "content", None)
            if content and getattr(content, "parts", None):
                for part in content.parts:
                    if getattr(part, "text", None):
                        text_chunks.append(part.text)
    finally:
        await runner.close()
    return "".join(text_chunks), tokens_in, tokens_out


def ask(name: str, instruction: str, prompt: str, *,
        media: Iterable[Media] | None = None,
        fallback: Any = None) -> LlmResult:
    """Run one ADK agent turn and return parsed JSON, or `fallback`."""
    media = list(media or [])
    if not LLM_AVAILABLE:
        return LlmResult(fallback, ok=False, note="no model credentials")
    try:
        raw, tokens_in, tokens_out = _run_coro(_invoke(name, instruction, prompt, media))
        return LlmResult(parse_json(raw), ok=True, tokens_in=tokens_in,
                         tokens_out=tokens_out, raw=raw)
    except Exception as exc:                              # noqa: BLE001
        return LlmResult(fallback, ok=False,
                         note=f"{type(exc).__name__}: {exc}"[:180])


def fleet() -> list[dict]:
    """The declared agent fleet, for the README/architecture diagram and the
    `/api/fleet` endpoint the UI uses to label the trace strip."""
    return [
        {"agent": "intake", "label": "Intake",
         "does": "Tamil voice / handwriting → line items + SKU match"},
        {"agent": "stock_pricing", "label": "Stock & Pricing",
         "does": "inventory check, tier pricing, substitute suggestion"},
        {"agent": "credit_guardian", "label": "Credit Guardian",
         "does": "deterministic credit verdict, Gemini phrases it"},
        {"agent": "quotation", "label": "Quotation",
         "does": "GST quotation PDF with HSN + CGST/SGST split"},
        {"agent": "purchase_entry", "label": "Purchase Entry",
         "does": "supplier invoice OCR → stock delta + payable"},
        {"agent": "khata_digitizer", "label": "Khata Digitizer",
         "does": "handwritten ledger page → rows with source bboxes"},
        {"agent": "gst_compiler", "label": "GST Compiler",
         "does": "monthly CA-ready summary, fired by Cloud Scheduler"},
        {"agent": "notifier", "label": "Notifier",
         "does": "approval cards, digests, CA dispatch"},
    ]
