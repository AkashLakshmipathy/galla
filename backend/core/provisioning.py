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
from core.adk import ask
from core.config import GEMINI_MODEL_FAST, SHOP_ID
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


_ALL_CAPS_WORD = re.compile(r"^[A-Z0-9][A-Z0-9./&'\"-]*$")


def _readable(description: str) -> str:
    """SHOUTED invoice text into something a person reads.

    `str.title()` is not good enough here: it turns G.I.PIPE into G.I.Pipe and
    SDR11 into Sdr11. Short tokens, anything with a digit, and known trade
    abbreviations are left exactly as printed — on a hardware bill those are
    grades and sizes, and changing their case changes what they mean.
    """
    words = (description or "").split()
    if not any(_ALL_CAPS_WORD.match(w) for w in words):
        return description.strip()
    keep = {"GI", "MS", "PVC", "CPVC", "UPVC", "HDPE", "OPC", "PPC", "SS", "MM",
            "KG", "HSN", "GST", "TMT", "SDR", "CL", "HVY", "LTR", "ML", "SQ",
            "MTR", "NOS", "WT", "OD", "ID"}
    out = []
    for word in words:
        bare = word.strip(".,")
        acronym = bare.isupper() and any(ch in ".-/" for ch in bare)
        if (acronym or bare.upper() in keep or any(ch.isdigit() for ch in word)
                or len(bare) <= 2):
            out.append(word)          # a grade, a size, or an acronym — as printed
        else:
            out.append(word.capitalize() if word.isupper() else word)
    return " ".join(out)


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
        "name": _readable(description),
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


SAME_PRODUCT_INSTRUCTION = """You decide whether a line on an Indian hardware
supplier's invoice is a product the shop already stocks, or something new.

Suppliers write the same item differently on every bill — "GI PIPE 1", "G.I.PIPE
1\" HVY", "Tata GI Pipe 1 inch Class B" are one product. But a different size,
grade, or class is a *different* product: 1" is not 3/4", 53 grade is not 43
grade, Class B is not Class C. Brand alone does not make it different.

Return ONLY JSON: {"sku_id": "<the id it matches, or null>", "confidence": 0-1,
"why": "<eight words>"}
Answer null unless you are genuinely confident. A wrong match merges two
products in a shop's stock count, which is worse than asking the owner."""


def _model_decides(description: str, candidates: list[dict]) -> tuple[str | None, float]:
    """Ask Gemini whether a shorthand line is a product already on the shelf.

    Fuzzy string distance cannot know that "G.I.PIPE" and "GI Pipe Heavy" are the
    same thing while 1" and 3/4" are not — that is product knowledge, not string
    similarity, and it is exactly what the model is for. Used only in the
    ambiguous band; a certain match never needs it and an obviously new product
    never needs it.
    """
    if not candidates:
        return None, 0.0
    listing = "\n".join(
        f'- {c["sku_id"]}: {c.get("name")} (unit {c.get("unit")}, HSN {c.get("hsn_code")})'
        for c in candidates)
    result = ask("purchase_entry", SAME_PRODUCT_INSTRUCTION,
                 f"Invoice line: {description}\n\nAlready in stock:\n{listing}",
                 fallback={"sku_id": None, "confidence": 0.0},
                 model=GEMINI_MODEL_FAST)
    data = result.data if isinstance(result.data, dict) else {}
    sku_id = data.get("sku_id")
    known = {c["sku_id"] for c in candidates}
    if sku_id not in known:
        return None, 0.0
    return sku_id, float(data.get("confidence") or 0)


def resolve_sku(line: dict, use_model: bool = True) -> Resolution:
    rows = catalog.load()
    description = str(line.get("description_raw") or "").strip()
    match = catalog.match(description, rows)
    score = match.confidence

    if match.matched and score >= CERTAIN:
        # Certain, but the wording may be new — remember how this supplier
        # writes it so the next bill does not have to be worked out again.
        catalog.learn_alias(match.sku_id, description)
        return Resolution(USE, match.sku_id, score, alternatives=match.alternatives)

    if score >= AMBIGUOUS:
        candidates = [catalog.by_id(a["sku_id"], rows) for a in match.alternatives
                      if a.get("sku_id")]
        candidates = [c for c in candidates if c]
        sku_id, confidence = (_model_decides(description, candidates)
                              if use_model else (None, 0.0))
        if sku_id and confidence >= CERTAIN:
            catalog.learn_alias(sku_id, description)
            return Resolution(USE, sku_id, confidence,
                              alternatives=match.alternatives)
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


