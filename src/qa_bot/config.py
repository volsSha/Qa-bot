from pathlib import Path

from pydantic import Field, SecretStr, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

_BASE_DIR = Path(__file__).resolve().parent.parent.parent
_DATA_DIR = _BASE_DIR / "data"
_SCREENSHOTS_DIR = _DATA_DIR / "screenshots"
_REPORTS_DIR = _DATA_DIR / "reports"


def ensure_data_dirs() -> None:
    _SCREENSHOTS_DIR.mkdir(parents=True, exist_ok=True)
    _REPORTS_DIR.mkdir(parents=True, exist_ok=True)


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=str(_BASE_DIR / ".env"),
        env_file_encoding="utf-8",
        frozen=True,
    )

    openrouter_api_key: SecretStr
    llm_model: str = "openai/gpt-4"
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

    @field_validator("health_healthy_threshold")
    @classmethod
    def healthy_must_exceed_degraded(cls, v: int, info) -> int:
        degraded = info.data.get("health_degraded_threshold", 50)
        if v <= degraded:
            raise ValueError("healthy_threshold must exceed degraded_threshold")
        return v
