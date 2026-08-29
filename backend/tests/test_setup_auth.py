"""First-run setup and the passcode gate.

The property that matters: before a shop exists anyone may create one; the
moment one does, nobody gets at the ledger without the owner's passcode.
"""
import pytest
from fastapi.testclient import TestClient

import main
from core import auth
from core.firestore_client import db


@pytest.fixture()
def app(seeded):
    db().collection("shop").document("main").delete()   # a fresh, unopened shop
    auth._ATTEMPTS.clear()
    return TestClient(main.app)


SETUP = {"name": "Murugan Hardware", "name_ta": "முருகன் ஹார்டுவேர்",
         "gstin": "33AAMPM8712K1ZQ", "address": "Thudiyalur, Coimbatore",
         "phone": "+919842200000", "passcode": "4271"}


def test_a_fresh_install_reports_it_needs_setting_up(app):
    state = app.get("/api/setup/state").json()
    assert state["configured"] is False
    assert "33" in state["states"]


def test_setting_up_derives_the_state_from_the_gstin(app):
    """The first two digits of a GSTIN are the state code, so the two can never
    disagree and the owner never picks from a list."""
    body = app.post("/api/setup", json=SETUP).json()
    assert body["configured"] is True
    assert body["shop"]["state_code"] == "33"
    assert body["shop"]["state_name"] == "Tamil Nadu"


def test_a_malformed_gstin_is_refused(app):
    r = app.post("/api/setup", json={**SETUP, "gstin": "NOTAGSTIN"})
    assert r.status_code == 400 and "GSTIN" in r.json()["detail"]


def test_a_shop_without_gstin_must_name_its_state(app):
    assert app.post("/api/setup",
                    json={**SETUP, "gstin": None}).status_code == 400
    assert app.post("/api/setup",
                    json={**SETUP, "gstin": None, "state_code": "33"}
                    ).status_code == 200


def test_the_passcode_is_never_stored_in_the_clear(app):
    app.post("/api/setup", json=SETUP)
    stored = db().collection("shop").document("main").get().to_dict()
    assert "4271" not in str(stored)
    assert set(stored["auth"]) == {"salt", "hash", "rounds"}


def test_setup_closes_behind_itself(app):
    """Otherwise the setup form is a way to take over a running shop."""
    app.post("/api/setup", json=SETUP)
    again = app.post("/api/setup", json={**SETUP, "passcode": "9999"})
    assert again.status_code == 409


def test_the_ledger_is_shut_to_anyone_without_the_passcode(app):
    app.post("/api/setup", json=SETUP)
    assert app.get("/api/parties").status_code == 401
    assert app.get("/api/counter").status_code == 401
    assert app.post("/api/orders/x/decision",
                    json={"action": "approve"}).status_code == 401


def test_the_right_passcode_opens_it(app):
    app.post("/api/setup", json=SETUP)
    token = app.post("/api/session", json={"passcode": "4271"}).json()["token"]
    headers = {"Authorization": f"Bearer {token}"}
    assert app.get("/api/parties", headers=headers).status_code == 200


def test_a_wrong_passcode_does_not(app):
    app.post("/api/setup", json=SETUP)
    assert app.post("/api/session", json={"passcode": "0000"}).status_code == 401


def test_a_forged_token_is_rejected(app):
    app.post("/api/setup", json=SETUP)
    for bad in ["nonsense", "a.b", "", "Bearer"]:
        assert app.get("/api/parties",
                       headers={"Authorization": f"Bearer {bad}"}).status_code == 401


def test_an_expired_token_is_rejected(app, monkeypatch):
    app.post("/api/setup", json=SETUP)
    monkeypatch.setattr(auth, "TOKEN_TTL_SECONDS", -1)
    token = auth.issue_token()
    assert app.get("/api/parties",
                   headers={"Authorization": f"Bearer {token}"}).status_code == 401


def test_guessing_is_throttled(app):
    """Six digits is not many. Brute-forcing them should not be free."""
    app.post("/api/setup", json=SETUP)
    codes = [app.post("/api/session", json={"passcode": "0000"}).status_code
             for _ in range(auth.MAX_ATTEMPTS + 2)]
    assert 429 in codes


def test_the_app_shell_still_loads_when_locked(app):
    """The PWA must open offline and show its own lock screen, not a 401 page."""
    app.post("/api/setup", json=SETUP)
    assert app.get("/api/setup/state").status_code == 200


def test_erasing_needs_both_the_passcode_and_a_typed_confirmation(app):
    app.post("/api/setup", json=SETUP)
    assert app.post("/api/setup/erase",
                    json={"passcode": "0000", "confirm": "ERASE"}).status_code == 401
    assert app.post("/api/setup/erase",
                    json={"passcode": "4271", "confirm": "yes"}).status_code == 400

    ok = app.post("/api/setup/erase", json={"passcode": "4271", "confirm": "ERASE"})
    assert ok.status_code == 200
    assert app.get("/api/setup/state").json()["configured"] is False
    assert len(list(db().collection("parties").stream())) == 0


def test_ingest_is_guarded_even_though_it_is_not_under_api(app):
    """/ingest writes into the books. Living outside /api/ is a URL detail, not
    a reason to let a stranger post orders into a locked shop."""
    app.post("/api/setup", json=SETUP)
    assert app.post("/ingest", json={"type": "sale_order", "party_id": "x",
                                     "transcript": "20 bags"}).status_code == 401

    token = app.post("/api/session", json={"passcode": "4271"}).json()["token"]
    assert app.post("/ingest", headers={"Authorization": f"Bearer {token}"},
                    json={"type": "sale_order", "party_id": "selvam",
                          "transcript": "20 bags ramco 53"}).status_code == 200


def test_the_api_docs_are_not_published_for_a_real_shop(app, monkeypatch):
    """The schema is free reconnaissance for anyone who finds the URL."""
    import main as main_module
    assert main_module.DEMO_MODE is False or main_module.app.docs_url == "/docs"
    if not main_module.DEMO_MODE:
        assert app.get("/docs").status_code == 404
        assert app.get("/openapi.json").status_code == 404
