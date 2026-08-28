"""Routes a Pub/Sub event to the right agent chain, by event type.

sale_order    : intake -> stock_pricing -> credit_guardian -> quotation -> notifier
purchase_inv  : purchase_entry -> notifier
khata_page    : khata_digitizer -> notifier
gst_compile   : gst_compiler -> notifier   (fired by Cloud Scheduler, not Pub/Sub)

The sale chain deliberately stops short of generating a quotation when the
Credit Guardian did not approve: the quotation is parked as a `waiting` step and
the trace closes as `awaiting_owner`. That parked dot is the honest picture of
the system — the machine has done everything it may do without a human, and the
owner's tap in `resume_after_decision` finishes the chain on the same trace.
"""
from __future__ import annotations

import logging

from agents import (credit_guardian_agent, gst_compiler_agent, intake_agent,
                    khata_digitizer_agent, notifier_agent, purchase_entry_agent,
                    quotation_agent, stock_pricing_agent)
from core.firestore_client import db
from core.trace import Trace

log = logging.getLogger("galla.router")

CHAINS = {
    "sale_order": ["intake", "stock_pricing", "credit_guardian", "quotation", "notifier"],
    "purchase_inv": ["purchase_entry", "notifier"],
    "khata_page": ["khata_digitizer", "notifier"],
    "gst_compile": ["gst_compiler", "notifier"],
}


def _sale_order(payload: dict, trace: Trace) -> dict:
    order = intake_agent.run(payload, trace)
    order = stock_pricing_agent.run(order, trace)
    verdict = credit_guardian_agent.run(order["party_id"], order["total"], trace)
    order["credit_verdict"] = verdict
    db().collection("orders").document(order["order_id"]).update(
        {"credit_verdict": verdict, "status": "awaiting_approval"})
    order["status"] = "awaiting_approval"

    if verdict["decision"] == "approve":
        order = quotation_agent.run(order, trace)
    else:
        trace.waiting("quotation", "Held until you decide")

    notifier_agent.run({"kind": "approval_card", "order": order}, trace)
    trace.finish("awaiting_owner")
    return order


def resume_after_decision(order: dict, kind: str, advance: int = 0) -> dict:
    """Continue the order's original trace once the owner has decided.

    `kind` is "approve" (generate and send the quotation) or "part_payment"
    (hold it and ask for the advance).
    """
    trace = Trace.load(order.get("trace_id")) if order.get("trace_id") \
        else Trace("sale_order", {"type": "order", "id": order["order_id"]})
    try:
        if kind == "approve":
            order = quotation_agent.run(order, trace)
            notifier_agent.run({"kind": "quotation", "order": order}, trace)
        else:
            notifier_agent.run({"kind": "advance_request", "order": order,
                                "advance": advance}, trace)
        trace.finish("complete")
    except Exception as exc:                              # noqa: BLE001
        trace.finish("failed", error=str(exc))
        raise
    return order


def handle(event_type: str, payload: dict) -> dict:
    trace = Trace(event_type)
    try:
        if event_type == "sale_order":
            return _sale_order(payload, trace)
        if event_type == "purchase_inv":
            result = purchase_entry_agent.run(payload, trace)
            notifier_agent.run({"kind": "approval_card", "purchase": result}, trace)
            trace.finish("awaiting_owner")
            return result
        if event_type == "khata_page":
            result = khata_digitizer_agent.run(payload, trace)
            notifier_agent.run({"kind": "approval_card", "khata": result}, trace)
            trace.finish("awaiting_owner")
            return result
        if event_type == "gst_compile":
            result = gst_compiler_agent.run(payload, trace)
            notifier_agent.run({"kind": "gst_summary", "register": result}, trace)
            trace.finish("complete")
            return result
        raise ValueError(f"unknown event_type {event_type}")
    except Exception as exc:                              # noqa: BLE001
        log.exception("agent chain failed for %s", event_type)
        trace.finish("failed", error=str(exc))
        raise
