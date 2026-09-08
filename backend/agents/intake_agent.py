"""Intake — multimodal order capture.

Reads a Tamil/Tanglish voice note, a photo of a handwritten material list, or
typed text, and turns it into an order draft with one line per item.

Division of labour, deliberately:
  * The model does *perception* — transcribe, read handwriting, split the
    utterance into item fragments with a quantity and unit each.
  * `core.catalog` does *resolution* — trade slang to SKU, fuzzy, in-process,
    over a cached catalog. Keeping SKU choice out of the model means a wrong
    match is explainable and fixable in one place.

Per-line confidence is the *product* of both stages: the model's read of the
fragment and the catalog's certainty about the SKU. A line below the shop's
confidence threshold is flagged and queued for confirmation; it is never
silently priced as if it were certain.
"""
from __future__ import annotations

import re
from datetime import datetime, timezone

from core import catalog, confirm_queue, ids, storage
from core.config import SHOP_ID
from core.firestore_client import db
from core.llm import Media, ask

INSTRUCTION = """You are the intake agent for an Indian hardware shop in Coimbatore.
You receive a customer's order as Tamil/Tanglish speech, a photo of a handwritten
material list, or plain text. You transcribe and split it into item lines.

You do NOT choose product codes, you do NOT price anything, you do NOT judge credit.
You only report what was said or written, faithfully.

Return ONLY JSON:
{
  "transcript": "<verbatim, in the language spoken>",
  "transcript_en": "<plain English gloss>",
  "lines": [
    {"name_raw": "<the item as stated, without the quantity>",
     "qty": <number>,
     "unit": "<bag|piece|length|kg|box|tin|coil|packet or empty>",
     "confidence": <0-1 how clearly you heard/read this line>}
  ]
}
Rules: one entry per item. Quantity words become numbers ("ten" -> 10,
"பத்து" -> 10). Keep trade slang in name_raw exactly as stated ("ramco 53",
"3/4 pipe", "முக்கால் பைப்") — do not expand it into a full product name.
If a quantity was not stated, use 1 and lower the confidence."""

_SPLIT = re.compile(r"[,;\n]|\band\b|\bplus\b|\bமற்றும்\b")

# How an order actually opens and closes. These are politeness, not merchandise,
# and a fragment made only of them is not a line the shop should try to price.
_PLEASANTRIES = {
    "அண்ணே", "அண்ணா", "தம்பி", "சார்", "வணக்கம்", "அனுப்புங்க", "அனுப்புங்கள்",
    "வேணும்", "கொடுங்க", "கொடுங்கள்", "please", "sir", "anna", "bro", "boss",
    "hello", "hi", "thanks", "thank", "you", "send", "give", "need", "want",
    "me", "us", "the", "some", "also", "then", "ok",
}


def _is_pleasantry(fragment: str) -> bool:
    words = [w for w in re.split(r"[^\w஀-௿]+", (fragment or "").lower()) if w]
    return bool(words) and all(w in _PLEASANTRIES for w in words)


def _split_fallback(text: str, heard: float = 1.0) -> list[dict]:
    """Deterministic intake. Runs whenever the model is unavailable or fails —
    the demo must never show an empty draft.

    `heard` is the perception confidence. Splitting text we were *given* is
    exact, so it is 1.0 and the line's final confidence ends up reflecting SKU
    resolution alone; a media-only payload with no model gets discounted,
    because in that case we genuinely did not read anything.
    """
    lines: list[dict] = []
    for fragment in _SPLIT.split(text or ""):
        fragment = fragment.strip(" .·-")
        if len(fragment) < 2 or _is_pleasantry(fragment):
            continue
        qty, unit = catalog.parse_qty(fragment)
        lines.append({"name_raw": fragment, "qty": qty, "unit": unit,
                      "confidence": heard})
    return lines


