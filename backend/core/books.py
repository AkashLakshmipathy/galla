"""The two ledgers a shop actually reasons about.

A trade shop has money going out on credit to customers and money owed to
suppliers. They are the same arithmetic pointed in opposite directions, and
mixing them is a real hazard: a supplier we owe fifty thousand to, listed under
"who owes you", overstates what the shop is worth by a hundred thousand.

So direction is decided once, here, by the party's own type — never by the sign
of an entry, which reads differently depending on whose book you are in.
"""
from __future__ import annotations

from collections import defaultdict
from core import merge
from core.firestore_client import db

CUSTOMER_TYPES = {"customer", "both"}
SUPPLIER_TYPES = {"supplier", "both"}

# What "period" means on screen. All-time is a real option: a shop digitising
# twenty years wants the whole book, not the last six months of it.
GRANULARITY = {"month": 7, "year": 4, "all": 0}


def bucket_for(days: int) -> str:
    return ("current" if days <= 30 else "30" if days <= 60
            else "60" if days <= 90 else "90+")


def period_key(date_value, granularity: str) -> str:
    width = GRANULARITY.get(granularity, 7)
    return "all" if not width else str(date_value or "")[:width]


def parties_of(kind: str) -> dict[str, dict]:
    """Live parties on one side of the book. Merged-away profiles are excluded;
    their history reaches the survivor through `merge.resolve`."""
    wanted = CUSTOMER_TYPES if kind == "customer" else SUPPLIER_TYPES
    out = {}
    for snap in db().collection("parties").stream():
        party = snap.to_dict() or {}
        if party.get("merged_into"):
            continue
        if (party.get("type") or "customer") in wanted:
            out[snap.id] = party
    return out


def ledger_rollup(kind: str, granularity: str = "month") -> tuple[dict, dict]:
    """(per-party stats, per-period stats) from the append-only ledger.

    `out` is money leaving the shop's control — goods handed over on credit, or
    a bill owed to a supplier. `back` is money settling it. Which ledger
    direction means which flips with the side of the book, which is exactly why
    this is computed in one place.
    """
    live = parties_of(kind)
    out_direction = "debit" if kind == "customer" else "credit"

    per_party: dict[str, dict] = defaultdict(
        lambda: {"out": 0, "back": 0, "entries": 0, "first": None, "last": None})
    per_period: dict[str, dict] = {}

    for snap in db().collection("ledger").stream():
        entry = snap.to_dict() or {}
        party_id = merge.resolve(entry.get("party_id") or "")
        if party_id not in live:
            continue
        amount = int(entry.get("amount") or 0)
        leaving = entry.get("direction") == out_direction
        date_value = entry.get("date")

        stats = per_party[party_id]
        stats["out" if leaving else "back"] += amount
        stats["entries"] += 1
        stats["first"] = min(filter(None, [stats["first"], date_value]), default=None)
        stats["last"] = max(filter(None, [stats["last"], date_value]), default=None)

        key = period_key(date_value, granularity)
        row = per_period.setdefault(key, {"period": key, "out": 0, "back": 0,
                                          "entries": 0, "parties": set()})
        row["out" if leaving else "back"] += amount
        row["entries"] += 1
        row["parties"].add(party_id)

    periods = [{**row, "parties": len(row["parties"]),
                "net": row["out"] - row["back"]}
               for row in sorted(per_period.values(), key=lambda r: r["period"])]
    return per_party, _fill_gaps(periods, granularity)


def _fill_gaps(periods: list[dict], granularity: str) -> list[dict]:
    """Insert the quiet periods.

    Skipping months with no entries puts March next to November on the axis and
    makes a gap in trading look like continuous business. An empty month is
    information — it is the months a customer did not buy anything — so it gets
    its own column.
    """
    if granularity == "all" or len(periods) < 2:
        return periods

    def step(key: str) -> str:
        if granularity == "year":
            return str(int(key) + 1)
        year, month = int(key[:4]), int(key[5:7])
        return f"{year + 1:04d}-01" if month == 12 else f"{year:04d}-{month + 1:02d}"

    filled, key = [], periods[0]["period"]
    index = {row["period"]: row for row in periods}
    last = periods[-1]["period"]
    guard = 0
    while guard < 600:
        filled.append(index.get(key, {"period": key, "out": 0, "back": 0,
                                      "entries": 0, "parties": 0, "net": 0}))
        if key == last:
            break
        key = step(key)
        guard += 1
    return filled


def purchase_rollup() -> tuple[dict, dict]:
    """(per-supplier purchase stats, per-SKU stats) from confirmed bills.

    Only bills the owner actually saved to stock count. An extraction sitting in
    review is not yet a purchase, and counting it would tell him he had bought
    something he has not agreed to.
    """
    per_supplier: dict[str, dict] = defaultdict(
        lambda: {"bills": 0, "value": 0, "items": 0, "last_bill": None,
                 "skus": defaultdict(lambda: {"qty": 0, "value": 0, "bills": 0})})
    per_sku: dict[str, dict] = defaultdict(
        lambda: {"qty": 0, "value": 0, "bills": 0, "suppliers": set(),
                 "last_rate": 0, "last_date": None})

    for snap in db().collection("purchases").stream():
        purchase = snap.to_dict() or {}
        if not purchase.get("stock_applied"):
            continue
        supplier_id = merge.resolve(purchase.get("supplier_id") or "") or "unknown"
        date_value = purchase.get("invoice_date")
        stats = per_supplier[supplier_id]
        stats["bills"] += 1
        stats["value"] += int((purchase.get("totals") or {}).get("total") or 0)
        stats["last_bill"] = max(filter(None, [stats["last_bill"], date_value]),
                                 default=None)

        for line in purchase.get("lines") or []:
            sku_id = line.get("sku_id")
            if not sku_id:
                continue
            qty = float(line.get("qty") or 0)
            value = int(line.get("amount") or 0)
            stats["items"] += 1
            stats["skus"][sku_id]["qty"] += qty
            stats["skus"][sku_id]["value"] += value
            stats["skus"][sku_id]["bills"] += 1

            row = per_sku[sku_id]
            row["qty"] += qty
            row["value"] += value
            row["bills"] += 1
            row["suppliers"].add(supplier_id)
            if not row["last_date"] or str(date_value or "") >= str(row["last_date"]):
                row["last_date"] = date_value
                row["last_rate"] = float(line.get("rate") or 0)

    return per_supplier, per_sku
