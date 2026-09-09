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


# --------------------------------------------------------- the money guard
# Deliberately not using the fixture above: this asserts on the environment the
# suite actually runs in, unmutated.
LIVE_CREDENTIALS = ("GOOGLE_API_KEY", "GEMINI_API_KEY", "AWS_PROFILE",
                    "AWS_ACCESS_KEY_ID", "AWS_SECRET_ACCESS_KEY")

# `GALLA_TEST_LIVE_LLM=1` is the deliberate opt-in to a paid endpoint. These
# describe the default mode, so under the opt-in they skip rather than fail —
# a guard that punishes the documented escape hatch just gets deleted.
live_optin = pytest.mark.skipif(
    os.environ.get("GALLA_TEST_LIVE_LLM") == "1",
    reason="live-LLM opt-in: credentials are reachable on purpose")


@live_optin
def test_no_live_credentials_are_visible_to_the_suite():
    """The suite must not be able to reach a paid endpoint even by accident.

    conftest strips these, but `core.config` reads `.env` at import time and
    used to hand them straight back — it only skips keys already present, and a
    popped key is not present. That is how a machine-local file started billing
    real calls on every `pytest`, and how this laptop could pass a suite that
    would fail in CI where no `.env` exists.
    """
    leaked = [name for name in LIVE_CREDENTIALS if os.environ.get(name)]
    assert not leaked, (
        f"live credentials reached the test environment: {leaked}. "
        "conftest must strip them and GALLA_SKIP_DOTENV must stop .env "
        "restoring them.")


@live_optin
def test_the_suite_cannot_build_a_model_at_all():
    """Three independent guards; this asserts the outcome they exist for."""
    model.reset()
    assert os.environ.get("GALLA_NO_LLM") == "1"
    assert os.environ.get("GALLA_MODEL_PROVIDER") == "none"
    assert model.provider() == "none"
    assert model.model() is None
    assert model.available() is False


@live_optin
def test_dotenv_is_not_read_during_tests():
    from core import config
    assert os.environ.get("GALLA_SKIP_DOTENV") == "1"
    assert not config.GEMINI_API_KEY, \
        "config picked up a key, so .env was read despite GALLA_SKIP_DOTENV"
