import time
from datetime import UTC, datetime

from bs4 import BeautifulSoup
from playwright.async_api import Page, Response
from playwright.async_api import TimeoutError as PlaywrightTimeoutError
from playwright.async_api import async_playwright
from tenacity import (
    retry,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential,
)

from qa_bot.config import Settings
from qa_bot.domain.models import PageSnapshot


class PlaywrightReadinessError(RuntimeError):
    pass


_PLAYWRIGHT_READINESS_HINT = (
    "Playwright Chromium is not ready. Install browser binaries with "
    "`playwright install chromium` and ensure required OS dependencies "
    "are available for this runtime."
)


async def ensure_playwright_runtime_ready() -> None:
    try:
        async with async_playwright() as pw:
            browser = await pw.chromium.launch(headless=True)
            await browser.close()
    except Exception as exc:
        raise PlaywrightReadinessError(_PLAYWRIGHT_READINESS_HINT) from exc


class PageFetcher:
    def __init__(self, settings: Settings):
        self._settings = settings

    async def fetch(self, url: str) -> PageSnapshot:
        try:
            return await self._fetch_with_retry(url)
        except PlaywrightReadinessError as exc:
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
            try:
                browser = await pw.chromium.launch(headless=True)
            except Exception as exc:
                raise PlaywrightReadinessError(_PLAYWRIGHT_READINESS_HINT) from exc
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
                response: Response | None = None
                try:
                    response = await page.goto(
                        url,
                        wait_until="domcontentloaded",
                        timeout=self._settings.page_load_timeout * 1000,
                    )
                except (TimeoutError, PlaywrightTimeoutError) as exc:
                    console_errors.append(f"Navigation timed out: {exc}")
                    snapshot = await self._capture_snapshot(
                        page=page,
                        url=url,
                        response=response,
                        console_errors=console_errors,
                        load_time_ms=int((time.monotonic() - start) * 1000),
                    )
                    if self._has_usable_partial_content(snapshot):
                        return snapshot
                    raise TimeoutError(str(exc)) from exc

                return await self._capture_snapshot(
                    page=page,
                    url=url,
                    response=response,
                    console_errors=console_errors,
                    load_time_ms=int((time.monotonic() - start) * 1000),
                )
            finally:
                await browser.close()

    async def _capture_snapshot(
        self,
        *,
        page: Page,
        url: str,
        response: Response | None,
        console_errors: list[str],
        load_time_ms: int,
    ) -> PageSnapshot:
        html = await page.content()

        try:
            screenshot = await page.screenshot(full_page=True, type="png")
        except Exception as exc:
            console_errors.append(f"Screenshot capture failed: {exc}")
            screenshot = b""

        try:
            text_content = await page.evaluate("() => document.body.innerText")
        except Exception as exc:
            console_errors.append(f"Text capture failed: {exc}")
            text_content = ""
        text_content = (text_content or "")[: self._settings.text_content_max_chars]

        return PageSnapshot(
            url=url,
            html=html,
            screenshot=screenshot,
            text_content=text_content,
            console_errors=console_errors,
            load_time_ms=load_time_ms,
            status_code=response.status if response else 0,
            fetched_at=datetime.now(UTC),
        )

    def _has_usable_partial_content(self, snapshot: PageSnapshot) -> bool:
        if snapshot.text_content.strip():
            return True

        soup = BeautifulSoup(snapshot.html, "lxml")
        return bool(soup.get_text(separator=" ", strip=True))
