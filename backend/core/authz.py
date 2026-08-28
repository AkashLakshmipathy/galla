"""Verifying that a caller really is Pub/Sub or Cloud Scheduler.

`/pubsub/push` and `/jobs/gst-compile` are the two endpoints a stranger could
otherwise use to inject a fake sale into the shop's books or to burn Gemini
credits by re-running the monthly compile. Google signs both callers with an
OIDC token; this checks it.

Off by default. `deploy.sh` wires the service accounts that make it work, and
`REQUIRE_OIDC=true` turns it on — deliberately a separate step, because an
authentication check that has only ever been exercised against a mock is not
something to switch on for the first time during a demo.
"""
from __future__ import annotations

import logging
import os

log = logging.getLogger("galla.authz")

REQUIRE_OIDC = os.environ.get("REQUIRE_OIDC", "false").lower() == "true"
# The service account deploy.sh gives to the push subscription and the job.
EXPECTED_SA = os.environ.get("OIDC_SERVICE_ACCOUNT", "")
EXPECTED_AUDIENCE = os.environ.get("OIDC_AUDIENCE", "")


def verify(authorization: str | None) -> tuple[bool, str]:
    """(ok, reason). Always ok when the check is off."""
    if not REQUIRE_OIDC:
        return True, "oidc check disabled"
    if not authorization or not authorization.lower().startswith("bearer "):
        return False, "missing bearer token"

    token = authorization.split(" ", 1)[1].strip()
    try:
        from google.auth.transport import requests as google_requests
        from google.oauth2 import id_token

        claims = id_token.verify_oauth2_token(
            token, google_requests.Request(),
            audience=EXPECTED_AUDIENCE or None)
    except Exception as exc:                              # noqa: BLE001
        return False, f"token rejected: {type(exc).__name__}"

    if not claims.get("email_verified"):
        return False, "unverified caller"
    if EXPECTED_SA and claims.get("email") != EXPECTED_SA:
        return False, f"unexpected caller {claims.get('email')}"
    return True, claims.get("email", "verified")
