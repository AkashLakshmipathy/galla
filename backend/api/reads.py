"""Read endpoints for the PWA. No writes here, ever."""
from __future__ import annotations

from datetime import datetime, timezone

from fastapi import APIRouter, HTTPException, Response
from google.cloud.firestore_v1.base_query import FieldFilter

from agents.router import fleet
from core import books, catalog, merge, serialize, storage
from core.config import CONFIDENCE_THRESHOLD, SHOP_ID
from core.firestore_client import db
from agents.credit_guardian_agent import days_since
from agents.router import CHAINS

router = APIRouter(prefix="/api")


def _docs(collection: str, order_field: str | None = None, desc: bool = True,
          limit: int = 50, where: tuple | None = None) -> list[dict]:
    query = db().collection(collection)
    if where:
        query = query.where(filter=FieldFilter(*where))
    if order_field:
        query = query.order_by(order_field,
                               direction="DESCENDING" if desc else "ASCENDING")
    return [snap.to_dict() for snap in query.limit(limit).stream()]


@router.get("/fleet")
def get_fleet():
    """Agent roster + the chain per event type — the trace strip renders its
    idle dots from this, so it can show what *will* run, not just what has."""
    return {"agents": fleet(), "chains": CHAINS,
            "confidence_threshold": CONFIDENCE_THRESHOLD}


@router.get("/shop")
def get_shop():
    return serialize.jsonable(db().collection("shop").document(SHOP_ID).get().to_dict())


@router.get("/counter")
def counter(limit: int = 20):
    """The inbox: every order, purchase and khata page as one reverse-chronological
    thread, which is the only screen the owner spends real time on."""
    items = []
    for order in _docs("orders", "created_at", limit=limit):
        items.append({"kind": "order", "id": order.get("order_id"),
                      "at": order.get("created_at"), "data": serialize.order_view(order)})
    for purchase in _docs("purchases", "created_at", limit=limit):
        items.append({"kind": "purchase", "id": purchase.get("purchase_id"),
                      "at": purchase.get("created_at"),
                      "data": serialize.purchase_view(purchase)})
    for record in _docs("khata_imports", "created_at", limit=limit):
        items.append({"kind": "khata", "id": record.get("import_id"),
                      "at": record.get("created_at"),
                      "data": serialize.khata_view(record)})
    items.sort(key=lambda i: str(i["at"] or ""), reverse=True)
    return {"items": serialize.jsonable(items[:limit])}


@router.get("/orders/{order_id}")
def get_order(order_id: str):
    order = db().collection("orders").document(order_id).get().to_dict()
    if not order:
        raise HTTPException(404, "order not found")
    view = serialize.order_view(order)
    view["party"] = serialize.party_view(
        db().collection("parties").document(order["party_id"]).get().to_dict())
    return view


@router.get("/traces/{trace_id}")
def get_trace(trace_id: str):
    trace = db().collection("agent_traces").document(trace_id).get().to_dict()
    if not trace:
        raise HTTPException(404, "trace not found")
    return serialize.trace_view(trace)


@router.get("/traces")
def list_traces(limit: int = 20):
    return {"traces": serialize.jsonable(_docs("agent_traces", "created_at",
                                               limit=limit))}


@router.get("/approvals")
def approvals():
    """Everything waiting on the owner — including work that is *finished* and
    simply has not been posted yet.

    A page read, reviewed and reconciled is worth nothing until its entries
    reach the ledger, and there was no sign anywhere that the last tap was
    still outstanding. Four pages sat in review for a day looking done.
    """
    orders = [serialize.order_view(o) for o in
              _docs("orders", "created_at", limit=50)
              if o.get("status") == "awaiting_approval"]
    queue = [serialize.jsonable(i) for i in
             _docs("confirm_queue", "created_at", desc=False, limit=50)
             if i.get("status") == "pending"]

    ready, waiting = [], []
    for record in _docs("khata_imports", "created_at", limit=100):
        if record.get("status") == "committed":
            continue
        rows = record.get("rows") or []
        blocked = sum(1 for r in rows if r.get("status") == "needs_confirm")
        entry = {
            "import_id": record.get("import_id"),
            "party_name_raw": record.get("party_name_raw"),
            "rows": len(rows), "blocked": blocked,
            "opening_balance": record.get("opening_balance"),
            "closing_balance": record.get("closing_balance"),
            "balances": bool((record.get("arithmetic") or {}).get("balances")),
        }
        (waiting if blocked else ready).append(serialize.jsonable(entry))

    unconfirmed = [serialize.purchase_view(p) for p in
                   _docs("purchases", "created_at", limit=50)
                   if not p.get("stock_applied")]

    return {"orders": orders, "confirm_queue": queue,
            "khata_ready": ready, "khata_waiting": waiting,
            "purchases_unsaved": unconfirmed,
            "badge": len(orders) + len(queue) + len(ready) + len(unconfirmed)}


