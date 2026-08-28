"""Datastore handle + the one blessed way to move money.

`db()` returns a real Firestore client when credentials exist, and the local
JSON shim otherwise. Both expose the same surface, so agents never branch on it.

`run_transaction(fn)` is the *only* sanctioned way to write anything that
touches a balance, stock level or ledger entry. Inside `fn`, read with
`ref.get(transaction=txn)` and write with `txn.set(...)` / `txn.update(...)`;
that call style is identical on both backends.
"""
from functools import lru_cache
from typing import Any, Callable

from core.config import LOCAL_DATA_DIR, LOCAL_STORE, PROJECT


@lru_cache(maxsize=1)
def db():
    if LOCAL_STORE:
        from core.localstore import LocalClient
        return LocalClient(LOCAL_DATA_DIR)
    from google.cloud import firestore
    return firestore.Client(project=PROJECT)


def run_transaction(fn: Callable[[Any], Any]) -> Any:
    """Execute `fn(transaction)` atomically. Raises → nothing is written."""
    client = db()
    if LOCAL_STORE:
        with client.transaction() as txn:
            return fn(txn)
    from google.cloud import firestore

    @firestore.transactional
    def _wrapped(transaction):
        return fn(transaction)

    return _wrapped(client.transaction())
