"""Khata Digitizer — twenty-five years of paper ledger, one page at a time.

The owner trusts his khata because he can *see* every entry, so this agent's
output is built to be inspected: every row carries a normalised `bbox` locating
it on the source photograph, which is what lets the review screen highlight the
exact handwriting a number came from when the owner taps the row.

Nothing posts to the ledger here. Rows land in `khata_imports` as
`auto_accepted` or `needs_confirm`; only a committed import moves balances, in
one transaction. A bad OCR read must never silently change what a contractor
owes.
"""
from __future__ import annotations

import json
from datetime import datetime, timezone

from core import confirm_queue, ids, parties, storage
from core.adk import Media, ask
from core.config import CONFIDENCE_THRESHOLD, FIXTURES_DIR, GEMINI_MODEL_FAST
from core.firestore_client import db
from core.money import inr

INSTRUCTION = """You read pages from a handwritten Indian shop credit ledger (khata).
Entries are in Tamil and English, one per ruled line, oldest first. A page has a
party name, a date, an amount, and whether it was goods taken on credit or a
payment made.

Return ONLY JSON:
{
  "page_no": <number printed on the page, or null>,
  "rows": [
    {"party_name_raw": "<name exactly as written>",
     "date": "<YYYY-MM-DD>",
     "amount": <number>,
     "entry_type": "sale_credit" | "payment_received",
     "confidence": <0-1 how legible this row was>,
     "bbox": {"x": <0-1>, "y": <0-1>, "w": <0-1>, "h": <0-1>},
     "alternatives": [<the amount you read, then the next most likely readings>]}
  ]
}
`bbox` must be the row's rectangle on the image, normalised 0-1 from the top-left
— the owner taps a row to see the handwriting it came from, so this has to be
right. Where a digit is genuinely ambiguous, lower the confidence and list the
alternative readings; do not guess confidently."""


def _fixture() -> dict:
    path = FIXTURES_DIR / "khata_page.json"
    return json.loads(path.read_text("utf-8")) if path.exists() else {"rows": []}


def _extract(payload: dict) -> tuple[dict, object]:
    image_uri = payload.get("media_path") or payload.get("page_image_url")
    media: list[Media] = []
    if image_uri:
        blob = storage.get_bytes(image_uri)
        if blob:
            media.append(Media(storage.content_type_of(image_uri), blob))
    result = ask("khata_digitizer", INSTRUCTION,
                 "Read this khata page and return the JSON.",
                 media=media, fallback=_fixture(),
                 model=GEMINI_MODEL_FAST)
    data = result.data if isinstance(result.data, dict) and result.data.get("rows") \
        else _fixture()
    return data, result


def _resolve_rows(raw_rows: list[dict]) -> list[dict]:
    index = parties.index()
    rows: list[dict] = []
    for position, raw in enumerate(raw_rows, start=1):
        read = float(raw.get("confidence") or 0.9)
        party_id, name_score = parties.match(raw.get("party_name_raw", ""), index)
        # An unreadable *name* is as disqualifying as an unreadable amount: the
        # entry cannot post to a ledger without knowing whose ledger it is.
        confidence = round(read * (name_score if party_id else 0.5), 2)
        rows.append({
            "row_id": f"r{position}",
            "party_name_raw": raw.get("party_name_raw"),
            "party_id": party_id,
            "date": raw.get("date"),
            "amount": float(raw.get("amount") or 0),
            "entry_type": raw.get("entry_type") or "sale_credit",
            "confidence": confidence,
            "bbox": raw.get("bbox") or {"x": 0, "y": 0, "w": 1, "h": 0},
            "status": ("auto_accepted" if confidence >= CONFIDENCE_THRESHOLD
                       else "needs_confirm"),
            "alternatives": raw.get("alternatives") or [],
        })
    return rows


def _queue_uncertain(import_id: str, rows: list[dict],
                     image_uri: str | None) -> int:
    """The card carries the row's bbox, so the owner sees the actual ink rather
    than being asked to trust a number in a list."""
    queued = 0
    for row in rows:
        if row["status"] != "needs_confirm":
            continue
        queued += 1
        known_party = bool(row.get("party_id"))
        confirm_queue.enqueue(
            source_type="khata", source_id=import_id, row_id=row["row_id"],
            field="amount" if known_party else "party_id",
            extracted_value=(inr(row["amount"]) if known_party
                             else row.get("party_name_raw")),
            confidence=row["confidence"],
            alternatives=([inr(a) for a in row.get("alternatives") or []]
                          if known_party else []),
            source_image_url=image_uri, crop_bbox=row["bbox"])
    return queued


def run(payload: dict, trace) -> dict:
    with trace.step("khata_digitizer") as s:
        extraction, result = _extract(payload)
        s.from_llm(result)
        rows = _resolve_rows(extraction.get("rows") or [])
        image_uri = payload.get("media_path") or payload.get("page_image_url")
        import_id = payload.get("import_id") or ids.import_id()
        accepted = sum(1 for row in rows if row["status"] == "auto_accepted")
        pending = len(rows) - accepted

        record = {
            "import_id": import_id,
            "page_no": extraction.get("page_no") or payload.get("page_no"),
            "page_image_url": image_uri,
            "rows": rows,
            "auto_accepted_count": accepted,
            "needs_confirm_count": pending,
            "status": "reviewing",
            "trace_id": trace.trace_id,
            "created_at": datetime.now(timezone.utc),
        }
        db().collection("khata_imports").document(import_id).set(record)
        trace.set_ref("khata_import", import_id)
        _queue_uncertain(import_id, rows, image_uri)

        s.status = "flagged" if pending else "done"
        s.summary = (f"Page {record['page_no']} read — {len(rows)} entries, "
                     f"{accepted} clear, {pending} to confirm")
    return record
