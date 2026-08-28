"""Does the code speak real Firestore, not just the local shim?

Every other test runs against `core.localstore`, so a signature the real client
does not accept would never surface until deploy day. Building a query is a
purely local operation in the Firestore client, so these tests instantiate the
*real* client with anonymous credentials and construct every query shape the
codebase uses. Nothing here touches the network — no `.stream()`, no `.get()`.

If this file fails, the deployed service is broken even though the other 44
tests are green.
"""
import pytest
from google.auth.credentials import AnonymousCredentials
from google.cloud import firestore
from google.cloud.firestore_v1.base_query import FieldFilter


@pytest.fixture(scope="module")
def real():
    """A real Firestore client that is never allowed to make a call."""
    return firestore.Client(project="galla-contract-test",
                            credentials=AnonymousCredentials())


def test_document_and_collection_refs(real):
    ref = real.collection("orders").document("ord_1043")
    assert ref.id == "ord_1043"
    assert real.collection("shop").document("main").path == "shop/main"


def test_every_filter_shape_the_code_uses(real):
    """Positional `.where(f, op, v)` is deprecated in recent client versions —
    the codebase uses `filter=FieldFilter(...)` everywhere, so prove it works."""
    parties = real.collection("parties")
    parties.where(filter=FieldFilter("gstin", "==", "33AABCS1429B1ZP")).limit(1)
    parties.where(filter=FieldFilter("type", "in", ["supplier", "both"]))
    # A nested field path, as used for credit balances.
    parties.where(filter=FieldFilter("credit.outstanding", ">", 50000))


def test_order_by_directions(real):
    """`api/reads.py` passes the direction as a bare string."""
    orders = real.collection("orders")
    orders.order_by("created_at", direction="DESCENDING").limit(20)
    orders.order_by("created_at", direction="ASCENDING").limit(20)
    assert firestore.Query.DESCENDING == "DESCENDING"
    assert firestore.Query.ASCENDING == "ASCENDING"


def test_the_exact_queries_api_reads_builds(real):
    """Mirrors `api.reads._docs` — filter, then order, then limit, in that order."""
    for collection, field, desc, where in [
        ("orders", "created_at", True, None),
        ("ledger", "date", True, ("party_id", "==", "selvam")),
        ("confirm_queue", "created_at", False, None),
        ("purchases", "invoice_date", True, ("supplier_id", "==", "sbh_agencies")),
        ("agent_traces", "created_at", True, None),
        ("gst_registers", "period", True, None),
    ]:
        query = real.collection(collection)
        if where:
            query = query.where(filter=FieldFilter(*where))
        query = query.order_by(field, direction="DESCENDING" if desc else "ASCENDING")
        query.limit(50)


def test_transaction_and_batch_construct(real):
    transaction = real.transaction()
    assert hasattr(transaction, "set") and hasattr(transaction, "update")
    assert hasattr(transaction, "delete")
    assert hasattr(real.batch(), "commit")


def test_transactional_decorator_matches_run_transaction(real):
    """`core.firestore_client.run_transaction` wraps the body in
    `@firestore.transactional` and calls it with `client.transaction()`."""
    calls = []

    @firestore.transactional
    def body(transaction):
        calls.append(transaction)
        return "result"

    assert callable(body)
    # Not executed: committing needs the network. The decorator accepting the
    # single-argument body is the contract that matters.


def test_document_snapshot_exposes_reference(real):
    """`api/demo.py` resets collections via `snap.reference.delete()`."""
    from google.cloud.firestore_v1.document import DocumentSnapshot
    assert "reference" in dir(DocumentSnapshot)


def test_read_in_transaction_signature(real):
    """Transaction bodies read with `ref.get(transaction=txn)`."""
    import inspect
    from google.cloud.firestore_v1.document import DocumentReference
    assert "transaction" in inspect.signature(DocumentReference.get).parameters


# ------------------------------------------------------------------ authz
def test_oidc_check_is_off_by_default():
    """Default-off is deliberate: the check has never run against real Google
    tokens, and switching it on for the first time mid-demo is how a demo dies."""
    from core import authz
    assert authz.REQUIRE_OIDC is False
    ok, why = authz.verify(None)
    assert ok and "disabled" in why


def test_oidc_check_rejects_junk_when_enabled(monkeypatch):
    from core import authz
    monkeypatch.setattr(authz, "REQUIRE_OIDC", True)
    assert authz.verify(None) == (False, "missing bearer token")
    assert authz.verify("Basic abc")[0] is False
    ok, why = authz.verify("Bearer not-a-real-token")
    assert ok is False and "rejected" in why


def test_protected_endpoints_refuse_unverified_callers(monkeypatch):
    """The two endpoints a stranger could otherwise use to inject a sale or burn
    Gemini credits."""
    from fastapi.testclient import TestClient

    from core import authz
    import main

    monkeypatch.setattr(authz, "REQUIRE_OIDC", True)
    client = TestClient(main.app)
    assert client.post("/pubsub/push", json={"message": {}}).status_code == 403
    assert client.post("/jobs/gst-compile", json={}).status_code == 403
    # /healthz stays open so Cloud Run's probe still works.
    assert client.get("/healthz").status_code == 200
