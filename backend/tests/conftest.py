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
