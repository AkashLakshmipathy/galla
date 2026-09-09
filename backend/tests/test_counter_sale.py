"""The counter sale: search, bill, share — P0 #4.2 end to end.

These go through the API the way the counter screen does, because the point of
the flow is that it reuses the order pipeline rather than forking it.
"""
import pytest

from core.firestore_client import db


def _sale(client, **overrides):
    body = {"lines": [{"sku_id": "cem-ramco-53", "qty": 2}],
            "price_includes_tax": True, "paid": True}
    body.update(overrides)
    return client.post("/api/counter-sale", json=body)


def test_search_finds_a_sku_by_its_trade_alias(client, seeded):
    results = client.get("/api/catalog/search", params={"q": "ramco"}).json()
    assert results["results"], "typing a brand name must find the cement"
    assert results["results"][0]["sku_id"] == "cem-ramco-53"
    assert "price_tiers" in results["results"][0]


def test_search_on_an_empty_box_returns_nothing(client, seeded):
    assert client.get("/api/catalog/search", params={"q": ""}).json()["results"] == []


def test_counter_sale_bills_and_returns_a_shareable_invoice(client, seeded):
    body = _sale(client).json()
    assert body["invoice_no"].startswith("SBH/")
    assert body["invoice_url"].startswith("/api/media/")
    assert body["order"]["total"] > 0
    # The link the owner taps Share on has to actually resolve.
    assert client.get(body["invoice_url"]).status_code == 200


def test_a_paid_counter_sale_leaves_the_walk_in_balance_at_zero(client, seeded):
    before = (db().collection("parties").document("walk_in").get().to_dict()
              or {}).get("credit", {}).get("outstanding", 0)
    _sale(client)
    after = (db().collection("parties").document("walk_in").get().to_dict()
             or {}).get("credit", {}).get("outstanding", 0)
    assert after == before, "cash at the counter must not become a receivable"


def test_a_paid_counter_sale_still_writes_both_ledger_entries(client, seeded):
    """Netting to nothing would lose the sale from the outward register."""
    order_id = _sale(client).json()["order"]["order_id"]
    entries = [e.to_dict() for e in db().collection("ledger").stream()
               if (e.to_dict().get("ref") or {}).get("id") == order_id]
    kinds = {e["type"]: e for e in entries}
    assert set(kinds) == {"sale_credit", "payment"}
    assert kinds["sale_credit"]["amount"] == kinds["payment"]["amount"]
    assert kinds["sale_credit"]["direction"] == "debit"
    assert kinds["payment"]["direction"] == "credit"


def test_counter_sale_decrements_stock(client, seeded):
    before = db().collection("inventory").document("cem-ramco-53").get().to_dict()
    _sale(client, lines=[{"sku_id": "cem-ramco-53", "qty": 2}])
    after = db().collection("inventory").document("cem-ramco-53").get().to_dict()
    assert after["qty_on_hand"] == before["qty_on_hand"] - 2


def test_inclusive_pricing_bills_the_price_the_owner_said(client, seeded):
    """"bag 445, with tax" — two bags is 890 payable, not 890 plus tax."""
    body = _sale(client, lines=[{"sku_id": "cem-ramco-53", "qty": 2,
                                 "unit_price": 445}],
                 price_includes_tax=True).json()
    assert body["order"]["total"] == 890


def test_exclusive_pricing_adds_tax_on_top(client, seeded):
    body = _sale(client, lines=[{"sku_id": "cem-ramco-53", "qty": 1,
                                 "unit_price": 415}],
                 price_includes_tax=False).json()
    assert body["order"]["total"] == 531        # 415 + 28%, rounded to the rupee


def test_invoice_numbers_are_consecutive_and_never_reused(client, seeded):
    numbers = [_sale(client).json()["invoice_no"] for _ in range(3)]
    assert len(set(numbers)) == 3
    tails = [int(n.split("/")[-1]) for n in numbers]
    assert tails == sorted(tails) and tails[-1] - tails[0] == 2


def test_reissuing_an_invoice_reuses_its_number(client, seeded):
    first = _sale(client).json()
    again = client.post(f"/api/orders/{first['order']['order_id']}/invoice").json()
    assert again["invoice_no"] == first["invoice_no"]


def test_an_unknown_sku_is_refused_before_anything_is_written(client, seeded):
    assert _sale(client, lines=[{"sku_id": "nope", "qty": 1}]).status_code == 400


def test_an_empty_sale_is_refused(client, seeded):
    assert _sale(client, lines=[]).status_code == 400


