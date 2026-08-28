"""Quotation — the GST document the shop actually hands over.

Deterministic end to end: no model call, because a tax document is arithmetic and
a template, and either of those going hallucinated is a compliance problem. The
agent works out HSN codes per line, the CGST/SGST split (IGST if the party is
out-of-state), and the amount in words, then drops the PDF in Cloud Storage.

House styling lives in `core.documents`, shared with the GST summary.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

from reportlab.lib.units import mm
from reportlab.platypus import Paragraph, Table, TableStyle

from core import catalog, documents, storage
from core.config import SHOP_ID
from core.documents import BODY, SMALL, gap, rupees
from core.firestore_client import db
from core.money import ddmmyyyy, gst_split, inr, rupees_in_words

VALID_DAYS = 7
COLUMNS = [7 * mm, 52 * mm, 14 * mm, 17 * mm, 20 * mm, 22 * mm, 13 * mm, 25 * mm]


def quotation_no(order_id: str) -> str:
    return "Q-" + order_id.split("_")[-1]


def is_intra_state(shop: dict, party: dict) -> bool:
    """Same state means CGST+SGST; across a state line it is IGST. An
    unregistered customer is local by definition for this shop."""
    gstin = party.get("gstin")
    return not gstin or gstin[:2] == shop.get("state_code", "33")


def _rows(order: dict, intra_state: bool) -> tuple[list[list], dict]:
    rows = [["#", "Item", "HSN", "Qty", "Rate", "Taxable", "GST", "Amount"]]
    catalog_rows = catalog.load()
    totals = {"taxable": 0, "cgst": 0, "sgst": 0, "igst": 0}
    for index, line in enumerate(order.get("lines") or [], start=1):
        sku = catalog.by_id(line.get("sku_id"), catalog_rows) or {}
        taxable = int(line.get("amount") or 0)
        split = gst_split(taxable, float(line.get("gst_rate") or 0), intra_state)
        totals["taxable"] += taxable
        for key in ("cgst", "sgst", "igst"):
            totals[key] += split[key]
        rows.append([
            str(index),
            Paragraph(sku.get("name") or line.get("name_raw") or "Item", BODY),
            sku.get("hsn_code", ""),
            f"{int(line.get('qty') or 0)} {line.get('unit') or ''}".strip(),
            rupees(line.get("rate")), rupees(taxable),
            f"{int(line.get('gst_rate') or 0)}%",
            rupees(taxable + split["total"]),
        ])
    return rows, totals


def build_pdf(order: dict, shop: dict, party: dict) -> bytes:
    intra_state = is_intra_state(shop, party)
    rows, totals = _rows(order, intra_state)
    tax = totals["cgst"] + totals["sgst"] + totals["igst"]
    grand = totals["taxable"] + tax
    issued = datetime.now(timezone.utc)
    number = quotation_no(order["order_id"])

    parties_block = Table([[
        Paragraph(f"<b>QUOTATION {number}</b><br/>Date {ddmmyyyy(issued)}"
                  f"<br/>Valid {VALID_DAYS} days", BODY),
        Paragraph(f"<b>{party.get('name', 'Customer')}</b><br/>"
                  + (f"GSTIN {party['gstin']}" if party.get("gstin") else "Unregistered")
                  + f"<br/>{party.get('phone', '')}", BODY),
    ]], colWidths=[85 * mm, 85 * mm], style=TableStyle([
        ("VALIGN", (0, 0), (-1, -1), "TOP"), ("LEFTPADDING", (0, 0), (-1, -1), 0),
    ]))

    summary = [["Taxable value", rupees(totals["taxable"])]]
    summary += ([["CGST", rupees(totals["cgst"])], ["SGST", rupees(totals["sgst"])]]
                if intra_state else [["IGST", rupees(totals["igst"])]])
    summary.append(["Total incl. GST", rupees(grand)])

    flow = documents.letterhead(shop) + [
        gap(8), parties_block, gap(6),
        documents.line_table(rows, COLUMNS), gap(5),
        documents.totals_table(summary), gap(4),
        Paragraph(f"<b>{rupees_in_words(grand)}</b>", BODY), gap(6),
        Paragraph("Quotation only — not a tax invoice. Prices hold for "
                  f"{VALID_DAYS} days from {ddmmyyyy(issued)}. Goods once sold are "
                  "subject to the shop's usual terms.", SMALL),
    ]
    return documents.render(flow, f"Quotation {number}", shop.get("name", "Galla"))


def run(order: dict, trace) -> dict:
    with trace.step("quotation") as s:
        shop = db().collection("shop").document(SHOP_ID).get().to_dict() or {}
        party = db().collection("parties").document(
            order.get("party_id") or "_").get().to_dict() or {}
        number = quotation_no(order["order_id"])
        uri = storage.put_bytes(f"quotations/{number}.pdf",
                                build_pdf(order, shop, party), "application/pdf")

        valid_until = (datetime.now(timezone.utc) + timedelta(days=VALID_DAYS)).date()
        db().collection("orders").document(order["order_id"]).update(
            {"quotation_url": uri})
        order["quotation_url"] = uri
        s.summary = (f"Quotation {number} generated — {inr(order.get('total', 0))}, "
                     f"valid to {ddmmyyyy(valid_until)}")
    return order
