"""The only places money moves.

Each function here maps to one "Transaction boundary" in docs/firestore-schema.md
and does all of its writes inside a single Firestore transaction, so a crash
between two of them is impossible.

Invariants held here, not by callers:
  * `ledger` is append-only. A correction is a new reversing entry.
  * `parties.credit.outstanding` is maintained, never summed on read, and only
    ever changes in the same transaction as the ledger entry that explains it.
  * `purchases.stock_applied` guards the inventory increment, so a Pub/Sub
    redelivery cannot double-count a supplier bill.
"""
from __future__ import annotations

from datetime import datetime, timezone

from core import ids, provisioning
from core.firestore_client import db, run_transaction


def _today() -> str:
    return datetime.now(timezone.utc).date().isoformat()


def _ledger_ref(entry_id: str):
    return db().collection("ledger").document(entry_id)


def approve_order(order_id: str, note: str = "", by: str = "owner") -> dict:
    """Ledger entry + party balance + order status, atomically.

    Debit on a sale means "the customer owes us more", which is why the party's
    outstanding goes up by the full GST-inclusive total.
    """
    order_ref = db().collection("orders").document(order_id)

    def txn_body(txn):
        order = (order_ref.get(transaction=txn).to_dict() or {})
        if not order:
            raise LookupError(f"order {order_id} not found")
        if order.get("status") == "approved":
            return {"order_id": order_id, "already": True,
                    "entry_id": (order.get("owner_action") or {}).get("entry_id")}

        # A SKU created from a supplier bill is received into stock but has no
        # selling price until a human sets one. Approving an order containing it
        # would post a ledger entry that understates the sale — money moving on a
        # number nobody chose. Refuse, and say which line.
        unpriced = [line.get("name_raw") or line.get("sku_id")
                    for line in order.get("lines") or []
                    if line.get("sku_id") and not int(line.get("rate") or 0)]
        if unpriced:
            raise ValueError(
                "cannot approve: no selling price set for " + ", ".join(map(str, unpriced)))

        party_ref = db().collection("parties").document(order["party_id"])
        party = party_ref.get(transaction=txn).to_dict() or {}
        credit = dict(party.get("credit") or {})
        total = int(order.get("total") or 0)
        balance_after = int(credit.get("outstanding") or 0) + total

        entry_id = ids.entry_id()
        txn.set(_ledger_ref(entry_id), {
            "entry_id": entry_id, "party_id": order["party_id"], "date": _today(),
            "type": "sale_credit", "amount": total, "direction": "debit",
            "balance_after": balance_after,
            "ref": {"type": "order", "id": order_id},
            "source": "owner", "note": note or f"Order {order_id} approved",
            "created_at": datetime.now(timezone.utc),
        })
        txn.update(party_ref, {"credit.outstanding": balance_after,
                               "updated_at": datetime.now(timezone.utc)})
        txn.update(order_ref, {
            "status": "approved",
            "owner_action": {"action": "approve", "at": datetime.now(timezone.utc),
                             "note": note, "by": by, "entry_id": entry_id},
        })
        return {"order_id": order_id, "entry_id": entry_id,
                "balance_after": balance_after, "amount": total}

    return run_transaction(txn_body)


def record_owner_action(order_id: str, action: str, note: str = "",
                        advance: int = 0, by: str = "owner") -> dict:
    """Decisions that do *not* move money: asking for an advance, declining.

    Nothing is posted to the ledger, because nothing has been sold yet — the
    quotation is held until the contractor responds. Kept separate from
    `approve_order` so that reading the call site tells you whether money moved.
    """
    status = {"part_payment": "awaiting_approval", "reject": "rejected",
              "modify": "draft"}.get(action, "awaiting_approval")
    db().collection("orders").document(order_id).update({
        "status": status,
        "owner_action": {"action": action, "at": datetime.now(timezone.utc),
                         "note": note, "advance": int(advance), "by": by},
    })
    return {"order_id": order_id, "status": status, "advance": int(advance)}


