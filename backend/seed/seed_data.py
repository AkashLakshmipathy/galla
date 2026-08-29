"""Seed the demo shop. Numbers here match the design prototype exactly so the
UI, the demo script and the database tell one consistent story.

    python -m seed.seed_data
"""
from datetime import datetime, timedelta, timezone, date


def _days_ago(n: int) -> str:
    """Seed payment dates relative to today.

    The demo script says Selvam "last paid 34 days ago" and the Credit Guardian
    recomputes that from the date, so a hard-coded date drifts a day for every
    day the recording slips — and Ravi eventually crosses OVERDUE by accident.
    Anchoring to today keeps every verdict, and every line of the script, true
    on whatever morning the video gets shot.
    """
    return (datetime.now(timezone.utc).date() - timedelta(days=n)).isoformat()
from core.firestore_client import db

SHOP = {
    "shop_id": "main", "name": "Sri Balaji Hardware",
    "name_ta": "ஸ்ரீ பாலாஜி ஹார்டுவேர்", "gstin": "33AAMPM8712K1ZQ",
    "state_code": "33", "address": "Thudiyalur, Coimbatore",
    "phone": "+914224561234",
    "ca_contact": {"name": "CA Ramesh Krishnan", "phone": "+919842200000",
                   "email": "ramesh@krishnanandco.in"},
    "defaults": {"credit_limit": 50000, "credit_days": 30},
    "confidence_threshold": 0.85,
}

PARTIES = [
    # Selvam is the demo's amber case: 92% of limit after the new order.
    {"party_id": "selvam", "name": "Selvam", "name_ta": "செல்வம்", "type": "customer",
     "price_tier": "contractor",
     "credit": {"limit": 95000, "outstanding": 87400, "last_payment_date": _days_ago(34),
                "last_payment_amount": 20000, "days_since_payment": 34,   # recomputed on read; seeded for completeness
                "avg_days_to_pay": 41, "dispute_count": 0}},
    {"party_id": "kumar", "name": "Kumar Constructions", "name_ta": "குமார்", "type": "customer",
     "price_tier": "contractor",
     "credit": {"limit": 150000, "outstanding": 32000, "last_payment_date": _days_ago(8),
                "last_payment_amount": 45000, "days_since_payment": 8,
                "avg_days_to_pay": 22, "dispute_count": 0}},
    {"party_id": "ravi", "name": "Ravi Builders", "name_ta": "ரவி", "type": "customer",
     "price_tier": "bulk",
     "credit": {"limit": 120000, "outstanding": 118500, "last_payment_date": _days_ago(59),
                "last_payment_amount": 10000, "days_since_payment": 59,
                "avg_days_to_pay": 64, "dispute_count": 1}},
    # Names that appear on the old khata pages.
    {"party_id": "palani", "name": "Palani", "name_ta": "பழனி", "type": "customer",
     "price_tier": "retail",
     "credit": {"limit": 40000, "outstanding": 6300, "last_payment_date": _days_ago(16),
                "last_payment_amount": 5000, "days_since_payment": 16,
                "avg_days_to_pay": 28, "dispute_count": 0}},
    {"party_id": "kannan", "name": "Kannan", "name_ta": "கண்ணன்", "type": "customer",
     "price_tier": "retail",
     "credit": {"limit": 60000, "outstanding": 14800, "last_payment_date": _days_ago(23),
                "last_payment_amount": 12000, "days_since_payment": 23,
                "avg_days_to_pay": 31, "dispute_count": 0}},
    {"party_id": "raja_mason", "name": "Raja Mason", "name_ta": "ராஜா", "type": "customer",
     "price_tier": "contractor",
     "credit": {"limit": 50000, "outstanding": 9200, "last_payment_date": _days_ago(10),
                "last_payment_amount": 8000, "days_since_payment": 10,
                "avg_days_to_pay": 25, "dispute_count": 0}},
    {"party_id": "murthy", "name": "Murthy Electric", "name_ta": "மூர்த்தி",
     "type": "customer", "price_tier": "retail",
     "credit": {"limit": 30000, "outstanding": 4600, "last_payment_date": _days_ago(19),
                "last_payment_amount": 3000, "days_since_payment": 19,
                "avg_days_to_pay": 34, "dispute_count": 0}},
    {"party_id": "sbh_agencies", "name": "Sri Balaji Hardware Agencies", "type": "supplier",
     "gstin": "33AABCS1429B1ZP", "price_tier": "retail",
     "credit": {"limit": 0, "outstanding": 0}},
]

