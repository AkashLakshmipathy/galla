"""The model provider, behind one switch.

Hard rule 10: the provider lives here and is changed with one environment
variable, `GALLA_MODEL_PROVIDER`. No other file in the repo names a vendor.

    GALLA_MODEL_PROVIDER=vertex     Gemini on Vertex AI, billed to our GCP project
    GALLA_MODEL_PROVIDER=litellm    Gemini through an AI Studio API key
    GALLA_MODEL_PROVIDER=bedrock    Amazon Bedrock — Strands' native provider
    GALLA_MODEL_PROVIDER=none       force the deterministic path (tests, demo)

Vertex and AI Studio reach the same models by different doors, and the door
matters: an AI Studio key has its own free-tier quota that no amount of GCP
credit can raise, while Vertex bills the project and carries proper quotas.
Running out of the former is what sent us looking for the latter.

Unset, it takes the path it can verify: a Gemini key, else AWS credentials,
else deterministic. Bedrock is deliberately opt-in — see `provider()`.

TWO TIERS, THE SAME REASON AS BEFORE

`fast` is the cheap, high-throughput model used for document extraction and
routing; the standard model handles handwriting vision and the one sentence the
Credit Guardian speaks. Splitting them is most of why this build runs on almost
nothing, and it survives the provider swap.

NOTHING HERE RAISES ON IMPORT

Hard rule 6 says every model call needs a deterministic fallback, which is only
possible if asking for a model that cannot be built returns `None` instead of
exploding. `available()` is what callers branch on.
"""
from __future__ import annotations

import os
from functools import lru_cache
from pathlib import Path

from core.config import (GEMINI_API_KEY, GEMINI_MODEL, GEMINI_MODEL_FAST,
                         PROJECT, VERTEX_LOCATION)

BEDROCK = "bedrock"
LITELLM = "litellm"      # Gemini through an AI Studio API key
VERTEX = "vertex"        # Gemini through Vertex AI on our own GCP project
NONE = "none"

# Claude for the work that needs judgement, Nova for the high-volume extraction.
# Both are the ids Bedrock serves; override per environment rather than in code.
# Sonnet where the work is hard or a human reads the output, Haiku where the
# input is clean and the trace strip is waiting on camera. Both verified
# grantable on this account; Sonnet 4.6 still sits behind Anthropic's use-case
# form and Sonnet 5 is not offered here, so these are the best available pair.
BEDROCK_MODEL = os.environ.get(
    "BEDROCK_MODEL", "us.anthropic.claude-sonnet-4-5-20250929-v1:0")
BEDROCK_MODEL_FAST = os.environ.get(
    "BEDROCK_MODEL_FAST", "us.anthropic.claude-haiku-4-5-20251001-v1:0")
BEDROCK_REGION = os.environ.get("AWS_REGION") or os.environ.get(
    "AWS_DEFAULT_REGION", "us-east-1")

# LiteLLM addresses Gemini as `gemini/<model>` through AI Studio and
# `vertex_ai/<model>` through Vertex; our config already pins the ids.
LITELLM_MODEL = os.environ.get("LITELLM_MODEL", f"gemini/{GEMINI_MODEL}")
LITELLM_MODEL_FAST = os.environ.get("LITELLM_MODEL_FAST", f"gemini/{GEMINI_MODEL_FAST}")
VERTEX_MODEL = os.environ.get("VERTEX_MODEL", f"vertex_ai/{GEMINI_MODEL}")
VERTEX_MODEL_FAST = os.environ.get("VERTEX_MODEL_FAST", f"vertex_ai/{GEMINI_MODEL_FAST}")

TEMPERATURE = float(os.environ.get("MODEL_TEMPERATURE", "0.1"))
MAX_TOKENS = int(os.environ.get("MODEL_MAX_TOKENS", "2048"))


def _aws_credentialed() -> bool:
    """Enough to build a Bedrock client — env keys, a profile, or a role.

    Deliberately does not call STS: this runs at import on every cold start and
    a network round trip there would show up as latency on the first scan.
    """
    if os.environ.get("AWS_ACCESS_KEY_ID") and os.environ.get("AWS_SECRET_ACCESS_KEY"):
        return True
    if os.environ.get("AWS_PROFILE") or os.environ.get("AWS_ROLE_ARN"):
        return True
    return (Path.home() / ".aws" / "credentials").exists()


