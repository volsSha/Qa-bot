from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from qa_bot.services.auth import AuthService
    from qa_bot.services.orchestrator import QABot
    from qa_bot.services.scheduler import ScanScheduler

bot: QABot | None = None
scheduler: ScanScheduler | None = None
auth_service: AuthService | None = None
