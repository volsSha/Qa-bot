from __future__ import annotations

from nicegui import app, ui

import qa_bot.ui_dashboard
import qa_bot.ui_scan
import qa_bot.ui_settings
import qa_bot.ui_sites  # noqa: F401 - registers @ui.page("/sites")
from qa_bot.config import _SCREENSHOTS_DIR, Settings, ensure_data_dirs
from qa_bot.database import Database
from qa_bot.orchestrator import QABot
from qa_bot.scheduler import ScanScheduler

_bot: QABot | None = None
_scheduler: ScanScheduler | None = None


def main() -> None:
    global _bot, _scheduler

    ensure_data_dirs()
    settings = Settings()
    database = Database(settings)

    app.add_static_files("/screenshots", str(_SCREENSHOTS_DIR))

    @app.on_startup
    async def _startup():
        global _bot, _scheduler
        await database.init()
        _bot = QABot(settings, database=database)
        _scheduler = ScanScheduler(bot=_bot)
        _scheduler.set_on_scan_complete(_on_scheduled_scan)
        _scheduler.start_timer(interval=60.0)

        app.storage.general["bot"] = _bot
        app.storage.general["scheduler"] = _scheduler

    @app.on_shutdown
    async def _shutdown():
        if _scheduler:
            _scheduler.stop_timer()
        await database.close()

    ui.run(host="0.0.0.0", port=7860, title="QA Bot", reload=False)


async def _on_scheduled_scan(entry, report):
    from nicegui import ui as _ui

    status = report.overall_status
    score = report.health_score
    _ui.notify(
        f"Scheduled scan: {entry.url} — {status} ({score:.0f})",
        type="positive" if status == "healthy" else "warning",
    )


if __name__ == "__main__":
    main()
