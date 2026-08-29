"""Purchase Entry — the data-entry person this shop cannot afford.

A photographed supplier bill goes in; supplier, invoice number, GSTIN, line
items and tax come out, each line carrying the confidence the extraction earned.

Nothing here touches stock. The agent only *proposes*: it writes a `purchases`
document with `stock_applied: false` and routes every low-confidence line to the
confirm queue. Inventory and the supplier payable move later, in one transaction,
when the owner taps Save — see `core.transactions.confirm_purchase`.
"""
from __future__ import annotations

import json
from datetime import datetime, timezone

from google.cloud.firestore_v1.base_query import FieldFilter
from rapidfuzz import fuzz

from core import catalog, confirm_queue, ids, provisioning, storage
from core.adk import Media, ask
from core.config import FIXTURES_DIR, GEMINI_MODEL_FAST
from core.firestore_client import db
from core.money import gst_split, inr

INSTRUCTION = """You read printed GST purchase invoices from Indian building-material
suppliers. Transcribe exactly what is on the paper — do not tidy up abbreviations,
do not convert units, do not recompute totals.

Return ONLY JSON:
{
  "supplier_name_raw": "<as printed>",
  "supplier_gstin": "<15 chars or null>",
  "invoice_no": "<as printed>",
  "invoice_date": "<YYYY-MM-DD>",
  "printed_total": <the grand total printed on the bill, or null>,
  "printed_taxable": <the taxable value printed on the bill, or null>,
  "lines": [
    {"description_raw": "<exactly as printed>",
     "qty": <number>, "rate": <number per unit>,
     "gst_rate": <5|12|18|28>,
     "confidence": <0-1 how legible this line was>}
  ]
}
Lower the confidence on any line where a digit is smudged, overwritten or
ambiguous. Being honest about a doubtful digit is more useful than guessing it."""


def _fixture() -> dict:
    path = FIXTURES_DIR / "supplier_invoice.json"
    return json.loads(path.read_text("utf-8")) if path.exists() else {"lines": []}


def _extract(payload: dict) -> tuple[dict, object]:
    image_uri = payload.get("media_path") or payload.get("source_image_url")
    media: list[Media] = []
    if image_uri:
        blob = storage.get_bytes(image_uri)
        if blob:
            media.append(Media(storage.content_type_of(image_uri), blob))
    result = ask("purchase_entry", INSTRUCTION,
                 "Read this supplier invoice and return the JSON.",
                 media=media, fallback=_fixture(),
                 model=GEMINI_MODEL_FAST)
    data = result.data if isinstance(result.data, dict) and result.data.get("lines") \
        else _fixture()
    return data, result


def _match_supplier(name_raw: str, gstin: str | None) -> str | None:
    """GSTIN is the identity; the printed name is only a hint."""
    parties = db().collection("parties")
    if gstin:
        found = list(parties.where(filter=FieldFilter("gstin", "==", gstin))
                     .limit(1).stream())
        if found:
            return found[0].id
    needle = catalog.normalise(name_raw or "")
    best, best_score = None, 0.0
    for snap in parties.where(filter=FieldFilter("type", "in",
                                                 ["supplier", "both"])).stream():
        party = snap.to_dict() or {}
        score = fuzz.token_set_ratio(needle, catalog.normalise(party.get("name", "")))
        if score > best_score:
            best, best_score = snap.id, score
    return best if best_score >= 80 else None


def _resolve_lines(raw_lines: list[dict], purchase_id: str) -> list[dict]:
    """Attach a SKU to every line — or propose creating one.

    A bill routinely lists things the shop has never stocked. Rather than parking
    those in the confirm queue forever, the agent proposes a catalog entry built
    from what the bill itself states. The proposal is not written here; it is
    applied in the same transaction that moves the stock, so a discarded scan
    leaves no phantom products behind.
    """
    lines: list[dict] = []
    for raw in raw_lines:
        description = str(raw.get("description_raw") or "").strip()
        read = float(raw.get("confidence") or 0.9)
        qty = float(raw.get("qty") or 0)
        rate = float(raw.get("rate") or 0)
        resolution = provisioning.resolve_sku({**raw, "_purchase_id": purchase_id})

        line = {
            "sku_id": resolution.existing_id,
            "description_raw": description,
            "qty": qty, "rate": rate,
            "amount": int(round(qty * rate)),
            "gst_rate": float(raw.get("gst_rate") or 18),
            "confidence": round(read * max(resolution.score, 0.1), 2),
            "matched": resolution.action == provisioning.USE,
        }
        if resolution.creates:
            # Nothing ambiguous was found: this really is a new product.
            line["new_sku"] = resolution.proposed
            line["confidence"] = round(read, 2)
        elif resolution.action == provisioning.ASK:
            # Close to something we already stock — the owner decides, because
            # guessing here is how one product ends up in the catalog twice.
            line["new_sku"] = resolution.proposed
            line["near_miss"] = resolution.near_miss
        lines.append(line)
    return lines


