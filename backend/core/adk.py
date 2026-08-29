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
import concurrent.futures
import json
import re
import threading
from dataclasses import dataclass, field
from typing import Any, Iterable, Sequence

from core.config import (GEMINI_MODEL, LLM_AVAILABLE, LLM_TIMEOUT_SECONDS,
                         LLM_VISION_TIMEOUT_SECONDS, PROJECT, USE_VERTEX,
                         VERTEX_LOCATION)

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
_LOOP: asyncio.AbstractEventLoop | None = None
_LOOP_LOCK = threading.Lock()


def _background_loop() -> asyncio.AbstractEventLoop:
    """One long-lived loop on a daemon thread, shared by every agent call.

    The obvious implementation — a fresh loop per call, closed on return — is
    wrong in a way that only shows up against a real endpoint: closing the loop
    tears it down while the HTTPS transport underneath the model client is still
    open, which raises `Event loop is closed` out of the SSL layer and leaves the
    client in a state that breaks the *next* call. It also forces a new TLS
    handshake per agent, which is latency the trace strip shows on camera.

    Keeping the loop alive for the process lifetime fixes both: transports live
    as long as the loop, and connections are reused across the agent chain.
    """
    global _LOOP
    with _LOOP_LOCK:
        if _LOOP is not None and not _LOOP.is_closed():
            return _LOOP
        loop = asyncio.new_event_loop()
        threading.Thread(target=loop.run_forever, daemon=True,
                         name="galla-adk-loop").start()
        _LOOP = loop
        return loop


def _run_coro(coro, timeout: float = 120.0):
    """Run a coroutine from sync code, safely, even under a live FastAPI loop.

    Agents are called from both sync scripts (seeding, tests) and async request
    handlers, so this never assumes whether a loop is already running here — it
    hands the work to the dedicated loop and blocks for the result.
    """
    loop = _background_loop()
    try:
        return asyncio.run_coroutine_threadsafe(coro, loop).result(timeout)
    except concurrent.futures.TimeoutError as exc:
        raise TimeoutError(f"model call exceeded {timeout}s") from exc


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
def _vertex_model(model: str):
    """On Vertex the model must be addressed through a client pinned to the
    region that actually serves it, which is not the region the data lives in."""
    if not USE_VERTEX:
        return model                       # AI Studio: the id is enough
    from google.adk.models import Gemini
    return Gemini(model=model, client_kwargs={
        "vertexai": True, "project": PROJECT, "location": VERTEX_LOCATION})


def _build_agent(name: str, instruction: str, model: str):
    from google.adk.agents import LlmAgent
    from google.genai import types

    return LlmAgent(
        name=name,
        model=_vertex_model(model),
        description=f"Galla {name} agent",
        instruction=instruction,
        generate_content_config=types.GenerateContentConfig(
            temperature=0.1,
            response_mime_type="application/json",
        ),
    )


async def _invoke(name: str, instruction: str, prompt: str,
                  media: Sequence[Media], model: str) -> tuple[str, int, int]:
    from google.adk import Runner
    from google.adk.sessions import InMemorySessionService
    from google.genai import types

    agent = _build_agent(name, instruction, model)
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
        fallback: Any = None,
        model: str | None = None,
        timeout: float | None = None) -> LlmResult:
    """Run one ADK agent turn and return parsed JSON, or `fallback`."""
    media = list(media or [])
    model = model or GEMINI_MODEL
    if not LLM_AVAILABLE:
        return LlmResult(fallback, ok=False, model=model,
                         note="no model credentials")
    try:
        budget = timeout or (LLM_VISION_TIMEOUT_SECONDS if media
                             else LLM_TIMEOUT_SECONDS)
        raw, tokens_in, tokens_out = _run_coro(
            _invoke(name, instruction, prompt, media, model), timeout=budget)
        return LlmResult(parse_json(raw), ok=True, model=model,
                         tokens_in=tokens_in, tokens_out=tokens_out, raw=raw)
    except Exception as exc:                              # noqa: BLE001
        return LlmResult(fallback, ok=False, model=model,
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
