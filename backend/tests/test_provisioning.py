"""Creating catalog items and party profiles from scanned paper.

The behaviour under test is the three-band rule. The middle band is the whole
point: a name close to an existing record must never be auto-created, because
two profiles for one contractor means his real exposure is double what either
one shows.
"""
import pytest

from core import catalog, provisioning
from core.firestore_client import db
from core.transactions import commit_khata_import, confirm_purchase


# ------------------------------------------------------------------ banding
def test_a_known_product_is_reused_not_recreated(seeded):
    r = provisioning.resolve_sku({"description_raw": "RAMCO SUPERGRADE OPC 53 50KG"})
    assert r.action == provisioning.USE
    assert r.existing_id == "cem-ramco-53"


def test_a_genuinely_new_product_is_proposed(seeded):
    r = provisioning.resolve_sku({
        "description_raw": "ASIAN PAINTS APEX ULTIMA 20L", "rate": 4200,
        "gst_rate": 18, "hsn_code": "3209"})
    assert r.creates
    assert r.proposed["name"]
    assert r.proposed["purchase_rate"] == 4200
    assert r.proposed["gst_rate"] == 18
    assert r.proposed["hsn_code"] == "3209"


def test_a_new_product_is_received_but_not_sellable(seeded):
    """Quantity and purchase rate are printed on the bill. A selling price is
    not, and guessing a margin is deciding money."""
    r = provisioning.resolve_sku({"description_raw": "FEVICOL SH 500G", "rate": 180})
    assert set(r.proposed["price_tiers"].values()) == {0}
    assert r.proposed["needs_pricing"] is True
    assert r.proposed["provisional"] is True


def test_a_known_party_is_reused(seeded):
    r = provisioning.resolve_party("Kumar Constructions")
    assert r.action == provisioning.USE and r.existing_id == "kumar"


def test_an_unknown_person_gets_a_profile_proposed(seeded):
    r = provisioning.resolve_party("Anbarasu")
    assert r.creates
    assert r.proposed["type"] == "customer"
    assert r.proposed["is_company"] is False
    assert r.proposed["credit"]["outstanding"] == 0


def test_a_company_name_is_recognised_as_a_firm(seeded):
    r = provisioning.resolve_party("Sakthi Traders")
    assert r.creates and r.proposed["is_company"] is True


def test_a_new_party_gets_the_shops_default_limit_not_an_invented_one(seeded):
    shop = db().collection("shop").document("main").get().to_dict()
    r = provisioning.resolve_party("Brand New Person")
    assert r.proposed["credit"]["limit"] == shop["defaults"]["credit_limit"]


def test_a_tamil_name_is_stored_as_tamil(seeded):
    r = provisioning.resolve_party("அன்பரசு")
    assert r.creates and r.proposed["name_ta"] == "அன்பரசு"


# ---------------------------------------------------- the dangerous middle band
def test_a_near_miss_party_is_never_auto_created(seeded):
    """'Selvan' vs the seeded 'Selvam'. Creating here would split one
    contractor across two ledgers and double his effective credit limit."""
    r = provisioning.resolve_party("Selvan")
    assert r.action == provisioning.ASK
    assert not r.creates
    assert r.near_miss["party_id"] == "selvam"


def test_a_near_miss_product_is_never_auto_created(seeded):
    r = provisioning.resolve_sku({"description_raw": "DALMIA 53 OPC"})
    assert r.action in (provisioning.USE, provisioning.ASK)
    assert not r.creates


