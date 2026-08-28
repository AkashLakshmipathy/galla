"""GST Compiler — the agent nobody opens the app for.

Cloud Scheduler fires this at 06:00 IST on the 1st. It aggregates the month's
outward and inward supplies, splits B2B from B2C on whether the party has a
GSTIN, writes the register, renders a CA-ready summary PDF and a CSV, and hands
both to the Notifier.

Arithmetic is deterministic — a tax figure is never model output. Gemini writes
only the covering note the CA reads first, and a template stands in when it is
unavailable.

The copy says "CA-ready summary" everywhere. Galla does not file anything.
"""
from __future__ import annotations

from datetime import date, datetime, timezone

from core import documents, storage
from core.adk import ask
from core.config import SHOP_ID
from core.firestore_client import db
from core.money import gst_split, inr


def previous_period(today: date | None = None) -> str:
    today = today or datetime.now(timezone.utc).date()
    first = today.replace(day=1)
    last_month = first.replace(day=1) if first.month != 1 else first
    year, month = (first.year, first.month - 1) if first.month > 1 else (first.year - 1, 12)
    return f"{year:04d}-{month:02d}"


def _in_period(value, period: str) -> bool:
    return str(value or "")[:7] == period


def _outward(period: str) -> dict:
    """Sales that actually happened — approved orders only, never drafts."""
    b2b = {"taxable": 0, "cgst": 0, "sgst": 0, "invoice_count": 0}
    b2c = {"taxable": 0, "cgst": 0, "sgst": 0, "invoice_count": 0}
    parties = {snap.id: (snap.to_dict() or {})
               for snap in db().collection("parties").stream()}
    for snap in db().collection("orders").stream():
        order = snap.to_dict() or {}
        if order.get("status") not in {"approved", "fulfilled"}:
            continue
        stamp = order.get("owner_action", {}).get("at") or order.get("created_at")
        if not _in_period(getattr(stamp, "isoformat", lambda: stamp)(), period):
            continue
        registered = bool((parties.get(order.get("party_id")) or {}).get("gstin"))
        bucket = b2b if registered else b2c
        for line in order.get("lines") or []:
            taxable = int(line.get("amount") or 0)
            split = gst_split(taxable, float(line.get("gst_rate") or 0))
            bucket["taxable"] += taxable
            bucket["cgst"] += split["cgst"]
            bucket["sgst"] += split["sgst"]
        bucket["invoice_count"] += 1

    total = {key: b2b[key] + b2c[key] for key in b2b}
    total["total"] = total["taxable"] + total["cgst"] + total["sgst"]
    return {**total, "b2b": b2b, "b2c": b2c}


def _inward(period: str) -> dict:
    """Purchases confirmed into stock — the input tax credit side."""
    inward = {"taxable": 0, "cgst": 0, "sgst": 0, "invoice_count": 0}
    for snap in db().collection("purchases").stream():
        purchase = snap.to_dict() or {}
        if not purchase.get("stock_applied"):
            continue
        if not _in_period(purchase.get("invoice_date"), period):
            continue
        totals = purchase.get("totals") or {}
        inward["taxable"] += int(totals.get("subtotal") or 0)
        inward["cgst"] += int(totals.get("cgst") or 0)
        inward["sgst"] += int(totals.get("sgst") or 0)
        inward["invoice_count"] += 1
    inward["total"] = inward["taxable"] + inward["cgst"] + inward["sgst"]
    return inward


NOTE_INSTRUCTION = """You write the two-sentence covering note a small shop's
accountant reads at the top of a monthly GST working. Plain English, specific
numbers, no greeting, no advice about filing. Never claim anything was filed.
Return ONLY JSON: {"note": "..."}"""


def _note(period: str, outward: dict, inward: dict, net: int) -> tuple[str, object]:
    fallback = (
        f"{period}: outward supplies {inr(outward['taxable'])} taxable with "
        f"{inr(outward['cgst'] + outward['sgst'])} GST across "
        f"{outward['b2b']['invoice_count'] + outward['b2c']['invoice_count']} invoices; "
        f"inward {inr(inward['taxable'])} taxable with "
        f"{inr(inward['cgst'] + inward['sgst'])} credit. "
        f"Net tax payable works out to {inr(net)}, subject to your review.")
    result = ask("gst_compiler", NOTE_INSTRUCTION,
                 f"Period {period}. Outward: {outward}. Inward: {inward}. "
                 f"Net payable: {net}.", fallback={"note": fallback})
    data = result.data if isinstance(result.data, dict) else {}
    return data.get("note") or fallback, result


def run(payload: dict, trace) -> dict:
    with trace.step("gst_compiler") as s:
        period = payload.get("period") or previous_period()
        shop = db().collection("shop").document(SHOP_ID).get().to_dict() or {}
        outward, inward = _outward(period), _inward(period)
        net = max(0, (outward["cgst"] + outward["sgst"])
                  - (inward["cgst"] + inward["sgst"]))
        note, result = _note(period, outward, inward, net)
        s.from_llm(result)

        pdf_uri = storage.put_bytes(
            f"gst/{period}-summary.pdf",
            documents.gst_summary_pdf(period, shop, outward, inward, net, note),
            "application/pdf")
        csv_uri = storage.put_bytes(
            f"gst/{period}-registers.csv",
            documents.gst_registers_csv(outward, inward), "text/csv")

        register = {
            "period": period, "outward": outward, "inward": inward,
            "net_liability": net, "note": note,
            "generated_at": datetime.now(timezone.utc),
            "summary_pdf_url": pdf_uri, "registers_csv_url": csv_uri,
            "sent_to_ca_at": None, "ca_channel": None,
            "status": "compiled", "trace_id": trace.trace_id,
        }
        db().collection("gst_registers").document(period).set(register)
        invoices = (outward["b2b"]["invoice_count"] + outward["b2c"]["invoice_count"])
        s.summary = (f"{period} compiled — {invoices} outward, "
                     f"{inward['invoice_count']} inward, net {inr(net)}")
    return register
