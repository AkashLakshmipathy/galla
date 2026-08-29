"""Write endpoints — every owner decision the PWA can make.

Anything that moves money delegates to `core.transactions`; nothing in this file
writes a ledger entry or a balance directly.
"""
from __future__ import annotations

from datetime import datetime, timezone

from fastapi import APIRouter, HTTPException, UploadFile, File, Form
from pydantic import BaseModel, Field

from agents import router as agent_router
from agents import stock_pricing_agent
from core import catalog, ids, merge, parties, serialize, stock, storage
from core.config import CONFIDENCE_THRESHOLD
from core.firestore_client import db
from core.money import order_totals, parse_amount
from core.transactions import (approve_order, commit_khata_import,
                               confirm_purchase, record_owner_action)

router = APIRouter(prefix="/api")


class Decision(BaseModel):
    action: str = Field(pattern="^(approve|part_payment|reject|modify)$")
    note: str = ""
    advance: int = 0


@router.post("/orders/{order_id}/decision")
def decide_order(order_id: str, body: Decision):
    """Approve · Ask part-payment · Decline. The three fat buttons on S2.

    Approving is the only branch that moves money, and it does so in one
    transaction before the quotation is generated — so a failure to render a PDF
    can never leave the books half-written.
    """
    order = db().collection("orders").document(order_id).get().to_dict()
    if not order:
        raise HTTPException(404, "order not found")

    if body.action == "approve":
        result = approve_order(order_id, note=body.note)
        order = db().collection("orders").document(order_id).get().to_dict()
        order = agent_router.resume_after_decision(order, "approve")
    else:
        advance = body.advance or int(
            (order.get("credit_verdict") or {}).get("suggested_advance") or 0)
        result = record_owner_action(order_id, body.action, note=body.note,
                                     advance=advance)
        order = db().collection("orders").document(order_id).get().to_dict()
        if body.action == "part_payment":
            order = agent_router.resume_after_decision(order, "part_payment",
                                                       advance=advance)
    return {"result": serialize.jsonable(result),
            "order": serialize.order_view(
                db().collection("orders").document(order_id).get().to_dict())}


class LineEdit(BaseModel):
    index: int
    qty: float | None = None
    rate: int | None = None
    sku_id: str | None = None
    remove: bool = False


@router.patch("/orders/{order_id}/lines")
def edit_lines(order_id: str, edits: list[LineEdit]):
    """Line editor sheet: quantity stepper, rate keypad, remove, re-match SKU.

    A rate the owner typed is marked as overridden so a later reprice leaves it
    alone — the shop's word beats the catalogue's.
    """
    ref = db().collection("orders").document(order_id)
    order = ref.get().to_dict()
    if not order:
        raise HTTPException(404, "order not found")
    if order.get("status") == "approved":
        raise HTTPException(409, "order already approved — post a correction instead")

    lines = list(order.get("lines") or [])
    for edit in sorted(edits, key=lambda e: e.index, reverse=True):
        if not 0 <= edit.index < len(lines):
            raise HTTPException(400, f"no line {edit.index}")
        if edit.remove:
            if len(lines) == 1:
                raise HTTPException(400, "an order needs at least one line")
            lines.pop(edit.index)
            continue
        line = dict(lines[edit.index])
        if edit.sku_id:
            sku = catalog.by_id(edit.sku_id)
            if not sku:
                raise HTTPException(400, f"unknown sku {edit.sku_id}")
            line.update({"sku_id": edit.sku_id, "confidence": 1.0,
                         "unit": sku.get("unit"), "gst_rate": sku.get("gst_rate")})
        if edit.qty is not None:
            line["qty"] = float(edit.qty)
        if edit.rate is not None:
            line["rate"] = int(edit.rate)
            line["rate_overridden"] = True
        lines[edit.index] = line

    tier = stock.tier_of(order.get("party_id"))
    lines = stock_pricing_agent.price_lines(lines, tier)
    subtotal, gst, total = order_totals(lines)
    ref.update({"lines": lines, "subtotal": subtotal, "gst": gst, "total": total,
                "updated_at": datetime.now(timezone.utc)})
    return serialize.order_view(ref.get().to_dict())


