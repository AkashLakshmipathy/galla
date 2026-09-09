"""The Strands orchestrator — the specialists become tools it can call.

Every agent in the fleet is wrapped as a `@tool` here, and a Strands `Agent`
decides which to call and in what order. This is the agents-as-tools pattern:
the model sequences the work, the tools do it deterministically.

WHAT THE MODEL IS AND IS NOT ALLOWED TO DECIDE

It chooses the order of operations. It does not choose a credit verdict, a
price, a tax figure or a stock level — every one of those is computed inside a
tool by plain Python over the shop's own records, exactly as before. Wrapping
the fleet in an orchestrator moved the *sequencing* to the model and nothing
else. `rule_fired` is still stored on every verdict.

TOOLS TAKE IDs, NOT DOCUMENTS

Each tool takes an `order_id` and reads what it needs from Firestore, returning
a small summary. Passing whole order documents through the model would burn
context, invite it to paraphrase a number, and put the shop's ledger in a
prompt. The ids keep the conversation small and the data where it belongs.

THE TRACE RIDES IN A CONTEXTVAR

A Strands tool is called by the model with JSON arguments, so there is nowhere
to pass the trace object through. It is bound per-run in a context variable
instead, which is also correct under the thread `core.llm` runs calls on.
"""
from __future__ import annotations

import contextvars
import logging

from strands import Agent, tool

from agents import (billing_agent, credit_guardian_agent, intake_agent,
                    notifier_agent, quotation_agent, stock_pricing_agent)
from core import model as provider
from core.firestore_client import db
from core.money import inr

log = logging.getLogger("galla.orchestrator")

_TRACE: contextvars.ContextVar = contextvars.ContextVar("galla_trace")
_PAYLOAD: contextvars.ContextVar = contextvars.ContextVar("galla_payload")


def _order(order_id: str) -> dict:
    return db().collection("orders").document(order_id).get().to_dict() or {}


@tool
def read_incoming_order() -> dict:
    """Read the customer's message — voice, photo or text — into an order draft.

    Call this first, exactly once. Returns the order_id every other tool needs.
    """
    order = intake_agent.run(_PAYLOAD.get(), _TRACE.get())
    return {"order_id": order["order_id"], "party_id": order.get("party_id"),
            "lines": len(order.get("lines") or []),
            "unmatched": sum(1 for l in order.get("lines") or []
                             if not l.get("sku_id"))}


@tool
def price_and_check_stock(order_id: str) -> dict:
    """Apply this customer's tier prices, compute tax, and flag short stock."""
    order = stock_pricing_agent.run(_order(order_id), _TRACE.get())
    short = [l.get("name_raw") for l in order.get("lines") or []
             if not l.get("in_stock")]
    return {"total": order.get("total"), "subtotal": order.get("subtotal"),
            "short_on_stock": short}


@tool
def check_credit(order_id: str) -> dict:
    """Decide whether this order is safe on credit: approve, part_payment or
    escalate. The verdict comes from the shop's rules, not from you."""
    order = _order(order_id)
    verdict = credit_guardian_agent.run(order.get("party_id"),
                                        int(order.get("total") or 0), _TRACE.get())
    db().collection("orders").document(order_id).update(
        {"credit_verdict": verdict, "status": "awaiting_approval"})
    return {"decision": verdict["decision"], "rule_fired": verdict["rule_fired"],
            "exposure_pct": verdict["exposure_pct"],
            "suggested_advance": verdict["suggested_advance"]}


@tool
def draft_quotation(order_id: str) -> dict:
    """Generate the GST quotation PDF. Only for an order credit approved."""
    order = quotation_agent.run(_order(order_id), _TRACE.get())
    return {"quotation_url": order.get("quotation_url")}


@tool
def notify_owner(order_id: str) -> dict:
    """Send the owner the approval card for this order."""
    result = notifier_agent.run(
        {"kind": "approval_card", "order": _order(order_id)}, _TRACE.get())
    return {"sent": result.get("sent"), "audience": result.get("audience")}


TOOLS = [read_incoming_order, price_and_check_stock, check_credit,
         draft_quotation, notify_owner]

SYSTEM_PROMPT = """You run the back office of an Indian hardware shop. A message
has arrived from a customer and you turn it into an order the owner can act on.

Work in this order:
1. read_incoming_order — always first, exactly once. Keep the order_id.
2. price_and_check_stock — always.
3. check_credit — always, unless nothing in the order matched a product.
4. draft_quotation — ONLY if check_credit returned "approve". If it returned
   part_payment or escalate, skip it: the owner decides, and the quotation is
   generated after he does.
5. notify_owner — always last.

You never decide money. Prices, tax, stock and the credit verdict are computed
by the tools from the shop's own records; your job is to call them in order and
stop. Never issue a tax invoice — that happens only after the owner approves.

When you are done, reply with one short sentence for the owner."""


def run(payload: dict, trace) -> dict:
    """Orchestrate one sale. Returns the order document.

    Falls back to the deterministic chain if the model is unavailable or the
    orchestration does not produce a priced order — hard rule 6. The fallback is
    not a lesser path: it is the same tools in the same order, minus the model
    choosing that order.
    """
    from agents.router import sale_order_chain

    _TRACE.set(trace)
    _PAYLOAD.set(payload)

    llm = provider.model()
    if llm is None:
        return sale_order_chain(payload, trace)

    try:
        agent = Agent(model=llm, system_prompt=SYSTEM_PROMPT, tools=TOOLS,
                      name="galla_orchestrator", callback_handler=None)
        agent(f"A customer message has arrived. Payload keys: "
              f"{sorted(payload.keys())}. Process it.")
    except Exception as exc:                              # noqa: BLE001
        log.warning("orchestrator failed, using the deterministic chain: %s", exc)
        return sale_order_chain(payload, trace)

    order_id = payload.get("order_id")
    order = _order(order_id) if order_id else {}
    if not order or not order.get("total"):
        log.warning("orchestrator produced no priced order; falling back")
        return sale_order_chain(payload, trace)

    _park_what_the_owner_gates(order, trace)
    trace.finish("awaiting_owner")
    return order


def _park_what_the_owner_gates(order: dict, trace) -> None:
    """Draw the steps the orchestrator correctly declined to run.

    When credit is not approved the orchestrator skips the quotation, which is
    right — but skipping it silently leaves a gap where the trace strip should
    show a paused dot. That parked dot is the honest picture of the system: the
    machine has done everything it may do without a human, and it is waiting.
    An absent step reads as one that was never considered.
    """
    ran = {step.get("agent") for step in trace.steps}
    approved = ((order.get("credit_verdict") or {}).get("decision") == "approve")
    if "quotation" not in ran and not approved:
        trace.waiting("quotation", "Held until you decide")
    if "billing" not in ran:
        trace.waiting("billing", "Invoice on approval")
