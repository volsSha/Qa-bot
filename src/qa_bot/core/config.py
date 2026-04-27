from __future__ import annotations

from pathlib import Path

from pydantic import AliasChoices, Field, SecretStr, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

_BASE_DIR = Path(__file__).resolve().parents[3]
_DATA_DIR = _BASE_DIR / "data"
_SCREENSHOTS_DIR = _DATA_DIR / "screenshots"
_REPORTS_DIR = _DATA_DIR / "reports"
_WEAK_SESSION_SECRETS = {
    "change-me-in-production",
    "changeme",
    "secret",
    "password",
}


def ensure_data_dirs() -> None:
    _SCREENSHOTS_DIR.mkdir(parents=True, exist_ok=True)
    _REPORTS_DIR.mkdir(parents=True, exist_ok=True)


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=str(_BASE_DIR / ".env"),
        env_file_encoding="utf-8",
        frozen=True,
    )

    app_env: str = "development"
    app_host: str = "0.0.0.0"
    app_port: int = Field(
        default=7860,
        ge=1,
        le=65535,
        validation_alias=AliasChoices("APP_PORT", "PORT"),
    )

    openrouter_api_key: SecretStr
    llm_model: str = "openai/gpt-4"
    llm_vision_model: str | None = None
    llm_text_model: str | None = None
    database_url: str = f"sqlite+aiosqlite:///{_DATA_DIR / 'qa_bot.db'}"
    page_load_timeout: int = Field(default=30, ge=5, le=120)
    max_page_size_kb: int = Field(default=5000, ge=100, le=50000)
    rate_limit_rpm: int = Field(default=10, ge=1, le=60)
    max_concurrent_scans: int = Field(default=3, ge=1, le=20)
    screenshot_width: int = Field(default=1280, ge=640, le=1920)
    text_content_max_chars: int = Field(default=4000, ge=500, le=10000)
    health_score_critical_penalty: int = Field(default=30, ge=1, le=50)
    health_score_warning_penalty: int = Field(default=10, ge=1, le=30)
    health_score_info_penalty: int = Field(default=2, ge=0, le=10)
    health_healthy_threshold: int = Field(default=80, ge=50, le=100)
    health_degraded_threshold: int = Field(default=50, ge=20, le=80)
    screenshot_history_depth: int = Field(default=2, ge=0, le=5)
    screenshot_history_max_width: int = Field(default=640, ge=320, le=1280)
    visual_regression_enabled: bool = True
    health_score_regression_penalty: int = Field(default=5, ge=0, le=30)
    auth_session_cookie_name: str = "qa_bot_session"
    auth_session_secret: SecretStr = SecretStr("change-me-in-production")
    auth_session_cookie_secure: bool | None = None
    auth_session_ttl_hours: int = Field(default=24, ge=1, le=168)
    auth_session_absolute_ttl_hours: int = Field(default=168, ge=1, le=720)
    admin_bootstrap_email: str | None = None
    admin_bootstrap_password: SecretStr | None = None
    auth_login_max_attempts: int = Field(default=5, ge=1, le=20)
    auth_login_attempt_window_seconds: int = Field(default=900, ge=60, le=86400)
    auth_login_block_seconds: int = Field(default=900, ge=60, le=86400)
    auth_trust_proxy_headers: bool = True

    @property
    def is_dual_model(self) -> bool:
        return self.llm_vision_model is not None and self.llm_text_model is not None

    @field_validator("llm_vision_model", "llm_text_model")
    @classmethod
    def normalize_optional_model(cls, v: str | None) -> str | None:
        if v is None:
            return None
        normalized = v.strip()
        return normalized or None

    @property
    def session_cookie_secure(self) -> bool:
        if self.auth_session_cookie_secure is not None:
            return self.auth_session_cookie_secure
        return self.app_env.lower() == "production"

    @field_validator("app_env")
    @classmethod
    def normalize_app_env(cls, v: str) -> str:
        return v.strip().lower()

    @field_validator("database_url")
    @classmethod
    def normalize_database_url(cls, v: str) -> str:
        value = v.strip()
        if value.startswith("postgres://"):
            return value.replace("postgres://", "postgresql+asyncpg://", 1)
        if value.startswith("postgresql://") and "+" not in value.split("://", 1)[0]:
            return value.replace("postgresql://", "postgresql+asyncpg://", 1)
        if value.startswith("sqlite:///") and not value.startswith("sqlite+aiosqlite:///"):
            return value.replace("sqlite:///", "sqlite+aiosqlite:///", 1)
        return value

    @field_validator("health_healthy_threshold")
    @classmethod
    def healthy_must_exceed_degraded(cls, v: int, info) -> int:
        degraded = info.data.get("health_degraded_threshold", 50)
        if v <= degraded:
            raise ValueError("healthy_threshold must exceed degraded_threshold")
        return v

    @field_validator("admin_bootstrap_email")
    @classmethod
    def normalize_bootstrap_email(cls, v: str | None) -> str | None:
        if v is None:
            return None
        normalized = v.strip().lower()
        return normalized or None

    @field_validator("auth_session_secret")
    @classmethod
    def validate_session_secret(cls, v: SecretStr) -> SecretStr:
        if len(v.get_secret_value()) < 16:
            raise ValueError("auth_session_secret must be at least 16 characters")
        return v

    @field_validator("auth_session_absolute_ttl_hours")
    @classmethod
    def absolute_ttl_gte_idle_ttl(cls, v: int, info) -> int:
        idle = info.data.get("auth_session_ttl_hours", 24)
        if v < idle:
            raise ValueError("auth_session_absolute_ttl_hours must be >= auth_session_ttl_hours")
        return v

    @field_validator("admin_bootstrap_password")
    @classmethod
    def normalize_bootstrap_password(cls, v: SecretStr | None) -> SecretStr | None:
        if v is None:
            return None
        trimmed = v.get_secret_value().strip()
        if not trimmed:
            return None
        if len(trimmed) < 12:
            raise ValueError("admin_bootstrap_password must be at least 12 characters")
        return SecretStr(trimmed)

    @model_validator(mode="after")
    def validate_production_security(self) -> Settings:
        if self.app_env != "production":
            return self

        session_secret = self.auth_session_secret.get_secret_value().strip()
        if session_secret.lower() in _WEAK_SESSION_SECRETS:
            raise ValueError(
                "auth_session_secret is using an unsafe placeholder value for production"
            )
        if len(session_secret) < 24:
            raise ValueError("auth_session_secret must be at least 24 characters in production")

        return self
