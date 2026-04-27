from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from qa_bot.config import _BASE_DIR, Settings

if TYPE_CHECKING:
    pass

logger = logging.getLogger(__name__)

_ENV_PATH = _BASE_DIR / ".env"

_DEFAULTS: dict[str, str] = {
    "LLM_MODEL": "openai/gpt-4",
    "PAGE_LOAD_TIMEOUT": "30",
    "MAX_PAGE_SIZE_KB": "5000",
    "RATE_LIMIT_RPM": "10",
    "MAX_CONCURRENT_SCANS": "3",
    "HEALTH_SCORE_CRITICAL_PENALTY": "30",
    "HEALTH_SCORE_WARNING_PENALTY": "10",
    "HEALTH_SCORE_INFO_PENALTY": "2",
    "HEALTH_HEALTHY_THRESHOLD": "80",
    "HEALTH_DEGRADED_THRESHOLD": "50",
}

_EDITABLE_FIELDS: list[tuple[str, str, str]] = [
    ("LLM_MODEL", "LLM Model", "text"),
    ("PAGE_LOAD_TIMEOUT", "Page Load Timeout (s)", "number"),
    ("MAX_PAGE_SIZE_KB", "Max Page Size (KB)", "number"),
    ("MAX_CONCURRENT_SCANS", "Max Concurrent Scans", "number"),
    ("RATE_LIMIT_RPM", "Rate Limit (req/min)", "number"),
    ("HEALTH_SCORE_CRITICAL_PENALTY", "Critical Penalty", "number"),
    ("HEALTH_SCORE_WARNING_PENALTY", "Warning Penalty", "number"),
    ("HEALTH_SCORE_INFO_PENALTY", "Info Penalty", "number"),
    ("HEALTH_HEALTHY_THRESHOLD", "Healthy Threshold", "number"),
    ("HEALTH_DEGRADED_THRESHOLD", "Degraded Threshold", "number"),
]

_FIELD_GROUPS = [
    ("LLM Configuration", ["LLM_MODEL"]),
    (
        "Performance",
        [
            "PAGE_LOAD_TIMEOUT",
            "MAX_PAGE_SIZE_KB",
            "MAX_CONCURRENT_SCANS",
            "RATE_LIMIT_RPM",
        ],
    ),
    ("Health Scoring", [
        "HEALTH_SCORE_CRITICAL_PENALTY", "HEALTH_SCORE_WARNING_PENALTY",
        "HEALTH_SCORE_INFO_PENALTY", "HEALTH_HEALTHY_THRESHOLD",
        "HEALTH_DEGRADED_THRESHOLD",
    ]),
]


def _read_env() -> dict[str, str]:
    values: dict[str, str] = dict(_DEFAULTS)
    if not _ENV_PATH.exists():
        return values
    for line in _ENV_PATH.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        if "=" in line:
            key, _, val = line.partition("=")
            values[key.strip()] = val.strip()
    return values


def _write_env(values: dict[str, str]) -> None:
    existing_lines: list[str] = []
    if _ENV_PATH.exists():
        existing_lines = _ENV_PATH.read_text(encoding="utf-8").splitlines()

    written_keys: set[str] = set()
    new_lines: list[str] = []
    for line in existing_lines:
        stripped = line.strip()
        if stripped and not stripped.startswith("#") and "=" in stripped:
            key = stripped.split("=", 1)[0].strip()
            if key in values:
                new_lines.append(f"{key}={values[key]}")
                written_keys.add(key)
            else:
                new_lines.append(line)
        else:
            new_lines.append(line)

    for key in values:
        if key not in written_keys:
            new_lines.append(f"{key}={values[key]}")

    _ENV_PATH.write_text("\n".join(new_lines) + "\n", encoding="utf-8")


def get_current_settings() -> dict[str, str]:
    return _read_env()


def save_settings(changes: dict[str, str]) -> dict[str, list[str]]:
    current = _read_env()
    errors: dict[str, list[str]] = {}

    num_fields = {
        "PAGE_LOAD_TIMEOUT", "MAX_PAGE_SIZE_KB", "MAX_CONCURRENT_SCANS",
        "RATE_LIMIT_RPM", "HEALTH_SCORE_CRITICAL_PENALTY",
        "HEALTH_SCORE_WARNING_PENALTY", "HEALTH_SCORE_INFO_PENALTY",
        "HEALTH_HEALTHY_THRESHOLD", "HEALTH_DEGRADED_THRESHOLD",
    }
    for key in changes:
        if key in num_fields:
            try:
                int(changes[key])
            except ValueError:
                errors.setdefault(key, []).append("Must be a number")

    healthy_key = "HEALTH_HEALTHY_THRESHOLD"
    degraded_key = "HEALTH_DEGRADED_THRESHOLD"
    healthy_val = changes.get(healthy_key, current.get(healthy_key, "80"))
    degraded_val = changes.get(degraded_key, current.get(degraded_key, "50"))
    try:
        h = int(healthy_val)
        d = int(degraded_val)
        if h <= d:
            errors.setdefault(healthy_key, []).append(
                "Healthy threshold must exceed degraded threshold"
            )
    except (ValueError, TypeError):
        pass

    if errors:
        return errors

    current.update(changes)
    _write_env(current)
    return {}


def build_new_settings() -> Settings:
    values = _read_env()
    return Settings(
        openrouter_api_key=values.get("OPENROUTER_API_KEY", ""),
        llm_model=values.get("LLM_MODEL", "openai/gpt-4"),
        page_load_timeout=int(values.get("PAGE_LOAD_TIMEOUT", "30")),
        max_page_size_kb=int(values.get("MAX_PAGE_SIZE_KB", "5000")),
        rate_limit_rpm=int(values.get("RATE_LIMIT_RPM", "10")),
        max_concurrent_scans=int(values.get("MAX_CONCURRENT_SCANS", "3")),
        health_score_critical_penalty=int(values.get("HEALTH_SCORE_CRITICAL_PENALTY", "30")),
        health_score_warning_penalty=int(values.get("HEALTH_SCORE_WARNING_PENALTY", "10")),
        health_score_info_penalty=int(values.get("HEALTH_SCORE_INFO_PENALTY", "2")),
        health_healthy_threshold=int(values.get("HEALTH_HEALTHY_THRESHOLD", "80")),
        health_degraded_threshold=int(values.get("HEALTH_DEGRADED_THRESHOLD", "50")),
    )


def get_field_definitions():
    return _FIELD_GROUPS, _EDITABLE_FIELDS, _DEFAULTS
