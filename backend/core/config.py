"""Runtime configuration.

Two run modes, one codebase:

  STORE=firestore  (deployed)  real Firestore + GCS + Vertex AI
  STORE=local      (dev/demo)  JSON-file store + local media dir, so the whole
                              agent fleet can be exercised without GCP credentials.

The mode is auto-detected: if no ADC/service-account credentials are visible we
fall back to `local` rather than crashing on import. Nothing about agent logic
changes between the two — only where bytes land.
"""
import os
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[2]


def _load_dotenv() -> None:
    """Read `.env` at the repo root, without overriding the real environment.

    The README tells you to `cp .env.example .env`, so something has to read it.
    Real values already exported — and everything Cloud Run injects — win, so a
    stale local file can never shadow a deployed setting. `.env` is gitignored;
    production secrets belong in Secret Manager, not here.
    """
    # A test run must not inherit the developer's `.env`. conftest strips the
    # credentials out of the environment, but this function used to hand them
    # straight back — it only skips keys already present, and popped keys are
    # not present. That is how the suite ended up making live billable calls
    # off a machine-local file, and how a laptop could pass a suite that fails
    # in CI. conftest sets this before importing anything under `core`.
    if os.environ.get("GALLA_SKIP_DOTENV"):
        return
    path = _REPO_ROOT / ".env"
    if not path.exists():
        return
    for line in path.read_text("utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        key, value = key.strip(), value.split(" #")[0].strip().strip("'\"")
        if key and key not in os.environ:
            os.environ[key] = value


_load_dotenv()

PROJECT = os.environ.get("GOOGLE_CLOUD_PROJECT", "galla-hackathon")
# Where the shop's data lives. Firestore, Cloud Storage and Cloud Run are all
# in Mumbai: lowest latency for Coimbatore, and the right answer for an
# India-first product holding Indian traders' financial records.
LOCATION = os.environ.get("GOOGLE_CLOUD_LOCATION", "asia-south1")

# Where inference happens, which is a *different* question. asia-south1 serves
# gemini-3.5-flash but not flash-lite; the `global` endpoint serves both and
# routes to whichever region has capacity. Model calls are transient — no record
# is stored there — so the residency story is unaffected by pointing them at
# `global` while every stored byte stays in Mumbai.
VERTEX_LOCATION = os.environ.get("VERTEX_LOCATION", "global")
# Pinned, never a `-latest` alias. Google's own docs say the aliases are
# hot-swapped with every release and are not recommended for production; the
# alias was also the one returning 503 under load while pinned models answered
# in a second. A pinned id is additionally the only way a judge can verify which
# model actually ran, and the hackathon requires Gemini 3.5+.
GEMINI_MODEL = os.environ.get("GEMINI_MODEL", "gemini-3.5-flash")

# Document parsing and other high-throughput extraction go to Flash-Lite: it is
# what Google recommends for exactly that shape of work, and it measured ~3x
# faster than Flash on our own prompts. Cheaper too, and the credits have to
# last to demo day.
GEMINI_MODEL_FAST = os.environ.get("GEMINI_MODEL_FAST", "gemini-3.5-flash-lite")

# A model call that hangs is worse than one that fails — the owner is standing at
# the counter. Past this we stop waiting and use the deterministic fallback.
# Reading a photograph is slower than reading text and the phone may be on a
# patchy shop connection, so vision gets appreciably longer before we give up on
# it: falling back on a bill the model could have read is the worse outcome.
LLM_TIMEOUT_SECONDS = float(os.environ.get("LLM_TIMEOUT_SECONDS", "25"))
LLM_VISION_TIMEOUT_SECONDS = float(
    os.environ.get("LLM_VISION_TIMEOUT_SECONDS", "60"))
GCS_BUCKET = os.environ.get("GCS_BUCKET", "galla-media")
PUBSUB_TOPIC = os.environ.get("PUBSUB_TOPIC", "shop-events")
CONFIDENCE_THRESHOLD = float(os.environ.get("CONFIDENCE_THRESHOLD", "0.85"))
DEMO_MODE = os.environ.get("DEMO_MODE", "true").lower() == "true"
SHOP_ID = "main"

REPO_ROOT = Path(__file__).resolve().parents[2]
BACKEND_ROOT = Path(__file__).resolve().parents[1]
LOCAL_DATA_DIR = Path(os.environ.get("GALLA_LOCAL_DIR", BACKEND_ROOT / ".localdata"))
FIXTURES_DIR = BACKEND_ROOT / "seed" / "fixtures"


def _credentials_present() -> bool:
    if os.environ.get("GOOGLE_APPLICATION_CREDENTIALS"):
        return True
    if os.environ.get("K_SERVICE"):          # running on Cloud Run
        return True
    adc = Path.home() / ".config" / "gcloud" / "application_default_credentials.json"
    return adc.exists()


STORE = os.environ.get("GALLA_STORE") or ("firestore" if _credentials_present() else "local")
LOCAL_STORE = STORE == "local"

# The LLM is reachable only with credentials (Vertex) or an API key (AI Studio).
GEMINI_API_KEY = os.environ.get("GOOGLE_API_KEY") or os.environ.get("GEMINI_API_KEY")
USE_VERTEX = os.environ.get("GOOGLE_GENAI_USE_VERTEXAI", "").lower() in {"1", "true"}
LLM_AVAILABLE = (
    not os.environ.get("GALLA_NO_LLM")
    and (bool(GEMINI_API_KEY) or (_credentials_present() and USE_VERTEX))
)
