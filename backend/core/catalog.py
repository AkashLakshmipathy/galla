"""Catalog cache + trade-slang → SKU resolution.

Alias matching is done here, in-process, over a cached catalog — never as a
Firestore query. A shop catalog is a few hundred rows; a fuzzy pass over it is
microseconds, and it is the only way "10 adi 3/4 pipe" ever becomes a SKU.
"""
from __future__ import annotations

import re
import time
from dataclasses import dataclass, field

from rapidfuzz import fuzz, process

from core.firestore_client import db

_CACHE: dict[str, object] = {"at": 0.0, "rows": []}
_TTL_SECONDS = 120

# Trade words that carry no identity — they are quantity, not product.
_NOISE = {
    "bag", "bags", "nos", "no", "piece", "pieces", "pcs", "pc", "length",
    "lengths", "feet", "foot", "ft", "adi", "kg", "box", "boxes", "tin",
    "tins", "coil", "coils", "packet", "packets", "mtr", "meter", "metre",
    "of", "and", "x", "×", "the", "please", "send", "need", "want",
}
_FRACTIONS = {"¾": "3/4", "½": "1/2", "¼": "1/4", "⅜": "3/8", "⅝": "5/8"}
_UNIT_WORDS = {
    "bag": "bag", "bags": "bag", "pcs": "piece", "pc": "piece",
    "piece": "piece", "pieces": "piece", "nos": "piece", "no": "piece",
    "length": "length", "lengths": "length", "ft": "length", "feet": "length",
    "foot": "length", "adi": "length", "kg": "kg", "box": "box",
    "tin": "tin", "tins": "tin", "coil": "coil", "packet": "packet",
    # Tamil trade units — the owner and the contractor both speak these.
    "மூட்டை": "bag", "மூட்டைகள்": "bag", "பேக்": "bag", "அடி": "length",
    "எண்ணம்": "piece", "பீஸ்": "piece", "கிலோ": "kg", "பாக்கெட்": "packet",
}
# Numbers that describe the *product*, not the quantity: "53 grade", "4 inch".
_MEASURE_SUFFIX = {"inch", "mm", "cm", "grade", "sq", "g", "ml", "l", "litre",
                   "watt", "w", "amp", "gauge", "இன்ச்", "கிரேடு"}
_TAMIL_NUMBERS = {
    "ஒன்று": 1, "இரண்டு": 2, "மூன்று": 3, "நான்கு": 4, "ஐந்து": 5,
    "ஆறு": 6, "ஏழு": 7, "எட்டு": 8, "ஒன்பது": 9, "பத்து": 10,
    "இருபது": 20, "முப்பது": 30, "நாற்பது": 40, "ஐம்பது": 50,
}
_EN_NUMBERS = {
    "one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6,
    "seven": 7, "eight": 8, "nine": 9, "ten": 10, "twelve": 12,
    "fifteen": 15, "twenty": 20, "twentyfive": 25, "thirty": 30,
    "forty": 40, "fifty": 50, "hundred": 100,
}

# Number words carry quantity, never identity — they must not dilute matching.
_QTY_WORDS = set(_EN_NUMBERS) | set(_TAMIL_NUMBERS)


@dataclass
class Match:
    sku_id: str | None
    name: str
    confidence: float
    unit: str = ""
    gst_rate: float = 0
    hsn_code: str = ""
    alternatives: list[dict] = field(default_factory=list)

    @property
    def matched(self) -> bool:
        return self.sku_id is not None


def load(force: bool = False) -> list[dict]:
    """Cached catalog. TTL is short so an owner adding a SKU mid-demo still works."""
    stale = force or (time.time() - float(_CACHE["at"])) > _TTL_SECONDS
    if stale or not _CACHE["rows"]:
        rows = [snap.to_dict() for snap in db().collection("catalog").stream()]
        _CACHE["rows"] = [r for r in rows if r and r.get("active", True)]
        _CACHE["at"] = time.time()
    return list(_CACHE["rows"])            # type: ignore[arg-type]


def invalidate() -> None:
    _CACHE["at"] = 0.0


def normalise(text: str) -> str:
    """Fold a printed or spoken line down to its identifying tokens.

    Supplier invoices are written in shorthand — `G.I.PIPE 3/4" HVY 6MTR` — so
    dotted acronyms are rejoined (`g i pipe` -> `gi pipe`), digits are split off
    the words they are glued to (`6mtr` -> `6 mtr`), and quantity words, units
    and bare numbers are dropped, because they are never identity.
    """
    text = (text or "").lower().strip()
    for glyph, plain in _FRACTIONS.items():
        text = text.replace(glyph, plain)
    text = text.replace('"', " inch ").replace("″", " inch ")
    text = re.sub(r"[^\w஀-௿/.\s]", " ", text)
    text = text.replace(".", " ")
    text = re.sub(r"(?<=\d)(?=[a-z])|(?<=[a-z])(?=\d)", " ", text)

    tokens = [t for t in text.split()
              if t and t not in _NOISE and t not in _QTY_WORDS
              and not re.fullmatch(r"\d+(\.\d+)?", t)]

    # Rejoin what was a dotted acronym before the split above.
    folded: list[str] = []
    for token in tokens:
        if len(token) == 1 and token.isalpha() and folded and folded[-1].isalpha() \
                and len(folded[-1]) <= 2:
            folded[-1] += token
        else:
            folded.append(token)
    return " ".join(folded)


