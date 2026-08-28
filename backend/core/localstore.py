"""A tiny, Firestore-API-shaped JSON store for local development and offline demos.

Why this exists: the agent fleet, the transaction boundaries and the whole PWA
have to be runnable and testable without GCP credentials. This implements only
the surface `galla` actually uses — collection/document reads and writes,
`FieldFilter` queries, ordering, limits, and a serialised transaction — so that
`core.firestore_client.db()` can hand back either this or the real client and no
agent knows the difference.

Not a Firestore emulator. No indexes, no subcollections, no listeners, single
process, one lock around all writes. That is deliberate: it is a dev harness,
and every deployed path uses the real client.
"""
from __future__ import annotations

import json
import threading
import uuid
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any, Iterator

_LOCK = threading.RLock()
_DT_PREFIX = "@dt:"
_DATE_PREFIX = "@date:"


# ---------------------------------------------------------------- serialisation
def _encode(value: Any) -> Any:
    if isinstance(value, datetime):
        return _DT_PREFIX + value.astimezone(timezone.utc).isoformat()
    if isinstance(value, date):
        return _DATE_PREFIX + value.isoformat()
    if isinstance(value, dict):
        return {k: _encode(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_encode(v) for v in value]
    return value


def _decode(value: Any) -> Any:
    if isinstance(value, str):
        if value.startswith(_DT_PREFIX):
            return datetime.fromisoformat(value[len(_DT_PREFIX):])
        if value.startswith(_DATE_PREFIX):
            return date.fromisoformat(value[len(_DATE_PREFIX):])
        return value
    if isinstance(value, dict):
        return {k: _decode(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_decode(v) for v in value]
    return value


def _copy(value: Any) -> Any:
    """Hand out detached copies so callers can never mutate the store in place."""
    return _decode(_encode(value))


def _sort_key(value: Any):
    """Total order across the mixed types a demo dataset actually contains."""
    if value is None:
        return (0, "")
    if isinstance(value, bool):
        return (1, int(value))
    if isinstance(value, (int, float)):
        return (2, float(value))
    if isinstance(value, datetime):
        return (3, value.astimezone(timezone.utc).timestamp())
    if isinstance(value, date):
        return (3, datetime(value.year, value.month, value.day,
                            tzinfo=timezone.utc).timestamp())
    return (4, str(value))


def _get_path(data: dict, path: str) -> Any:
    cur: Any = data
    for part in path.split("."):
        if not isinstance(cur, dict):
            return None
        cur = cur.get(part)
    return cur


def _matches(data: dict, field: str, op: str, want: Any) -> bool:
    have = _get_path(data, field)
    if op == "==":
        return have == want
    if op == "!=":
        return have != want
    if op == "in":
        return have in (want or [])
    if op == "not-in":
        return have not in (want or [])
    if op == "array_contains":
        return isinstance(have, list) and want in have
    if op == "array_contains_any":
        return isinstance(have, list) and any(w in have for w in (want or []))
    if have is None:
        return False
    a, b = _sort_key(have), _sort_key(want)
    if op == "<":
        return a < b
    if op == "<=":
        return a <= b
    if op == ">":
        return a > b
    if op == ">=":
        return a >= b
    raise ValueError(f"unsupported operator {op!r}")


def _unpack_filter(args, kwargs) -> tuple[str, str, Any]:
    f = kwargs.get("filter")
    if f is not None:
        return f.field_path, f.op_string, f.value
    if len(args) == 3:
        return args
    if len(args) == 1 and hasattr(args[0], "field_path"):
        f = args[0]
        return f.field_path, f.op_string, f.value
    raise TypeError("where() needs filter=FieldFilter(...) or (field, op, value)")


# ------------------------------------------------------------------- snapshots
class DocumentSnapshot:
    def __init__(self, ref: "DocumentReference", data: dict | None):
        self.reference = ref
        self.id = ref.id
        self._data = data

    @property
    def exists(self) -> bool:
        return self._data is not None

    def to_dict(self) -> dict | None:
        return _copy(self._data) if self._data is not None else None

    def get(self, path: str) -> Any:
        return _get_path(self._data or {}, path)


# ------------------------------------------------------------------ references
class DocumentReference:
    def __init__(self, client: "LocalClient", collection: str, doc_id: str):
        self._client = client
        self.collection_name = collection
        self.id = doc_id
        self.path = f"{collection}/{doc_id}"

    # reads -------------------------------------------------------------
    def get(self, transaction: "Transaction | None" = None) -> DocumentSnapshot:
        if transaction is not None:
            return transaction.get(self)
        return DocumentSnapshot(self, self._client._read(self.collection_name, self.id))

    # writes ------------------------------------------------------------
    def set(self, data: dict, merge: bool = False) -> None:
        self._client._write(self.collection_name, self.id, data, merge=merge)

    def update(self, data: dict) -> None:
        self._client._update(self.collection_name, self.id, data)

    def delete(self) -> None:
        self._client._delete(self.collection_name, self.id)

    def __repr__(self) -> str:  # pragma: no cover
        return f"<LocalDocumentReference {self.path}>"


class Query:
    def __init__(self, client: "LocalClient", collection: str):
        self._client = client
        self._collection = collection
        self._filters: list[tuple[str, str, Any]] = []
        self._order: list[tuple[str, bool]] = []
        self._limit: int | None = None

    def _clone(self) -> "Query":
        q = Query(self._client, self._collection)
        q._filters = list(self._filters)
        q._order = list(self._order)
        q._limit = self._limit
        return q

    def where(self, *args, **kwargs) -> "Query":
        q = self._clone()
        q._filters.append(_unpack_filter(args, kwargs))
        return q

    def order_by(self, field: str, direction: str = "ASCENDING") -> "Query":
        q = self._clone()
        q._order.append((field, str(direction).upper().startswith("DESC")))
        return q

    def limit(self, count: int) -> "Query":
        q = self._clone()
        q._limit = count
        return q

    def stream(self, transaction=None) -> Iterator[DocumentSnapshot]:
        rows = self._client._all(self._collection)
        for field, op, want in self._filters:
            rows = [(i, d) for i, d in rows if _matches(d, field, op, want)]
        for field, reverse in reversed(self._order):
            rows.sort(key=lambda kv: _sort_key(_get_path(kv[1], field)), reverse=reverse)
        if self._limit is not None:
            rows = rows[: self._limit]
        for doc_id, data in rows:
            yield DocumentSnapshot(
                DocumentReference(self._client, self._collection, doc_id), data)

    def get(self, transaction=None) -> list[DocumentSnapshot]:
        return list(self.stream())


class CollectionReference(Query):
    def document(self, doc_id: str | None = None) -> DocumentReference:
        return DocumentReference(
            self._client, self._collection, doc_id or uuid.uuid4().hex[:20])

    def add(self, data: dict, document_id: str | None = None):
        ref = self.document(document_id)
        ref.set(data)
        return datetime.now(timezone.utc), ref

    def list_documents(self) -> list[DocumentReference]:
        return [DocumentReference(self._client, self._collection, i)
                for i, _ in self._client._all(self._collection)]


# ----------------------------------------------------------------- transaction
class Transaction:
    """Serialised, all-or-nothing, and deliberately *not* read-your-writes.

    Real Firestore buffers writes locally and does not send them until commit, so
    a read inside a transaction never sees a write made earlier in the same
    transaction — it returns the pre-transaction snapshot. Offering
    read-your-writes here would be *friendlier* and would let a transaction body
    pass locally, then silently lose a write in production. So the overlay is
    kept for commit ordering only, and `get` ignores it.

    Concurrency is handled by holding the global store lock for the duration —
    correct for a single-process dev harness, and the shape of the call sites is
    identical to the real client's, which is the point.
    """

    def __init__(self, client: "LocalClient"):
        self._client = client
        self._writes: list[tuple[str, DocumentReference, dict]] = []
        self._depth = 0

    def __enter__(self) -> "Transaction":
        _LOCK.acquire()
        self._depth += 1
        return self

    def __exit__(self, exc_type, exc, tb) -> bool:
        self._depth -= 1
        try:
            if exc is None:
                self._commit()
            else:
                self._writes.clear()
        finally:
            _LOCK.release()
        return False

    def get(self, ref) -> DocumentSnapshot:
        """The pre-transaction snapshot, exactly as Firestore would return it.

        Reads intentionally bypass `_overlay`: see the class docstring. If a
        transaction body needs the value it just wrote, it must carry that value
        forward itself rather than re-reading.
        """
        if isinstance(ref, Query) and not isinstance(ref, CollectionReference):
            return list(ref.stream())          # query-in-transaction
        return DocumentSnapshot(ref, self._client._read(ref.collection_name, ref.id))

    def set(self, ref: DocumentReference, data: dict, merge: bool = False) -> None:
        self._writes.append(("merge" if merge else "set", ref, _copy(data)))

    def update(self, ref: DocumentReference, data: dict) -> None:
        self._writes.append(("update", ref, _copy(data)))

    def delete(self, ref: DocumentReference) -> None:
        self._writes.append(("delete", ref, {}))

    def _commit(self) -> None:
        """Apply the buffered writes in order, the way Firestore's Commit does."""
        for kind, ref, data in self._writes:
            if kind == "set":
                self._client._write(ref.collection_name, ref.id, data)
            elif kind == "merge":
                self._client._write(ref.collection_name, ref.id, data, merge=True)
            elif kind == "update":
                self._client._update(ref.collection_name, ref.id, data)
            else:
                self._client._delete(ref.collection_name, ref.id)
        self._writes.clear()


def _set_path(data: dict, path: str, value: Any) -> None:
    parts = path.split(".")
    cur = data
    for part in parts[:-1]:
        nxt = cur.get(part)
        if not isinstance(nxt, dict):
            nxt = {}
            cur[part] = nxt
        cur = nxt
    cur[parts[-1]] = value


class WriteBatch:
    def __init__(self, client: "LocalClient"):
        self._client = client
        self._ops: list[tuple[str, DocumentReference, dict]] = []

    def set(self, ref, data, merge: bool = False):
        self._ops.append(("set", ref, data))

    def update(self, ref, data):
        self._ops.append(("update", ref, data))

    def delete(self, ref):
        self._ops.append(("delete", ref, {}))

    def commit(self):
        with _LOCK:
            for kind, ref, data in self._ops:
                if kind == "set":
                    self._client._write(ref.collection_name, ref.id, data)
                elif kind == "update":
                    self._client._update(ref.collection_name, ref.id, data)
                else:
                    self._client._delete(ref.collection_name, ref.id)
        self._ops.clear()


# ---------------------------------------------------------------------- client
class LocalClient:
    """One JSON file per collection under `root`."""

    def __init__(self, root: Path):
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)
        self._cache: dict[str, dict] = {}

    # storage ------------------------------------------------------------
    def _file(self, collection: str) -> Path:
        return self.root / f"{collection}.json"

    def _load(self, collection: str) -> dict:
        if collection in self._cache:
            return self._cache[collection]
        path = self._file(collection)
        if path.exists():
            raw = json.loads(path.read_text("utf-8"))
        else:
            raw = {}
        self._cache[collection] = {k: _decode(v) for k, v in raw.items()}
        return self._cache[collection]

    def _flush(self, collection: str) -> None:
        data = {k: _encode(v) for k, v in self._cache[collection].items()}
        tmp = self._file(collection).with_suffix(".json.tmp")
        tmp.write_text(json.dumps(data, ensure_ascii=False, indent=1), "utf-8")
        tmp.replace(self._file(collection))

    def _read(self, collection: str, doc_id: str) -> dict | None:
        with _LOCK:
            doc = self._load(collection).get(doc_id)
            return _copy(doc) if doc is not None else None

    def _all(self, collection: str) -> list[tuple[str, dict]]:
        with _LOCK:
            return [(k, _copy(v)) for k, v in self._load(collection).items()]

    def _write(self, collection: str, doc_id: str, data: dict, merge: bool = False) -> None:
        # Deep-copy in, always. A shallow copy would leave nested dicts shared
        # with the caller's object, so a later `update` on a nested path would
        # reach back and mutate whatever the caller still holds — which real
        # Firestore can never do, and which silently corrupted seed constants
        # the first time it happened.
        with _LOCK:
            store = self._load(collection)
            if merge and doc_id in store:
                merged = _copy(store[doc_id])
                merged.update(_copy(data))
                store[doc_id] = merged
            else:
                store[doc_id] = _copy(data)
            self._flush(collection)

    def _update(self, collection: str, doc_id: str, data: dict) -> None:
        with _LOCK:
            store = self._load(collection)
            current = _copy(store.get(doc_id) or {})
            for key, value in data.items():
                _set_path(current, key, _copy(value))
            store[doc_id] = current
            self._flush(collection)

    def _delete(self, collection: str, doc_id: str) -> None:
        with _LOCK:
            self._load(collection).pop(doc_id, None)
            self._flush(collection)

    # firestore.Client surface -------------------------------------------
    def collection(self, name: str) -> CollectionReference:
        return CollectionReference(self, name)

    def document(self, path: str) -> DocumentReference:
        collection, doc_id = path.split("/", 1)
        return DocumentReference(self, collection, doc_id)

    def transaction(self) -> Transaction:
        return Transaction(self)

    def batch(self) -> WriteBatch:
        return WriteBatch(self)

    def collections(self) -> list[CollectionReference]:
        return [CollectionReference(self, p.stem) for p in sorted(self.root.glob("*.json"))]

    def reset(self) -> None:
        with _LOCK:
            self._cache.clear()
            for path in self.root.glob("*.json"):
                path.unlink()
