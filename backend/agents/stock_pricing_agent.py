"""Stock & Pricing — inventory truth and the party's price tier.

No model call here at all, and that is the point: quantities on hand and a
contractor's agreed rate are facts in Firestore, not things to infer. The agent
reads inventory, applies the party's tier, and flags any line stock cannot fill.

The substitution *prompt* is derived at read time by `core.stock`, not stored:
the owner accepts or rejects it on screen, and an accepted swap is recorded the
way the schema says — a line with `substitute_of` set. The agent never silently
changes what the customer asked for.
"""
from __future__ import annotations

from datetime import datetime, timezone

from core import catalog, stock
from core.firestore_client import db
from core.money import inr, line_amount, order_totals


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


def run(order: dict, trace) -> dict:
    with trace.step("stock_pricing") as s:
        tier = stock.tier_of(order.get("party_id"))
        lines = price_lines(order.get("lines") or [], tier)
        subtotal, gst, total = order_totals(lines)

        update = {"lines": lines, "subtotal": subtotal, "gst": gst, "total": total,
                  "updated_at": datetime.now(timezone.utc)}
        db().collection("orders").document(order["order_id"]).update(update)
        order.update(update)

        short = [line for line in lines if not line.get("in_stock")]
        s.status = "flagged" if short else "done"
        s.summary = (f"{tier} rates applied, {inr(total)} incl. GST"
                     + (f" — {len(short)} line short on stock" if short else ""))
    return order
