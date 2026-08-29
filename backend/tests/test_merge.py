"""Merging duplicate party profiles.

The property that matters most: after a merge the shop's view of what a trader
owes must equal what the two profiles owed together. Getting this wrong in
either direction is a money bug — understate it and the Credit Guardian approves
credit that should have been refused.
"""
import pytest

from core import merge
from core.firestore_client import db
from core.transactions import commit_khata_import


def _make_duplicate(seeded, party_id="selvan", name="Selvan", outstanding=12000):
    """A second profile for a contractor already on file as Selvam."""
    db().collection("parties").document(party_id).set({
        "party_id": party_id, "name": name, "type": "customer",
        "price_tier": "contractor", "provisional": True,
        "credit": {"limit": 50000, "outstanding": outstanding,
                   "last_payment_date": "2026-08-20", "last_payment_amount": 4000,
                   "avg_days_to_pay": 30, "total_business_value": 60000,
                   "dispute_count": 1},
    })
    return party_id


# ------------------------------------------------------------------ detection
def test_a_near_identical_name_is_suggested(seeded):
    _make_duplicate(seeded)
    pairs = merge.find_duplicates()
    assert any({p.a, p.b} == {"selvam", "selvan"} for p in pairs)


def test_a_shared_phone_is_treated_as_proof_not_a_guess(seeded):
    db().collection("parties").document("selvam").update({"phone": "+919000000001"})
    db().collection("parties").document("totally_different").set({
        "party_id": "totally_different", "name": "Zzz Enterprises",
        "type": "customer", "phone": "+919000000001", "credit": {"outstanding": 0}})
    pair = next(p for p in merge.find_duplicates()
                if {p.a, p.b} == {"selvam", "totally_different"})
    assert pair.score == 1.0 and pair.reason == "same phone number"


def test_a_customer_is_never_paired_with_a_supplier(seeded):
    assert not any({p.a, p.b} == {"selvam", "sbh_agencies"}
                   for p in merge.find_duplicates())


def test_an_already_merged_profile_stops_being_suggested(seeded):
    _make_duplicate(seeded)
    merge.merge_parties("selvan", "selvam")
    assert not any({p.a, p.b} == {"selvam", "selvan"} for p in merge.find_duplicates())


# --------------------------------------------------------------------- merging
def test_the_combined_balance_is_the_sum_of_both(seeded):
    """The whole reason duplicates are dangerous."""
    _make_duplicate(seeded, outstanding=12000)
    before = db().collection("parties").document("selvam").get() \
        .to_dict()["credit"]["outstanding"]

    result = merge.merge_parties("selvan", "selvam")

    survivor = db().collection("parties").document("selvam").get().to_dict()
    assert survivor["credit"]["outstanding"] == before + 12000
    assert result["moved_outstanding"] == 12000
    assert db().collection("parties").document("selvan").get() \
        .to_dict()["credit"]["outstanding"] == 0


def test_the_survivors_credit_limit_is_not_inflated(seeded):
    """Summing two limits would hand the trader more rope than anyone agreed."""
    _make_duplicate(seeded)
    before = db().collection("parties").document("selvam").get() \
        .to_dict()["credit"]["limit"]
    merge.merge_parties("selvan", "selvam")
    assert db().collection("parties").document("selvam").get() \
        .to_dict()["credit"]["limit"] == before


def test_history_that_matters_for_risk_is_combined(seeded):
    _make_duplicate(seeded)
    merge.merge_parties("selvan", "selvam")
    credit = db().collection("parties").document("selvam").get().to_dict()["credit"]
    # The more recent payment wins; disputes and business value accumulate.
    assert credit["last_payment_date"] == "2026-08-20"
    assert credit["dispute_count"] == 1
    assert credit["total_business_value"] >= 60000


def test_the_merged_profile_points_at_the_survivor(seeded):
    _make_duplicate(seeded)
    merge.merge_parties("selvan", "selvam")
    stale = db().collection("parties").document("selvan").get().to_dict()
    assert stale["merged_into"] == "selvam" and stale["active"] is False
    assert merge.resolve("selvan") == "selvam"


def test_a_merge_chain_resolves_to_the_last_survivor(seeded):
    _make_duplicate(seeded, "selvan", "Selvan", 1000)
    _make_duplicate(seeded, "selvamm", "Selvamm", 2000)
    merge.merge_parties("selvamm", "selvan")
    merge.merge_parties("selvan", "selvam")
    assert merge.resolve("selvamm") == "selvam"
    assert set(merge.merged_sources("selvam")) == {"selvan", "selvamm"}


