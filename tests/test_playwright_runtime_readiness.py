from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from qa_bot.config import Settings
from qa_bot.services.fetcher import (
    PageFetcher,
    PlaywrightReadinessError,
    ensure_playwright_runtime_ready,
)


def _make_settings(**overrides) -> Settings:
    defaults = {"openrouter_api_key": "test-key", "page_load_timeout": 30}
    defaults.update(overrides)
    return Settings(**defaults)


def _build_playwright_cm_with_launch(launch: AsyncMock) -> MagicMock:
    pw_instance = MagicMock()
    pw_instance.chromium.launch = launch
    cm = MagicMock()
    cm.__aenter__ = AsyncMock(return_value=pw_instance)
    cm.__aexit__ = AsyncMock(return_value=False)
    return cm


class TestReadinessCheck:
    @patch("qa_bot.services.fetcher.async_playwright")
    async def test_readiness_check_passes_when_browser_launches(self, mock_pw) -> None:
        browser = AsyncMock()
        launch = AsyncMock(return_value=browser)
        mock_pw.return_value = _build_playwright_cm_with_launch(launch)

        await ensure_playwright_runtime_ready()

        launch.assert_called_once_with(headless=True)
        browser.close.assert_awaited_once()

    @patch("qa_bot.services.fetcher.async_playwright")
    async def test_missing_browser_binary_returns_actionable_error(self, mock_pw) -> None:
        launch = AsyncMock(side_effect=RuntimeError("Executable doesn't exist"))
        mock_pw.return_value = _build_playwright_cm_with_launch(launch)

        with pytest.raises(PlaywrightReadinessError, match="playwright install chromium"):
            await ensure_playwright_runtime_ready()

    @patch("qa_bot.services.fetcher.async_playwright")
    async def test_system_dependency_error_returns_actionable_error(self, mock_pw) -> None:
        launch = AsyncMock(side_effect=RuntimeError("Host system is missing dependencies"))
        mock_pw.return_value = _build_playwright_cm_with_launch(launch)

        with pytest.raises(PlaywrightReadinessError, match="OS dependencies"):
            await ensure_playwright_runtime_ready()


class TestFetcherReadinessFallback:
    @patch("qa_bot.services.fetcher.async_playwright")
    async def test_fetch_returns_predictable_readiness_failure_snapshot(self, mock_pw) -> None:
        launch = AsyncMock(side_effect=RuntimeError("Executable doesn't exist"))
        mock_pw.return_value = _build_playwright_cm_with_launch(launch)

        fetcher = PageFetcher(_make_settings())
        snapshot = await fetcher.fetch("https://example.com")

        assert snapshot.status_code == 0
        assert snapshot.html == ""
        assert snapshot.screenshot == b""
        assert len(snapshot.console_errors) == 1
        assert "Playwright Chromium is not ready" in snapshot.console_errors[0]
