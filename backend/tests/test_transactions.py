"""Transaction boundaries from docs/firestore-schema.md.

The property under test throughout is *idempotence under retry*: Pub/Sub
delivers at least once, and a redelivered message must not double a balance or
double stock. Each of these would be a silent money bug in production.
"""
from core.firestore_client import db
from core.trace import Trace
from core.transactions import (approve_order, commit_khata_import,
                               confirm_purchase, record_owner_action)


def _order(seeded, party_id="selvam"):
    from agents import router
    payload = {"party_id": party_id, "source": "text",
               "transcript": "20 bags ramco 53"}
    return router.handle("sale_order", payload)


def test_approving_writes_one_ledger_entry_and_moves_the_balance(seeded):
    order = _order(seeded)
    before = seeded.collection("parties").document("selvam").get() \
        .to_dict()["credit"]["outstanding"]

    result = approve_order(order["order_id"])

    party = seeded.collection("parties").document("selvam").get().to_dict()
    assert party["credit"]["outstanding"] == before + order["total"]
    entry = seeded.collection("ledger").document(result["entry_id"]).get().to_dict()
    assert entry["type"] == "sale_credit"
    assert entry["direction"] == "debit"
    assert entry["balance_after"] == party["credit"]["outstanding"]
    assert entry["ref"] == {"type": "order", "id": order["order_id"]}


def test_approving_twice_does_not_double_the_debt(seeded):
    order = _order(seeded)
    approve_order(order["order_id"])
    after_first = seeded.collection("parties").document("selvam").get() \
        .to_dict()["credit"]["outstanding"]

    second = approve_order(order["order_id"])

    assert second["already"] is True
    party = seeded.collection("parties").document("selvam").get().to_dict()
    assert party["credit"]["outstanding"] == after_first
    entries = [s.to_dict() for s in seeded.collection("ledger").stream()
               if s.to_dict()["ref"].get("id") == order["order_id"]]
    assert len(entries) == 1


def test_asking_for_an_advance_moves_no_money(seeded):
    """Nothing has been sold yet, so nothing may touch the ledger."""
    order = _order(seeded)
    before = seeded.collection("parties").document("selvam").get() \
        .to_dict()["credit"]["outstanding"]
    ledger_before = len(list(seeded.collection("ledger").stream()))

    record_owner_action(order["order_id"], "part_payment", advance=15000)

    assert seeded.collection("parties").document("selvam").get() \
        .to_dict()["credit"]["outstanding"] == before
    assert len(list(seeded.collection("ledger").stream())) == ledger_before


def test_confirming_a_purchase_increments_stock_once(seeded):
    from agents import router
    purchase = router.handle("purchase_inv", {})
    before = seeded.collection("inventory").document("plm-gi-075").get() \
        .to_dict()["qty_on_hand"]

    first = confirm_purchase(purchase["purchase_id"])
    second = confirm_purchase(purchase["purchase_id"])

    assert second["already"] is True
    after = seeded.collection("inventory").document("plm-gi-075").get() \
        .to_dict()["qty_on_hand"]
    assert after == before + 25
    assert any(d["sku_id"] == "plm-gi-075" and d["before"] == before
               and d["after"] == after for d in first["stock_delta"])


def test_confirming_a_purchase_records_the_supplier_payable(seeded):
    from agents import router
    purchase = router.handle("purchase_inv", {})
    result = confirm_purchase(purchase["purchase_id"])
    entry = seeded.collection("ledger").document(result["payable_ledger_id"]) \
        .get().to_dict()
    assert entry["type"] == "purchase_credit"
    assert entry["direction"] == "credit"
    assert entry["party_id"] == "sbh_agencies"


def test_khata_posts_only_confirmed_rows(seeded):
    from agents import router
    record = router.handle("khata_page", {})
    pending = [r for r in record["rows"] if r["status"] == "needs_confirm"]
    assert pending, "the fixture must contain rows below the threshold"

    result = commit_khata_import(record["import_id"])

    posted = [s.to_dict() for s in seeded.collection("ledger").stream()
              if s.to_dict()["ref"].get("type") == "khata_import"]
    assert result["posted"] == len(posted) == len(record["rows"]) - len(pending)


def test_khata_payment_rows_reduce_the_balance(seeded):
    from agents import router
    record = router.handle("khata_page", {})
    before = seeded.collection("parties").document("palani").get() \
        .to_dict()["credit"]["outstanding"]

    commit_khata_import(record["import_id"])

    rows = [r for r in record["rows"]
            if r["party_id"] == "palani" and r["status"] == "auto_accepted"]
    expected = before + sum(
        -r["amount"] if r["entry_type"] == "payment_received" else r["amount"]
        for r in rows)
    after = seeded.collection("parties").document("palani").get() \
        .to_dict()["credit"]["outstanding"]
    assert after == expected


def test_committing_a_khata_import_twice_posts_nothing_new(seeded):
    from agents import router
    record = router.handle("khata_page", {})
    commit_khata_import(record["import_id"])
    count = len(list(seeded.collection("ledger").stream()))

    again = commit_khata_import(record["import_id"])

    assert again["already"] is True
    assert len(list(seeded.collection("ledger").stream())) == count


def test_a_failed_transaction_writes_nothing(seeded):
    """Rollback is the whole point of the boundary — assert it directly."""
    from core.firestore_client import run_transaction
    before = seeded.collection("parties").document("selvam").get() \
        .to_dict()["credit"]["outstanding"]
    ref = seeded.collection("parties").document("selvam")

    def blow_up(txn):
        txn.update(ref, {"credit.outstanding": 999999})
        raise RuntimeError("something went wrong mid-write")

    try:
        run_transaction(blow_up)
    except RuntimeError:
        pass

    assert seeded.collection("parties").document("selvam").get() \
        .to_dict()["credit"]["outstanding"] == before


def test_the_same_sku_twice_on_one_invoice_adds_both_quantities(seeded):
    """Suppliers split a SKU across lines all the time — two rates, two batches.

    With Firestore semantics a read inside the loop cannot see a write made
    earlier in the same transaction, so a naive read-modify-write per line
    silently drops every increment but the last.
    """
    from agents import router
    purchase = router.handle("purchase_inv", {})
    ref = db().collection("purchases").document(purchase["purchase_id"])
    lines = ref.get().to_dict()["lines"]
    gi = next(dict(line) for line in lines if line["sku_id"] == "plm-gi-075")
    gi["qty"] = 10
    ref.update({"lines": lines + [gi]})          # same SKU, a second line of 10

    before = seeded.collection("inventory").document("plm-gi-075").get() \
        .to_dict()["qty_on_hand"]

    result = confirm_purchase(purchase["purchase_id"])

    after = seeded.collection("inventory").document("plm-gi-075").get() \
        .to_dict()["qty_on_hand"]
    assert after == before + 25 + 10, "both lines must be added, not just the last"
    gi_deltas = [d for d in result["stock_delta"] if d["sku_id"] == "plm-gi-075"]
    assert len(gi_deltas) == 1, "the delta shown to the owner is per SKU, not per line"
    assert gi_deltas[0] == {"sku_id": "plm-gi-075", "before": before, "after": after}