def _vertex_credentialed() -> bool:
    """Application Default Credentials, or the service account Cloud Run gives us.

    No network call: this runs at import on every cold start, and a round trip
    here would land as latency on the shop's first scan of the day.
    """
    if os.environ.get("GOOGLE_APPLICATION_CREDENTIALS") or os.environ.get("K_SERVICE"):
        return True
    adc = Path.home() / ".config" / "gcloud" / "application_default_credentials.json"
    return adc.exists()


@lru_cache(maxsize=1)
def provider() -> str:
    """Which provider this process will use. Decided once, logged in the trace."""
    # GALLA_NO_LLM is a hard override and is checked first, deliberately. The
    # test suite sets it to force the deterministic path; `.env` sets
    # GALLA_MODEL_PROVIDER for the app. Reading the provider first let the
    # developer's `.env` win over conftest and the whole suite quietly started
    # billing real API calls — slow, flaky, and it stops testing the fallbacks
    # that keep the demo alive, which is the one thing those tests are for.
    if os.environ.get("GALLA_NO_LLM"):
        return NONE
    choice = (os.environ.get("GALLA_MODEL_PROVIDER") or "").strip().lower()
    if choice in {BEDROCK, LITELLM, VERTEX, NONE}:
        return choice
    # Prefer the provider we can be sure of. Bedrock is the better answer for
    # this hackathon and one env var away, but "credentials exist" is not the
    # same as "Bedrock is reachable and the models are granted" — a laptop with
    # a work AWS profile on it has the first and none of the second. Guessing
    # wrong is not free: every call would spend its whole timeout before the
    # deterministic fallback catches it, which on camera is a dead counter.
    # So auto-detect picks the verified path, and Bedrock is chosen explicitly.
    if _vertex_credentialed():
        return VERTEX
    if GEMINI_API_KEY:
        return LITELLM
    if _aws_credentialed():
        return BEDROCK
    return NONE


@lru_cache(maxsize=2)
def model(fast: bool = False):
    """A Strands model object, or `None` if this process cannot build one.

    Cached per tier: constructing a provider opens a client, and the agent chain
    builds one per step. Returning `None` rather than raising is what lets every
    caller fall back deterministically.
    """
    which = provider()
    try:
        if which == BEDROCK:
            from strands.models import BedrockModel
            return BedrockModel(
                model_id=BEDROCK_MODEL_FAST if fast else BEDROCK_MODEL,
                region_name=BEDROCK_REGION,
                temperature=TEMPERATURE,
                max_tokens=MAX_TOKENS,
            )
        if which == VERTEX:
            from strands.models.litellm import LiteLLMModel
            # `client_args` is spread straight into `litellm.acompletion`, which
            # is how the project and region reach Vertex. Auth is ADC, so there
            # is no key to leak into an environment variable.
            return LiteLLMModel(
                client_args={"vertex_project": PROJECT,
                             "vertex_location": VERTEX_LOCATION},
                model_id=VERTEX_MODEL_FAST if fast else VERTEX_MODEL,
                params={"temperature": TEMPERATURE, "max_tokens": MAX_TOKENS},
            )
        if which == LITELLM:
            from strands.models.litellm import LiteLLMModel
            return LiteLLMModel(
                client_args={"api_key": GEMINI_API_KEY},
                model_id=LITELLM_MODEL_FAST if fast else LITELLM_MODEL,
                params={"temperature": TEMPERATURE, "max_tokens": MAX_TOKENS},
            )
    except Exception:                                     # noqa: BLE001
        # A missing extra, a bad region, an SDK that moved: none of these are
        # worth taking the shop's counter down for.
        return None
    return None


def model_id(fast: bool = False) -> str:
    """What to write on the trace step, so a judge can see which model ran."""
    which = provider()
    if which == BEDROCK:
        return BEDROCK_MODEL_FAST if fast else BEDROCK_MODEL
    if which == LITELLM:
        return LITELLM_MODEL_FAST if fast else LITELLM_MODEL
    if which == VERTEX:
        return VERTEX_MODEL_FAST if fast else VERTEX_MODEL
    return "deterministic"


def available() -> bool:
    """True when a model call is worth attempting at all."""
    return provider() != NONE and model() is not None


def describe() -> dict:
    """Provider provenance for `/api/fleet` and the README."""
    return {"provider": provider(), "model": model_id(),
            "model_fast": model_id(fast=True), "available": available()}


def reset() -> None:
    """Drop the cached provider — tests flip the env var between cases."""
    provider.cache_clear()
    model.cache_clear()