@router.get("/confirm-queue")
def confirm_queue():
    items = [serialize.jsonable(i) for i in
             _docs("confirm_queue", "created_at", desc=False, limit=100)
             if i.get("status") == "pending"]
    # The item stores the import id, and the screen was showing it: "From khata
    # imp_15 · row r3". That is our filing reference, not a fact about anyone's
    # customer. Resolve it to the name on the page — one read per distinct
    # source, not per row, since a page usually contributes several.
    names: dict[str, str] = {}
    for item in items:
        item["source_image_path"] = storage.http_path(item.get("source_image_url"))
        source_id = item.get("source_id")
        if item.get("source_type") == "khata" and source_id:
            if source_id not in names:
                record = db().collection("khata_imports").document(
                    source_id).get().to_dict() or {}
                names[source_id] = record.get("party_name_raw") or ""
            item["source_label"] = names[source_id]
    return {"items": items, "count": len(items)}


@router.get("/purchases/{purchase_id}")
def get_purchase(purchase_id: str):
    purchase = db().collection("purchases").document(purchase_id).get().to_dict()
    if not purchase:
        raise HTTPException(404, "purchase not found")
    return serialize.purchase_view(purchase)


@router.get("/khata/{import_id}")
def get_khata(import_id: str):
    record = db().collection("khata_imports").document(import_id).get().to_dict()
    if not record:
        raise HTTPException(404, "khata import not found")
    return serialize.khata_view(record)


@router.get("/parties")
def parties():
    rows = [serialize.party_view(p) for p in _docs("parties", limit=100)]
    for row in rows:
        credit = row.get("credit") or {}
        credit["days_since_payment"] = days_since(credit.get("last_payment_date"))
    return {"parties": rows}


@router.get("/parties/{party_id}/ledger")
def party_ledger(party_id: str, limit: int = 50):
    """One consolidated history, even when profiles have been merged.

    Merging never rewrites a ledger row — an entry filed twenty years ago under
    a differently-spelled name stays filed there, which is what makes the merge
    reversible and the audit trail honest. The consolidation happens here, on
    read: the survivor's history is its own entries plus every merged profile's,
    in date order, each tagged with the name it was originally recorded under.
    """
    survivor = merge.resolve(party_id)
    sources = merge.merged_sources(survivor)

    entries = []
    for owner in [survivor, *sources]:
        name = (db().collection("parties").document(owner).get().to_dict()
                or {}).get("name")
        for entry in _docs("ledger", "date", limit=limit,
                           where=("party_id", "==", owner)):
            entries.append({**entry,
                            "recorded_under": name if owner != survivor else None,
                            "recorded_under_id": owner if owner != survivor else None})
    entries.sort(key=lambda e: str(e.get("date") or ""), reverse=True)

    view = serialize.party_view(
        db().collection("parties").document(survivor).get().to_dict())
    if view is not None:
        view["merged_from"] = [
            {"party_id": s,
             "name": (db().collection("parties").document(s).get().to_dict()
                      or {}).get("name")}
            for s in sources]
    kind = "supplier" if (view or {}).get("type") == "supplier" else "customer"
    stats, _ = books.ledger_rollup(kind, "all")
    mine = stats.get(survivor, {"out": 0, "back": 0, "first": None})
    return {"party": view,
            "requested_id": party_id,
            "redirected": survivor != party_id,
            "given": mine["out"], "received": mine["back"], "since": mine["first"],
            "entries": serialize.jsonable(entries[:limit])}


@router.get("/parties/duplicates")
def duplicate_parties():
    """Profiles that look like the same trader. A suggestion, never an action —
    two ledgers for one contractor hides half his exposure, so the threshold is
    deliberately loose and a human decides."""
    pairs = []
    for pair in merge.find_duplicates():
        a = db().collection("parties").document(pair.a).get().to_dict() or {}
        b = db().collection("parties").document(pair.b).get().to_dict() or {}
        pairs.append({
            "score": pair.score, "reason": pair.reason,
            "combined_outstanding": pair.combined_outstanding,
            "a": serialize.party_view(a), "b": serialize.party_view(b),
        })
    return {"pairs": pairs, "count": len(pairs)}


