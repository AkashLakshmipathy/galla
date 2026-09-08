"""The model provider, behind one switch.

Hard rule 10: the provider lives here and is changed with one environment
variable, `GALLA_MODEL_PROVIDER`. No other file in the repo names a vendor.

    GALLA_MODEL_PROVIDER=bedrock    Amazon Bedrock — Strands' native provider
    GALLA_MODEL_PROVIDER=litellm    Gemini through LiteLLM
    GALLA_MODEL_PROVIDER=none       force the deterministic path (tests, demo)

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

from core.config import GEMINI_API_KEY, GEMINI_MODEL, GEMINI_MODEL_FAST

BEDROCK = "bedrock"
LITELLM = "litellm"
NONE = "none"

# Claude for the work that needs judgement, Nova for the high-volume extraction.
# Both are the ids Bedrock serves; override per environment rather than in code.
BEDROCK_MODEL = os.environ.get("BEDROCK_MODEL", "global.anthropic.claude-sonnet-4-6")
BEDROCK_MODEL_FAST = os.environ.get("BEDROCK_MODEL_FAST", "us.amazon.nova-lite-v1:0")
BEDROCK_REGION = os.environ.get("AWS_REGION") or os.environ.get(
    "AWS_DEFAULT_REGION", "us-east-1")

# LiteLLM addresses Gemini as `gemini/<model>`; our config already pins the ids.
LITELLM_MODEL = os.environ.get("LITELLM_MODEL", f"gemini/{GEMINI_MODEL}")
LITELLM_MODEL_FAST = os.environ.get("LITELLM_MODEL_FAST", f"gemini/{GEMINI_MODEL_FAST}")

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


@lru_cache(maxsize=1)
def provider() -> str:
    """Which provider this process will use. Decided once, logged in the trace."""
    choice = (os.environ.get("GALLA_MODEL_PROVIDER") or "").strip().lower()
    if choice in {BEDROCK, LITELLM, NONE}:
        return choice
    if os.environ.get("GALLA_NO_LLM"):
        return NONE
    # Prefer the provider we can be sure of. Bedrock is the better answer for
    # this hackathon and one env var away, but "credentials exist" is not the
    # same as "Bedrock is reachable and the models are granted" — a laptop with
    # a work AWS profile on it has the first and none of the second. Guessing
    # wrong is not free: every call would spend its whole timeout before the
    # deterministic fallback catches it, which on camera is a dead counter.
    # So auto-detect picks the verified path, and Bedrock is chosen explicitly.
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