def _totals(lines: list[dict], printed: dict | None = None) -> dict:
    """What the shop owes, which is what the paper says.

    Recomputing GST line by line and rounding each one drifts a rupee or two
    from the supplier's own arithmetic — they may round the invoice once, or per
    tax slab. Our number is not more correct than theirs: the invoice is the
    document the shop will be asked to pay, so the printed total wins and any
    difference is recorded rather than quietly absorbed. Over a year of bills
    those rupees are a real reconciliation problem.
    """
    subtotal = sum(int(line["amount"]) for line in lines)
    cgst = sgst = 0
    for line in lines:
        split = gst_split(int(line["amount"]), float(line["gst_rate"]))
        cgst += split["cgst"]
        sgst += split["sgst"]
    computed = subtotal + cgst + sgst

    stated = int(round(float((printed or {}).get("total") or 0))) or None
    totals = {"subtotal": subtotal, "cgst": cgst, "sgst": sgst,
              "computed_total": computed, "total": stated or computed}
    if stated and stated != computed:
        totals["rounding_difference"] = stated - computed
    return totals


def _queue_uncertain(purchase_id: str, lines: list[dict],
                     image_uri: str | None) -> int:
    queued = 0
    for index, line in enumerate(lines):
        if line.get("new_sku") and not line.get("near_miss"):
            continue          # not uncertain — just new. It will be created.
        if not confirm_queue.is_uncertain(line["confidence"]):
            continue
        queued += 1
        confirm_queue.enqueue(
            source_type="purchase", source_id=purchase_id, row_id=index,
            field="sku_id", extracted_value=line["description_raw"],
            confidence=line["confidence"],
            alternatives=[a["name"] for a in
                          catalog.match(line["description_raw"]).alternatives],
            source_image_url=image_uri)
    return queued


def run(payload: dict, trace) -> dict:
    with trace.step("purchase_entry") as s:
        extraction, result = _extract(payload)
        s.from_llm(result)
        image_uri = payload.get("media_path") or payload.get("source_image_url")
        purchase_id = payload.get("purchase_id") or ids.purchase_id()
        lines = _resolve_lines(extraction.get("lines") or [], purchase_id)
        totals = _totals(lines, {"total": extraction.get("printed_total"),
                                 "taxable": extraction.get("printed_taxable")})
        low = sum(1 for line in lines
                  if confirm_queue.is_uncertain(line["confidence"]))

        supplier_name = extraction.get("supplier_name_raw", "")
        supplier_gstin = extraction.get("supplier_gstin")
        supplier_id = _match_supplier(supplier_name, supplier_gstin)
        purchase = {
            "purchase_id": purchase_id,
            "supplier_id": supplier_id,
            "new_supplier": (None if supplier_id or not supplier_name
                             else provisioning.propose_supplier(supplier_name,
                                                                supplier_gstin)),
            "supplier_name_raw": extraction.get("supplier_name_raw"),
            "invoice_no": extraction.get("invoice_no"),
            "invoice_date": extraction.get("invoice_date"),
            "supplier_gstin": extraction.get("supplier_gstin"),
            "source_image_url": image_uri,
            "lines": lines, "totals": totals,
            "status": "needs_confirm" if low else "extracted",
            "stock_applied": False, "stock_delta": [],
            "payable_ledger_id": None, "trace_id": trace.trace_id,
            "created_at": datetime.now(timezone.utc),
        }
        db().collection("purchases").document(purchase_id).set(purchase)
        trace.set_ref("purchase", purchase_id)
        _queue_uncertain(purchase_id, lines, image_uri)

        new_skus = sum(1 for line in lines
                       if line.get("new_sku") and not line.get("near_miss"))
        s.status = "flagged" if low else "done"
        s.summary = (f"Invoice {purchase['invoice_no']} read — {len(lines)} lines, "
                     f"{inr(totals['total'])}"
                     + (f", {new_skus} new to the catalogue" if new_skus else "")
                     + (f", {low} needs confirming" if low else ""))
    return purchase
