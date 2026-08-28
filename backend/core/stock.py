"""Inventory reads and substitute suggestions.

Shared by the Stock & Pricing agent (which prices an order) and the API (which
re-derives the on-screen substitution prompt at read time). Deriving rather than
storing keeps the order document to the fields in the schema, and means the
prompt reflects stock *now* rather than stock when the agent happened to run.
"""
from __future__ import annotations

import re

from core import catalog
from core.firestore_client import db
from core.money import inr


def stock_of(sku_id: str | None) -> int:
    if not sku_id:
        return 0
    snap = db().collection("inventory").document(sku_id).get()
    return int((snap.to_dict() or {}).get("qty_on_hand", 0)) if snap.exists else 0


def tier_of(party_id: str | None) -> str:
    if not party_id:
        return "retail"
    snap = db().collection("parties").document(party_id).get()
    return (snap.to_dict() or {}).get("price_tier", "retail") if snap.exists else "retail"


def substitute_for(sku: dict, qty: float, rows: list[dict] | None = None) -> dict | None:
    """First declared substitute that can actually fill the shortfall."""
    rows = rows if rows is not None else catalog.load()
    shortfall = qty - stock_of(sku.get("sku_id"))
    for candidate_id in sku.get("substitutes") or []:
        candidate = catalog.by_id(candidate_id, rows)
        if candidate and stock_of(candidate_id) >= shortfall:
            return candidate
    return None


_SIZE_TAIL = re.compile(r"\s*(\(.*\)|\d+\s*(kg|kgs|ft|m|mm|ltr|l)\b.*)$", re.I)


def short_name(sku: dict) -> str:
    """'Ramco Supergrade OPC 53 Grade 50kg' -> 'Ramco Supergrade OPC 53 Grade'.

    Shop copy names the product, not the packing; the packing is already implied
    by the unit shown next to the quantity.
    """
    return _SIZE_TAIL.sub("", sku.get("name", "")).strip() or sku.get("name", "")


def _copy(sku: dict, qty: float, on_hand: int, alternative: dict | None,
          tier: str) -> str:
    shortfall = int(qty - on_hand)
    unit = sku.get("unit", "unit")
    head = (f"{short_name(sku)} is short — {on_hand} of {int(qty)} "
            f"{unit}s in stock")
    if alternative:
        return (f"{head}. {short_name(alternative)} covers the other {shortfall} "
                f"at {inr(catalog.rate_for(alternative, tier))} a {unit}.")
    return f"{head}. No substitute in the catalogue — part-fill or order in."


def suggestions_for(order: dict) -> list[dict]:
    """One entry per line that cannot be filled from stock as ordered."""
    rows = catalog.load()
    tier = tier_of(order.get("party_id"))
    out: list[dict] = []
    for index, line in enumerate(order.get("lines") or []):
        sku_id = line.get("sku_id")
        if not sku_id or line.get("substitute_of"):
            continue
        qty = float(line.get("qty") or 0)
        on_hand = stock_of(sku_id)
        if on_hand >= qty:
            continue
        sku = catalog.by_id(sku_id, rows)
        if not sku:
            continue
        alternative = substitute_for(sku, qty, rows)
        out.append({
            "line_index": index,
            "sku_id": sku_id,
            "name": sku.get("name"),
            "qty_wanted": qty,
            "qty_available": on_hand,
            "unit": sku.get("unit"),
            "substitute_sku_id": (alternative or {}).get("sku_id"),
            "substitute_name": (alternative or {}).get("name"),
            "substitute_rate": catalog.rate_for(alternative, tier) if alternative else 0,
            "message": _copy(sku, qty, on_hand, alternative, tier),
        })
    return out
