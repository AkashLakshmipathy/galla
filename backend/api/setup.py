"""Opening the shop: first-run setup, sign in, and starting over.

These are the only routes that work before a passcode exists, and `POST /setup`
closes behind itself the moment it succeeds — otherwise the setup form would be
a way for anyone to take over a running shop.
"""
from __future__ import annotations

import re
from datetime import datetime, timezone

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field

from core import auth, serialize
from core.config import SHOP_ID
from core.firestore_client import db

router = APIRouter(prefix="/api")

# 22AAAAA0000A1Z5 — 2-digit state, 10-char PAN, entity digit, Z, checksum.
GSTIN = re.compile(r"^[0-9]{2}[A-Z]{5}[0-9]{4}[A-Z][0-9A-Z]Z[0-9A-Z]$")

STATE_CODES = {
    "27": "Maharashtra", "29": "Karnataka", "33": "Tamil Nadu", "36": "Telangana",
    "32": "Kerala", "24": "Gujarat", "07": "Delhi", "09": "Uttar Pradesh",
    "19": "West Bengal", "08": "Rajasthan", "23": "Madhya Pradesh", "03": "Punjab",
    "06": "Haryana", "21": "Odisha", "10": "Bihar", "37": "Andhra Pradesh",
    "02": "Himachal Pradesh", "04": "Chandigarh", "05": "Uttarakhand",
    "20": "Jharkhand", "22": "Chhattisgarh", "18": "Assam", "30": "Goa",
}


class ShopSetup(BaseModel):
    name: str = Field(min_length=2, max_length=80)
    name_ta: str | None = None
    gstin: str | None = None
    state_code: str | None = None
    address: str = ""
    phone: str = ""
    ca_name: str = ""
    ca_phone: str = ""
    ca_email: str = ""
    credit_limit: int = 50000
    credit_days: int = 30
    confidence_threshold: float = 0.85
    passcode: str = Field(min_length=auth.MIN_PASSCODE, max_length=12)


@router.get("/setup/state")
def setup_state():
    """What the app asks before drawing anything: is there a shop here yet?"""
    return {"configured": auth.is_configured(),
            "locked": auth.passcode_required(),
            "states": STATE_CODES}


@router.post("/setup")
def create_shop(body: ShopSetup):
    if auth.is_configured():
        raise HTTPException(409, "this shop is already set up")

    gstin = (body.gstin or "").strip().upper() or None
    if gstin and not GSTIN.match(gstin):
        raise HTTPException(400, "that GSTIN does not look right — 15 characters, "
                                 "like 33AAMPM8712K1ZQ")
    # The first two digits of a GSTIN *are* the state code, so a registered shop
    # never has to pick from a list and the two can never disagree.
    state_code = gstin[:2] if gstin else (body.state_code or "")
    if not state_code:
        raise HTTPException(400, "pick your state, or enter your GSTIN")
    if not body.passcode.isdigit():
        raise HTTPException(400, "the passcode must be digits only")

    shop = {
        "shop_id": SHOP_ID,
        "name": body.name.strip(),
        "name_ta": (body.name_ta or "").strip() or None,
        "gstin": gstin,
        "state_code": state_code,
        "state_name": STATE_CODES.get(state_code, ""),
        "address": body.address.strip(),
        "phone": body.phone.strip(),
        "ca_contact": {"name": body.ca_name.strip(), "phone": body.ca_phone.strip(),
                       "email": body.ca_email.strip()},
        "defaults": {"credit_limit": int(body.credit_limit),
                     "credit_days": int(body.credit_days)},
        "confidence_threshold": float(body.confidence_threshold),
        "auth": auth.hash_passcode(body.passcode),
        "created_at": datetime.now(timezone.utc),
    }
    db().collection("shop").document(SHOP_ID).set(shop)
    return {"configured": True, "token": auth.issue_token(SHOP_ID),
            "shop": serialize.jsonable({k: v for k, v in shop.items() if k != "auth"})}


class SignIn(BaseModel):
    passcode: str


@router.post("/session")
def sign_in(body: SignIn, request: Request):
    if not auth.is_configured():
        raise HTTPException(409, "no shop here yet — set one up first")

    who = request.client.host if request.client else "unknown"
    allowed, wait = auth.throttle(who)
    if not allowed:
        raise HTTPException(429, f"too many attempts — wait {wait} seconds")

    shop = db().collection("shop").document(SHOP_ID).get().to_dict() or {}
    if not auth.verify_passcode(body.passcode, shop.get("auth") or {}):
        auth.record_failure(who)
        raise HTTPException(401, "wrong passcode")

    auth.clear_failures(who)
    return {"token": auth.issue_token(SHOP_ID),
            "shop": serialize.jsonable({k: v for k, v in shop.items() if k != "auth"})}


class Wipe(BaseModel):
    passcode: str
    confirm: str


@router.post("/setup/erase")
def erase_everything(body: Wipe):
    """Delete every record and return to first-run.

    Guarded by the passcode *and* a typed confirmation, because there is no undo
    and it destroys the ledger. Used to clear demo data before a shop starts
    trading for real.
    """
    shop_doc = db().collection("shop").document(SHOP_ID).get().to_dict() or {}
    if shop_doc.get("auth") and not auth.verify_passcode(body.passcode,
                                                         shop_doc["auth"]):
        raise HTTPException(401, "wrong passcode")
    if body.confirm.strip().upper() != "ERASE":
        raise HTTPException(400, 'type ERASE to confirm')

    removed = {}
    for name in ("orders", "purchases", "khata_imports", "confirm_queue",
                 "agent_traces", "gst_registers", "counters", "ledger",
                 "inventory", "catalog", "parties", "shop"):
        count = 0
        for snap in db().collection(name).stream():
            snap.reference.delete()
            count += 1
        removed[name] = count
    from core import catalog
    catalog.invalidate()
    return {"erased": True, "removed": removed}
