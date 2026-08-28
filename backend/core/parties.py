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
    """(party_id, normalised name) for every name a party goes by."""
    rows: list[tuple[str, str]] = []
    for snap in db().collection("parties").stream():
        party = snap.to_dict() or {}
        for name in (party.get("name"), party.get("name_ta")):
            if name:
                rows.append((snap.id, catalog.normalise(name)))
    return rows


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
