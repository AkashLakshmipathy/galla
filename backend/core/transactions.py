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
            # Already sold. Returning early is what keeps a redelivered message
            # or a double-tap from deducting the stock twice.
            return {"order_id": order_id, "already": True,
                    "entry_id": (order.get("owner_action") or {}).get("entry_id"),
                    "stock_delta": order.get("stock_delta") or []}

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

        # Goods leaving the shop have to leave the stock count in the same
        # breath as the money entering the ledger. Without this, buying adds and
        # selling never subtracts: the count drifts upward forever, the low-stock
        # warnings become fiction, and the substitute suggestion stops firing on
        # the very line it exists for.
        #
        # Totalled per SKU first, for the same reason the purchase side is: a
        # transaction cannot see its own writes, so one read-modify-write per
        # line would keep only the last.
        sold: dict[str, float] = {}
        for line in order.get("lines") or []:
            sku_id = line.get("sku_id")
            if sku_id:
                sold[sku_id] = sold.get(sku_id, 0) + float(line.get("qty") or 0)

        # Read every inventory document first. One read-then-write per SKU is
        # what Firestore refuses, and it only shows up on the second line.
        on_hand = {sku_id: (db().collection("inventory").document(sku_id)
                            .get(transaction=txn).to_dict() or {})
                   for sku_id in sold}

        stock_delta = []
        for sku_id, qty in sold.items():
            inventory_ref = db().collection("inventory").document(sku_id)
            current = on_hand[sku_id]
            before = int(current.get("qty_on_hand") or 0)
            after = int(before - qty)
            # A shop routinely promises goods it has not received yet. Refusing
            # the sale would be wrong; hiding the shortfall would be worse, so
            # the count is allowed to go negative and says so on screen.
            txn.set(inventory_ref, {
                "sku_id": sku_id, "qty_on_hand": after,
                "reorder_level": current.get("reorder_level", 15),
                "last_updated": datetime.now(timezone.utc),
                "last_order_id": order_id,
            })
            stock_delta.append({"sku_id": sku_id, "before": before, "after": after})

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
            "stock_delta": stock_delta,
            "owner_action": {"action": "approve", "at": datetime.now(timezone.utc),
                             "note": note, "by": by, "entry_id": entry_id},
        })
        return {"order_id": order_id, "entry_id": entry_id,
                "balance_after": balance_after, "amount": total,
                "stock_delta": stock_delta}

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

    Every read happens before every write. Firestore requires that and raises
    `ReadAfterWriteError` otherwise — creating a catalogue row and then reading
    an inventory document failed with a 500 the first time a real shop pressed
    Save on a bill containing a product it had never stocked.

    `stock_applied` is read inside the transaction, so a redelivered Pub/Sub
    message or a double-tap cannot increment stock twice.
    """
    purchase_ref = db().collection("purchases").document(purchase_id)

    def txn_body(txn):
        # ---- reads ---------------------------------------------------------
        purchase = purchase_ref.get(transaction=txn).to_dict() or {}
        if not purchase:
            raise LookupError(f"purchase {purchase_id} not found")
        if purchase.get("stock_applied"):
            return {"purchase_id": purchase_id, "already": True,
                    "stock_delta": purchase.get("stock_delta") or [],
                    "created_skus": purchase.get("created_skus") or [],
                    "supplier_id": purchase.get("supplier_id"),
                    "created_supplier": purchase.get("created_supplier"),
                    "payable_ledger_id": purchase.get("payable_ledger_id"),
                    "amount": int((purchase.get("totals") or {}).get("total") or 0)}

        lines = list(purchase.get("lines") or [])
        # Which lines bring a product the shop has never stocked. Decided now;
        # written later.
        to_create = [line for line in lines
                     if not line.get("sku_id") and line.get("new_sku")
                     and not line.get("near_miss")]

        # Total per SKU before touching inventory: a supplier splits one product
        # across several lines, and a transaction cannot see its own writes.
        wanted: dict[str, int] = {}
        for line in lines:
            sku_id = line.get("sku_id") or (
                line["new_sku"]["sku_id"] if line in to_create else None)
            if sku_id:
                wanted[sku_id] = wanted.get(sku_id, 0) + int(line.get("qty") or 0)

        existing_stock = {}
        for sku_id in wanted:
            if any(l["new_sku"]["sku_id"] == sku_id for l in to_create):
                continue                     # about to be created; starts at zero
            existing_stock[sku_id] = (
                db().collection("inventory").document(sku_id)
                .get(transaction=txn).to_dict() or {})

        supplier_id = purchase.get("supplier_id")
        creating_supplier = not supplier_id and purchase.get("new_supplier")
        supplier_balance = 0
        if supplier_id:
            supplier = (db().collection("parties").document(supplier_id)
                        .get(transaction=txn).to_dict() or {})
            supplier_balance = int((supplier.get("credit") or {}).get("outstanding") or 0)

        # ---- writes --------------------------------------------------------
        created_skus = []
        for line in to_create:
            sku_id = provisioning.create_sku(txn, line["new_sku"], purchase_id)
            line["sku_id"] = sku_id
            line["matched"] = True
            created_skus.append(sku_id)

        created_supplier = None
        if creating_supplier:
            supplier_id = provisioning.create_party(
                txn, purchase["new_supplier"], purchase_id)
            created_supplier = supplier_id

        delta = []
        for sku_id, qty in wanted.items():
            current = existing_stock.get(sku_id, {})
            before = int(current.get("qty_on_hand") or 0)
            after = before + qty
            txn.set(db().collection("inventory").document(sku_id), {
                "sku_id": sku_id, "qty_on_hand": after,
                "reorder_level": current.get("reorder_level", 15),
                "last_updated": datetime.now(timezone.utc),
                "last_purchase_id": purchase_id,
            })
            delta.append({"sku_id": sku_id, "before": before, "after": after})

        total = int((purchase.get("totals") or {}).get("total") or 0)
        balance_after = supplier_balance + total
        entry_id = ids.entry_id()
        if supplier_id:
            txn.update(db().collection("parties").document(supplier_id),
                       {"credit.outstanding": balance_after,
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
            "supplier_id": supplier_id, "created_supplier": created_supplier,
            "payable_ledger_id": entry_id,
            "confirmed_at": datetime.now(timezone.utc),
        })
        return {"purchase_id": purchase_id, "stock_delta": delta,
                "created_skus": created_skus, "supplier_id": supplier_id,
                "created_supplier": created_supplier,
                "payable_ledger_id": entry_id, "amount": total}

    result = run_transaction(txn_body)
    if result.get("created_skus"):
        from core import catalog
        catalog.invalidate()
    return result


def commit_khata_import(import_id: str) -> dict:
    """Every confirmed row becomes a ledger entry and moves its party's balance,
    in one transaction. Rows still needing confirmation are left alone — a bad
    OCR read must never silently change a balance.

    Reads first, writes second: opening an account and then reading another
    party's balance is the interleaving Firestore refuses.
    """
    import_ref = db().collection("khata_imports").document(import_id)

    def txn_body(txn):
        # ---- reads ---------------------------------------------------------
        record = import_ref.get(transaction=txn).to_dict() or {}
        if not record:
            raise LookupError(f"khata import {import_id} not found")
        if record.get("status") == "committed":
            return {"import_id": import_id, "already": True,
                    "posted": record.get("posted_count", 0),
                    "created_parties": record.get("created_parties") or []}

        rows = list(record.get("rows") or [])
        confirmed = [r for r in rows
                     if r.get("status") in {"auto_accepted", "confirmed"}]

        # Which rows name somebody with no account yet. One proposal per person,
        # however many lines mention them.
        to_open: dict[str, dict] = {}
        for row in confirmed:
            if row.get("party_id") or not row.get("new_party") or row.get("near_miss"):
                continue
            to_open.setdefault(row["new_party"]["party_id"], row["new_party"])

        balances: dict[str, int] = {pid: 0 for pid in to_open}
        for row in confirmed:
            party_id = row.get("party_id")
            if party_id and party_id not in balances:
                party = (db().collection("parties").document(party_id)
                         .get(transaction=txn).to_dict() or {})
                balances[party_id] = int(
                    (party.get("credit") or {}).get("outstanding") or 0)

        # ---- writes --------------------------------------------------------
        created_parties = [provisioning.create_party(txn, proposed, import_id)
                           for proposed in to_open.values()]
        for row in confirmed:
            if not row.get("party_id") and row.get("new_party") \
                    and not row.get("near_miss"):
                row["party_id"] = row["new_party"]["party_id"]

        posted = 0
        for row in confirmed:
            party_id = row.get("party_id")
            if not party_id:
                continue
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
