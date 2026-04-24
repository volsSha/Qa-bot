from __future__ import annotations

from qa_bot.config import Settings
from qa_bot.orchestrator import QABot
from qa_bot.ui import create_app


def main() -> None:
    settings = Settings()
    bot = QABot(settings)
    app = create_app(bot)
    app.launch(server_name="0.0.0.0", server_port=7860)


if __name__ == "__main__":
    main()