def test_a_counter_sale_reaches_the_gst_outward_register_as_b2c(client, seeded):
    """A walk-in is unregistered, so the sale is B2C — and it must carry its
    taxable value, not just bump the invoice count. A sale contributing a zero
    to the taxable column is the kind of wrong number only a CA finds."""
    from datetime import datetime, timezone

    from agents import router

    _sale(client, lines=[{"sku_id": "cem-ramco-53", "qty": 2}])
    period = datetime.now(timezone.utc).strftime("%Y-%m")
    register = router.handle("gst_compile", {"period": period})

    b2c = register["outward"]["b2c"]
    assert b2c["invoice_count"] == 1
    assert b2c["taxable"] > 0, "the sale must carry its taxable value"
    assert b2c["cgst"] > 0 and b2c["sgst"] > 0
    assert register["outward"]["b2b"]["invoice_count"] == 0


def test_a_finished_counter_sale_does_not_look_like_it_is_still_running(client, seeded):
    """The counter feed decides a card is still working by whether it can find
    a trace. A sale saved without `trace_id` shows a spinner for ever — it is
    finished, the money has moved, and the screen says otherwise."""
    client.post("/api/counter-sale", json={
        "lines": [{"sku_id": "cem-ramco-53", "qty": 2}],
        "price_includes_tax": True, "paid": True})

    order = next(i["data"] for i in client.get("/api/counter").json()["items"]
                 if i["kind"] == "order")
    assert order["trace_id"], "the order must carry the trace the feed follows"

    trace = client.get(f"/api/traces/{order['trace_id']}").json()
    assert trace["status"] == "complete"
    assert [s["agent"] for s in trace["steps"]] == ["billing"]
    assert trace["steps"][0]["output_summary"], "the step must say what it did"


def test_the_counter_chain_promises_only_the_steps_it_runs(client, seeded):
    """An idle dot on the strip is a step the owner is still waiting for."""
    chain = client.get("/api/fleet").json()["chains"]["counter_sale"]
    client.post("/api/counter-sale", json={
        "lines": [{"sku_id": "cem-ramco-53", "qty": 1}],
        "price_includes_tax": True, "paid": True})
    order = next(i["data"] for i in client.get("/api/counter").json()["items"]
                 if i["kind"] == "order")
    ran = [s["agent"] for s in
           client.get(f"/api/traces/{order['trace_id']}").json()["steps"]]
    assert chain == ran


def test_an_inclusive_line_shows_what_the_customer_pays(client, seeded):
    """`amount` is the taxable value the GST register wants. The row on screen
    reads "2 bag x Rs 445", so it needs the figure that actually follows from
    that — otherwise it shows Rs 695 under a line that multiplies to Rs 890."""
    body = _sale(client, lines=[{"sku_id": "cem-ramco-53", "qty": 2,
                                 "unit_price": 445}],
                 price_includes_tax=True).json()
    line = body["order"]["lines"][0]
    assert line["line_total"] == 890
    assert line["amount"] == 695          # taxable, for the register
    assert body["order"]["total"] == 890


def test_reprinting_appends_to_the_orders_own_trace(client, seeded):
    first = _sale(client).json()
    order_id = first["order"]["order_id"]
    again = client.post(f"/api/orders/{order_id}/invoice").json()

    assert again["trace_id"] == first["order"]["trace_id"], \
        "a reprint belongs to this order's story, not an orphan trace"
    steps = client.get(f"/api/traces/{again['trace_id']}").json()["steps"]
    assert [s["agent"] for s in steps] == ["billing", "billing"]
    assert "Duplicate" in steps[1]["output_summary"]


def test_a_single_letter_is_not_a_search(client, seeded):
    """One character matches nearly the whole catalogue through the literal
    pass, and a list of everything is not a result — at one letter the owner
    has not told us anything yet."""
    assert client.get("/api/catalog/search", params={"q": "a"}).json()["results"] == []
    assert client.get("/api/catalog/search", params={"q": "ra"}).json()["results"]


def test_a_single_digit_still_searches(client, seeded):
    """"3" is a real query in a shop that stocks 3/4 pipe and 53-grade cement."""
    assert client.get("/api/catalog/search", params={"q": "3"}).json()["results"]


def test_the_cash_bucket_is_not_a_debtor(client, seeded):
    """Walk-in is where cash sales are booked, so it is square by construction —
    a debit and a receipt in the same transaction. A name sitting at zero in a
    list headed "who owes you" is someone the owner reads and dismisses every
    time he opens the book."""
    _sale(client)  # walk-in now has history, still owes nothing
    names = [p["name"] for p in client.get("/api/credit").json()["parties"]]
    assert "Walk-in customer" not in names
    assert "Selvam" in names, "real debtors must still be listed"
