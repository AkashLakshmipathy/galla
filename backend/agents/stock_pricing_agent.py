"""Stock & Pricing — inventory truth and the party's price tier.

No model call here at all, and that is the point: quantities on hand and a
contractor's agreed rate are facts in Firestore, not things to infer. The agent
reads inventory, applies the party's tier, and flags any line stock cannot fill.

Totals come from `core.tax`, the same engine that prints the invoice. They used
to come from `money.order_totals`, which rounds each line's GST to a whole rupee
before summing — a different rule from the invoice's round-once-at-the-foot, and
on a multi-line order the two answers can differ by a rupee or two. That gap
would put a different number in the ledger than on the tax document the customer
is holding, which is the one disagreement a shop cannot explain away.

The substitution *prompt* is derived at read time by `core.stock`, not stored:
the owner accepts or rejects it on screen, and an accepted swap is recorded the
way the schema says — a line with `substitute_of` set. The agent never silently
changes what the customer asked for.
"""
from __future__ import annotations

from datetime import datetime, timezone

from core import catalog, stock, tax
from core.config import SHOP_ID
from core.firestore_client import db
from core.money import inr, line_amount


def price_lines(lines: list[dict], tier: str) -> list[dict]:
    """Apply tier rate, line amount, GST rate and stock availability."""
    rows = catalog.load()
    priced: list[dict] = []
    for line in lines:
        row = dict(line)
        sku = catalog.by_id(line.get("sku_id"), rows) if line.get("sku_id") else None
        if not sku:
            row.update({"rate": 0, "amount": 0, "in_stock": False})
            priced.append(row)
            continue
        qty = float(line.get("qty") or 0)
        # An owner-set rate override survives repricing; only agent rates move.
        rate = int(line.get("rate") or 0) if line.get("rate_overridden") \
            else catalog.rate_for(sku, tier)
        row.update({
            "rate": rate,
            "amount": line_amount(qty, rate),
            "gst_rate": sku.get("gst_rate", line.get("gst_rate", 0)),
            "in_stock": stock.stock_of(sku["sku_id"]) >= qty,
        })
        priced.append(row)
    return priced


def totals_for(order: dict, lines: list[dict]) -> tuple[int, dict, int]:
    """(subtotal, gst dict, payable) straight off the shared tax engine."""
    party = db().collection("parties").document(
        order.get("party_id") or "_").get().to_dict() or {}
    shop = db().collection("shop").document(SHOP_ID).get().to_dict() or {}
    includes_tax = bool(order.get("price_includes_tax", False))

    invoice = tax.compute_invoice(
        [{"qty": line.get("qty", 0), "unit_price": line.get("rate", 0),
          "gst_rate": line.get("gst_rate", 0),
          "price_includes_tax": line.get("price_includes_tax", includes_tax)}
         for line in lines],
        intra_state=tax.is_intra_state(
            party.get("state_code") or (party.get("gstin") or "")[:2],
            shop.get("state_code", "33")),
        default_includes_tax=includes_tax,
    )
    gst = {"cgst": int(round(float(invoice.total_cgst))),
           "sgst": int(round(float(invoice.total_sgst))),
           "igst": int(round(float(invoice.total_igst))),
           "total": int(round(float(invoice.total_tax)))}
    return int(round(float(invoice.subtotal_taxable))), gst, invoice.payable


def run(order: dict, trace) -> dict:
    with trace.step("stock_pricing") as s:
        tier = stock.tier_of(order.get("party_id"))
        lines = price_lines(order.get("lines") or [], tier)
        subtotal, gst, total = totals_for(order, lines)

        update = {"lines": lines, "subtotal": subtotal, "gst": gst, "total": total,
                  "updated_at": datetime.now(timezone.utc)}
        db().collection("orders").document(order["order_id"]).update(update)
        order.update(update)

        short = [line for line in lines if not line.get("in_stock")]
        s.status = "flagged" if short else "done"
        s.summary = (f"{tier} rates applied, {inr(total)} incl. GST"
                     + (f" — {len(short)} line short on stock" if short else ""))
    return order