# ------------------------------------------------------------- end to end
def test_scanning_a_bill_creates_the_missing_product_and_stocks_it(seeded):
    from agents import router
    purchase = router.handle("purchase_inv", {})
    ref = db().collection("purchases").document(purchase["purchase_id"])
    lines = ref.get().to_dict()["lines"]
    # Deliberately a product the demo bill does not already carry, so the
    # assertion measures creation rather than the per-SKU line aggregation.
    lines.append({
        "sku_id": None, "description_raw": "FINOLEX FR 1.5 SQMM 90M COIL",
        "qty": 12, "rate": 1650, "amount": 19800, "gst_rate": 18,
        "confidence": 0.95, "matched": False,
        "new_sku": provisioning.propose_sku({
            "description_raw": "FINOLEX FR 1.5 SQMM 90M COIL", "rate": 1650,
            "gst_rate": 18, "hsn_code": "8544"}),
    })
    ref.update({"lines": lines})

    result = confirm_purchase(purchase["purchase_id"])

    new_id = next(s for s in result["created_skus"] if "finolex" in s)
    created = db().collection("catalog").document(new_id).get().to_dict()
    assert created["provisional"] is True
    # ...and it is actually in stock, with the quantity off the bill.
    stock = db().collection("inventory").document(new_id).get().to_dict()
    assert stock["qty_on_hand"] == 12          # the quantity printed on the bill
    assert catalog.by_id(new_id) is not None, "cache must not hide a fresh SKU"


def test_an_unpriced_product_cannot_be_sold(seeded):
    """The guard that makes auto-created SKUs safe."""
    from agents import router
    from core.transactions import approve_order
    order = router.handle("sale_order", {"party_id": "kumar", "source": "text",
                                         "transcript": "20 bags ramco 53"})
    ref = db().collection("orders").document(order["order_id"])
    lines = ref.get().to_dict()["lines"]
    lines[0]["rate"] = 0                       # as a provisional SKU would be
    ref.update({"lines": lines})

    with pytest.raises(ValueError, match="no selling price"):
        approve_order(order["order_id"])

    party = db().collection("parties").document("kumar").get().to_dict()
    assert party["credit"]["outstanding"] == 32000, "nothing may have moved"


def test_committing_a_khata_page_opens_accounts_for_new_names(seeded):
    from agents import router
    record = router.handle("khata_page", {})
    ref = db().collection("khata_imports").document(record["import_id"])
    rows = ref.get().to_dict()["rows"]
    rows.append({
        "row_id": "rNEW", "party_name_raw": "Anbarasu", "party_id": None,
        "date": rows[0]["date"], "amount": 5400, "entry_type": "sale_credit",
        "confidence": 0.95, "bbox": rows[0]["bbox"], "status": "confirmed",
        "alternatives": [], "new_party": provisioning.propose_party("Anbarasu"),
    })
    ref.update({"rows": rows})

    result = commit_khata_import(record["import_id"])

    new_id = next(p for p in result["created_parties"] if p == "anbarasu")
    party = db().collection("parties").document(new_id).get().to_dict()
    assert party["name"] == "Anbarasu"
    assert party["provisional"] is True
    # The scanned entry is on the new account, and the balance reflects only it.
    assert party["credit"]["outstanding"] == 5400
    entries = [s.to_dict() for s in db().collection("ledger").stream()
               if s.to_dict()["party_id"] == new_id]
    assert len(entries) == 1 and entries[0]["amount"] == 5400


def test_discarding_a_scan_leaves_no_phantom_records(seeded):
    """Proposals are written only by the transaction that moves money."""
    from agents import router
    before_catalog = len(list(db().collection("catalog").stream()))
    before_parties = len(list(db().collection("parties").stream()))

    router.handle("purchase_inv", {})
    router.handle("khata_page", {})          # scanned, never confirmed

    assert len(list(db().collection("catalog").stream())) == before_catalog
    assert len(list(db().collection("parties").stream())) == before_parties


def test_two_tamil_only_names_get_different_ids(seeded):
    """ASCII slugging leaves nothing behind for a pure-Tamil name. If both
    collapsed to the same id, the second person's credit would post to the
    first person's ledger."""
    a = provisioning.resolve_party("அன்பரசு").proposed["party_id"]
    b = provisioning.resolve_party("முருகன் ஸ்டோர்ஸ்").proposed["party_id"]
    assert a != b
    assert a.startswith("party-") and b.startswith("party-")


def test_a_tamil_name_stays_readable_even_with_an_opaque_id(seeded):
    proposed = provisioning.resolve_party("அன்பரசு").proposed
    assert proposed["name"] == "அன்பரசு"
    assert proposed["name_ta"] == "அன்பரசு"


