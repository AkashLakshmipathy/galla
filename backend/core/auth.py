"""Owner access: a shop passcode, hashed, exchanged for a signed session token.

The shop's ledger is its customers' financial history — what each contractor
owes, their phone numbers, twenty years of credit. An open API is fine for a
demo and indefensible the moment a real shop puts real data in, so every `/api`
route is gated except the three needed to get through the door.

This is a passcode, not an identity system: one owner, one shop, one device in a
pocket. It is deliberately what a 52-year-old will actually use — the same four
to six digits he already uses to unlock his phone. Firebase Auth with a phone
number is the stronger successor and the natural next step; this is what ships
today and it is a great deal better than nothing.

What it does do properly: PBKDF2 with a per-shop salt so the stored value cannot
be reversed, HMAC-signed tokens that expire, constant-time comparison, and a
lockout that makes brute force impractical.
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
import secrets
import time
from dataclasses import dataclass

from core.firestore_client import db

PBKDF2_ROUNDS = 240_000
TOKEN_TTL_SECONDS = int(os.environ.get("SESSION_TTL_SECONDS", 60 * 60 * 24 * 30))
MAX_ATTEMPTS = 8
LOCKOUT_SECONDS = 300
MIN_PASSCODE = 4

_ATTEMPTS: dict[str, list[float]] = {}


@dataclass
class Session:
    shop_id: str
    issued_at: int
    expires_at: int


# ------------------------------------------------------------------ passcodes
def hash_passcode(passcode: str, salt: bytes | None = None) -> dict:
    salt = salt or secrets.token_bytes(16)
    digest = hashlib.pbkdf2_hmac("sha256", passcode.encode("utf-8"), salt,
                                 PBKDF2_ROUNDS)
    return {"salt": base64.b64encode(salt).decode(),
            "hash": base64.b64encode(digest).decode(),
            "rounds": PBKDF2_ROUNDS}


def verify_passcode(passcode: str, stored: dict) -> bool:
    if not stored or not stored.get("salt"):
        return False
    salt = base64.b64decode(stored["salt"])
    digest = hashlib.pbkdf2_hmac("sha256", passcode.encode("utf-8"), salt,
                                 int(stored.get("rounds") or PBKDF2_ROUNDS))
    return hmac.compare_digest(base64.b64encode(digest).decode(), stored["hash"])


def throttle(key: str) -> tuple[bool, int]:
    """(allowed, seconds_to_wait). Brute-forcing six digits should not be free."""
    now = time.time()
    tries = [t for t in _ATTEMPTS.get(key, []) if now - t < LOCKOUT_SECONDS]
    _ATTEMPTS[key] = tries
    if len(tries) >= MAX_ATTEMPTS:
        return False, int(LOCKOUT_SECONDS - (now - tries[0]))
    return True, 0


def record_failure(key: str) -> None:
    _ATTEMPTS.setdefault(key, []).append(time.time())


def clear_failures(key: str) -> None:
    _ATTEMPTS.pop(key, None)


# --------------------------------------------------------------------- tokens
def _signing_key() -> bytes:
    """Derived from the shop's own stored salt, so it survives restarts without
    a separate secret to manage, and rotates if the passcode is ever reset."""
    shop = db().collection("shop").document("main").get().to_dict() or {}
    material = (shop.get("auth") or {}).get("salt", "") + shop.get("shop_id", "main")
    env_secret = os.environ.get("SESSION_SECRET", "")
    return hashlib.sha256((material + env_secret).encode("utf-8")).digest()


def issue_token(shop_id: str = "main") -> str:
    now = int(time.time())
    payload = {"shop": shop_id, "iat": now, "exp": now + TOKEN_TTL_SECONDS}
    body = base64.urlsafe_b64encode(
        json.dumps(payload, separators=(",", ":")).encode()).rstrip(b"=")
    signature = hmac.new(_signing_key(), body, hashlib.sha256).digest()
    return f"{body.decode()}.{base64.urlsafe_b64encode(signature).rstrip(b'=').decode()}"


def read_token(token: str | None) -> Session | None:
    if not token or "." not in token:
        return None
    body, _, signature = token.partition(".")
    try:
        expected = hmac.new(_signing_key(), body.encode(), hashlib.sha256).digest()
        given = base64.urlsafe_b64decode(signature + "=" * (-len(signature) % 4))
        if not hmac.compare_digest(expected, given):
            return None
        payload = json.loads(base64.urlsafe_b64decode(body + "=" * (-len(body) % 4)))
    except Exception:                                     # noqa: BLE001
        return None
    if int(payload.get("exp", 0)) < time.time():
        return None
    return Session(payload.get("shop", "main"), payload.get("iat", 0),
                   payload.get("exp", 0))


# ------------------------------------------------------------------- shop state
def is_configured() -> bool:
    """Is there a shop here at all?

    Deliberately *not* "does it have a passcode". A shop that exists but is
    unlocked is a perfectly coherent state — an owner testing on a device he
    keeps in his hand, or a locally-run instance — and conflating the two sent
    a configured shop back to the setup form.
    """
    shop = db().collection("shop").document("main").get()
    return bool(shop.exists and (shop.to_dict() or {}).get("name"))


def passcode_required() -> bool:
    """A shop with no passcode set yet cannot be locked out of itself."""
    shop = db().collection("shop").document("main").get().to_dict() or {}
    return bool((shop.get("auth") or {}).get("hash"))
