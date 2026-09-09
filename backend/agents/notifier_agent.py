"""Notifier — the last mile out of the shop.

Everything Galla produces has to reach a human on WhatsApp: the approval card to
the owner, the quotation to the contractor, the monthly summary to the CA.

The dispatch itself is deliberately thin. In this build it logs the message and
stamps the delivery status on the document that owns it (`gst_registers` has
`sent_to_ca_at` and `ca_channel` for exactly this) — no new collection, and no
half-built WhatsApp Business integration to break on camera. Swapping the body
of `_dispatch` for a real Business API call is the only change production needs.
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone

from core.config import DEMO_MODE
from core.firestore_client import db
from core.money import inr

log = logging.getLogger("galla.notifier")


def _dispatch(channel: str, to: str, message: str) -> bool:
    log.info("notify[%s] -> %s: %s", channel, to, message)
    return True                      # DEMO_MODE: delivery is logged, not sent


def _approval_card(payload: dict) -> str:
    """One card, whichever kind of work is waiting on the owner."""
    if payload.get("purchase"):
        purchase = payload["purchase"]
        return (f"Invoice {purchase.get('invoice_no')} read — "
                f"{inr((purchase.get('totals') or {}).get('total', 0))}, "
                f"{len(purchase.get('lines') or [])} lines to review")
    if payload.get("khata"):
        record = payload["khata"]
        # A khata page rarely carries a number, and "Khata page None read" is
        # what the owner saw when it did not. Name the customer instead — that
        # is what he is looking for anyway.
        whose = record.get("party_name_raw") or record.get("page_no")
        return (f"{whose or 'Khata page'} read — "
                f"{record.get('auto_accepted_count', 0)} clear, "
                f"{record.get('needs_confirm_count', 0)} to confirm")
    order = payload.get("order") or {}
    verdict = order.get("credit_verdict") or {}
    return (f"Order {order.get('order_id')} · {inr(order.get('total', 0))} · "
            f"{verdict.get('decision', 'pending')} — {verdict.get('reason', '')}")


def _quotation(payload: dict) -> str:
    order = payload.get("order") or {}
    return (f"Quotation for {inr(order.get('total', 0))} sent to "
            f"{order.get('party_id')} · {order.get('quotation_url')}")


def _advance_request(payload: dict) -> str:
    order = payload.get("order") or {}
    return (f"Advance of {inr(payload.get('advance', 0))} requested from "
            f"{order.get('party_id')} — quotation held")


def _gst_summary(payload: dict) -> str:
    register = payload.get("register") or {}
    period = register.get("period")
    ref = db().collection("gst_registers").document(period)
    shop = db().collection("shop").document("main").get().to_dict() or {}
    ca = shop.get("ca_contact") or {}
    channel = "whatsapp" if ca.get("phone") else "email"
    ref.update({"sent_to_ca_at": datetime.now(timezone.utc),
                "ca_channel": channel, "status": "sent"})
    return (f"CA-ready summary for {period} sent to {ca.get('name', 'the CA')} "
            f"on {channel} · net {inr(register.get('net_liability', 0))}")


_KINDS = {
    "approval_card": ("owner", _approval_card),
    "quotation": ("customer", _quotation),
    "advance_request": ("customer", _advance_request),
    "gst_summary": ("ca", _gst_summary),
}


def run(payload: dict, trace) -> dict:
    kind = payload.get("kind", "approval_card")
    with trace.step("notifier") as s:
        audience, render = _KINDS.get(kind, _KINDS["approval_card"])
        message = render(payload)
        sent = _dispatch("whatsapp", audience, message)
        s.summary = (f"Sent to {audience}: {message}"[:180] if sent
                     else f"Delivery to {audience} failed")
        s.status = "done" if sent else "error"
    return {"kind": kind, "audience": audience, "message": message, "sent": sent,
            "demo_mode": DEMO_MODE}
