"""The two books, and the direction of money in each.

The bug these exist to prevent: a supplier the shop *owes* appearing in the list
of who owes the shop. It overstates what the business is worth by twice the
figure — once by adding it, once by not subtracting it.
"""
from api.reads import credit_book, party_ledger, purchases_book
from core import books
from core.firestore_client import db


def _supplier(seeded, party_id="annai", payable=59849):
    db().collection("parties").document(party_id).set({
        "party_id": party_id, "name": "Sri Annai Traders", "type": "supplier",
        "gstin": "33AAECS4521P1ZK", "credit": {"limit": 0, "outstanding": payable}})
    db().collection("ledger").document(f"led_{party_id}").set({
        "entry_id": f"led_{party_id}", "party_id": party_id, "date": "2026-08-27",
        "type": "purchase_credit", "amount": payable, "direction": "credit",
        "balance_after": payable, "ref": {"type": "purchase", "id": "pur_1"},
        "source": "owner"})
    return party_id


def test_a_supplier_never_appears_in_who_owes_you(seeded):
    _supplier(seeded)
    book = credit_book()
    assert "annai" not in {p["party_id"] for p in book["parties"]}
    assert all(p["party_id"] != "annai" for p in book["parties"])


def test_money_owed_to_a_supplier_is_not_counted_as_an_asset(seeded):
    before = credit_book()["totals"]["outstanding"]
    _supplier(seeded, payable=59849)
    assert credit_book()["totals"]["outstanding"] == before


def test_the_supplier_shows_up_on_the_purchases_side(seeded):
    _supplier(seeded)
    book = purchases_book()
    row = next(s for s in book["suppliers"] if s["party_id"] == "annai")
    assert row["payable"] == 59849
    assert book["totals"]["payable"] == 59849


def test_a_customer_never_appears_in_purchases(seeded):
    assert "selvam" not in {s["party_id"] for s in purchases_book()["suppliers"]}


def test_out_and_back_flip_with_the_side_of_the_book(seeded):
    """A debit grows a customer's debt and shrinks a supplier's. Reading the
    sign without knowing whose book it is gets this exactly backwards."""
    _supplier(seeded)
    customers, _ = books.ledger_rollup("customer", "all")
    suppliers, _ = books.ledger_rollup("supplier", "all")
    assert customers["selvam"]["out"] > 0          # goods handed over on credit
    assert suppliers["annai"]["out"] == 59849      # a bill we have not paid


def test_periods_roll_up_by_month_year_and_all_time(seeded):
    for date, amount in [("2025-03-14", 22000), ("2025-07-02", 15000),
                         ("2026-01-08", 31000)]:
        eid = f"led_{date}"
        db().collection("ledger").document(eid).set({
            "entry_id": eid, "party_id": "selvam", "date": date,
            "type": "sale_credit", "amount": amount, "direction": "debit",
            "balance_after": amount, "ref": {"type": "manual", "id": "x"},
            "source": "khata_import"})

    months = {p["period"] for p in credit_book("month")["periods"]}
    years = {p["period"] for p in credit_book("year")["periods"]}
    all_time = credit_book("all")["periods"]

    assert {"2025-03", "2025-07", "2026-01"} <= months
    assert {"2025", "2026"} <= years
    assert len(all_time) == 1 and all_time[0]["period"] == "all"
    # All-time must equal the sum of the months, or two screens disagree.
    assert all_time[0]["given"] == sum(
        p["given"] for p in credit_book("month")["periods"])


def test_only_bills_saved_to_stock_count_as_bought(seeded):
    """An extraction sitting in review is not a purchase. Counting it would tell
    the owner he had bought something he has not agreed to."""
    from agents import router
    from core.transactions import confirm_purchase
    purchase = router.handle("purchase_inv", {})
    assert purchases_book()["totals"]["bills"] == 0

    confirm_purchase(purchase["purchase_id"])
    assert purchases_book()["totals"]["bills"] == 1


def test_a_party_page_carries_its_own_lifetime_totals(seeded):
    view = party_ledger("selvam")
    assert view["given"] >= 0 and view["received"] >= 0
    assert view["since"] is not None


def test_quiet_months_get_their_own_column(seeded):
    """March next to November on the axis makes a gap in trading look like
    continuous business."""
    for date in ("2026-01-05", "2026-04-05"):
        eid = f"led_{date}"
        db().collection("ledger").document(eid).set({
            "entry_id": eid, "party_id": "selvam", "date": date,
            "type": "sale_credit", "amount": 1000, "direction": "debit",
            "balance_after": 1000, "ref": {"type": "manual", "id": "x"},
            "source": "owner"})

    periods = [p["period"] for p in credit_book("month")["periods"]]
    assert "2026-02" in periods and "2026-03" in periods
    quiet = next(p for p in credit_book("month")["periods"]
                 if p["period"] == "2026-02")
    assert quiet["given"] == 0 and quiet["entries"] == 0
    # Consecutive, with no jumps.
    assert periods == sorted(periods)


def test_all_time_is_a_single_column(seeded):
    periods = credit_book("all")["periods"]
    assert len(periods) == 1 and periods[0]["period"] == "all"
