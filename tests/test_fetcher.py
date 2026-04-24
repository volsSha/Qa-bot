from datetime import datetime
from unittest.mock import AsyncMock, MagicMock, patch

from qa_bot.config import Settings
from qa_bot.fetcher import PageFetcher
from qa_bot.models import PageSnapshot


def _make_settings(**overrides) -> Settings:
    defaults = {"openrouter_api_key": "test-key"}
    defaults.update(overrides)
    return Settings(**defaults)


def _make_page(
    *,
    html: str = "<html><body>Hello</body></html>",
    screenshot: bytes = b"\x89PNGfake",
    text_content: str = "Hello",
    status: int = 200,
    goto_side_effect=None,
) -> AsyncMock:
    page = AsyncMock()
    page.content.return_value = html
    page.screenshot.return_value = screenshot
    page.evaluate.return_value = text_content
    page.on = MagicMock()
    if goto_side_effect:
        page.goto.side_effect = goto_side_effect
    else:
        page.goto.return_value = MagicMock(status=status)
    return page


def _make_browser(page: AsyncMock) -> AsyncMock:
    browser = AsyncMock()
    browser.new_page.return_value = page
    return browser


def _build_playwright_cm(browser: AsyncMock) -> MagicMock:
    pw_instance = MagicMock()
    pw_instance.chromium.launch = AsyncMock(return_value=browser)
    cm = MagicMock()
    cm.__aenter__ = AsyncMock(return_value=pw_instance)
    cm.__aexit__ = AsyncMock(return_value=False)
    return cm


class TestHappyPath:
    @patch("qa_bot.fetcher.async_playwright")
    async def test_fetch_returns_snapshot(self, mock_pw):
        page = _make_page()
        browser = _make_browser(page)
        mock_pw.return_value = _build_playwright_cm(browser)

        fetcher = PageFetcher(_make_settings())
        result = await fetcher.fetch("https://example.com")

        assert isinstance(result, PageSnapshot)
        assert result.status_code == 200
        assert result.html == "<html><body>Hello</body></html>"
        assert result.screenshot == b"\x89PNGfake"
        assert result.text_content == "Hello"
        assert result.console_errors == []
        assert result.load_time_ms >= 0
        assert isinstance(result.fetched_at, datetime)
        page.goto.assert_called_once_with(
            "https://example.com", wait_until="networkidle", timeout=30000
        )
        page.screenshot.assert_called_once_with(full_page=True, type="png")
        page.evaluate.assert_called_once_with("() => document.body.innerText")
        page.on.assert_called_once()
        assert page.on.call_args[0][0] == "console"


class TestConsoleErrors:
    @patch("qa_bot.fetcher.async_playwright")
    async def test_console_errors_captured(self, mock_pw):
        page = _make_page()
        browser = _make_browser(page)
        mock_pw.return_value = _build_playwright_cm(browser)

        captured_handler = None

        def capture_on(event, handler):
            nonlocal captured_handler
            captured_handler = handler

        page.on = MagicMock(side_effect=capture_on)

        async def goto_with_console(*args, **kwargs):
            if captured_handler:
                captured_handler(
                    MagicMock(type="error", text="Uncaught TypeError: x is not defined")
                )
                captured_handler(MagicMock(type="warning", text="Deprecation warning"))
                captured_handler(MagicMock(type="error", text="Failed to load resource"))
            return MagicMock(status=200)

        page.goto.side_effect = goto_with_console

        fetcher = PageFetcher(_make_settings())
        result = await fetcher.fetch("https://example.com")

        assert result.status_code == 200
        assert len(result.console_errors) == 2
        assert "Uncaught TypeError" in result.console_errors[0]
        assert "Failed to load resource" in result.console_errors[1]


class TestTimeout:
    @patch("asyncio.sleep", new_callable=AsyncMock)
    @patch("qa_bot.fetcher.async_playwright")
    async def test_timeout_retry_then_failure(self, mock_pw, mock_sleep):
        page = _make_page(goto_side_effect=TimeoutError("Navigation timed out"))
        browser = _make_browser(page)
        mock_pw.return_value = _build_playwright_cm(browser)

        fetcher = PageFetcher(_make_settings())
        result = await fetcher.fetch("https://example.com")

        assert result.status_code == 0
        assert result.html == ""
        assert result.screenshot == b""
        assert len(result.console_errors) == 1
        assert "TimeoutError" in result.console_errors[0]
        assert page.goto.call_count == 3


class TestNetworkError:
    @patch("asyncio.sleep", new_callable=AsyncMock)
    @patch("qa_bot.fetcher.async_playwright")
    async def test_dns_failure(self, mock_pw, mock_sleep):
        page = _make_page(goto_side_effect=ConnectionError("DNS lookup failed"))
        browser = _make_browser(page)
        mock_pw.return_value = _build_playwright_cm(browser)

        fetcher = PageFetcher(_make_settings())
        result = await fetcher.fetch("https://example.com")

        assert result.status_code == 0
        assert result.html == ""
        assert result.screenshot == b""
        assert len(result.console_errors) == 1
        assert "ConnectionError" in result.console_errors[0]
        assert page.goto.call_count == 3


class TestHTTP500:
    @patch("qa_bot.fetcher.async_playwright")
    async def test_http_500_captured(self, mock_pw):
        page = _make_page(status=500)
        browser = _make_browser(page)
        mock_pw.return_value = _build_playwright_cm(browser)

        fetcher = PageFetcher(_make_settings())
        result = await fetcher.fetch("https://example.com")

        assert result.status_code == 500
        assert result.html == "<html><body>Hello</body></html>"
        assert result.screenshot == b"\x89PNGfake"
