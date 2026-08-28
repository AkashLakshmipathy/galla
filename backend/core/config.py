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

PROJECT = os.environ.get("GOOGLE_CLOUD_PROJECT", "galla-hackathon")
LOCATION = os.environ.get("GOOGLE_CLOUD_LOCATION", "asia-south1")
GEMINI_MODEL = os.environ.get("GEMINI_MODEL", "gemini-flash-latest")
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
LLM_AVAILABLE = bool(GEMINI_API_KEY) or (_credentials_present() and USE_VERTEX)
