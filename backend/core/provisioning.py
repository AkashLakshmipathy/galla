"""Creating catalog items and party profiles from scanned paper.

A shop that has just installed Galla has an empty catalog and no party records,
so without this every line of every bill lands in the confirm queue and the
product is useless on day one. The point of the thing is that the paper *is* the
data entry.

The whole design is one idea: **three bands, not two.**

    score >= CERTAIN     the record already exists — use it
    AMBIGUOUS..CERTAIN   it might be an existing record — ask, never create
    score <  AMBIGUOUS   genuinely new — propose creating it

The middle band is the entire reason this file is careful. Auto-creating there
is how "Selvam" and "Selvan" become two ledgers — and two ledgers for one
contractor means his real exposure is double what either profile shows, which is
precisely the failure the Credit Guardian exists to prevent. A duplicate SKU is
untidy; a duplicate debtor is a loss. So the ambiguous band always asks.

Nothing here writes on its own. `resolve_*` returns a *proposal*; creation runs
inside the transaction that also moves the stock or posts the ledger entry, so
scanning a page you then discard leaves no phantom records behind.
"""
from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass, field
from datetime import datetime, timezone

from core import catalog, parties
from core.config import SHOP_ID
from core.firestore_client import db

CERTAIN = 0.85          # same as the shop's confidence threshold
AMBIGUOUS = 0.55        # below this, nothing plausible was found

USE, ASK, CREATE = "use", "ask", "create"


@dataclass
class Resolution:
    """What to do about one scanned name."""
    action: str                       # use | ask | create
    existing_id: str | None = None
    score: float = 0.0
    proposed: dict | None = None      # the record we would create
    near_miss: dict | None = None     # what it might have been, for the ask
    alternatives: list = field(default_factory=list)

    @property
    def creates(self) -> bool:
        return self.action == CREATE


# --------------------------------------------------------------------- SKUs
_UNIT_HINTS = {
    "bag": ["bag", "bags", "50kg", "cement"],
    "length": ["pipe", "rod", "mtr", "metre", "meter", "ft", "feet", "length"],
    "kg": ["kg", "kgs", "kilo"],
    "litre": ["ltr", "litre", "liter", "ml"],
    "box": ["box", "carton"],
    "tin": ["tin", "bucket", "pail"],
    "coil": ["coil", "roll"],
}


def _guess_unit(description: str) -> str:
    lowered = (description or "").lower()
    for unit, hints in _UNIT_HINTS.items():
        if any(h in lowered for h in hints):
            return unit
    return "piece"


def _slug(text: str, existing: set[str], prefix: str = "rec") -> str:
    """A stable, readable document id.

    Names on a khata are often pure Tamil, which leaves nothing behind after
    ASCII slugging — every such name would collapse to the same id and the
    second one would silently land in the first one's ledger. When there is no
    usable ASCII, fall back to a short digest of the name: opaque, but unique
    and stable, and the readable form still lives in `name` / `name_ta`.
    """
    base = re.sub(r"[^a-z0-9]+", "-", (text or "").lower()).strip("-")
    base = "-".join([w for w in base.split("-") if w][:4])[:36]
    if not base:
        digest = hashlib.sha1((text or "").encode("utf-8")).hexdigest()[:8]
        base = f"{prefix}-{digest}"
    slug, n = base, 2
    while slug in existing:
        slug, n = f"{base}-{n}", n + 1
    return slug


def propose_sku(line: dict) -> dict:
    """Build a catalog record from one invoice line.

    Everything here is copied off the bill, never inferred — quantity, purchase
    rate, HSN and GST rate are printed on the paper. The one thing deliberately
    left blank is the *selling* price: guessing a margin is deciding money, and a
    bad guess sells cement at a loss. The SKU can be received into stock, which
    is a fact the bill states, and cannot be sold until a human prices it.
    """
    description = str(line.get("description_raw") or "").strip()
    rows = catalog.load()
    return {
        "sku_id": _slug(description, {r.get("sku_id") for r in rows}, "sku"),
        "name": description.title() if description.isupper() else description,
        "name_ta": None,
        "aliases": [description.lower()],
        "brand": None,
        "category": "uncategorised",
        "unit": _guess_unit(description),
        "hsn_code": str(line.get("hsn_code") or ""),
        "gst_rate": float(line.get("gst_rate") or 18),
        "purchase_rate": float(line.get("rate") or 0),
        "price_tiers": {"retail": 0, "contractor": 0, "bulk": 0},
        "substitutes": [],
        "active": True,
        "provisional": True,        # created from paper; owner has not reviewed it
        "needs_pricing": True,      # cannot be sold until a human sets a rate
        "created_from": {"type": "purchase", "id": line.get("_purchase_id")},
        "created_at": datetime.now(timezone.utc),
    }