def confirm_purchase(purchase_id: str) -> dict:
    """Stock increments + supplier payable + `stock_applied`, atomically.

    `stock_applied` is read inside the transaction, so a redelivered Pub/Sub
    message or a double-tap cannot increment stock twice.
    """
    purchase_ref = db().collection("purchases").document(purchase_id)

    def txn_body(txn):
        purchase = purchase_ref.get(transaction=txn).to_dict() or {}
        if not purchase:
            raise LookupError(f"purchase {purchase_id} not found")
        if purchase.get("stock_applied"):
            return {"purchase_id": purchase_id, "already": True,
                    "stock_delta": purchase.get("stock_delta") or []}

        # A line for a product the shop has never stocked carries a proposed
        # catalog record. Create it here, not at scan time, so a bill that gets
        # discarded leaves no phantom products behind.
        lines = list(purchase.get("lines") or [])
        created_skus = []
        for line in lines:
            if line.get("sku_id") or not line.get("new_sku"):
                continue
            if line.get("near_miss"):
                continue      # too close to something we stock; the owner decides
            sku_id = provisioning.create_sku(txn, line["new_sku"], purchase_id)
            line["sku_id"] = sku_id
            line["matched"] = True
            created_skus.append(sku_id)

        # Total the lines per SKU *before* touching inventory. A supplier
        # routinely splits one SKU across several lines, and a transaction
        # cannot see its own writes — so reading and writing a document once
        # per line would read stale on every line after the first and keep only
        # the last increment.
        wanted: dict[str, int] = {}
        for line in lines:
            sku_id = line.get("sku_id")
            if sku_id:
                wanted[sku_id] = wanted.get(sku_id, 0) + int(line.get("qty") or 0)

        delta = []
        for sku_id, qty in wanted.items():
            inventory_ref = db().collection("inventory").document(sku_id)
            current = inventory_ref.get(transaction=txn).to_dict() or {}
            before = int(current.get("qty_on_hand") or 0)
            after = before + qty
            txn.set(inventory_ref, {
                "sku_id": sku_id, "qty_on_hand": after,
                "reorder_level": current.get("reorder_level", 15),
                "last_updated": datetime.now(timezone.utc),
                "last_purchase_id": purchase_id,
            })
            delta.append({"sku_id": sku_id, "before": before, "after": after})

        supplier_id = purchase.get("supplier_id")
        total = int((purchase.get("totals") or {}).get("total") or 0)
        entry_id = ids.entry_id()
        balance_after = total
        if supplier_id:
            supplier_ref = db().collection("parties").document(supplier_id)
            supplier = supplier_ref.get(transaction=txn).to_dict() or {}
            credit = dict(supplier.get("credit") or {})
            balance_after = int(credit.get("outstanding") or 0) + total
            txn.update(supplier_ref, {"credit.outstanding": balance_after,
                                      "updated_at": datetime.now(timezone.utc)})
        txn.set(_ledger_ref(entry_id), {
            "entry_id": entry_id, "party_id": supplier_id, "date": _today(),
            "type": "purchase_credit", "amount": total, "direction": "credit",
            "balance_after": balance_after,
            "ref": {"type": "purchase", "id": purchase_id},
            "source": "owner",
            "note": f"Invoice {purchase.get('invoice_no') or purchase_id}",
            "created_at": datetime.now(timezone.utc),
        })
        txn.update(purchase_ref, {
            "status": "confirmed", "stock_applied": True, "stock_delta": delta,
            "lines": lines, "created_skus": created_skus,
            "payable_ledger_id": entry_id,
            "confirmed_at": datetime.now(timezone.utc),
        })
        return {"purchase_id": purchase_id, "stock_delta": delta,
                "created_skus": created_skus,
                "payable_ledger_id": entry_id, "amount": total}

    result = run_transaction(txn_body)
    if result.get("created_skus"):
        # The catalog is cached in-process for read speed; a SKU created a
        # moment ago has to be visible to the very next line that mentions it.
        from core import catalog
        catalog.invalidate()
    return result


def commit_khata_import(import_id: str) -> dict:
    """Every confirmed row becomes a ledger entry and moves its party's balance,
    in one transaction. Rows still needing confirmation are left alone — a bad
    OCR read must never silently change a balance."""
    import_ref = db().collection("khata_imports").document(import_id)

    def txn_body(txn):
        record = import_ref.get(transaction=txn).to_dict() or {}
        if not record:
            raise LookupError(f"khata import {import_id} not found")
        if record.get("status") == "committed":
            return {"import_id": import_id, "already": True,
                    "posted": record.get("posted_count", 0)}

        rows = list(record.get("rows") or [])

        # Open an account for any confirmed row naming somebody we have never
        # traded with. Same transaction as the ledger entries, so a discarded
        # import never leaves an empty profile behind.
        created_parties = []
        for row in rows:
            if row.get("status") not in {"auto_accepted", "confirmed"}:
                continue
            if row.get("party_id") or not row.get("new_party"):
                continue
            if row.get("near_miss"):
                continue      # might be an existing contractor; the owner decides
            party_id = provisioning.create_party(txn, row["new_party"], import_id)
            row["party_id"] = party_id
            created_parties.append(party_id)

        postable = [r for r in rows
                    if r.get("status") in {"auto_accepted", "confirmed"}
                    and r.get("party_id")]
        balances: dict[str, int] = {}
        posted = 0
        for row in postable:
            party_id = row["party_id"]
            party_ref = db().collection("parties").document(party_id)
            if party_id not in balances:
                if party_id in created_parties:
                    # Just created in this transaction, so it cannot be read back
                    # — Firestore reads never see a transaction's own writes.
                    balances[party_id] = 0
                else:
                    party = party_ref.get(transaction=txn).to_dict() or {}
                    balances[party_id] = int(
                        (party.get("credit") or {}).get("outstanding") or 0)
            amount = int(row.get("amount") or 0)
            is_payment = row.get("entry_type") == "payment_received"
            balances[party_id] += -amount if is_payment else amount

            entry_id = ids.entry_id()
            txn.set(_ledger_ref(entry_id), {
                "entry_id": entry_id, "party_id": party_id,
                "date": row.get("date") or _today(),
                "type": row.get("entry_type") or "sale_credit",
                "amount": amount,
                "direction": "credit" if is_payment else "debit",
                "balance_after": balances[party_id],
                "ref": {"type": "khata_import", "id": import_id},
                "source": "khata_import",
                "note": f"Page {record.get('page_no')} row {row.get('row_id')}",
                "created_at": datetime.now(timezone.utc),
            })
            row["ledger_entry_id"] = entry_id
            posted += 1

        for party_id, balance in balances.items():
            txn.update(db().collection("parties").document(party_id),
                       {"credit.outstanding": balance,
                        "updated_at": datetime.now(timezone.utc)})
        txn.update(import_ref, {"status": "committed", "rows": rows,
                                "posted_count": posted,
                                "created_parties": created_parties,
                                "committed_at": datetime.now(timezone.utc)})
        return {"import_id": import_id, "posted": posted,
                "created_parties": created_parties,
                "parties_touched": len(balances)}

    return run_transaction(txn_body)
