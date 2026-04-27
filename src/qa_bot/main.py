from __future__ import annotations

import logging

from nicegui import app, ui
from pydantic import ValidationError

import qa_bot.ui.admin_users
import qa_bot.ui.auth
import qa_bot.ui.dashboard
import qa_bot.ui.scan
import qa_bot.ui.settings
import qa_bot.ui.sites  # noqa: F401
from qa_bot.config import _SCREENSHOTS_DIR, Settings, ensure_data_dirs
from qa_bot.db.database import Database
from qa_bot.services import state
from qa_bot.services.auth import AuthService
from qa_bot.services.fetcher import PlaywrightReadinessError, ensure_playwright_runtime_ready
from qa_bot.services.orchestrator import QABot
from qa_bot.services.scheduler import ScanScheduler

logger = logging.getLogger(__name__)


def main() -> None:
    ensure_data_dirs()
    try:
        settings = Settings()
    except ValidationError as exc:
        logger.critical("Configuration validation failed: %s", exc)
        raise SystemExit(1) from exc

    database = Database(settings)
    auth_service = AuthService(settings=settings, database=database)

    app.add_static_files("/screenshots", str(_SCREENSHOTS_DIR))

    @app.on_startup
    async def _startup():
        if settings.app_env == "production":
            logger.info("Running production startup validations")

        try:
            await ensure_playwright_runtime_ready()
        except PlaywrightReadinessError as exc:
            logger.warning("Playwright runtime readiness check failed: %s", exc)

        await database.init()
        await auth_service.bootstrap_admin_if_needed()
        bot = QABot(settings, database=database)
        scheduler = ScanScheduler(bot=bot)
        scheduler.set_on_scan_complete(_on_scheduled_scan)
        scheduler.start_timer(interval=60.0)
        state.bot = bot
        state.scheduler = scheduler
        state.auth_service = auth_service

    @app.on_shutdown
    async def _shutdown():
        if state.scheduler:
            state.scheduler.stop_timer()
        state.auth_service = None
        await database.close()

    ui.run(
        host=settings.app_host,
        port=settings.app_port,
        title="QA Bot",
        reload=False,
        storage_secret=settings.auth_session_secret.get_secret_value(),
        session_middleware_kwargs={
            "session_cookie": settings.auth_session_cookie_name,
            "https_only": settings.session_cookie_secure,
            "same_site": "lax",
            "max_age": settings.auth_session_absolute_ttl_hours * 3600,
        },
        proxy_headers=settings.auth_trust_proxy_headers,
        forwarded_allow_ips="*",
    )


async def _on_scheduled_scan(entry, report):
    status = report.overall_status
    score = report.health_score
    logger.info(
        "Scheduled scan: %s — %s (%.0f)", entry.url, status, score
    )


if __name__ == "__main__":
    main()
