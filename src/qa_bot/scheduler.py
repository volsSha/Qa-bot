from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from qa_bot.orchestrator import QABot

logger = logging.getLogger(__name__)

_INTERVAL_SECONDS = {
    "1h": 3600,
    "6h": 21600,
    "12h": 43200,
    "24h": 86400,
    "7d": 604800,
}


@dataclass
class ScheduleEntry:
    page_id: int
    url: str
    interval_key: str
    interval_seconds: int
    last_scan_at: datetime | None = None
    running: bool = False


@dataclass
class ScanScheduler:
    bot: QABot
    _entries: dict[int, ScheduleEntry] = field(default_factory=dict)
    _locks: dict[int, asyncio.Lock] = field(default_factory=dict)
    _tasks: set[asyncio.Task] = field(default_factory=set)
    _timer_running: bool = False
    _timer_task: asyncio.Task | None = field(default=None, repr=False)
    _timer_interval: float = 60.0
    _paused: bool = False
    _on_scan_complete: object | None = field(default=None, repr=False)

    def schedule(self, page_id: int, url: str, interval_key: str) -> None:
        seconds = _INTERVAL_SECONDS.get(interval_key)
        if seconds is None:
            return
        self._entries[page_id] = ScheduleEntry(
            page_id=page_id,
            url=url,
            interval_key=interval_key,
            interval_seconds=seconds,
        )
        if page_id not in self._locks:
            self._locks[page_id] = asyncio.Lock()

    def unschedule(self, page_id: int) -> None:
        self._entries.pop(page_id, None)

    def get_schedule(self, page_id: int) -> ScheduleEntry | None:
        return self._entries.get(page_id)

    def get_all_schedules(self) -> list[ScheduleEntry]:
        return list(self._entries.values())

    def pause(self) -> None:
        self._paused = True

    def resume(self) -> None:
        self._paused = False

    @property
    def is_paused(self) -> bool:
        return self._paused

    def next_scan_in(self, page_id: int) -> int | None:
        entry = self._entries.get(page_id)
        if entry is None or entry.last_scan_at is None:
            return None
        elapsed = (datetime.now(UTC) - entry.last_scan_at).total_seconds()
        remaining = entry.interval_seconds - elapsed
        return max(0, int(remaining))

    def set_on_scan_complete(self, callback) -> None:
        self._on_scan_complete = callback

    async def tick(self) -> None:
        if self._paused:
            return
        now = datetime.now(UTC)
        for entry in list(self._entries.values()):
            if entry.running:
                continue
            if entry.last_scan_at is None:
                due = True
            else:
                elapsed = (now - entry.last_scan_at).total_seconds()
                due = elapsed >= entry.interval_seconds
            if due:
                lock = self._locks.get(entry.page_id)
                if lock and not lock.locked():
                    task = asyncio.create_task(self._run_scheduled(entry))
                    task.add_done_callback(lambda t: self._tasks.discard(t))
                    self._tasks.add(task)

    async def _run_scheduled(self, entry: ScheduleEntry) -> None:
        lock = self._locks.get(entry.page_id)
        if lock is None:
            return
        async with lock:
            entry.running = True
            try:
                report = await self.bot.scan_url(entry.url)
                entry.last_scan_at = datetime.now(UTC)
                if self._on_scan_complete:
                    try:
                        await self._on_scan_complete(entry, report)
                    except Exception:
                        logger.exception("Scheduler callback failed")
            except Exception:
                logger.exception("Scheduled scan failed for %s", entry.url)
            finally:
                entry.running = False

    def start_timer(self, interval: float = 60.0) -> None:
        self._timer_interval = interval
        self._timer_running = True
        self._timer_task = asyncio.create_task(self._timer_loop())

    async def _timer_loop(self) -> None:
        import asyncio as _asyncio

        while self._timer_running:
            await _asyncio.sleep(self._timer_interval)
            try:
                await self.tick()
            except Exception:
                logger.exception("Scheduler tick failed")

    def stop_timer(self) -> None:
        self._timer_running = False
        if self._timer_task is not None:
            self._timer_task.cancel()
            self._timer_task = None
