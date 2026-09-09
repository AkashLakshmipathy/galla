"""The whole sale chain, end to end, against the seeded demo shop.

These assert the numbers in docs/demo-script.md — if a change breaks the video,
it breaks here first.
"""
import json

from core.config import FIXTURES_DIR
from core.firestore_client import db


def _voice_note():
    return json.loads((FIXTURES_DIR / "voice_selvam.json").read_text("utf-8"))


def test_the_demo_voice_note_produces_the_scripted_verdict(seeded):
    from agents import router
    order = router.handle("sale_order", _voice_note())

    assert order["total"] == 24380
    verdict = order["credit_verdict"]
    assert verdict["decision"] == "part_payment"
    assert verdict["rule_fired"] == "NEAR_LIMIT"
    assert verdict["exposure_pct"] == 92
    assert verdict["suggested_advance"] == 15000
    assert "₹87,400" in verdict["reason"] and "₹95,000" in verdict["reason"]
    assert verdict["reason_ta"], "the owner reads Tamil first"


def test_the_chain_writes_a_readable_trace(seeded):
    from agents import router
    order = router.handle("sale_order", _voice_note())
    trace = db().collection("agent_traces").document(order["trace_id"]).get().to_dict()

    assert trace["status"] == "awaiting_owner"
    assert [step["agent"] for step in trace["steps"]] == [
        "intake", "stock_pricing", "credit_guardian", "quotation", "billing",
        "notifier"]
    assert all(step["output_summary"] for step in trace["steps"]), \
        "every step must say what it did, in one line"

    # Two steps are parked rather than run, and for different reasons: the
    # quotation because the owner has not decided, the invoice because a tax
    # invoice is only issued once the goods are actually sold.
    parked = {s["agent"]: s for s in trace["steps"] if s["status"] == "waiting"}
    assert set(parked) == {"quotation", "billing"}
    assert order["quotation_url"] is None
    assert order.get("invoice_no") is None, \
        "an invoice number burned before approval would leave a gap in the series"


def test_out_of_stock_line_offers_the_catalogue_substitute(seeded):
    from agents import router
    from core import stock
    order = router.handle("sale_order", _voice_note())

    suggestions = stock.suggestions_for(order)
    assert len(suggestions) == 1
    assert suggestions[0]["sku_id"] == "cem-ramco-53"
    assert suggestions[0]["substitute_sku_id"] == "cem-dalmia-53"
    assert suggestions[0]["qty_available"] == 6


def test_approving_generates_the_quotation_on_the_same_trace(seeded):
    from agents import router
    from core.transactions import approve_order
    order = router.handle("sale_order", _voice_note())
    approve_order(order["order_id"])
    order = db().collection("orders").document(order["order_id"]).get().to_dict()

    router.resume_after_decision(order, "approve")

    saved = db().collection("orders").document(order["order_id"]).get().to_dict()
    assert saved["quotation_url"].endswith(".pdf")
    trace = db().collection("agent_traces").document(order["trace_id"]).get().to_dict()
    assert trace["status"] == "complete"
    assert [s["agent"] for s in trace["steps"]].count("quotation") == 2, \
        "the parked step plus the real one"


def test_all_three_verdicts_are_reachable_from_seed_data(seeded):
    """A submission requirement: the video has to show green, amber and red."""
    from agents import router
    outcomes = {}
    for party in ("kumar", "selvam", "ravi"):
        payload = {**_voice_note(), "party_id": party}
        order = router.handle("sale_order", payload)
        outcomes[party] = order["credit_verdict"]["decision"]
    assert outcomes == {"kumar": "approve", "selvam": "part_payment",
                        "ravi": "escalate"}


def test_khata_page_sends_exactly_three_rows_to_the_confirm_queue(seeded):
    """The demo beat is "3 low-confidence rows to confirm queue". The
    auto-accepted count is not asserted: the page also carries names the shop
    has never traded with, and how many of those there are is a property of the
    fixture, not of the agent."""
    from agents import router
    record = router.handle("khata_page", {})
    assert record["needs_confirm_count"] == 3
    assert record["auto_accepted_count"] + record["needs_confirm_count"] \
        == len(record["rows"])
    assert all("bbox" in row and 0 <= row["bbox"]["y"] <= 1 for row in record["rows"]), \
        "tap-to-trace needs a normalised rectangle on every row"


def test_gst_compiler_reports_a_ca_ready_summary(seeded):
    from agents import router
    from core.transactions import approve_order, confirm_purchase
    order = router.handle("sale_order", _voice_note())
    approve_order(order["order_id"])
    purchase = router.handle("purchase_inv", {})
    confirm_purchase(purchase["purchase_id"])

    period = str(order["created_at"])[:7]
    register = router.handle("gst_compile", {"period": period})

    # Selvam is GST-registered, so his order is outward B2B. The split is the
    # point of the register: a CA files the two halves differently.
    assert register["outward"]["b2b"]["invoice_count"] == 1
    assert register["outward"]["b2b"]["taxable"] > 0
    assert register["outward"]["b2c"]["invoice_count"] == 0
    assert register["inward"]["invoice_count"] == 1
    assert register["summary_pdf_url"].endswith(".pdf")
    assert register["registers_csv_url"].endswith(".csv")
    assert "file" not in register["note"].lower() or "filed" not in register["note"].lower()
    saved = db().collection("gst_registers").document(period).get().to_dict()
    assert saved["status"] == "sent" and saved["sent_to_ca_at"] is not None


def test_the_gst_summary_waits_when_the_ca_has_no_address(seeded):
    """Both CA fields are optional, so a shop can reach month end with nowhere
    to send the summary. Marking it sent would tell the owner his accountant has
    the figures when nobody does — and he finds out the month the CA asks."""
    from agents import router
    db().collection("shop").document("main").update({"ca_contact": {"name": "CA"}})
    period = "2026-08"
    router.handle("gst_compile", {"period": period})

    saved = db().collection("gst_registers").document(period).get().to_dict()
    assert saved["status"] == "ready", "not 'sent' — nothing was sent"
    assert saved["ca_channel"] is None
    assert saved.get("sent_to_ca_at") is None


def test_an_email_only_ca_still_gets_the_summary(seeded):
    """Phone is optional; an email is a perfectly good address for a document
    a CA opens on a computer."""
    from agents import router
    db().collection("shop").document("main").update(
        {"ca_contact": {"name": "CA Suresh", "email": "suresh@ca.in"}})
    period = "2026-08"
    router.handle("gst_compile", {"period": period})

    saved = db().collection("gst_registers").document(period).get().to_dict()
    assert saved["ca_channel"] == "email" and saved["status"] == "sent"