class Substitution(BaseModel):
    line_index: int
    accept: bool = True


@router.post("/orders/{order_id}/substitute")
def apply_substitute(order_id: str, body: Substitution):
    """Accept the Stock agent's suggestion: the short line is filled to what is
    actually on the shelf and the remainder becomes a new line carrying
    `substitute_of`, which is how the schema records a swap."""
    ref = db().collection("orders").document(order_id)
    order = ref.get().to_dict()
    if not order:
        raise HTTPException(404, "order not found")
    lines = list(order.get("lines") or [])
    if not 0 <= body.line_index < len(lines):
        raise HTTPException(400, "no such line")
    if not body.accept:
        return serialize.order_view(order)

    original = dict(lines[body.line_index])
    sku = catalog.by_id(original.get("sku_id"))
    if not sku:
        raise HTTPException(400, "line has no matched SKU")
    on_hand = stock.stock_of(sku["sku_id"])
    shortfall = float(original.get("qty") or 0) - on_hand
    alternative = stock.substitute_for(sku, float(original.get("qty") or 0))
    if shortfall <= 0 or not alternative:
        raise HTTPException(409, "nothing to substitute")

    original["qty"] = on_hand
    lines[body.line_index] = original
    lines.insert(body.line_index + 1, {
        "sku_id": alternative["sku_id"], "name_raw": alternative.get("name"),
        "qty": shortfall, "unit": alternative.get("unit"), "rate": 0, "amount": 0,
        "gst_rate": alternative.get("gst_rate"), "confidence": 1.0,
        "substitute_of": sku["sku_id"], "in_stock": True,
    })

    tier = stock.tier_of(order.get("party_id"))
    lines = stock_pricing_agent.price_lines(lines, tier)
    subtotal, gst, total = order_totals(lines)
    ref.update({"lines": lines, "subtotal": subtotal, "gst": gst, "total": total,
                "updated_at": datetime.now(timezone.utc)})
    return serialize.order_view(ref.get().to_dict())


class Resolution(BaseModel):
    value: str | float | int | None = None
    accept_extracted: bool = False


@router.post("/confirm-queue/{item_id}/resolve")
def resolve_queue_item(item_id: str, body: Resolution):
    """Clear one card off the confirm queue and write the answer back into the
    document it came from — the queue is a view onto real records, not a
    parallel copy of them."""
    ref = db().collection("confirm_queue").document(item_id)
    item = ref.get().to_dict()
    if not item:
        raise HTTPException(404, "queue item not found")
    if item.get("status") != "pending":
        return serialize.jsonable(item)

    value = item.get("extracted_value") if body.accept_extracted else body.value
    ref.update({
        "status": "confirmed" if body.accept_extracted else "corrected",
        "resolved_value": value, "resolved_by": "owner",
        "resolved_at": datetime.now(timezone.utc),
    })
    _write_back(item, value, body.accept_extracted)
    return serialize.jsonable(ref.get().to_dict())


def _resolved_field(item: dict, value, accept_extracted: bool,
                    current: dict) -> tuple[str, object] | None:
    """Turn what the owner tapped into (field, storable value).

    The queue shows *display* text — a formatted amount, a product name, a party
    name — so nothing here can be written straight through. `sku_id` and
    `party_id` are resolved through the same matchers the agents used, and an
    amount is parsed back out of its formatting. Accepting the extracted value
    for an id field means "the agent's match was right", which is the id already
    on the record, not the label shown beside it.
    """
    field = item.get("field") or "amount"
    if field == "sku_id":
        if accept_extracted:
            # "The agent was right." That is either the id it already attached,
            # or — when it found something close but would not commit to it —
            # the near miss it was asking about.
            return ("sku_id", current.get("sku_id")
                    or (current.get("near_miss") or {}).get("sku_id"))
        found = catalog.match(str(value))
        return ("sku_id", found.sku_id) if found.sku_id else None
    if field == "party_id":
        if accept_extracted:
            return ("party_id", current.get("party_id")
                    or (current.get("near_miss") or {}).get("party_id"))
        party_id, _ = parties.match(str(value))
        return ("party_id", party_id) if party_id else None
    if field in {"amount", "qty", "rate"}:
        return (field, parse_amount(value))
    return (field, value)


