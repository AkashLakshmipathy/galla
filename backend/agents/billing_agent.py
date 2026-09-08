"""Billing — the tax invoice, its number, and the link the owner shares.

No model call anywhere in this file, by design. A tax invoice is arithmetic and
a template; either of those going hallucinated is a compliance problem, not a
cosmetic one. The arithmetic itself lives in `core.tax` so it can be tested
against the spec's vectors without constructing an order at all.

Two things this agent is careful about:

* **The invoice number is minted once, at bill time.** Re-billing an order that
  already carries one re-renders the PDF against the same number rather than
  burning a second one. A gap in the series is what an auditor asks about, and
  a duplicate is the one defect a GST return cannot absorb.
* **Inclusive vs exclusive is a property of the sale, not of the code.** A
  walk-in is quoted "bag 445, with tax"; a contractor's order is priced ex-tax
  off his tier. The flag rides on the order and the engine works backwards.
"""
from __future__ import annotations

from datetime import datetime, timezone

from core import catalog, documents, ids, storage, tax
from core.config import SHOP_ID
from core.firestore_client import db
from core.money import inr

TITLE_TAX_INVOICE = "Tax Invoice"


def lines_for_tax(order: dict) -> list[dict]:
    """Order lines in the shape `core.tax` wants.

    `rate` on an order line is the per-unit price the party actually pays, and
    `amount` is qty x rate already computed by stock_pricing. The tax engine
    recomputes from qty and unit price rather than trusting `amount`, so a line
    the owner edited by hand cannot carry a stale total onto a legal document.
    """
    rows = catalog.load()
    prepared: list[dict] = []
    for line in order.get("lines") or []:
        sku = catalog.by_id(line.get("sku_id"), rows) or {}
        prepared.append({
            "sku_id": line.get("sku_id"),
            "description": sku.get("name") or line.get("name_raw") or "Item",
            "hsn_code": sku.get("hsn_code", ""),
            "unit": line.get("unit") or sku.get("unit", ""),
            "qty": line.get("qty", 1),
            "unit_price": line.get("rate", 0),
            "gst_rate": line.get("gst_rate", sku.get("gst_rate", 0)),
            "discount": line.get("discount", 0),
            "discount_pct": line.get("discount_pct", 0),
            "price_includes_tax": line.get(
                "price_includes_tax", order.get("price_includes_tax", False)),
        })
    return prepared


def price(order: dict, party: dict, shop: dict) -> tax.TaxInvoice:
    """The whole bill, split by place of supply. Pure — no writes, no numbering."""
    party_state = party.get("state_code") or (party.get("gstin") or "")[:2]
    return tax.compute_invoice(
        lines_for_tax(order),
        intra_state=tax.is_intra_state(party_state, shop.get("state_code", "33")),
        default_includes_tax=bool(order.get("price_includes_tax", False)),
    )


def build(order: dict, party: dict, shop: dict, number: str,
          title: str = TITLE_TAX_INVOICE) -> tuple[tax.TaxInvoice, bytes]:
    invoice = price(order, party, shop)
    pdf = documents.tax_invoice_pdf(invoice, shop, party, number, title=title)
    return invoice, pdf


def run(order: dict, trace) -> dict:
    with trace.step("billing") as s:
        shop = db().collection("shop").document(SHOP_ID).get().to_dict() or {}
        party = db().collection("parties").document(
            order.get("party_id") or "_").get().to_dict() or {}

        # Re-billing reuses the number already on the order; only a first bill
        # advances the counter.
        reissue = bool(order.get("invoice_no"))
        number = order.get("invoice_no") or ids.next_invoice_number(
            prefix=shop.get("invoice_prefix", "SBH"))
        invoice, pdf = build(order, party, shop, number,
                             title="Duplicate" if reissue else TITLE_TAX_INVOICE)

        uri = storage.put_bytes(
            f"invoices/{number.replace('/', '-')}.pdf", pdf, "application/pdf")
        record = {
            "invoice_no": number,
            "invoice_url": uri,
            "invoice_issued_at": datetime.now(timezone.utc),
            "invoice": invoice.as_dict(),
        }
        db().collection("orders").document(order["order_id"]).update(record)
        order.update(record)

        components = (f"CGST {inr(invoice.total_cgst)} + SGST {inr(invoice.total_sgst)}"
                      if invoice.intra_state else f"IGST {inr(invoice.total_igst)}")
        s.summary = (f"{'Duplicate' if reissue else 'Invoice'} {number} — "
                     f"{inr(invoice.payable)} payable ({components})")
    return order