CATALOG = [
    {"sku_id": "cem-ramco-53", "name": "Ramco Supergrade OPC 53 Grade 50kg",
     "name_ta": "ராம்கோ 53 சிமெண்ட்",
     "aliases": ["ramco 53", "ramco bag", "ராம்கோ", "supergrade", "53 grade ramco"],
     "brand": "Ramco", "category": "cement", "unit": "bag", "hsn_code": "2523",
     "gst_rate": 28, "purchase_rate": 385,
     "price_tiers": {"retail": 445, "contractor": 415, "bulk": 405},
     "substitutes": ["cem-dalmia-53"], "active": True},
    {"sku_id": "cem-dalmia-53", "name": "Dalmia OPC 53 Grade 50kg",
     "aliases": ["dalmia 53", "dalmia"], "brand": "Dalmia", "category": "cement",
     "unit": "bag", "hsn_code": "2523", "gst_rate": 28, "purchase_rate": 378,
     "price_tiers": {"retail": 438, "contractor": 408, "bulk": 398},
     "substitutes": ["cem-ramco-53"], "active": True},
    {"sku_id": "plm-cpvc-075", "name": 'CPVC Pipe 3/4" (10 ft)',
     "aliases": ["3/4 pipe", "cpvc 3/4", "முக்கால் பைப்", "adi pipe"],
     "brand": "Astral", "category": "plumbing", "unit": "length", "hsn_code": "3917",
     "gst_rate": 18, "purchase_rate": 210,
     "price_tiers": {"retail": 265, "contractor": 245, "bulk": 238},
     "substitutes": [], "active": True},
    {"sku_id": "plm-gi-075", "name": 'GI Pipe 3/4" (6 m)',
     "aliases": ["gi pipe", "gi 3/4", "ஜி ஐ பைப்", "ஜி ஐ பைப் முக்கால்",
                 "ஜிஐ பைப்", "gi pipe 3/4"], "brand": "Tata",
     "category": "plumbing", "unit": "length", "hsn_code": "7306", "gst_rate": 18,
     "purchase_rate": 640, "price_tiers": {"retail": 760, "contractor": 715, "bulk": 700},
     "substitutes": [], "active": True},
    {"sku_id": "hw-hinge-4", "name": 'Steel Butt Hinge 4 inch',
     "aliases": ["4 inch hinge", "hinges", "கீல்", "நாலு இன்ச் கீல்",
                 "4 இன்ச் கீல்", "butt hinge"], "brand": "Ebco",
     "category": "hardware", "unit": "piece", "hsn_code": "8302", "gst_rate": 18,
     "purchase_rate": 62, "price_tiers": {"retail": 85, "contractor": 76, "bulk": 72},
     "substitutes": [], "active": True},
]

INVENTORY = {"cem-ramco-53": 6, "cem-dalmia-53": 90, "plm-cpvc-075": 120,
             "plm-gi-075": 40, "hw-hinge-4": 300}


def main(reset: bool = False):
    c = db()
    if reset and hasattr(c, "reset"):
        c.reset()
    c.collection("shop").document("main").set(SHOP)
    for p in PARTIES:
        c.collection("parties").document(p["party_id"]).set(p)
    for s in CATALOG:
        c.collection("catalog").document(s["sku_id"]).set(s)
    for sku, qty in INVENTORY.items():
        c.collection("inventory").document(sku).set(
            {"sku_id": sku, "qty_on_hand": qty, "reorder_level": 15,
             "last_updated": datetime.now(timezone.utc)})
    # opening balances so the ledger is not empty on camera
    for p in PARTIES:
        if p["type"] != "customer":
            continue
        c.collection("ledger").add({
            "party_id": p["party_id"], "date": date(2026, 6, 1).isoformat(),
            "type": "opening_balance", "amount": p["credit"]["outstanding"],
            "direction": "debit", "balance_after": p["credit"]["outstanding"],
            "ref": {"type": "manual", "id": "seed"}, "source": "owner",
            "created_at": datetime.now(timezone.utc)})
    print(f"seeded: shop, {len(PARTIES)} parties, {len(CATALOG)} SKUs, "
          f"{len(INVENTORY)} inventory rows, opening ledger")


if __name__ == "__main__":
    import sys
    main(reset="--reset" in sys.argv)
