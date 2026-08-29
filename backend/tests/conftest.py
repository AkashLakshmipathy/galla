"""Every test runs against a throwaway local store, never a real project."""
import os
import sys
import tempfile
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND))

os.environ["GALLA_STORE"] = "local"
os.environ["GALLA_LOCAL_DIR"] = tempfile.mkdtemp(prefix="galla-test-")
os.environ["DEMO_MODE"] = "true"

# Tests exercise the deterministic path, always. A developer with a real key in
# .env would otherwise have the suite quietly start calling Gemini: slow, flaky,
# billable, and it would stop testing the fallbacks that keep the demo alive.
# Set GALLA_TEST_LIVE_LLM=1 to opt in deliberately.
if os.environ.get("GALLA_TEST_LIVE_LLM") != "1":
    for var in ("GOOGLE_API_KEY", "GEMINI_API_KEY", "GOOGLE_GENAI_USE_VERTEXAI"):
        os.environ.pop(var, None)
    os.environ["GALLA_NO_LLM"] = "1"

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
