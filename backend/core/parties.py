"""Resolving a written or spoken name to a party.

Shared by the Khata Digitizer (a name in handwriting) and the confirm queue (the
owner picking a party off a list). A single implementation matters here: if the
queue resolved names differently from the agent, correcting a row could silently
attach it to a different contractor's ledger than the one shown on screen.
"""
from __future__ import annotations

from rapidfuzz import fuzz

from core import catalog
from core.firestore_client import db

MIN_SCORE = 0.8


def index() -> list[tuple[str, str]]:
    """(party_id, normalised name) for every name a party goes by.

    Includes learned aliases and the names of profiles merged into this one, so
    twenty years of a khata spelling somebody four ways still lands on one
    account.
    """
    rows: list[tuple[str, str]] = []
    for snap in db().collection("parties").stream():
        party = snap.to_dict() or {}
        if party.get("merged_into"):
            continue
        known = [party.get("name"), party.get("name_ta"),
                 *(party.get("aliases") or []),
                 *(party.get("aliases_merged") or [])]
        for name in known:
            if name:
                rows.append((snap.id, catalog.normalise(name)))
    return rows


def learn_alias(party_id: str, name_raw: str) -> bool:
    """Remember that this customer is also written *this* way.

    A khata spells one man "Kumar Tiruppur", "Tiruppur Kumar" and "Kumar T"
    across three pages. Resolving one and forgetting is how a single debtor ends
    up as three accounts with a third of his debt each — which is exactly the
    state the merge tool exists to clean up after.
    """
    normalised = catalog.normalise(name_raw)
    if not party_id or not normalised:
        return False
    ref = db().collection("parties").document(party_id)
    party = ref.get().to_dict()
    if not party:
        return False
    known = {catalog.normalise(n) for n in
             [party.get("name"), party.get("name_ta"), *(party.get("aliases") or [])]
             if n}
    if normalised in known:
        return False
    aliases = list(party.get("aliases") or [])
    aliases.append(name_raw.strip())
    ref.update({"aliases": aliases[-30:]})
    return True


def match(name_raw: str, rows: list[tuple[str, str]] | None = None
          ) -> tuple[str | None, float]:
    """(party_id or None, score 0-1). Below `MIN_SCORE` the caller must ask."""
    rows = rows if rows is not None else index()
    needle = catalog.normalise(name_raw or "")
    best_id, best = None, 0.0
    for party_id, name in rows:
        score = fuzz.token_set_ratio(needle, name) / 100.0
        if score > best:
            best_id, best = party_id, score
    return (best_id, best) if best >= MIN_SCORE else (None, best)
