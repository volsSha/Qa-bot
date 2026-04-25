from __future__ import annotations

from datetime import UTC, datetime
from typing import TYPE_CHECKING

from nicegui import ui

from qa_bot.models import ScanBatch
from qa_bot.reporter import format_report_markdown
from qa_bot.ui_helpers import (
    find_latest_screenshot,
    parse_urls,
    score_badge,
    status_badge,
)
from qa_bot.ui_layout import create_layout

if TYPE_CHECKING:
    from qa_bot.orchestrator import QABot


async def _scan(
    bot: QABot,
    text: str,
    result_container: ui.column,
    progress: ui.linear_progress,
):
    urls = parse_urls(text)
    if not urls:
        ui.notify("No valid URLs provided", type="warning")
        return

    total = len(urls)
    progress.set_value(0)
    progress.set_visibility(True)

    try:
        with result_container:
            result_container.clear()
            with ui.row().classes("items-center gap-3 py-4"):
                ui.spinner("dots", size="lg", color="blue")
                ui.label(
                    f"Scanning {total} URL{'' if total == 1 else 's'}..."
                ).classes(
                    "text-lg text-slate-600 dark:text-slate-300"
                )

        reports = []
        for i, url in enumerate(urls):
            try:
                report = await bot.scan_url(url)
                reports.append(report)
            except Exception:
                reports.append(None)
                ui.notify(f"Failed to scan {url}", type="negative")
            progress.set_value((i + 1) / total)

        batch = ScanBatch(
            urls=urls,
            reports=[r for r in reports if r is not None],
            generated_at=datetime.now(UTC),
        )

        with result_container:
            result_container.clear()
            with ui.row().classes("items-center gap-4 mb-4"):
                healthy = sum(
                    1 for r in batch.reports if r.overall_status == "healthy"
                )
                degraded = sum(
                    1 for r in batch.reports if r.overall_status == "degraded"
                )
                broken = sum(
                    1 for r in batch.reports if r.overall_status == "broken"
                )
                ui.label(f"Scanned {len(batch.reports)} URLs").classes(
                    "text-lg font-semibold text-slate-800 dark:text-white"
                )
                if healthy:
                    ui.html(
                        f'<span class="text-green-500 font-semibold">'
                        f"{healthy} healthy</span>"
                    )
                if degraded:
                    ui.html(
                        f'<span class="text-yellow-500 font-semibold">'
                        f"{degraded} degraded</span>"
                    )
                if broken:
                    ui.html(
                        f'<span class="text-red-500 font-semibold">'
                        f"{broken} broken</span>"
                    )

            with ui.row().classes("w-full gap-4 flex-wrap"):
                for report in batch.reports:
                    with ui.card().classes(
                        "flex-1 min-w-[280px] max-w-[400px]"
                    ).tight():
                        with ui.row().classes(
                            "items-center justify-between px-4 py-2 "
                            "bg-gray-50 dark:bg-slate-800"
                        ):
                            ui.label(report.url).classes(
                                "text-sm font-medium truncate "
                                "text-slate-800 dark:text-white"
                            )
                        with ui.column().classes("px-4 py-3 gap-2"):
                            with ui.row().classes("items-center gap-2"):
                                ui.html(status_badge(report.overall_status))
                                ui.html(score_badge(report.health_score))
                            ui.label(report.summary).classes(
                                "text-xs text-slate-500 dark:text-slate-400"
                            )

                            screenshot_file = find_latest_screenshot(report.url)
                            if screenshot_file:
                                with ui.expansion("Screenshot"):
                                    ui.image(
                                        f"/screenshots/{screenshot_file}"
                                    ).classes("w-full rounded")

                            with ui.expansion("Details"):
                                ui.markdown(format_report_markdown(report))

            ui.notify(
                f"Scanned {len(batch.reports)} URLs", type="positive"
            )
    finally:
        progress.set_visibility(False)


@ui.page("/scan")
async def scan_page():
    from nicegui import app

    create_layout(active="scan")
    bot: QABot | None = app.storage.general.get("bot")

    if bot is None:
        ui.label("Bot not initialized").classes("text-red-500 p-8")
        return

    with ui.column().classes("w-full max-w-5xl mx-auto px-6 py-6 gap-4"):
        with ui.card().classes("w-full"):
            ui.label("Scan Web Pages").classes(
                "text-lg font-semibold text-slate-800 dark:text-white mb-3"
            )
            url_input = ui.textarea(
                placeholder=(
                    "Enter URLs, one per line\n"
                    "https://example.com\n"
                    "https://another-site.com"
                ),
            ).classes("w-full")
            with ui.row().classes("items-center gap-3"):
                scan_btn = ui.button(
                    "Run Scan",
                    icon="search",
                    on_click=lambda: _scan(
                        bot, url_input.value, result_container, progress
                    ),
                )
                scan_btn.props("color=primary")

        progress = ui.linear_progress(value=0).classes("w-full")
        progress.set_visibility(False)

        result_container = ui.column().classes("w-full")