def test_the_suppliers_printed_total_wins_over_our_arithmetic(seeded):
    """Rounding GST per line drifts a rupee or two from the supplier's own sum.
    The invoice is the document the shop will be asked to pay, so the paper wins
    and the difference is recorded rather than quietly absorbed."""
    from agents.purchase_entry_agent import _totals
    lines = [{"amount": 19600, "gst_rate": 28}, {"amount": 15210, "gst_rate": 18},
             {"amount": 9120, "gst_rate": 18}, {"amount": 3180, "gst_rate": 18},
             {"amount": 1950, "gst_rate": 18}]

    ours = _totals(lines)
    theirs = _totals(lines, {"total": 59849})

    assert ours["total"] == ours["computed_total"]
    assert theirs["total"] == 59849, "what the shop actually owes"
    assert theirs["computed_total"] == ours["computed_total"]
    assert theirs["rounding_difference"] == 59849 - ours["computed_total"]


def test_no_printed_total_falls_back_to_our_own_sum(seeded):
    from agents.purchase_entry_agent import _totals
    lines = [{"amount": 1000, "gst_rate": 18}]
    t = _totals(lines, {"total": None})
    assert t["total"] == t["computed_total"] == 1180
    assert "rounding_difference" not in t


def test_a_bill_from_an_unknown_supplier_opens_their_account(seeded):
    """Otherwise the payable is recorded against nobody: the Purchases book
    cannot find it and the shop is told it owes nothing while a real bill sits
    on the counter."""
    from agents import router
    from api.reads import purchases_book
    db().collection("parties").document("sbh_agencies").delete()
    purchase = router.handle("purchase_inv", {})

    result = confirm_purchase(purchase["purchase_id"])

    assert result["created_supplier"], "a supplier account must be opened"
    supplier = db().collection("parties").document(result["supplier_id"]) \
        .get().to_dict()
    assert supplier["type"] == "supplier"
    assert supplier["credit"]["outstanding"] == result["amount"]
    assert supplier["credit"]["limit"] == 0, "we owe them, not the reverse"
    book = purchases_book()
    assert book["totals"]["payable"] == result["amount"]


def test_one_person_named_twice_on_a_page_gets_one_account(seeded):
    """The khata names the same customer on several lines. Two accounts would
    split their balance — the exact thing merge exists to undo."""
    from agents import router
    record = router.handle("khata_page", {})
    result = commit_khata_import(record["import_id"])
    assert len(result["created_parties"]) == len(set(result["created_parties"]))

    rows = db().collection("khata_imports").document(record["import_id"]) \
        .get().to_dict()["rows"]
    by_name = {}
    for row in rows:
        if row.get("party_id"):
            by_name.setdefault(row["party_name_raw"], set()).add(row["party_id"])
    for name, ids in by_name.items():
        assert len(ids) == 1, f"{name} was split across {ids}"


def test_shouted_invoice_text_becomes_a_readable_name(seeded):
    """str.title() turns G.I.PIPE into G.i.pipe and SDR11 into Sdr11. On a
    hardware bill those are grades and sizes; changing their case changes what
    they mean."""
    from core.provisioning import _readable
    assert _readable("ULTRATECH PPC CEMENT 50KG") == "Ultratech PPC Cement 50KG"
    assert _readable('TATA G.I.PIPE 1" HVY CL-B 6MTR').startswith("Tata G.I.PIPE")
    assert "Sdr11" not in _readable("ASTRAL CPVC PIPE 3/4 SDR11 3MTR")
    assert _readable("Asian Paints Primer 1L") == "Asian Paints Primer 1L"


def test_the_catalogue_learns_how_a_supplier_writes_a_name(seeded):
    """Matching a shorthand once and forgetting is what turns one product into
    four over a year of bills."""
    wording = "TATA GI PIPE 3/4"                  # confident, but new wording
    before = db().collection("catalog").document("plm-gi-075").get() \
        .to_dict()["aliases"]

    resolution = provisioning.resolve_sku({"description_raw": wording})

    assert resolution.action == provisioning.USE
    after = db().collection("catalog").document("plm-gi-075").get() \
        .to_dict()["aliases"]
    assert len(after) > len(before)
    assert wording.lower() in after


