"""Demo composer — the presenter's side of the counter.

Feature F11: a discreet mode that lets whoever is holding the phone send a
message *as the contractor*, so a single device can show both halves of the
story on camera. Every route here is inert unless `DEMO_MODE` is on, and the UI
never renders the chip outside demo mode.

The scenarios feed the same `/ingest` path as a real WhatsApp webhook would —
nothing here shortcuts the agent chain, which is the only way the demo proves
anything.
"""
from __future__ import annotations

import json

from fastapi import APIRouter, HTTPException

from core.config import DEMO_MODE, FIXTURES_DIR, LOCAL_STORE
from core.firestore_client import db

router = APIRouter(prefix="/api/demo")

SCENARIOS = {
    "voice_selvam": {
        "label": "Send voice note as Selvam",
        "sub": "Replays the WhatsApp order",
        "event": "sale_order", "fixture": "voice_selvam.json",
    },
    "voice_kumar": {
        "label": "Send voice note as Kumar",
        "sub": "The approved-on-the-spot case",
        "event": "sale_order", "fixture": "voice_selvam.json",
        "overrides": {"party_id": "kumar"},
    },
    "voice_ravi": {
        "label": "Send voice note as Ravi",
        "sub": "The escalation case",
        "event": "sale_order", "fixture": "voice_selvam.json",
        "overrides": {"party_id": "ravi"},
    },
    "supplier_bill": {
        "label": "Send a bill photo",
        "sub": "Printed invoice → stock & payable entry",
        "event": "purchase_inv", "fixture": None,
    },
    "khata_page": {
        "label": "Send a khata page",
        "sub": "Handwritten ledger → digital entries",
        "event": "khata_page", "fixture": None,
        "overrides": {"page_no": 12},
    },
}


def _guard() -> None:
    if not DEMO_MODE:
        raise HTTPException(403, "demo mode is off")


@router.get("/scenarios")
def scenarios():
    _guard()
    return {"scenarios": [{"key": key, **{k: v for k, v in value.items()
                                          if k in {"label", "sub", "event"}}}
                          for key, value in SCENARIOS.items()],
            "demo_mode": DEMO_MODE, "local_store": LOCAL_STORE}


@router.post("/send/{key}")
def send(key: str):
    """Queue a scenario through the real ingestion path."""
    _guard()
    scenario = SCENARIOS.get(key)
    if not scenario:
        raise HTTPException(404, f"unknown scenario {key}")

    payload: dict = {}
    if scenario.get("fixture"):
        path = FIXTURES_DIR / scenario["fixture"]
        if path.exists():
            payload = json.loads(path.read_text("utf-8"))
    payload.update(scenario.get("overrides") or {})

    from main import queue_event
    return queue_event(scenario["event"], payload)


@router.post("/reset")
def reset():
    """Back to the start of the story: reseed and clear everything the agents
    wrote, so the demo can be run twice in a row on camera."""
    _guard()
    client = db()
    # `inventory` is wiped too: a corrected SKU could have created a row the
    # seed does not know about, and a stale one would quietly skew stock counts.
    for collection in ("orders", "purchases", "khata_imports", "confirm_queue",
                       "agent_traces", "gst_registers", "counters", "ledger",
                       "inventory"):
        for snap in client.collection(collection).stream():
            snap.reference.delete()
    from seed.seed_data import main as reseed
    reseed()
    from core import catalog
    catalog.invalidate()
    return {"reset": True}