def _write_back(item: dict, value, accept_extracted: bool) -> None:
    """Push the owner's answer into the record the queue card came from."""
    source, source_id, row_id = (item.get("source_type"), item.get("source_id"),
                                 item.get("row_id"))
    if source == "khata":
        ref = db().collection("khata_imports").document(source_id)
        record = ref.get().to_dict() or {}
        rows = list(record.get("rows") or [])
        for row in rows:
            if str(row.get("row_id")) != str(row_id):
                continue
            resolved = _resolved_field(item, value, accept_extracted, row)
            if resolved is None:
                raise HTTPException(400, "could not resolve that value")
            row[resolved[0]] = resolved[1]
            row["status"] = "confirmed"
            row["confidence"] = 1.0
        ref.update({"rows": rows,
                    "auto_accepted_count": sum(
                        1 for r in rows if r.get("status") == "auto_accepted"),
                    "needs_confirm_count": sum(
                        1 for r in rows if r.get("status") == "needs_confirm")})
        return

    if source == "purchase":
        ref = db().collection("purchases").document(source_id)
        record = ref.get().to_dict() or {}
        lines = list(record.get("lines") or [])
        index = int(row_id or 0)
        if not 0 <= index < len(lines):
            raise HTTPException(400, "no such line")
        resolved = _resolved_field(item, value, accept_extracted, lines[index])
        if resolved is None:
            raise HTTPException(400, "could not resolve that value")
        lines[index][resolved[0]] = resolved[1]
        lines[index]["confidence"] = 1.0
        lines[index]["matched"] = bool(lines[index].get("sku_id"))
        lines[index]["amount"] = int(round(float(lines[index].get("qty") or 0)
                                           * float(lines[index].get("rate") or 0)))
        ref.update({"lines": lines, "totals": _purchase_totals(lines),
                    "status": "extracted" if all(
                        float(l.get("confidence") or 0) >= CONFIDENCE_THRESHOLD
                        for l in lines) else "needs_confirm"})
        return

    if source == "order":
        ref = db().collection("orders").document(source_id)
        record = ref.get().to_dict() or {}
        lines = list(record.get("lines") or [])
        index = int(row_id or 0)
        if not 0 <= index < len(lines):
            raise HTTPException(400, "no such line")
        resolved = _resolved_field(item, value, accept_extracted, lines[index])
        if resolved is None:
            raise HTTPException(400, "could not resolve that value")
        lines[index][resolved[0]] = resolved[1]
        lines[index]["confidence"] = 1.0
        priced = stock_pricing_agent.price_lines(
            lines, stock.tier_of(record.get("party_id")))
        subtotal, gst, total = order_totals(priced)
        ref.update({"lines": priced, "subtotal": subtotal, "gst": gst,
                    "total": total})


class Merge(BaseModel):
    source_id: str
    target_id: str


