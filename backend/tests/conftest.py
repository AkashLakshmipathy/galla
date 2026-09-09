"""Every test runs against a throwaway local store, never a real project."""
import os
import sys
import tempfile
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND))

# Tests exercise the deterministic path, always. A developer with a real key in
# `.env` would otherwise have the suite quietly start calling a paid endpoint:
# slow, flaky, billable, and it would stop testing the fallbacks that keep the
# demo alive — which is the one thing those tests are for.
#
# `GALLA_TEST_LIVE_LLM=1` opts in deliberately, and is the only path that leaves
# credentials reachable.
LIVE_LLM = os.environ.get("GALLA_TEST_LIVE_LLM") == "1"

if not LIVE_LLM:
    # Must be set before anything under `core` is imported: `core.config` reads
    # `.env` at import time, and it only skips keys already present — so popping
    # a key below would otherwise hand it straight back. This is the root cause
    # of the suite once making live calls off a machine-local file.
    os.environ["GALLA_SKIP_DOTENV"] = "1"

os.environ["GALLA_STORE"] = "local"
os.environ["GALLA_LOCAL_DIR"] = tempfile.mkdtemp(prefix="galla-test-")
os.environ["DEMO_MODE"] = "true"

# Three independent guards, because this fails silently and costs money: `.env`
# is not read, the credentials are stripped, the kill switch is set and the
# provider is pinned off. Any one would do; needing all four is the point.
if not LIVE_LLM:
    for var in ("GOOGLE_API_KEY", "GEMINI_API_KEY", "GOOGLE_GENAI_USE_VERTEXAI",
                "AWS_PROFILE", "AWS_ACCESS_KEY_ID", "AWS_SECRET_ACCESS_KEY"):
        os.environ.pop(var, None)
    os.environ["GALLA_NO_LLM"] = "1"
    os.environ["GALLA_MODEL_PROVIDER"] = "none"

import pytest                                              # noqa: E402

from core.firestore_client import db                       # noqa: E402


@pytest.fixture()
def seeded():
    """A freshly seeded shop, isolated per test."""
    from core import catalog
    from seed.seed_data import main as reseed

    client = db()
    client.reset()
    catalog.invalidate()
    reseed()
    yield client
    client.reset()
    catalog.invalidate()


@pytest.fixture()
def client(seeded):
    """The API as the PWA sees it, over a freshly seeded shop.

    The seed leaves the shop without a passcode, so the owner gate is open and
    a test can call an endpoint without signing in first. `test_setup_auth`
    covers the locked case deliberately.
    """
    from fastapi.testclient import TestClient

    import main
    return TestClient(main.app)