def propose_supplier(name_raw: str, gstin: str | None = None) -> dict:
    """A profile for a supplier whose bill just arrived.

    Without this the payable is recorded against nobody: the ledger entry has no
    party, the Purchases book cannot find it, and the shop is told it owes
    nothing while a real bill sits on the counter.
    """
    proposed = propose_party(name_raw, "purchase_credit")
    proposed["gstin"] = gstin
    proposed["type"] = "supplier"
    proposed["is_company"] = True          # a supplier issuing a GST bill is a firm
    proposed["credit"]["limit"] = 0        # we owe them, not the other way round
    return proposed


SAME_PERSON_INSTRUCTION = """You decide whether a name written in an Indian shop's
handwritten credit ledger is somebody the shop already has an account for.

The same trader is written many ways: "Kumar Tiruppur", "Tiruppur Kumar",
"Kumar T", "Kumar Constructions". Word order, an initial, a place name, or the
firm's suffix do not make a different person. A genuinely different first name
does, and so does a different town when the first names also differ.

Return ONLY JSON: {"party_id": "<the id it matches, or null>", "confidence": 0-1,
"why": "<eight words>"}
Answer null unless you are genuinely confident. Merging two traders puts one
man's debt on another's account, which is far worse than asking the owner."""


def _model_decides_party(name_raw: str, candidates: list[dict]
                         ) -> tuple[str | None, float]:
    """Ask Gemini whether two spellings are one trader.

    Only in the ambiguous band. Word order is already handled by token matching;
    what the model adds is knowing that an initial or a firm suffix is the same
    person while a different given name is not.
    """
    if not candidates:
        return None, 0.0
    listing = "\n".join(
        f'- {c["party_id"]}: {c.get("name")}'
        + (f' (also {", ".join(c.get("aliases") or [])})' if c.get("aliases") else "")
        for c in candidates)
    result = ask("khata_digitizer", SAME_PERSON_INSTRUCTION,
                 f"Name on the page: {name_raw}\n\nAccounts already open:\n{listing}",
                 fallback={"party_id": None, "confidence": 0.0},
                 model=GEMINI_MODEL_FAST)
    data = result.data if isinstance(result.data, dict) else {}
    party_id = data.get("party_id")
    if party_id not in {c["party_id"] for c in candidates}:
        return None, 0.0
    return party_id, float(data.get("confidence") or 0)


def party_by_balance(opening: float | None) -> str | None:
    """Whose account is this page, judged by its brought-forward figure.

    A khata's pages chain: the balance one page closes at is the balance the
    next one opens with. That makes "B/F" an identifier — a far better one than
    the name, because a scrawled name is read three different ways across three
    pages while ₹26,992 is ₹26,992 whatever the handwriting is like.

    Only an exact match counts, and only when exactly one account sits on that
    figure. Two customers who happen to owe the same amount is a coincidence,
    not evidence, and guessing between them would put one man's purchases on
    another man's account.
    """
    if opening is None:
        return None
    target = int(round(float(opening)))
    if target <= 0:
        return None
    found = [snap.id for snap in db().collection("parties").stream()
             if not (snap.to_dict() or {}).get("merged_into")
             and int(((snap.to_dict() or {}).get("credit") or {})
                     .get("outstanding") or 0) == target]
    return found[0] if len(found) == 1 else None


def resolve_party(name_raw: str, entry_type: str = "sale_credit",
                  index: list | None = None, use_model: bool = True,
                  opening_balance: float | None = None) -> Resolution:
    index = index if index is not None else parties.index()
    party_id, score = parties.match(name_raw, index)

    # The balance the page carries forward outranks the name. Handwriting is
    # ambiguous; an exact rupee figure is not.
    by_balance = party_by_balance(opening_balance)
    if by_balance and (not party_id or party_id != by_balance):
        parties.learn_alias(by_balance, name_raw)
        return Resolution(USE, by_balance, 1.0)

    if party_id and score >= CERTAIN:
        parties.learn_alias(party_id, name_raw)
        return Resolution(USE, party_id, score)
    if score >= AMBIGUOUS:
        # Close but not certain. Creating here is how one contractor becomes two
        # ledgers and his real exposure doubles unseen. Always ask.
        ranked = sorted({r[0] for r in index},
                        key=lambda pid: -max(_similar(name_raw, n)
                                             for p, n in index if p == pid))[:3]
        candidates = []
        for pid in ranked:
            snap = db().collection("parties").document(pid).get().to_dict() or {}
            candidates.append({"party_id": pid, "name": snap.get("name"),
                               "aliases": snap.get("aliases")})
        chosen, confidence = (_model_decides_party(name_raw, candidates)
                              if use_model else (None, 0.0))
        if chosen and confidence >= CERTAIN:
            parties.learn_alias(chosen, name_raw)
            return Resolution(USE, chosen, confidence)

        near = candidates[0] if candidates else None
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
