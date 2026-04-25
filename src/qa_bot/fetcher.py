import time
from datetime import UTC, datetime

from playwright.async_api import async_playwright
from tenacity import (
    retry,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential,
)

from qa_bot.config import Settings
from qa_bot.models import PageSnapshot


class PageFetcher:
    def __init__(self, settings: Settings):
        self._settings = settings

    async def fetch(self, url: str) -> PageSnapshot:
        try:
            return await self._fetch_with_retry(url)
        except Exception as exc:
            return PageSnapshot(
                url=url,
                html="",
                screenshot=b"",
                text_content="",
                console_errors=[str(exc)],
                load_time_ms=0,
                status_code=0,
                fetched_at=datetime.now(UTC),
            )

    @retry(
        retry=retry_if_exception_type((ConnectionError, TimeoutError)),
        stop=stop_after_attempt(3),
        wait=wait_exponential(min=1, max=10),
    )
    async def _fetch_with_retry(self, url: str) -> PageSnapshot:
        async with async_playwright() as pw:
            browser = await pw.chromium.launch(headless=True)
            try:
                page = await browser.new_page(
                    viewport={"width": self._settings.screenshot_width, "height": 800}
                )

                console_errors: list[str] = []
                page.on(
                    "console",
                    lambda msg: console_errors.append(msg.text)
                    if msg.type == "error"
                    else None,
                )

                start = time.monotonic()
                response = await page.goto(
                    url,
                    wait_until="networkidle",
                    timeout=self._settings.page_load_timeout * 1000,
                )
                load_time_ms = int((time.monotonic() - start) * 1000)

                html = await page.content()
                screenshot = await page.screenshot(full_page=True, type="png")
                text_content = await page.evaluate("() => document.body.innerText")
                text_content = (text_content or "")[: self._settings.text_content_max_chars]

                status_code = response.status if response else 0

                return PageSnapshot(
                    url=url,
                    html=html,
                    screenshot=screenshot,
                    text_content=text_content,
                    console_errors=console_errors,
                    load_time_ms=load_time_ms,
                    status_code=status_code,
                    fetched_at=datetime.now(UTC),
                )
            finally:
                await browser.close()
