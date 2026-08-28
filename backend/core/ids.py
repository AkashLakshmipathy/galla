"""Human-readable sequential ids.

Order numbers are read aloud in a shop ("quotation ten forty-three"), so they
are sequential, not random. Kept in a counter document and bumped in a
transaction, because two ingests can land in the same second.
"""
from __future__ import annotations

import uuid

from core.firestore_client import db, run_transaction

_SEEDS = {"orders": 1042, "purchases": 2870, "khata_imports": 11}


def next_seq(kind: str) -> int:
    ref = db().collection("counters").document(kind)

    def bump(txn):
        snap = ref.get(transaction=txn)
        current = (snap.to_dict() or {}).get("value", _SEEDS.get(kind, 1000))
        value = int(current) + 1
        txn.set(ref, {"kind": kind, "value": value})
        return value

    return run_transaction(bump)


def order_id() -> str:
    return f"ord_{next_seq('orders')}"


def purchase_id() -> str:
    return f"pur_{next_seq('purchases')}"


def import_id() -> str:
    return f"imp_{next_seq('khata_imports')}"


def entry_id() -> str:
    return f"led_{uuid.uuid4().hex[:12]}"


def item_id() -> str:
    return f"cq_{uuid.uuid4().hex[:10]}"
