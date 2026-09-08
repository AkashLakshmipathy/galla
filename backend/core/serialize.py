"""Firestore documents -> JSON the PWA can render directly.

Two jobs. First, make the payload JSON-safe (datetimes to ISO). Second, do the
read-time denormalisation the schema deliberately keeps *out* of Firestore:
product names joined from the catalog, media paths turned into URLs the app can
fetch, `needs_confirm` derived from confidence, and the substitution prompt
recomputed against stock as it is now. Storing any of that would mean a second
copy of a fact that can go stale.
"""
from __future__ import annotations

from datetime import date, datetime

from core import catalog, stock, storage
from core.config import CONFIDENCE_THRESHOLD
from core.firestore_client import db


def jsonable(value):
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, date):
        return value.isoformat()
    if isinstance(value, dict):
        return {k: jsonable(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [jsonable(v) for v in value]
    return value


def line_view(line: dict, rows: list[dict] | None = None) -> dict:
    sku = catalog.by_id(line.get("sku_id"), rows) if line.get("sku_id") else None
    view = dict(line)
    view["name"] = (sku or {}).get("name") or line.get("name_raw") or "Unmatched item"
    view["name_ta"] = (sku or {}).get("name_ta")
    view["hsn_code"] = (sku or {}).get("hsn_code")
    view["needs_confirm"] = float(line.get("confidence") or 1) < CONFIDENCE_THRESHOLD
    return view


def order_view(order: dict | None) -> dict | None:
    if not order:
        return None
    rows = catalog.load()
    view = dict(order)
    party = db().collection("parties").document(
        order.get("party_id") or "_").get().to_dict() or {}
    view["party_name"] = party.get("name") or order.get("party_id")
    view["party_name_ta"] = party.get("name_ta")
    view["price_tier"] = party.get("price_tier")
    view["lines"] = [line_view(line, rows) for line in order.get("lines") or []]
    view["stock_suggestions"] = stock.suggestions_for(order)
    view["source_media_path"] = storage.http_path(order.get("source_media_url"))
    view["quotation_path"] = storage.http_path(order.get("quotation_url"))
    view["invoice_path"] = storage.http_path(order.get("invoice_url"))
    return jsonable(view)


def purchase_view(purchase: dict | None) -> dict | None:
    if not purchase:
        return None
    rows = catalog.load()
    view = dict(purchase)
    view["lines"] = [
        {**line,
         "name": (catalog.by_id(line.get("sku_id"), rows) or {}).get("name")
         or (line.get("new_sku") or {}).get("name")
         or line.get("description_raw"),
         # A brand-new product is not "uncertain" — it is simply new, and the
         # UI says so rather than nagging for a confirmation there is no
         # alternative to.
         "is_new": bool(line.get("new_sku")) and not line.get("near_miss"),
         "near_miss": line.get("near_miss"),
         "needs_confirm": float(line.get("confidence") or 1) < CONFIDENCE_THRESHOLD
         or bool(line.get("near_miss"))}
        for line in purchase.get("lines") or []
    ]
    view["new_sku_count"] = sum(1 for l in view["lines"] if l["is_new"])
    view["source_image_path"] = storage.http_path(purchase.get("source_image_url"))
    return jsonable(view)


def khata_view(record: dict | None) -> dict | None:
    if not record:
        return None
    view = dict(record)
    view["rows"] = [
        {**row,
         "is_new_party": bool(row.get("new_party")) and not row.get("near_miss"),
         "proposed_name": (row.get("new_party") or {}).get("name"),
         "is_company": (row.get("new_party") or {}).get("is_company", False)}
        for row in record.get("rows") or []
    ]
    view["new_party_count"] = len({r["proposed_name"] for r in view["rows"]
                                   if r["is_new_party"]})
    view["page_image_path"] = storage.http_path(record.get("page_image_url"))
    return jsonable(view)


def trace_view(trace: dict | None) -> dict | None:
    return jsonable(trace) if trace else None


def party_view(party: dict | None) -> dict | None:
    if not party:
        return None
    view = dict(party)
    credit = view.get("credit") or {}
    limit = int(credit.get("limit") or 0)
    outstanding = int(credit.get("outstanding") or 0)
    view["exposure_pct"] = int(round(outstanding / limit * 100)) if limit else 0
    return jsonable(view)