@router.post("/parties/merge")
def merge_party_profiles(body: Merge):
    """Fold one profile into another. The balance moves and the documents
    follow; the ledger is never rewritten, so this can be undone."""
    try:
        return serialize.jsonable(
            merge.merge_parties(body.source_id, body.target_id))
    except LookupError as exc:
        raise HTTPException(404, str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(409, str(exc)) from exc


@router.post("/purchases/{purchase_id}/confirm")
def confirm_purchase_endpoint(purchase_id: str):
    """Save on S3: stock increments, supplier payable posts, and `stock_applied`
    makes the whole thing idempotent."""
    return serialize.jsonable(confirm_purchase(purchase_id))


class PurchaseLineEdit(BaseModel):
    index: int
    qty: float | None = None
    rate: int | None = None
    sku_id: str | None = None


@router.patch("/purchases/{purchase_id}/lines")
def edit_purchase_lines(purchase_id: str, edits: list[PurchaseLineEdit]):
    ref = db().collection("purchases").document(purchase_id)
    purchase = ref.get().to_dict()
    if not purchase:
        raise HTTPException(404, "purchase not found")
    if purchase.get("stock_applied"):
        raise HTTPException(409, "already applied to stock")
    lines = list(purchase.get("lines") or [])
    for edit in edits:
        if not 0 <= edit.index < len(lines):
            raise HTTPException(400, f"no line {edit.index}")
        line = dict(lines[edit.index])
        if edit.sku_id:
            line["sku_id"] = edit.sku_id
            line["matched"] = True
        if edit.qty is not None:
            line["qty"] = float(edit.qty)
        if edit.rate is not None:
            line["rate"] = int(edit.rate)
        line["amount"] = int(round(float(line.get("qty") or 0)
                                   * float(line.get("rate") or 0)))
        line["confidence"] = 1.0
        lines[edit.index] = line
    totals = _purchase_totals(lines)
    ref.update({"lines": lines, "totals": totals,
                "status": "extracted", "updated_at": datetime.now(timezone.utc)})
    return serialize.purchase_view(ref.get().to_dict())


def _purchase_totals(lines: list[dict]) -> dict:
    from core.money import gst_split
    subtotal = sum(int(l.get("amount") or 0) for l in lines)
    cgst = sgst = 0
    for line in lines:
        split = gst_split(int(line.get("amount") or 0),
                          float(line.get("gst_rate") or 0))
        cgst += split["cgst"]
        sgst += split["sgst"]
    return {"subtotal": subtotal, "cgst": cgst, "sgst": sgst,
            "total": subtotal + cgst + sgst}


class KhataRow(BaseModel):
    row_id: str
    amount: float | None = None
    party_id: str | None = None
    date: str | None = None
    confirm: bool = True


@router.post("/khata/{import_id}/rows")
def edit_khata_rows(import_id: str, rows_in: list[KhataRow]):
    ref = db().collection("khata_imports").document(import_id)
    record = ref.get().to_dict()
    if not record:
        raise HTTPException(404, "khata import not found")
    if record.get("status") == "committed":
        raise HTTPException(409, "already committed to the ledger")
    rows = list(record.get("rows") or [])
    wanted = {r.row_id: r for r in rows_in}
    for row in rows:
        edit = wanted.get(str(row.get("row_id")))
        if not edit:
            continue
        if edit.amount is not None:
            row["amount"] = float(edit.amount)
        if edit.party_id is not None:
            row["party_id"] = edit.party_id
        if edit.date is not None:
            row["date"] = edit.date
        if edit.confirm:
            row["status"] = "confirmed"
            row["confidence"] = 1.0
    ref.update({"rows": rows,
                "needs_confirm_count": sum(
                    1 for r in rows if r.get("status") == "needs_confirm")})
    return serialize.khata_view(ref.get().to_dict())


@router.post("/khata/{import_id}/commit")
def commit_khata(import_id: str):
    """Only confirmed rows post. A row still in doubt stays out of the books."""
    return serialize.jsonable(commit_khata_import(import_id))


@router.post("/upload")
async def upload(file: UploadFile = File(...), kind: str = Form("photo")):
    """Camera or voice capture — returns the storage path to hand to /ingest."""
    suffix = (file.filename or "").rsplit(".", 1)[-1].lower() or "bin"
    folder = {"voice": "voice", "invoice": "invoices",
              "khata": "khata"}.get(kind, "photos")
    path = f"{folder}/{ids.item_id()}.{suffix}"
    uri = storage.put_bytes(path, await file.read(),
                            file.content_type or storage.content_type_of(path))
    return {"uri": uri, "path": storage.http_path(uri)}
