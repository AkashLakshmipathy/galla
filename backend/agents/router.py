"""Routes a Pub/Sub event to the right agent chain, by event type.

sale_order    : intake -> stock_pricing -> credit_guardian -> quotation -> notifier
counter_sale  : billing                    (walk-in; no credit decision to make)
purchase_inv  : purchase_entry -> notifier
khata_page    : khata_digitizer -> notifier
gst_compile   : gst_compiler -> notifier   (fired by Cloud Scheduler, not Pub/Sub)

Approving a sale adds one step after the money has moved: `billing`, which mints
the invoice number and renders the tax invoice. A quotation is what the shop
offers; a tax invoice is what it issues once the goods are gone — so the invoice
is deliberately not generated until the owner has approved.

The sale chain deliberately stops short of generating a quotation when the
Credit Guardian did not approve: the quotation is parked as a `waiting` step and
the trace closes as `awaiting_owner`. That parked dot is the honest picture of
the system — the machine has done everything it may do without a human, and the
owner's tap in `resume_after_decision` finishes the chain on the same trace.
"""
from __future__ import annotations

import logging

from agents import (billing_agent, credit_guardian_agent, gst_compiler_agent,
                    intake_agent, khata_digitizer_agent, notifier_agent,
                    purchase_entry_agent, quotation_agent, stock_pricing_agent)
from core.firestore_client import db
from core.trace import Trace

log = logging.getLogger("galla.router")

CHAINS = {
    "sale_order": ["intake", "stock_pricing", "credit_guardian", "quotation",
                   "billing", "notifier"],
    # No notifier on a counter sale: the customer is standing at the counter and
    # the owner hands him the bill with the device's own share sheet. Listing a
    # step that never runs would draw an idle dot on the strip for ever.
    "counter_sale": ["billing"],
    "purchase_inv": ["purchase_entry", "notifier"],
    "khata_page": ["khata_digitizer", "notifier"],
    "gst_compile": ["gst_compiler", "notifier"],
}


def _sale_order(payload: dict, trace: Trace) -> dict:
    order = intake_agent.run(payload, trace)
    order = stock_pricing_agent.run(order, trace)

    # If nothing in the message resolved to a product, there is no order here to
    # judge. Running the Credit Guardian anyway would produce a confident-looking
    # verdict on a zero-rupee order — the machine claiming a decision it has no
    # basis for, which is worse than admitting it could not read the message.
    if not any(line.get("sku_id") and line.get("amount") for line in order["lines"]):
        db().collection("orders").document(order["order_id"]).update(
            {"status": "unreadable"})
        order["status"] = "unreadable"
        trace.waiting("credit_guardian", "Nothing to price — waiting for you")
        notifier_agent.run({"kind": "approval_card", "order": order}, trace)
        trace.finish("awaiting_owner")
        return order

    verdict = credit_guardian_agent.run(order["party_id"], order["total"], trace)
    order["credit_verdict"] = verdict
    db().collection("orders").document(order["order_id"]).update(
        {"credit_verdict": verdict, "status": "awaiting_approval"})
    order["status"] = "awaiting_approval"

    if verdict["decision"] == "approve":
        order = quotation_agent.run(order, trace)
    else:
        trace.waiting("quotation", "Held until you decide")

    # The invoice is never minted before the owner taps approve — a tax invoice
    # is issued once the goods are gone, and a number burned on an order that is
    # then declined leaves a gap in the series. Park it so the strip says so
    # rather than leaving a dot that looks like it failed.
    trace.waiting("billing", "Invoice on approval")

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
            order = billing_agent.run(order, trace)
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


def fleet() -> list[dict]:
    """The declared agent fleet, for the README/architecture diagram and the
    `/api/fleet` endpoint the UI uses to label the trace strip.

    Lives beside CHAINS because they describe the same thing from two angles:
    who the agents are, and the order they run in."""
    return [
        {"agent": "intake", "label": "Intake",
         "does": "Tamil voice / handwriting → line items + SKU match"},
        {"agent": "stock_pricing", "label": "Stock & Pricing",
         "does": "inventory check, tier pricing, substitute suggestion"},
        {"agent": "credit_guardian", "label": "Credit Guardian",
         "does": "deterministic credit verdict, the model phrases it"},
        {"agent": "quotation", "label": "Quotation",
         "does": "GST quotation PDF with HSN + CGST/SGST split"},
        {"agent": "billing", "label": "Billing",
         "does": "invoice number, tax invoice PDF, share link — no model call"},
        {"agent": "purchase_entry", "label": "Purchase Entry",
         "does": "supplier invoice OCR → stock delta + payable"},
        {"agent": "khata_digitizer", "label": "Khata Digitizer",
         "does": "handwritten ledger page → rows with source bboxes"},
        {"agent": "gst_compiler", "label": "GST Compiler",
         "does": "monthly CA-ready summary, fired by Cloud Scheduler"},
        {"agent": "notifier", "label": "Notifier",
         "does": "approval cards, digests, CA dispatch"},
    ]
