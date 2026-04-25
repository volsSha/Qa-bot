from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from qa_bot.orchestrator import QABot
    from qa_bot.scheduler import ScanScheduler

bot: QABot | None = None
scheduler: ScanScheduler | None = None
