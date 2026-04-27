from __future__ import annotations

import re
from pathlib import Path


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[1]


def _extract_env_keys(env_example: str) -> set[str]:
    keys: set[str] = set()
    for line in env_example.splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        if "=" in stripped:
            key = stripped.split("=", 1)[0].strip()
            if key:
                keys.add(key)
    return keys


def _extract_backtick_vars(text: str) -> set[str]:
    return set(re.findall(r"`([A-Z][A-Z0-9_]+)`", text))


def test_readme_and_runbook_cover_required_env_vars() -> None:
    root = _repo_root()
    env_example = (root / ".env.example").read_text(encoding="utf-8")
    readme = (root / "README.md").read_text(encoding="utf-8")
    runbook = (root / "docs/deploy/heroku-runbook.md").read_text(encoding="utf-8")

    env_keys = _extract_env_keys(env_example)
    required = {
        "APP_ENV",
        "OPENROUTER_API_KEY",
        "AUTH_SESSION_SECRET",
        "ADMIN_BOOTSTRAP_EMAIL",
        "ADMIN_BOOTSTRAP_PASSWORD",
    }

    assert required.issubset(env_keys)
    assert required.issubset(_extract_backtick_vars(readme))
    assert required.issubset(_extract_backtick_vars(runbook))


def test_heroku_docs_match_procfile_startup_command() -> None:
    root = _repo_root()
    procfile = (root / "Procfile").read_text(encoding="utf-8").strip()
    readme = (root / "README.md").read_text(encoding="utf-8")
    runbook = (root / "docs/deploy/heroku-runbook.md").read_text(encoding="utf-8")

    assert procfile == "web: python -m qa_bot.main"
    assert "web: python -m qa_bot.main" in readme
    assert "web: python -m qa_bot.main" in runbook
