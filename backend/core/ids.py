"""Human-readable sequential ids.

Order numbers are read aloud in a shop ("quotation ten forty-three"), so they
are sequential, not random. Kept in a counter document and bumped in a
transaction, because two ingests can land in the same second.
"""
from __future__ import annotations

import uuid
from datetime import date

from core.firestore_client import db, run_transaction
from core.tax import counter_key, financial_year, invoice_number

_SEEDS = {"orders": 1042, "purchases": 2870, "khata_imports": 11}

# A tax invoice series restarts at 1 every financial year, so the FY-scoped
# counters seed at 0 rather than at the shop-flavoured numbers above.
_FY_SEED = 0


def next_seq(kind: str) -> int:
    ref = db().collection("counters").document(kind)
    seed = _FY_SEED if "#" in kind else _SEEDS.get(kind, 1000)

    def bump(txn):
        snap = ref.get(transaction=txn)
        current = (snap.to_dict() or {}).get("value", seed)
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


def next_invoice_number(prefix: str = "SBH", on: date | None = None) -> str:
    """`SBH/26-27/0042` — consecutive and gapless within the financial year.

    The sequence is bumped inside a transaction and the number is minted from
    whatever comes back, never read-then-written: two counter sales rung up in
    the same second must not be handed the same invoice number, because a
    duplicate is the one defect a GST return cannot absorb.

    Allocation happens at bill time and not a moment earlier. A number handed
    out when the screen opens and abandoned when the customer walks away is a
    gap in the series, and a gap is what an auditor asks about.
    """
    fy = financial_year(on)
    return invoice_number(next_seq(counter_key("invoice", fy=fy)),
                          prefix=prefix, fy=fy)


def next_quote_number(prefix: str = "SBH", on: date | None = None) -> str:
    """`SBHQ/26-27/0007` — quotations run on their own series.

    A quotation has no ledger effect until it is approved, so it must never
    consume a tax-invoice number: a quote the customer never took would leave a
    hole in the invoice series that an auditor will ask about. The `Q` rides in
    the prefix so the two series are unmistakable at a glance on a printed page.
    """
    fy = financial_year(on)
    return invoice_number(next_seq(counter_key("quote", fy=fy)),
                          prefix=f"{prefix}Q", fy=fy)
