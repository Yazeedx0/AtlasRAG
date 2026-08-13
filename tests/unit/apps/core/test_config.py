"""Tests use ``_env_file=None`` to bypass the repo's local ``.env`` file, so
results don't depend on what a given developer's machine has set.
"""

import pytest
from apps.core.config import Environment, Settings, get_settings

pytestmark = pytest.mark.unit


@pytest.fixture
def make_settings(monkeypatch):
    def _make(**env_vars: str) -> Settings:
        for key, value in env_vars.items():
            monkeypatch.setenv(key, value)
        return Settings(_env_file=None)

    return _make


def test_defaults_with_no_env(make_settings):
    settings = make_settings()

    assert settings.APP_NAME == "AtlasRAG"
    assert settings.APP_VERSION == "1.0.0"
    assert settings.ENVIROMENT is Environment.DEVELOPMENT
    assert settings.DEBUG is False


def test_environment_enum_values():
    assert Environment.DEVELOPMENT == "development"
    assert Environment.TEST == "test"
    assert Environment.PRODUCTION == "production"


def test_reads_prefixed_env_vars(make_settings):
    settings = make_settings(
        ATLAS_APP_NAME="CustomName",
        ATLAS_APP_VERSION="2.0.0",
        ATLAS_DEBUG="true",
    )

    assert settings.APP_NAME == "CustomName"
    assert settings.APP_VERSION == "2.0.0"
    assert settings.DEBUG is True


def test_unprefixed_env_vars_are_not_read(make_settings):
    settings = make_settings(APP_NAME="ShouldBeIgnored")

    assert settings.APP_NAME == "AtlasRAG"


def test_environment_field_reads_its_actual_env_var_name(make_settings):
    """The field is named ``ENVIROMENT`` (missing an N), so that's the env var
    name pydantic-settings actually binds to: ``ATLAS_ENVIROMENT``, not the
    correctly-spelled ``ATLAS_ENVIRONMENT`` used in .env / .env.example.
    """
    settings = make_settings(ATLAS_ENVIROMENT="production")

    assert settings.ENVIROMENT is Environment.PRODUCTION


def test_correctly_spelled_environment_env_var_is_silently_ignored(make_settings):
    """Regression guard for the field/env-var name mismatch above: setting the
    correctly-spelled ATLAS_ENVIRONMENT (as .env does) has no effect today.
    If this test starts failing, the typo was fixed - update/delete it then.
    """
    settings = make_settings(ATLAS_ENVIRONMENT="production")

    assert settings.ENVIROMENT is Environment.DEVELOPMENT


def test_unknown_env_vars_are_ignored(make_settings):
    make_settings(ATLAS_SOME_UNDECLARED_FIELD="whatever")


def test_get_settings_is_cached():
    get_settings.cache_clear()
    try:
        first = get_settings()
        second = get_settings()
        assert first is second

        get_settings.cache_clear()
        third = get_settings()
        assert third is not first
    finally:
        get_settings.cache_clear()