def _perceive(payload: dict) -> tuple[dict, object]:
    """Model pass. Returns (reading, LlmResult) — reading always usable."""
    text = payload.get("transcript") or payload.get("text") or ""
    media_uri = payload.get("media_path") or payload.get("source_media_url")
    media: list[Media] = []
    if media_uri:
        blob = storage.get_bytes(media_uri)
        if blob:
            # Shrunk for the model only; the full photograph stays in storage.
            payload, kind = storage.for_model(
                blob, storage.content_type_of(media_uri))
            media.append(Media(kind, payload))

    # A demo fixture ships its own known-good transcription; that is the
    # deterministic stand-in for the model, not a shortcut around it — with
    # credentials present the model reads the real audio and wins.
    fallback = {
        "transcript": text,
        "transcript_en": payload.get("transcript_en") or text,
        "lines": payload.get("lines")
        or _split_fallback(text, heard=1.0 if text else 0.6),
    }
    prompt = ("Read the attached order and return the JSON."
              if media else f"Order as text:\n{text}\n\nReturn the JSON.")
    result = ask("intake", INSTRUCTION, prompt, media=media, fallback=fallback,
                 fast=True)
    reading = result.data if isinstance(result.data, dict) else fallback
    if not reading.get("lines"):
        reading = fallback
    if not reading.get("transcript"):
        reading["transcript"] = text
    return reading, result


def _resolve(reading: dict) -> tuple[list[dict], list[catalog.Match]]:
    """Attach a SKU to every fragment.

    Returns the order lines (schema fields only — `needs_confirm` and the
    top-3 alternatives are derived, so they live on the confirm-queue item and
    in the API response, not duplicated in the order document) alongside the
    matches, which the queueing step needs.
    """
    rows = catalog.load()
    lines: list[dict] = []
    matches: list[catalog.Match] = []
    for raw in reading.get("lines") or []:
        name_raw = str(raw.get("name_raw") or "").strip()
        if not name_raw:
            continue
        heard = float(raw.get("confidence") or 0.9)
        found = catalog.match(name_raw, rows)
        confidence = round(heard * found.confidence, 2) if found.matched else round(
            heard * min(found.confidence, 0.4), 2)
        qty = float(raw.get("qty") or 0) or catalog.parse_qty(name_raw)[0]
        matches.append(found)
        lines.append({
            "sku_id": found.sku_id,
            "name_raw": name_raw,
            "qty": qty,
            "unit": raw.get("unit") or found.unit,
            "rate": 0, "amount": 0,
            "gst_rate": found.gst_rate,
            "confidence": confidence,
            "substitute_of": None,
            "in_stock": True,                 # stock_pricing decides for real
        })
    return lines, matches


def _queue_uncertain_lines(order_id: str, lines: list[dict],
                           matches: list[catalog.Match],
                           media_uri: str | None) -> int:
    """Below-threshold lines wait for the owner instead of being priced as if
    they were certain. Returns how many were queued."""
    queued = 0
    for index, (line, found) in enumerate(zip(lines, matches)):
        if not confirm_queue.is_uncertain(line["confidence"]):
            continue
        queued += 1
        confirm_queue.enqueue(
            source_type="order", source_id=order_id, row_id=index,
            field="sku_id", extracted_value=line["name_raw"],
            confidence=line["confidence"],
            alternatives=[a["name"] for a in found.alternatives],
            source_image_url=media_uri)
    return queued


def run(payload: dict, trace) -> dict:
    with trace.step("intake") as s:
        reading, result = _perceive(payload)
        s.from_llm(result)
        lines, matches = _resolve(reading)

        order_id = payload.get("order_id") or ids.order_id()
        media_uri = payload.get("media_path") or payload.get("source_media_url")
        order = {
            "order_id": order_id,
            "party_id": payload.get("party_id"),
            "source": payload.get("source") or ("voice" if media_uri else "text"),
            "source_media_url": media_uri,
            "transcript": reading.get("transcript", ""),
            "transcript_ta": reading.get("transcript_ta")
            or (reading.get("transcript", "") if _has_tamil(reading) else ""),
            "transcript_en": reading.get("transcript_en", ""),
            "lines": lines,
            "subtotal": 0, "gst": {"cgst": 0, "sgst": 0, "total": 0}, "total": 0,
            "credit_verdict": None,
            "status": "draft",
            "owner_action": None,
            "quotation_url": None,
            "trace_id": trace.trace_id,
            "created_at": datetime.now(timezone.utc),
            "shop_id": SHOP_ID,
        }
        db().collection("orders").document(order_id).set(order)
        trace.set_ref("order", order_id)
        low = _queue_uncertain_lines(order_id, lines, matches, media_uri)

        s.status = "flagged" if low else "done"
        matched = sum(1 for line in lines if line["sku_id"])
        s.summary = (f"{len(lines)} items read, {matched} matched to stock"
                     + (f", {low} need confirming" if low else ""))
    return order


def _has_tamil(reading: dict) -> bool:
    return any("஀" <= ch <= "௿" for ch in reading.get("transcript", ""))
