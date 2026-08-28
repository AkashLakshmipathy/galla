"""Intake and SKU resolution — where trade slang becomes a priced line.

Confidence is the contract here: a line the agents were not sure about must
reach the confirm queue rather than the books, whatever else happens.
"""
from core import catalog
from core.config import CONFIDENCE_THRESHOLD
from core.trace import Trace


def test_tamil_and_english_slang_resolve_to_the_same_sku(seeded):
    for phrase in ["20 bag ramco 53", "ராம்கோ 20 மூட்டை", "ramco 53 twenty bags"]:
        assert catalog.match(phrase).sku_id == "cem-ramco-53", phrase


def test_invoice_shorthand_resolves(seeded):
    """Supplier bills print `G.I.PIPE 3/4" HVY 6MTR` and mean the GI pipe."""
    assert catalog.match('G.I.PIPE 3/4" HVY 6MTR TATA').sku_id == "plm-gi-075"
    assert catalog.match("CPVC PIPE 3/4 10FT ASTRAL").sku_id == "plm-cpvc-075"


def test_an_unknown_product_is_not_forced_onto_a_sku(seeded):
    """Better to say "I don't know" than to price the wrong thing."""
    match = catalog.match("titanium flux capacitor")
    assert match.sku_id is None
    assert match.confidence < CONFIDENCE_THRESHOLD


def test_product_numbers_are_not_mistaken_for_quantities(seeded):
    assert catalog.parse_qty('4 inch hinge 50 nos') == (50.0, "piece")
    assert catalog.parse_qty("20 bags ramco 53")[0] == 20.0
    assert catalog.parse_qty("ramco 53 twenty bags")[0] == 20.0
    # No stated quantity at all: assume one, do not invent a number.
    assert catalog.parse_qty("ramco cement")[0] == 1.0


def test_intake_prices_nothing_and_matches_everything(seeded):
    from agents import intake_agent
    trace = Trace("sale_order")
    order = intake_agent.run(
        {"party_id": "selvam", "source": "text",
         "transcript": "20 bags Ramco 53, ten 3/4 pipe and 50 hinges"}, trace)

    assert [line["sku_id"] for line in order["lines"]] == [
        "cem-ramco-53", "plm-cpvc-075", "hw-hinge-4"]
    assert all(line["rate"] == 0 for line in order["lines"]), \
        "intake reads; stock_pricing prices"
    assert order["status"] == "draft"


def test_low_confidence_lines_go_to_the_queue_not_the_order(seeded):
    from agents import intake_agent
    from core.firestore_client import db
    trace = Trace("sale_order")
    order = intake_agent.run(
        {"party_id": "selvam", "source": "text",
         "transcript": "one titanium flux capacitor"}, trace)

    queued = [s.to_dict() for s in db().collection("confirm_queue").stream()
              if s.to_dict()["source_id"] == order["order_id"]]
    assert len(queued) == 1
    assert queued[0]["status"] == "pending"
    assert queued[0]["alternatives"], "the owner needs something to choose from"


def test_order_lines_carry_only_schema_fields(seeded):
    """Derived values (needs_confirm, alternatives, display names) belong in the
    API response, not duplicated into Firestore where they can go stale."""
    from agents import intake_agent
    trace = Trace("sale_order")
    order = intake_agent.run({"party_id": "selvam", "source": "text",
                              "transcript": "20 bags Ramco 53"}, trace)
    assert set(order["lines"][0]) == {
        "sku_id", "name_raw", "qty", "unit", "rate", "amount", "gst_rate",
        "confidence", "substitute_of", "in_stock"}
