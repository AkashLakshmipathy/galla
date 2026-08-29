"""Galla ingestion + API service (Cloud Run).

Endpoints:
  POST /ingest          - demo composer / WhatsApp webhook -> publish to Pub/Sub
  POST /pubsub/push     - Pub/Sub push subscription -> agent router
  POST /jobs/gst-compile- Cloud Scheduler -> GST compiler
  POST /api/...         - owner decisions (api/actions.py)
  GET  /api/...         - reads for the PWA (api/reads.py)

The event id is allocated *here*, before the work is queued, and returned to the
caller. That is what lets the PWA start polling a document that does not exist
yet — the same contract whether the chain runs behind Pub/Sub on Cloud Run or in
a local worker thread.
"""
from __future__ import annotations

import base64
import json
import logging
import os
import threading

from pathlib import Path

from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from agents import router as agent_router
from api import actions, demo, reads
from core import authz, ids
from core.config import LOCAL_STORE, PROJECT, PUBSUB_TOPIC, STORE

logging.basicConfig(level=logging.INFO)
log = logging.getLogger("galla")

app = FastAPI(title="Galla", version="1.0")
app.add_middleware(
    CORSMiddleware,
    allow_origins=json.loads(os.environ.get("CORS_ORIGINS", '["*"]')),
    allow_methods=["*"], allow_headers=["*"],
)
app.include_router(reads.router)
app.include_router(actions.router)
app.include_router(demo.router)

EVENT_TYPES = {"sale_order", "purchase_inv", "khata_page"}
_ID_FOR = {"sale_order": ("order_id", ids.order_id),
           "purchase_inv": ("purchase_id", ids.purchase_id),
           "khata_page": ("import_id", ids.import_id)}


def _publisher():
    from google.cloud import pubsub_v1
    client = pubsub_v1.PublisherClient()
    return client, client.topic_path(PROJECT, PUBSUB_TOPIC)


@app.get("/api/healthz")
@app.get("/healthz")
def healthz():
    """Both paths, because Google's frontend swallows a bare `/healthz` on Cloud
    Run — it returns its own 404 and the request never reaches the container.
    Anything under `/api/` routes through untouched."""
    return {"ok": True, "store": STORE}


def queue_event(event_type: str, payload: dict) -> dict:
    """Allocate the record id, then hand the work off asynchronously."""
    key, mint = _ID_FOR[event_type]
    payload = {**payload, "type": event_type}
    payload.setdefault(key, mint())

    if LOCAL_STORE:
        # No Pub/Sub without GCP: run the same chain in a worker thread so the
        # request returns immediately and the trace strip animates as it would.
        threading.Thread(target=_run_local, args=(event_type, payload),
                         daemon=True).start()
    else:
        client, topic = _publisher()
        client.publish(topic, json.dumps(payload, default=str).encode(),
                       type=event_type)
    return {"queued": True, "type": event_type, key: payload[key]}


def _run_local(event_type: str, payload: dict) -> None:
    try:
        agent_router.handle(event_type, payload)
    except Exception:                                     # noqa: BLE001
        log.exception("local chain failed for %s", event_type)


@app.post("/ingest")
async def ingest(req: Request):
    body = await req.json()
    event_type = body.get("type")
    if event_type not in EVENT_TYPES:
        raise HTTPException(400, f"type must be one of {sorted(EVENT_TYPES)}")
    return queue_event(event_type, body)


@app.post("/pubsub/push")
async def pubsub_push(req: Request):
    """Pub/Sub push target. Anyone who can reach this can inject a shop event,
    so it is the first thing `REQUIRE_OIDC` protects."""
    allowed, reason = authz.verify(req.headers.get("authorization"))
    if not allowed:
        log.warning("rejected pubsub push: %s", reason)
        raise HTTPException(403, "caller not verified")
    envelope = await req.json()
    message = envelope.get("message") or {}
    try:
        payload = json.loads(base64.b64decode(message["data"]).decode())
    except (KeyError, ValueError) as exc:
        log.error("undecodable pubsub message: %s", exc)
        return {"ok": True}          # ack malformed messages; retrying won't fix them
    event_type = (message.get("attributes") or {}).get("type") or payload.get("type")
    try:
        agent_router.handle(event_type, payload)
    except Exception:                                     # noqa: BLE001
        log.exception("agent chain failed; acking to avoid a redelivery storm")
    return {"ok": True}             # the trace records the failure for the owner


@app.post("/jobs/gst-compile")
async def gst_compile(req: Request):
    """Cloud Scheduler target. Nobody opens the app for this to happen."""
    allowed, reason = authz.verify(req.headers.get("authorization"))
    if not allowed:
        log.warning("rejected gst-compile: %s", reason)
        raise HTTPException(403, "caller not verified")
    raw = await req.body()
    body = json.loads(raw) if raw else {}
    return agent_router.handle("gst_compile", body)


# --------------------------------------------------------------- the PWA
# Mounted last so it never shadows an API route. Absent in local dev, where
# Vite serves the app on :5173 and proxies /api here.
_WEB = Path(__file__).resolve().parent / "web"
if _WEB.is_dir():
    app.mount("/assets", StaticFiles(directory=_WEB / "assets"), name="assets")

    @app.get("/{path:path}", include_in_schema=False)
    def spa(path: str):
        """Client-side routing: every unknown path returns the app shell."""
        candidate = (_WEB / path).resolve()
        if path and candidate.is_file() and _WEB in candidate.parents:
            return FileResponse(candidate)
        return FileResponse(_WEB / "index.html")
