from __future__ import annotations

import asyncio

from qa_bot.config import Settings, ensure_data_dirs
from qa_bot.orchestrator import QABot
from qa_bot.ui import create_app


async def _main() -> None:
    ensure_data_dirs()
    settings = Settings()
    bot = QABot(settings)
    app = create_app(bot)
    app.launch(server_name="0.0.0.0", server_port=7860)


def main() -> None:
    asyncio.run(_main())


if __name__ == "__main__":
    main()