def resolve_sku(line: dict) -> Resolution:
    rows = catalog.load()
    description = str(line.get("description_raw") or "").strip()
    match = catalog.match(description, rows)
    score = match.confidence

    if match.matched and score >= CERTAIN:
        return Resolution(USE, match.sku_id, score, alternatives=match.alternatives)
    if score >= AMBIGUOUS:
        near = {"sku_id": match.sku_id, "name": match.name} if match.sku_id else None
        return Resolution(ASK, None, score, proposed=propose_sku(line),
                          near_miss=near, alternatives=match.alternatives)
    return Resolution(CREATE, None, score, proposed=propose_sku(line),
                      alternatives=match.alternatives)


# ------------------------------------------------------------------ parties
_COMPANY_WORDS = {"constructions", "construction", "builders", "traders", "agencies",
                  "enterprises", "hardware", "electric", "electricals", "stores",
                  "company", "co", "pvt", "ltd", "&", "and sons", "industries"}


def looks_like_company(name: str) -> bool:
    """A shop's khata mixes people and firms; the profile should say which."""
    lowered = (name or "").lower()
    return any(word in lowered.split() or word in lowered for word in _COMPANY_WORDS)


def propose_party(name_raw: str, entry_type: str = "sale_credit") -> dict:
    """A profile for a name the khata mentions but the system has never seen.

    The credit limit is the shop's own default, never something inferred from
    the page: how much to trust someone is the owner's judgement, and a limit
    invented from a single scanned row would be a number nobody chose.
    """
    name = (name_raw or "").strip()
    shop = db().collection("shop").document(SHOP_ID).get().to_dict() or {}
    defaults = shop.get("defaults") or {}
    existing = {p.id for p in db().collection("parties").stream()}
    tamil = any("஀" <= ch <= "௿" for ch in name)
    return {
        "party_id": _slug(name, existing, "party"),
        "name": name,
        "name_ta": name if tamil else None,
        "type": "supplier" if entry_type == "purchase_credit" else "customer",
        "is_company": looks_like_company(name),
        "phone": None,
        "gstin": None,
        "price_tier": "retail",
        "credit": {
            "limit": int(defaults.get("credit_limit") or 50000),
            "outstanding": 0,
            "last_payment_date": None,
            "last_payment_amount": 0,
            "avg_days_to_pay": 0,
            "total_business_value": 0,
            "dispute_count": 0,
        },
        "provisional": True,
        "created_from": {"type": "khata_import", "id": None},
        "created_at": datetime.now(timezone.utc),
        "updated_at": datetime.now(timezone.utc),
    }


def resolve_party(name_raw: str, entry_type: str = "sale_credit",
                  index: list | None = None) -> Resolution:
    index = index if index is not None else parties.index()
    party_id, score = parties.match(name_raw, index)

    if party_id and score >= CERTAIN:
        return Resolution(USE, party_id, score)
    if score >= AMBIGUOUS:
        # Close but not certain. Creating here is how one contractor becomes two
        # ledgers and his real exposure doubles unseen. Always ask.
        best = max(index, key=lambda r: _similar(name_raw, r[1]), default=None)
        near = None
        if best:
            snap = db().collection("parties").document(best[0]).get().to_dict() or {}
            near = {"party_id": best[0], "name": snap.get("name")}
        return Resolution(ASK, None, score,
                          proposed=propose_party(name_raw, entry_type), near_miss=near)
    return Resolution(CREATE, None, score,
                      proposed=propose_party(name_raw, entry_type))


def _similar(a: str, b: str) -> float:
    from rapidfuzz import fuzz
    return fuzz.token_set_ratio(catalog.normalise(a or ""), b or "") / 100.0


# -------------------------------------------------------------- transactional
def create_sku(txn, proposed: dict, purchase_id: str | None = None) -> str:
    record = dict(proposed)
    record["created_from"] = {"type": "purchase", "id": purchase_id}
    txn.set(db().collection("catalog").document(record["sku_id"]), record)
    return record["sku_id"]


def create_party(txn, proposed: dict, import_id: str | None = None) -> str:
    record = dict(proposed)
    record["created_from"] = {"type": "khata_import", "id": import_id}
    txn.set(db().collection("parties").document(record["party_id"]), record)
    return record["party_id"]
