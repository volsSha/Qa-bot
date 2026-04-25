from __future__ import annotations

from nicegui import app, ui

from qa_bot.config import Settings, ensure_data_dirs
from qa_bot.database import Database
from qa_bot.orchestrator import QABot
from qa_bot.ui import create_app

_bot: QABot | None = None


@ui.page("/")
async def _index():
    if _bot is None:
        ui.label("Bot not initialized").classes("text-red-500")
        return
    create_app(_bot)


def main() -> None:
    global _bot

    ensure_data_dirs()
    settings = Settings()
    database = Database(settings)

    @app.on_startup
    async def _startup():
        global _bot
        await database.init()
        _bot = QABot(settings, database=database)

    @app.on_shutdown
    async def _shutdown():
        await database.close()

    ui.run(host="0.0.0.0", port=7860, title="QA Bot", reload=False)


if __name__ == "__main__":
    main()
