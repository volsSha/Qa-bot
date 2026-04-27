from __future__ import annotations

import pytest
from pydantic import ValidationError

from qa_bot.config import Settings


def _base_settings(**overrides) -> dict:
    defaults = {
        "openrouter_api_key": "test-key",
        "app_env": "production",
        "auth_session_secret": "x" * 32,
    }
    defaults.update(overrides)
    return defaults


class TestProductionValidation:
    def test_valid_production_settings_load(self) -> None:
        settings = Settings(**_base_settings())
        assert settings.app_env == "production"

    def test_rejects_placeholder_session_secret_in_production(self) -> None:
        with pytest.raises(ValidationError, match="unsafe placeholder"):
            Settings(
                **_base_settings(auth_session_secret="change-me-in-production")
            )

    def test_rejects_short_session_secret_in_production(self) -> None:
        with pytest.raises(ValidationError, match="at least 24"):
            Settings(**_base_settings(auth_session_secret="a" * 20))

    def test_auth_cookie_secure_explicit_override_still_respected(self) -> None:
        settings = Settings(
            **_base_settings(auth_session_cookie_secure=False)
        )
        assert settings.session_cookie_secure is False

    def test_bootstrap_password_minimum_length_enforced(self) -> None:
        with pytest.raises(ValidationError, match="at least 12"):
            Settings(**_base_settings(admin_bootstrap_password="short"))
