"""The provider switch — hard rule 10, and the guard that keeps tests free.

`core/model.py` is the only file in the repo allowed to name a vendor. These
pin the two things about it that break quietly rather than loudly.
"""
import os

import pytest

from core import model


@pytest.fixture(autouse=True)
def clean_env():
    """Each case owns the environment; the cache is per-process."""
    saved = {k: os.environ.get(k)
             for k in ("GALLA_NO_LLM", "GALLA_MODEL_PROVIDER")}
    yield
    for key, value in saved.items():
        os.environ.pop(key, None)
        if value is not None:
            os.environ[key] = value
    model.reset()


def provider_with(**env) -> str:
    for key, value in env.items():
        if value is None:
            os.environ.pop(key, None)
        else:
            os.environ[key] = value
    model.reset()
    return model.provider()


def test_no_llm_beats_an_explicit_provider():
    """The suite sets GALLA_NO_LLM; a developer's .env sets the provider. If the
    provider wins, every test quietly starts making real, billable API calls —
    and stops testing the deterministic fallbacks, which is what they are for.
    This is the regression that took the suite from 4s to 67s."""
    assert provider_with(GALLA_NO_LLM="1",
                         GALLA_MODEL_PROVIDER="litellm") == "none"
    assert provider_with(GALLA_NO_LLM="1",
                         GALLA_MODEL_PROVIDER="bedrock") == "none"


def test_no_model_is_built_when_the_provider_is_none():
    provider_with(GALLA_NO_LLM="1", GALLA_MODEL_PROVIDER=None)
    assert model.model() is None
    assert model.available() is False
    assert model.model_id() == "deterministic"


def test_the_switch_selects_each_provider():
    assert provider_with(GALLA_NO_LLM=None,
                         GALLA_MODEL_PROVIDER="bedrock") == "bedrock"
    assert provider_with(GALLA_NO_LLM=None,
                         GALLA_MODEL_PROVIDER="litellm") == "litellm"
    assert provider_with(GALLA_NO_LLM=None,
                         GALLA_MODEL_PROVIDER="none") == "none"


def test_an_unknown_provider_falls_through_to_autodetect():
    """A typo must not silently disable the model layer."""
    assert provider_with(GALLA_NO_LLM="1",
                         GALLA_MODEL_PROVIDER="bedrok") == "none"


def test_describe_reports_both_tiers():
    provider_with(GALLA_NO_LLM=None, GALLA_MODEL_PROVIDER="bedrock")
    described = model.describe()
    assert described["provider"] == "bedrock"
    assert described["model"] != described["model_fast"], \
        "the two tiers must not silently collapse into one model"