def parse_qty(text: str) -> tuple[float, str]:
    """('4 inch hinge 50 nos') -> (50.0, 'piece').

    Hardware lines are full of numbers that are *not* quantities — "53 grade",
    "3/4 inch", "1.5 sq mm". So a number only counts as a quantity when it sits
    next to a unit word, leads the line, or follows an "x". Otherwise the line
    is treated as qty 1 and the owner corrects it; a wrong quantity is worse
    than an obvious one.
    """
    lowered = (text or "").lower()
    for glyph, plain in _FRACTIONS.items():
        lowered = lowered.replace(glyph, plain)
    units = "|".join(sorted((re.escape(u) for u in _UNIT_WORDS), key=len, reverse=True))

    for pattern in (rf"(\d+(?:\.\d+)?)\s*({units})(?![a-z0-9])",   # 20 bags
                    rf"({units})(?![a-z0-9])\s*[:x×]?\s*(\d+(?:\.\d+)?)"):  # bags 20
        found = re.search(pattern, lowered)
        if found:
            groups = found.groups()
            number, unit = (groups if groups[0][0].isdigit() else groups[::-1])
            return float(number), _UNIT_WORDS[unit]

    lead = re.match(r"\s*(\d+(?:\.\d+)?)\s+(?!/)(\S+)", lowered)
    if lead and lead.group(2).strip(".,") not in _MEASURE_SUFFIX:
        return float(lead.group(1)), ""

    times = re.search(r"[x×]\s*(\d+(?:\.\d+)?)\s*$", lowered.strip())
    if times:
        return float(times.group(1)), ""

    for word, value in {**_EN_NUMBERS, **_TAMIL_NUMBERS}.items():
        if re.search(rf"\b{re.escape(word)}\b", lowered):
            return float(value), ""

    return 1.0, ""


def _haystack(row: dict) -> list[str]:
    values = [row.get("name", ""), row.get("name_ta", "") or ""]
    values += list(row.get("aliases") or [])
    values.append(f"{row.get('brand','')} {row.get('category','')}")
    return [normalise(v) for v in values if v]


def _score(needle: str, row: dict) -> tuple[float, bool]:
    """(score 0-1, exact_alias_hit). An exact alias hit is the strongest signal
    a shop catalog can give — "3/4 pipe" *is* the CPVC line, whatever else it
    fuzzy-matches."""
    candidates = _haystack(row)
    if not needle or not candidates:
        return 0.0, False
    exact = needle in candidates
    best = process.extractOne(needle, candidates, scorer=fuzz.token_set_ratio)
    partial = max(fuzz.partial_ratio(needle, c) for c in candidates)
    vocabulary = {token for c in candidates for token in c.split()}
    wanted = needle.split()
    coverage = sum(1 for t in wanted if t in vocabulary) / len(wanted)
    # token_set carries the shape, partial rescues a name buried in a long
    # transcript fragment, coverage is what separates "gi pipe" from "3/4 pipe".
    score = (0.50 * (best[1] if best else 0) + 0.20 * partial
             + 0.30 * coverage * 100) / 100.0
    return score, exact


def match(raw: str, catalog: list[dict] | None = None) -> Match:
    """Resolve one raw line to a SKU with a confidence and top-3 alternatives."""
    rows = catalog if catalog is not None else load()
    needle = normalise(raw)
    scored = []
    for row in rows:
        score, exact = _score(needle, row)
        scored.append((score + (0.35 if exact else 0.0), exact, row))
    scored.sort(key=lambda t: t[0], reverse=True)

    def alts(items):
        return [{"sku_id": r.get("sku_id"), "name": r.get("name"),
                 "confidence": round(min(s, 0.99), 2)} for s, _, r in items[:3]]

    if not scored or scored[0][0] < 0.45:
        return Match(None, raw.strip(),
                     round(min(scored[0][0], 0.99), 2) if scored else 0.0,
                     alternatives=alts(scored))

    score, exact, row = scored[0]
    runner_up = scored[1][0] if len(scored) > 1 else 0.0
    if exact:
        confidence = min(0.99, max(0.9, score))
    else:
        # A close second means genuine ambiguity — dock the confidence so the
        # line surfaces for confirmation instead of quietly picking a coin-flip.
        confidence = score - max(0.0, 0.30 - (score - runner_up))
    return Match(
        sku_id=row.get("sku_id"), name=row.get("name", ""),
        confidence=round(max(0.0, min(0.99, confidence)), 2),
        unit=row.get("unit", ""), gst_rate=row.get("gst_rate", 0),
        hsn_code=row.get("hsn_code", ""), alternatives=alts(scored),
    )


def rate_for(sku: dict, tier: str) -> int:
    tiers = sku.get("price_tiers") or {}
    return int(tiers.get(tier) or tiers.get("retail") or 0)


def by_id(sku_id: str, catalog: list[dict] | None = None) -> dict | None:
    for row in (catalog if catalog is not None else load()):
        if row.get("sku_id") == sku_id:
            return row
    return None