def test_the_wording_the_model_is_actually_needed_for(seeded):
    """'GI PIPE 3/4 HEAVY' scores 0.70 against the catalogue — too low to trust
    and too high to call new. String distance cannot tell that "HEAVY" is a
    class and not a different product; that is what the model is asked."""
    assert provisioning.AMBIGUOUS <= catalog.match("GI PIPE 3/4 HEAVY").confidence \
        < provisioning.CERTAIN


def test_confirming_a_line_teaches_the_catalogue(seeded):
    """The owner saying "yes, that is the GI pipe" is a better signal than any
    match score, so his wording is recognised outright next time."""
    from agents import router
    from api.actions import Resolution, resolve_queue_item
    purchase = router.handle("purchase_inv", {})
    item = next(s.to_dict() for s in db().collection("confirm_queue").stream()
                if s.to_dict()["source_id"] == purchase["purchase_id"])

    resolve_queue_item(item["item_id"], Resolution(accept_extracted=True))

    aliases = db().collection("catalog").document("plm-gi-075").get() \
        .to_dict()["aliases"]
    assert item["extracted_value"].lower() in aliases
    assert catalog.match(item["extracted_value"]).confidence >= provisioning.CERTAIN


def test_a_learned_alias_makes_the_next_bill_match_outright(seeded):
    wording = "G.I.PIPE 3/4 HVY CL-B TATA"
    catalog.learn_alias("plm-gi-075", wording)
    match = catalog.match(wording)
    assert match.sku_id == "plm-gi-075"
    assert match.confidence >= provisioning.CERTAIN


def test_learning_the_same_wording_twice_does_not_grow_the_list(seeded):
    catalog.learn_alias("plm-gi-075", "GI PIPE HEAVY")
    first = db().collection("catalog").document("plm-gi-075").get().to_dict()["aliases"]
    catalog.learn_alias("plm-gi-075", "gi pipe heavy")
    second = db().collection("catalog").document("plm-gi-075").get().to_dict()["aliases"]
    assert first == second


def test_the_alias_list_stays_bounded(seeded):
    """A catalogue row is read on every line of every bill."""
    for i in range(60):
        catalog.learn_alias("plm-gi-075", f"GI PIPE VARIANT {i} XY")
    assert len(db().collection("catalog").document("plm-gi-075").get()
               .to_dict()["aliases"]) <= 40


def test_the_model_is_only_consulted_in_the_ambiguous_band(seeded, monkeypatch):
    """A certain match does not need it and an obviously new product does not
    either — asking anyway would spend money and time on every line."""
    calls = []
    monkeypatch.setattr(provisioning, "_model_decides",
                        lambda d, c: calls.append(d) or (None, 0.0))

    provisioning.resolve_sku({"description_raw": "RAMCO SUPERGRADE OPC 53 50KG"})
    assert calls == [], "a confident match must not call the model"

    provisioning.resolve_sku({"description_raw": "ZZZ UNKNOWN WIDGET QQQ"})
    assert calls == [], "an obviously new product must not call the model"


def test_the_model_can_settle_an_ambiguous_line(seeded, monkeypatch):
    monkeypatch.setattr(provisioning, "_model_decides",
                        lambda d, c: ("plm-gi-075", 0.95))
    r = provisioning.resolve_sku({"description_raw": 'G.I.PIPE 3/4" HVY 6MTR TATA'})
    assert r.action == provisioning.USE and r.existing_id == "plm-gi-075"


def test_an_unsure_model_leaves_the_decision_to_the_owner(seeded, monkeypatch):
    monkeypatch.setattr(provisioning, "_model_decides", lambda d, c: (None, 0.0))
    r = provisioning.resolve_sku({"description_raw": 'G.I.PIPE 3/4" HVY 6MTR TATA'})
    assert r.action == provisioning.ASK
    assert not r.creates


# ------------------------------------------------- names written many ways
def test_word_order_in_a_name_does_not_matter(seeded):
    from core import parties
    db().collection("parties").document("kumar").update({"name": "Kumar Tiruppur"})
    for spelling in ("Tiruppur Kumar", "KUMAR TIRUPPUR", "Kumar, Tiruppur"):
        assert provisioning.resolve_party(spelling).existing_id == "kumar", spelling


