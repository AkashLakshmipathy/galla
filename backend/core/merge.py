"""Merging duplicate party profiles.

Two profiles for one contractor is the worst failure this system can have: his
real exposure is the sum of both, while the Credit Guardian only ever sees one,
so the shop can extend nearly double the credit it thinks it has. The scanning
agents refuse to auto-create in the ambiguous band precisely to avoid it — but
handwriting varies, a name gets spelled two ways over twenty years, and
duplicates arrive anyway. This is how they get fixed.

**The ledger is not rewritten.** `docs/firestore-schema.md` says ledger rows are
never updated or deleted, and that rule is not suspended because two rows turned
out to be the same person. Repointing `party_id` on historical entries would
make an old page of the khata silently disappear from the profile it was filed
under, which is exactly the kind of quiet history-editing the append-only rule
exists to prevent.

So instead: the balance moves, the source is marked `merged_into`, its documents
are repointed, and **reads of the survivor union in the merged profile's entries**.
Nothing is destroyed, the audit trail is intact, and because nothing is
destroyed a merge could be undone later.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone

from rapidfuzz import fuzz

from core import catalog
from core.firestore_client import db, run_transaction

# Deliberately lower than the agents' matching threshold: this list is a
# suggestion for a human to look at, not an action. Missing a real duplicate
# costs far more than showing one extra pair.
SUGGEST_THRESHOLD = 0.62


@dataclass
class DuplicatePair:
    a: str
    b: str
    score: float
    reason: str
    combined_outstanding: int


def _names(party: dict) -> list[str]:
    return [n for n in (party.get("name"), party.get("name_ta")) if n]


def _score(one: dict, two: dict) -> tuple[float, str]:
    """How likely are these the same trader? Returns (score, why)."""
    # An identical phone or GSTIN is proof, not a guess.
    for field, label in (("phone", "same phone number"), ("gstin", "same GSTIN")):
        a, b = one.get(field), two.get(field)
        if a and b and a == b:
            return 1.0, label

    best = 0.0
    for x in _names(one):
        for y in _names(two):
            best = max(best, fuzz.token_set_ratio(
                catalog.normalise(x), catalog.normalise(y)) / 100.0)
    return best, "similar name"


def find_duplicates(limit: int = 20) -> list[DuplicatePair]:
    """Every pair of live profiles that might be the same trader."""
    rows = [(s.id, s.to_dict() or {}) for s in db().collection("parties").stream()]
    rows = [(i, p) for i, p in rows if not p.get("merged_into")]
    pairs: list[DuplicatePair] = []
    for index, (a_id, a) in enumerate(rows):
        for b_id, b in rows[index + 1:]:
            if a.get("type") != b.get("type"):
                continue                    # a customer is not its own supplier
            score, reason = _score(a, b)
            if score < SUGGEST_THRESHOLD:
                continue
            pairs.append(DuplicatePair(
                a=a_id, b=b_id, score=round(score, 2), reason=reason,
                combined_outstanding=int((a.get("credit") or {}).get("outstanding") or 0)
                + int((b.get("credit") or {}).get("outstanding") or 0)))
    pairs.sort(key=lambda p: p.score, reverse=True)
    return pairs[:limit]


def resolve(party_id: str, seen: set[str] | None = None) -> str:
    """Follow a merge chain to the profile that survived. A → B → C gives C."""
    seen = seen or set()
    if party_id in seen:
        return party_id                     # cycle; refuse to loop
    snap = db().collection("parties").document(party_id).get()
    target = (snap.to_dict() or {}).get("merged_into") if snap.exists else None
    if not target:
        return party_id
    return resolve(target, seen | {party_id})


def merged_sources(party_id: str) -> list[str]:
    """Every profile that was folded into this one, at any depth."""
    out, frontier = [], [party_id]
    while frontier:
        current = frontier.pop()
        for snap in db().collection("parties").stream():
            data = snap.to_dict() or {}
            if data.get("merged_into") == current and snap.id not in out:
                out.append(snap.id)
                frontier.append(snap.id)
    return out


def _merge_credit(target: dict, source: dict) -> dict:
    """Combine two credit records without inventing anything.

    The survivor's limit stands — how much to trust someone is the owner's
    decision, and silently summing two limits would hand the trader more rope
    than anyone agreed to. Everything else combines the way the facts do.
    """
    t = dict(target.get("credit") or {})
    s = dict(source.get("credit") or {})
    dates = [d for d in (t.get("last_payment_date"), s.get("last_payment_date")) if d]
    t["outstanding"] = int(t.get("outstanding") or 0) + int(s.get("outstanding") or 0)
    t["last_payment_date"] = max(dates) if dates else None
    if dates and s.get("last_payment_date") == max(dates):
        t["last_payment_amount"] = s.get("last_payment_amount", 0)
    t["total_business_value"] = (int(t.get("total_business_value") or 0)
                                 + int(s.get("total_business_value") or 0))
    t["dispute_count"] = int(t.get("dispute_count") or 0) + int(s.get("dispute_count") or 0)
    averages = [int(x) for x in (t.get("avg_days_to_pay"), s.get("avg_days_to_pay")) if x]
    t["avg_days_to_pay"] = round(sum(averages) / len(averages)) if averages else 0
    return t


def merge_parties(source_id: str, target_id: str, by: str = "owner") -> dict:
    """Fold `source` into `target`. One transaction, nothing destroyed."""
    if source_id == target_id:
        raise ValueError("cannot merge a profile into itself")

    source_ref = db().collection("parties").document(source_id)
    target_ref = db().collection("parties").document(target_id)

    def txn_body(txn):
        source = source_ref.get(transaction=txn).to_dict()
        target = target_ref.get(transaction=txn).to_dict()
        if not source or not target:
            raise LookupError("both profiles must exist")
        if source.get("merged_into"):
            raise ValueError(f"{source_id} was already merged into "
                             f"{source['merged_into']}")
        if target.get("merged_into"):
            raise ValueError(f"{target_id} is itself merged into "
                             f"{target['merged_into']} — merge into that instead")

        moved = int((source.get("credit") or {}).get("outstanding") or 0)
        combined = _merge_credit(target, source)
        now = datetime.now(timezone.utc)

        # Every name the absorbed profile went by becomes a name the survivor
        # answers to, so the next khata page spelling it the old way lands on the
        # right account instead of opening the duplicate all over again.
        txn.update(target_ref, {
            "credit": combined,
            "aliases_merged": sorted(set(target.get("aliases_merged") or [])
                                     | set(_names(source))
                                     | set(source.get("aliases") or [])),
            "updated_at": now,
        })
        # The source keeps its history and its name; it simply stops being a
        # place money can land, and points at the profile that survived.
        txn.update(source_ref, {
            "merged_into": target_id,
            "credit.outstanding": 0,
            "active": False,
            "merged_at": now, "merged_by": by,
            "updated_at": now,
        })
        return {"source": source_id, "target": target_id,
                "moved_outstanding": moved,
                "combined_outstanding": combined["outstanding"]}

    result = run_transaction(txn_body)
    result["repointed"] = _repoint(source_id, target_id)
    return result


def _repoint(source_id: str, target_id: str) -> dict:
    """Move the documents that are *not* the append-only ledger.

    Orders, purchases and queue items name a party as a pointer, not as history,
    so they follow the merge. Ledger rows stay exactly where they were written;
    `party_ledger` unions them back in on read.
    """
    counts = {}
    for collection, field in (("orders", "party_id"), ("purchases", "supplier_id"),
                              ("confirm_queue", "resolved_value")):
        moved = 0
        for snap in db().collection(collection).stream():
            data = snap.to_dict() or {}
            if data.get(field) != source_id:
                continue
            snap.reference.update({field: target_id, "merged_from": source_id})
            moved += 1
        counts[collection] = moved

    rows_moved = 0
    for snap in db().collection("khata_imports").stream():
        record = snap.to_dict() or {}
        rows = list(record.get("rows") or [])
        touched = False
        for row in rows:
            if row.get("party_id") == source_id:
                row["party_id"] = target_id
                touched = True
                rows_moved += 1
        if touched:
            snap.reference.update({"rows": rows})
    counts["khata_rows"] = rows_moved
    return counts