@router.get("/credit")
def credit_book(period: str = "month", limit_periods: int = 24):
    """The khata: who owes the shop, how old the debt is, and how the book moved.

    Customers only. A supplier the shop *owes* money to has no business in a list
    headed "who owes you" — it overstates what the shop is worth by twice the
    figure, once by adding it and once by not subtracting it.
    """
    stats, periods = books.ledger_rollup("customer", period)
    live = books.parties_of("customer")

    ageing = {"current": 0, "30": 0, "60": 0, "90+": 0}
    rows = []
    for party_id, party in live.items():
        credit = party.get("credit") or {}
        outstanding = int(credit.get("outstanding") or 0)
        limit = int(credit.get("limit") or 0)
        days = days_since(credit.get("last_payment_date"))
        mine = stats.get(party_id, {"out": 0, "back": 0, "entries": 0,
                                    "first": None, "last": None})
        bucket = books.bucket_for(days)
        ageing[bucket] += outstanding
        rows.append({
            "party_id": party_id, "name": party.get("name"),
            "name_ta": party.get("name_ta"), "phone": party.get("phone"),
            "is_company": party.get("is_company", False),
            "provisional": party.get("provisional", False),
            "outstanding": outstanding, "limit": limit,
            "exposure_pct": int(round(outstanding / limit * 100)) if limit else 0,
            "days_since_payment": days, "bucket": bucket,
            "given": mine["out"], "received": mine["back"],
            "entries": mine["entries"], "since": mine["first"],
            "last_activity": mine["last"],
        })
    rows.sort(key=lambda r: r["outstanding"], reverse=True)

    shown = periods[-limit_periods:] if limit_periods else periods
    return {
        "period": period,
        "parties": rows,
        "totals": {
            "outstanding": sum(r["outstanding"] for r in rows),
            "limit": sum(r["limit"] for r in rows),
            "customers": len(rows),
            "in_debt": sum(1 for r in rows if r["outstanding"] > 0),
            "over_limit": sum(1 for r in rows
                              if r["limit"] and r["outstanding"] > r["limit"]),
            "given_all_time": sum(r["given"] for r in rows),
            "received_all_time": sum(r["received"] for r in rows),
        },
        "ageing": ageing,
        "periods": [{"period": p["period"], "given": p["out"],
                     "received": p["back"], "net": p["net"],
                     "entries": p["entries"], "parties": p["parties"]}
                    for p in shown],
    }


@router.get("/purchases-book")
def purchases_book(period: str = "month", limit_periods: int = 24):
    """The other half of the book: what the shop bought, from whom, and when.

    Supplier balances come from the ledger; what was actually bought comes from
    the bills themselves, so the owner can ask "what have I bought from Annai
    this year, and at what rate" and get an answer off his own paperwork.
    """
    stats, periods = books.ledger_rollup("supplier", period)
    buying, per_sku = books.purchase_rollup()
    live = books.parties_of("supplier")
    catalog_rows = catalog.load()

    rows = []
    for party_id, party in live.items():
        credit = party.get("credit") or {}
        mine = stats.get(party_id, {"out": 0, "back": 0, "entries": 0,
                                    "first": None, "last": None})
        bought = buying.get(party_id, {"bills": 0, "value": 0, "items": 0,
                                       "last_bill": None, "skus": {}})
        top = sorted(bought["skus"].items(), key=lambda kv: kv[1]["value"],
                     reverse=True)[:3]
        rows.append({
            "party_id": party_id, "name": party.get("name"),
            "gstin": party.get("gstin"), "phone": party.get("phone"),
            "provisional": party.get("provisional", False),
            "payable": int(credit.get("outstanding") or 0),
            "billed": mine["out"], "paid": mine["back"],
            "bills": bought["bills"], "bill_value": bought["value"],
            "last_bill": bought["last_bill"] or mine["last"],
            "since": mine["first"],
            "top_items": [{
                "sku_id": sku,
                "name": (catalog.by_id(sku, catalog_rows) or {}).get("name", sku),
                "qty": round(v["qty"], 2), "value": v["value"],
            } for sku, v in top],
        })
    rows.sort(key=lambda r: (r["payable"], r["bill_value"]), reverse=True)

    items = sorted(
        ({"sku_id": sku,
          "name": (catalog.by_id(sku, catalog_rows) or {}).get("name", sku),
          "unit": (catalog.by_id(sku, catalog_rows) or {}).get("unit", ""),
          "qty": round(v["qty"], 2), "value": v["value"], "bills": v["bills"],
          "suppliers": len(v["suppliers"]), "last_rate": v["last_rate"],
          "last_date": v["last_date"]}
         for sku, v in per_sku.items()),
        key=lambda r: r["value"], reverse=True)

    shown = periods[-limit_periods:] if limit_periods else periods
    return {
        "period": period,
        "suppliers": rows,
        "items": items,
        "totals": {
            "payable": sum(r["payable"] for r in rows),
            "suppliers": len(rows),
            "owed_to": sum(1 for r in rows if r["payable"] > 0),
            "bills": sum(r["bills"] for r in rows),
            # Billed comes from the ledger, the same place the payable does, so
            # the two figures on this card can never disagree. Bill *value* is
            # what the photographed documents add up to and can legitimately be
            # lower — an older debt may predate any bill the shop scanned.
            "bought_all_time": sum(r["billed"] for r in rows),
            "billed_from_scans": sum(r["bill_value"] for r in rows),
            "paid_all_time": sum(r["paid"] for r in rows),
        },
        "periods": [{"period": p["period"], "bought": p["out"],
                     "paid": p["back"], "net": p["net"],
                     "entries": p["entries"], "suppliers": p["parties"]}
                    for p in shown],
    }


