from __future__ import annotations

from pathlib import Path

from qa_bot.config import Settings


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[1]


def test_procfile_uses_python_module_entrypoint() -> None:
    procfile = (_repo_root() / "Procfile").read_text(encoding="utf-8").strip()
    assert procfile == "web: python -m qa_bot.main"


def test_procfile_does_not_depend_on_uv() -> None:
    procfile = (_repo_root() / "Procfile").read_text(encoding="utf-8")
    assert "uv run" not in procfile


def test_runtime_txt_declares_explicit_python_version() -> None:
    runtime_txt = (_repo_root() / "runtime.txt").read_text(encoding="utf-8").strip()
    assert runtime_txt.startswith("python-")
    version = runtime_txt.removeprefix("python-")
    parts = version.split(".")
    assert len(parts) == 3
    assert all(part.isdigit() for part in parts)


def test_settings_accept_heroku_port_alias() -> None:
    settings = Settings(openrouter_api_key="test-key", PORT=5001)
    assert settings.app_port == 5001
