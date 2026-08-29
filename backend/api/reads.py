"""Read endpoints for the PWA. No writes here, ever."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, HTTPException, Response
from google.cloud.firestore_v1.base_query import FieldFilter

from core import merge, serialize, storage
from core.adk import fleet
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
    orders = [serialize.order_view(o) for o in
              _docs("orders", "created_at", limit=50)
              if o.get("status") == "awaiting_approval"]
    queue = [serialize.jsonable(i) for i in
             _docs("confirm_queue", "created_at", desc=False, limit=50)
             if i.get("status") == "pending"]
    return {"orders": orders, "confirm_queue": queue,
            "badge": len(orders) + len(queue)}


@router.get("/confirm-queue")
def confirm_queue():
    items = [serialize.jsonable(i) for i in
             _docs("confirm_queue", "created_at", desc=False, limit=100)
             if i.get("status") == "pending"]
    for item in items:
        item["source_image_path"] = storage.http_path(item.get("source_image_url"))
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
    return {"party": view,
            "requested_id": party_id,
            "redirected": survivor != party_id,
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


@router.get("/inventory")
def inventory():
    from core import catalog
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