@router.get("/catalog/search")
def catalog_search(q: str = "", limit: int = 8):
    """Search-as-you-type for the counter screen.

    In-process over the cached catalogue, so it answers in microseconds and
    costs nothing — there is no model call and no database query behind this.
    """
    return {"query": q, "results": catalog.search(q, limit=limit)}


@router.get("/inventory")
def inventory():
    rows = catalog.load()
    out = []
    for item in _docs("inventory", limit=200):
        sku = catalog.by_id(item.get("sku_id"), rows) or {}
        out.append({**serialize.jsonable(item),
                    "name": sku.get("name") or item.get("sku_id"),
                    "unit": sku.get("unit"), "category": sku.get("category"),
                    "low": int(item.get("qty_on_hand") or 0)
                    <= int(item.get("reorder_level") or 0)})
    out.sort(key=lambda r: (not r["low"], r.get("name") or ""))
    return {"items": out}


@router.get("/dashboard")
def dashboard():
    """Today's trade, credit exposure, low stock, latest GST register — the
    single 'is my money safe?' read."""
    today = datetime.now(timezone.utc).date().isoformat()
    orders = _docs("orders", "created_at", limit=200)
    todays = [o for o in orders
              if str(o.get("created_at") or "")[:10] == today
              and o.get("status") in {"approved", "fulfilled"}]
    revenue = sum(int(o.get("total") or 0) for o in todays)

    parties = [serialize.party_view(p) for p in _docs("parties", limit=200)
               if p.get("type") in {"customer", "both"}]
    exposure = sum(int((p.get("credit") or {}).get("outstanding") or 0) for p in parties)
    limits = sum(int((p.get("credit") or {}).get("limit") or 0) for p in parties)
    risky = sorted(parties, key=lambda p: p.get("exposure_pct", 0), reverse=True)[:5]

    low_stock = [row for row in inventory()["items"] if row["low"]]
    registers = _docs("gst_registers", "period", limit=1)
    pending = len([o for o in orders if o.get("status") == "awaiting_approval"])
    queue = len([i for i in _docs("confirm_queue", limit=100)
                 if i.get("status") == "pending"])

    return {
        "today": {"date": today, "orders": len(todays), "revenue": revenue,
                  "credit": sum(int(o.get("total") or 0) for o in todays),
                  "cash": 0},
        "exposure": {"outstanding": exposure, "limit": limits,
                     "pct": int(round(exposure / limits * 100)) if limits else 0,
                     "top": risky},
        "low_stock": low_stock,
        "gst": serialize.jsonable(registers[0]) if registers else None,
        "pending_approvals": pending, "confirm_queue": queue,
    }


@router.get("/gst")
def gst_registers():
    return {"registers": serialize.jsonable(_docs("gst_registers", "period", limit=24))}


@router.get("/gst/{period}")
def gst_register(period: str):
    record = db().collection("gst_registers").document(period).get().to_dict()
    if not record:
        raise HTTPException(404, "no register for that period")
    view = serialize.jsonable(record)
    view["summary_pdf_path"] = storage.http_path(record.get("summary_pdf_url"))
    view["registers_csv_path"] = storage.http_path(record.get("registers_csv_url"))
    return view


@router.get("/media/{path:path}")
def media(path: str):
    """Serves source photos, voice notes and generated PDFs from whichever
    backing store is active, so the PWA never needs signing credentials."""
    blob = storage.get_bytes(path)
    if blob is None:
        raise HTTPException(404, "not found")
    return Response(blob, media_type=storage.content_type_of(path),
                    headers={"Cache-Control": "public, max-age=300"})
