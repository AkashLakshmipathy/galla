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