def test_a_confirmed_spelling_is_remembered(seeded):
    from core import parties
    db().collection("parties").document("kumar").update({"name": "Kumar Tiruppur"})
    provisioning.resolve_party("Tiruppur Kumar")
    aliases = db().collection("parties").document("kumar").get().to_dict()["aliases"]
    assert "Tiruppur Kumar" in aliases
    # ...and it is part of the index from then on
    assert any(a == "tiruppur kumar" for _, a in parties.index())


def test_the_model_settles_a_shortened_name(seeded, monkeypatch):
    """"Kumar T" scores 0.83 — below certainty, above nothing. Word order is
    already handled; what the model adds is knowing an initial is the same man."""
    db().collection("parties").document("kumar").update({"name": "Kumar Tiruppur"})
    monkeypatch.setattr(provisioning, "_model_decides_party",
                        lambda n, c: ("kumar", 0.93))
    r = provisioning.resolve_party("Kumar T")
    assert r.action == provisioning.USE and r.existing_id == "kumar"


def test_an_unsure_model_still_asks_the_owner(seeded, monkeypatch):
    """The ask band stays. Merging two traders puts one man's debt on another's
    account, so an uncertain answer is never allowed to act."""
    db().collection("parties").document("kumar").update({"name": "Kumar Tiruppur"})
    monkeypatch.setattr(provisioning, "_model_decides_party", lambda n, c: (None, 0.4))
    r = provisioning.resolve_party("Kumar T")
    assert r.action == provisioning.ASK and not r.creates
    assert r.near_miss["party_id"] == "kumar"


def test_merging_teaches_the_survivor_the_old_spellings(seeded):
    from core import merge, parties
    db().collection("parties").document("selvan").set({
        "party_id": "selvan", "name": "Selvan", "type": "customer",
        "aliases": ["Selvan Thudiyalur"],
        "credit": {"limit": 50000, "outstanding": 1000}})

    merge.merge_parties("selvan", "selvam")

    survivor = db().collection("parties").document("selvam").get().to_dict()
    assert "Selvan" in survivor["aliases_merged"]
    assert "Selvan Thudiyalur" in survivor["aliases_merged"]
    # the old spelling now resolves to the surviving account
    assert provisioning.resolve_party("Selvan Thudiyalur").existing_id == "selvam"


# ------------------------------------- a failed read must never invent data
def test_an_unread_khata_page_writes_nothing_in_a_real_shop(monkeypatch, seeded):
    """The fixture standing in for a failed model call is fine on stage and
    catastrophic in a shop: invented names and invented debts, indistinguishable
    from a genuine read."""
    import agents.khata_digitizer_agent as khata
    monkeypatch.setattr(khata, "DEMO_MODE", False)
    from core.trace import Trace

    trace = Trace("khata_page")
    record = khata.run({"media_path": "gs://x/none.jpg"}, trace)

    assert record["rows"] == []
    assert record["auto_accepted_count"] == 0
    step = trace.steps[0]
    assert step["status"] == "error"
    assert "again" in step["output_summary"]
    # ...and committing it posts nothing to anybody's ledger
    before = len(list(db().collection("ledger").stream()))
    commit_khata_import(record["import_id"])
    assert len(list(db().collection("ledger").stream())) == before


def test_an_unread_bill_writes_nothing_in_a_real_shop(monkeypatch, seeded):
    import agents.purchase_entry_agent as purchase
    monkeypatch.setattr(purchase, "DEMO_MODE", False)
    from core.trace import Trace

    trace = Trace("purchase_inv")
    record = purchase.run({"media_path": "gs://x/none.jpg"}, trace)

    assert record["lines"] == []
    assert trace.steps[0]["status"] == "error"
    stock_before = db().collection("inventory").document("plm-gi-075").get() \
        .to_dict()["qty_on_hand"]
    confirm_purchase(record["purchase_id"])
    assert db().collection("inventory").document("plm-gi-075").get() \
        .to_dict()["qty_on_hand"] == stock_before


def test_the_demo_still_has_its_fixtures(seeded):
    """DEMO_MODE is how the hackathon video runs without credentials."""
    import agents.khata_digitizer_agent as khata
    assert khata.DEMO_MODE is True
    assert khata._fixture().get("rows")
