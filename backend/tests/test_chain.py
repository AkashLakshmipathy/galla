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
        "intake", "stock_pricing", "credit_guardian", "quotation", "notifier"]
    assert all(step["output_summary"] for step in trace["steps"]), \
        "every step must say what it did, in one line"
    # The quotation is parked, not generated, because the owner has not decided.
    quotation = next(s for s in trace["steps"] if s["agent"] == "quotation")
    assert quotation["status"] == "waiting"
    assert order["quotation_url"] is None


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


def test_khata_page_splits_nine_clear_three_to_confirm(seeded):
    from agents import router
    record = router.handle("khata_page", {})
    assert (record["auto_accepted_count"], record["needs_confirm_count"]) == (9, 3)
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

    assert register["outward"]["b2c"]["invoice_count"] == 1
    assert register["inward"]["invoice_count"] == 1
    assert register["summary_pdf_url"].endswith(".pdf")
    assert register["registers_csv_url"].endswith(".csv")
    assert "file" not in register["note"].lower() or "filed" not in register["note"].lower()
    saved = db().collection("gst_registers").document(period).get().to_dict()
    assert saved["status"] == "sent" and saved["sent_to_ca_at"] is not None
