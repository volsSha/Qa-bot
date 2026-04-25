from __future__ import annotations

import logging

from nicegui import app, ui

import qa_bot.ui_dashboard
import qa_bot.ui_scan
import qa_bot.ui_settings
import qa_bot.ui_sites  # noqa: F401
from qa_bot import state
from qa_bot.config import _SCREENSHOTS_DIR, Settings, ensure_data_dirs
from qa_bot.database import Database
from qa_bot.orchestrator import QABot
from qa_bot.scheduler import ScanScheduler

logger = logging.getLogger(__name__)


def main() -> None:
    ensure_data_dirs()
    settings = Settings()
    database = Database(settings)

    app.add_static_files("/screenshots", str(_SCREENSHOTS_DIR))

    @app.on_startup
    async def _startup():
        await database.init()
        bot = QABot(settings, database=database)
        scheduler = ScanScheduler(bot=bot)
        scheduler.set_on_scan_complete(_on_scheduled_scan)
        scheduler.start_timer(interval=60.0)
        state.bot = bot
        state.scheduler = scheduler

    @app.on_shutdown
    async def _shutdown():
        if state.scheduler:
            state.scheduler.stop_timer()
        await database.close()

    ui.run(host="0.0.0.0", port=7860, title="QA Bot", reload=False)


async def _on_scheduled_scan(entry, report):
    status = report.overall_status
    score = report.health_score
    logger.info(
        "Scheduled scan: %s — %s (%.0f)", entry.url, status, score
    )


if __name__ == "__main__":
    main()