# ---------------------------------------------------------------- refusals
def test_a_profile_cannot_be_merged_into_itself(seeded):
    with pytest.raises(ValueError, match="into itself"):
        merge.merge_parties("selvam", "selvam")


def test_merging_the_same_profile_twice_is_refused(seeded):
    _make_duplicate(seeded)
    merge.merge_parties("selvan", "selvam")
    with pytest.raises(ValueError, match="already merged"):
        merge.merge_parties("selvan", "kumar")


def test_merging_into_a_dead_profile_is_refused(seeded):
    """Otherwise the balance lands somewhere nothing reads from."""
    _make_duplicate(seeded)
    merge.merge_parties("selvan", "selvam")
    _make_duplicate(seeded, "selvann", "Selvann", 500)
    with pytest.raises(ValueError, match="itself merged"):
        merge.merge_parties("selvann", "selvan")


def test_a_missing_profile_is_refused(seeded):
    with pytest.raises(LookupError):
        merge.merge_parties("ghost", "selvam")


# ------------------------------------------------------- consolidated view
def test_the_ledger_is_never_rewritten(seeded):
    """History stays filed where it was written — that is what makes the merge
    honest, and reversible."""
    _make_duplicate(seeded)
    db().collection("ledger").document("led_old").set({
        "entry_id": "led_old", "party_id": "selvan", "date": "2026-07-01",
        "type": "sale_credit", "amount": 12000, "direction": "debit",
        "balance_after": 12000, "ref": {"type": "manual", "id": "x"},
        "source": "owner"})

    merge.merge_parties("selvan", "selvam")

    entry = db().collection("ledger").document("led_old").get().to_dict()
    assert entry["party_id"] == "selvan", "the row must not be repointed"
    assert entry["amount"] == 12000


def test_the_survivor_shows_one_combined_history(seeded):
    from api.reads import party_ledger
    _make_duplicate(seeded)
    db().collection("ledger").document("led_old").set({
        "entry_id": "led_old", "party_id": "selvan", "date": "2026-07-01",
        "type": "sale_credit", "amount": 12000, "direction": "debit",
        "balance_after": 12000, "ref": {"type": "manual", "id": "x"},
        "source": "owner"})
    merge.merge_parties("selvan", "selvam")

    view = party_ledger("selvam")

    ids = {e["entry_id"] for e in view["entries"]}
    assert "led_old" in ids, "the merged profile's history must appear"
    old = next(e for e in view["entries"] if e["entry_id"] == "led_old")
    assert old["recorded_under"] == "Selvan", "and say which name it was filed under"
    assert view["party"]["merged_from"][0]["party_id"] == "selvan"


def test_looking_up_a_merged_profile_redirects_to_the_survivor(seeded):
    from api.reads import party_ledger
    _make_duplicate(seeded)
    merge.merge_parties("selvan", "selvam")
    view = party_ledger("selvan")
    assert view["redirected"] is True
    assert view["party"]["party_id"] == "selvam"


def test_orders_and_purchases_follow_the_merge(seeded):
    from agents import router
    _make_duplicate(seeded)
    order = router.handle("sale_order", {"party_id": "selvan", "source": "text",
                                         "transcript": "20 bags ramco 53"})
    merge.merge_parties("selvan", "selvam")
    moved = db().collection("orders").document(order["order_id"]).get().to_dict()
    assert moved["party_id"] == "selvam"
    assert moved["merged_from"] == "selvan"


def test_credit_guardian_sees_the_real_exposure_after_a_merge(seeded):
    """The point of the whole feature: before the merge the shop was blind to
    half of what this contractor owed."""
    from agents.credit_guardian_agent import decide
    _make_duplicate(seeded, outstanding=12000)
    party = db().collection("parties").document("selvam").get().to_dict()
    hidden = decide(party, 5000)

    merge.merge_parties("selvan", "selvam")

    party = db().collection("parties").document("selvam").get().to_dict()
    revealed = decide(party, 5000)
    assert revealed.exposure_pct > hidden.exposure_pct
    assert revealed.inputs["outstanding"] == hidden.inputs["outstanding"] + 12000
