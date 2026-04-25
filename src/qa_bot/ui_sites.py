from __future__ import annotations

import contextlib
from typing import TYPE_CHECKING

from nicegui import ui

from qa_bot.ui_helpers import (
    find_latest_screenshot,
    plural,
    score_badge,
    severity_badge,
    status_badge,
    validate_single_url,
)
from qa_bot.ui_layout import create_layout

if TYPE_CHECKING:
    from qa_bot.orchestrator import QABot
    from qa_bot.scheduler import ScanScheduler

_INTERVAL_OPTIONS = [
    ("None", None),
    ("Every hour", "1h"),
    ("Every 6 hours", "6h"),
    ("Every 12 hours", "12h"),
    ("Every day", "24h"),
    ("Every week", "7d"),
]


async def _load_sites(
    bot: QABot,
    scheduler: ScanScheduler | None,
    sites_container: ui.column,
    page_detail_container: ui.column,
) -> None:
    if bot._database is None:
        sites_container.clear()
        with sites_container:
            ui.label("Database not configured").classes("text-gray-400")
        return

    sites = await bot._database.get_sites()
    page_detail_container.clear()
    sites_container.clear()

    with sites_container:
        if not sites:
            ui.label("No sites tracked yet").classes(
                "text-gray-400 dark:text-gray-500 text-lg mt-4"
            )
            return

        for site in sites:
            domain = site["domain"]
            label = site.get("label")
            pages = site.get("pages", [])

            with ui.card().classes("w-full").tight():
                with ui.row().classes(
                    "flex items-center justify-between w-full "
                    "bg-gray-50 dark:bg-slate-800 px-4 py-3"
                ):
                    with ui.row().classes("items-center gap-2"):
                        ui.icon("language").classes("text-blue-500")
                        ui.label(domain).classes(
                            "text-lg font-semibold text-slate-800 dark:text-white"
                        )
                        if label:
                            ui.label(label).classes(
                                "text-gray-500 dark:text-gray-400 text-sm"
                            )
                    page_count = len(pages)
                    ui.badge(
                        f"{page_count} page{plural(page_count)}",
                        color="blue",
                    ).props("color=blue")

                if not pages:
                    continue

                with ui.row().classes("gap-3 flex-wrap w-full p-3"):
                    for p in pages:
                        _render_page_card(bot, scheduler, p, sites_container, page_detail_container)


def _render_page_card(
    bot: QABot,
    scheduler: ScanScheduler | None,
    p: dict,
    sites_container: ui.column,
    page_detail_container: ui.column,
) -> None:
    page_id = p["id"]
    url = p.get("url", "")
    status = p.get("latest_status")
    score = p.get("latest_score")
    scan_count = p.get("scan_count", 0)
    path = p.get("path") or url

    with ui.card().classes(
        "cursor-pointer hover:shadow-lg transition-shadow "
        "min-w-[220px] max-w-[300px]"
    ).on(
        "click",
        lambda pid=page_id: _show_page_detail(
            bot, scheduler, pid, sites_container, page_detail_container
        ),
    ):
        with ui.row().classes("items-center justify-between"):
            ui.label(path).classes(
                "font-medium text-sm truncate text-slate-800 dark:text-white"
            )

        with ui.row().classes("items-center gap-2 mt-1"):
            ui.html(status_badge(status))
            ui.html(score_badge(score))
            ui.label(f"{scan_count} scan{plural(scan_count)}").classes(
                "text-xs text-slate-400 dark:text-slate-500"
            )

        screenshot_file = find_latest_screenshot(url)
        if screenshot_file:
            ui.image(f"/screenshots/{screenshot_file}").classes(
                "w-full h-20 object-cover rounded mt-2"
            )

        if scheduler:
            entry = scheduler.get_schedule(page_id)
            if entry:
                remaining = scheduler.next_scan_in(page_id)
                if remaining is not None:
                    mins = remaining // 60
                    ui.label(f"Next scan in {mins}m").classes(
                        "text-xs text-blue-500 mt-1"
                    )

        with ui.row().classes("gap-1 mt-2").on("click.stop"):
            async def _rescan(u=url, sc=sites_container, pd=page_detail_container):
                ui.notify(f"Scanning {u}...", type="info")
                with contextlib.suppress(Exception):
                    await bot.scan_url(u)
                await _load_sites(bot, scheduler, sc, pd)
                ui.notify(f"Rescanned {u}", type="positive")

            ui.button(icon="refresh", on_click=_rescan).props(
                "flat round dense size=sm"
            ).classes("text-slate-400")

            if scheduler:
                def _make_schedule_handler(
                    pid=page_id,
                    u=url,
                    sc=sites_container,
                    pd=page_detail_container,
                ):
                    async def handler(e):
                        val = e.value if hasattr(e, "value") else e
                        if val is None or val == "None":
                            scheduler.unschedule(pid)
                        else:
                            scheduler.schedule(pid, u, val)
                        await _load_sites(bot, scheduler, sc, pd)
                    return handler

                current_interval = None
                if scheduler:
                    entry = scheduler.get_schedule(page_id)
                    if entry:
                        current_interval = entry.interval_key

                ui.select(
                    [opt[1] for opt in _INTERVAL_OPTIONS],
                    value=current_interval,
                    on_change=_make_schedule_handler(),
                ).props("dense borderless size=sm").classes("text-xs")


async def _show_page_detail(
    bot: QABot,
    scheduler: ScanScheduler | None,
    page_id: int,
    sites_container: ui.column,
    page_detail_container: ui.column,
) -> None:
    sites_container.set_visibility(False)
    await _load_page_detail(
        bot, scheduler, page_id, sites_container, page_detail_container
    )


async def _load_page_detail(
    bot: QABot,
    scheduler: ScanScheduler | None,
    page_id: int,
    sites_container: ui.column,
    page_detail_container: ui.column,
) -> None:
    page_detail_container.clear()
    with page_detail_container:
        if bot._database is None:
            ui.label("Database not configured")
            return

        detail = await bot._database.get_page_with_latest_scan(page_id)
        if detail is None:
            ui.label("Page not found")
            return

        with ui.card().classes("w-full").tight():
            with ui.row().classes(
                "flex items-center justify-between "
                "bg-gray-50 dark:bg-slate-800 px-4 py-3"
            ):
                with ui.row().classes("items-center gap-3"):
                    ui.label(detail["url"]).classes(
                        "text-lg font-semibold truncate text-slate-800 dark:text-white"
                    )
                ui.button(
                    "Back",
                    icon="arrow_back",
                    on_click=lambda: _go_back_to_sites(
                        bot, scheduler, sites_container, page_detail_container
                    ),
                ).props("flat color=primary")

            with ui.column().classes("px-4 py-3 gap-3"):
                ui.label(f"Domain: {detail.get('site_domain', '—')}").classes(
                    "text-sm text-slate-500 dark:text-slate-400"
                )
                ui.label(f"Total scans: {detail.get('scan_count', 0)}").classes(
                    "text-sm text-slate-500 dark:text-slate-400"
                )

                screenshot_file = find_latest_screenshot(detail["url"])
                if screenshot_file:
                    with ui.expansion("Latest Screenshot"):
                        ui.image(f"/screenshots/{screenshot_file}").classes(
                            "w-full max-w-2xl rounded"
                        )

                history_data = await bot._database.get_page_health_history(
                    page_id, limit=15
                )
                if len(history_data) >= 2:
                    scores = [h["score"] for h in reversed(history_data)]
                    ui.echart({
                        "backgroundColor": "transparent",
                        "xAxis": {
                            "show": False,
                            "type": "category",
                            "data": list(range(len(scores))),
                        },
                        "yAxis": {"show": False, "type": "value", "min": 0, "max": 100},
                        "grid": {"left": 0, "right": 0, "top": 5, "bottom": 5},
                        "series": [{
                            "type": "line",
                            "data": scores,
                            "smooth": True,
                            "symbol": "none",
                            "lineStyle": {"width": 2, "color": "#3b82f6"},
                            "areaStyle": {"opacity": 0.15, "color": "#3b82f6"},
                        }],
                    }).style("height: 60px; width: 100%;")

                latest = detail.get("latest_scan")
                if latest:
                    _render_latest_scan(latest)
                else:
                    ui.label("No scans yet.").classes(
                        "text-gray-400 dark:text-gray-500"
                    )

                history = []
                if bot._database:
                    history = await bot._database.get_scan_history(page_id, limit=20)
                if history:
                    _render_scan_history(history)


def _render_latest_scan(latest: dict) -> None:
    with ui.separator():
        pass
    ui.label("Latest Scan").classes("text-base font-semibold mt-2 text-slate-800 dark:text-white")
    with ui.row().classes("items-center gap-3"):
        ui.html(status_badge(latest["overall_status"]))
        score_html = (
            f'<span class="text-xl font-bold text-slate-800 dark:text-white">'
            f'{latest["health_score"]:.0f}</span>'
        )
        ui.html(score_html)
        model = latest.get("model_used", "—")
        ui.label(f"Model: {model}").classes(
            "text-sm text-slate-500 dark:text-slate-400"
        )
    ts = latest["scanned_at"]
    date_str = ts.strftime("%Y-%m-%d %H:%M:%S") if ts else "—"
    ui.label(f"Scanned: {date_str}").classes(
        "text-sm text-slate-500 dark:text-slate-400"
    )

    rule_results = latest.get("rule_results", [])
    if rule_results:
        with ui.expansion("Rule Results"):
            with ui.row().classes(
                "w-full gap-0 border-b border-gray-200 dark:border-slate-700 "
                "text-xs font-semibold text-slate-500 dark:text-slate-400"
            ):
                ui.label("Check").classes("w-[120px] px-2 py-1")
                ui.label("Severity").classes("w-[100px] px-2 py-1 text-center")
                ui.label("Message").classes("flex-1 px-2 py-1")
            for r in rule_results:
                with ui.row().classes(
                    "w-full gap-0 border-b border-gray-100 "
                    "dark:border-slate-700/50 text-sm"
                ):
                    ui.label(r.get("check_name", "—")).classes(
                        "w-[120px] px-2 py-1 font-mono text-xs"
                    )
                    ui.html(severity_badge(r.get("severity"))).classes(
                        "w-[100px] px-2 py-1 text-center"
                    )
                    ui.label(r.get("message", "—")).classes(
                        "flex-1 px-2 py-1"
                    )

    llm_eval = latest.get("llm_evaluation")
    if llm_eval:
        with ui.expansion("LLM Evaluation"):
            findings = llm_eval.get("findings", [])
            if findings:
                with ui.row().classes(
                    "w-full gap-0 border-b border-gray-200 dark:border-slate-700 "
                    "text-xs font-semibold text-slate-500 dark:text-slate-400"
                ):
                    ui.label("Category").classes("w-[120px] px-2 py-1")
                    ui.label("Passed").classes("w-[80px] px-2 py-1 text-center")
                    ui.label("Confidence").classes("w-[100px] px-2 py-1 text-center")
                    ui.label("Evidence").classes("flex-1 px-2 py-1")
                for f in findings:
                    with ui.row().classes(
                        "w-full gap-0 border-b border-gray-100 "
                        "dark:border-slate-700/50 text-sm"
                    ):
                        ui.label(f.get("category", "—")).classes(
                            "w-[120px] px-2 py-1"
                        )
                        passed = f.get("passed", False)
                        ui.label("Yes" if passed else "No").classes(
                            "w-[80px] px-2 py-1 text-center "
                            + (
                                "text-green-600 dark:text-green-400"
                                if passed
                                else "text-red-600 dark:text-red-400"
                            )
                        )
                        ui.label(f"{f.get('confidence', 0):.0%}").classes(
                            "w-[100px] px-2 py-1 text-center"
                        )
                        ui.label(f.get("evidence", "—")).classes(
                            "flex-1 px-2 py-1"
                        )

    summary = latest.get("summary", "")
    if summary:
        ui.label(summary).classes(
            "text-sm text-slate-600 dark:text-slate-400 mt-2 italic"
        )


def _render_scan_history(history: list[dict]) -> None:
    with ui.expansion("Scan History"):
        with ui.row().classes(
            "w-full gap-0 border-b border-gray-200 dark:border-slate-700 "
            "text-xs font-semibold text-slate-500 dark:text-slate-400"
        ):
            ui.label("Date").classes("w-[160px] px-2 py-1")
            ui.label("Status").classes("w-[100px] px-2 py-1 text-center")
            ui.label("Score").classes("w-[60px] px-2 py-1 text-center")
            ui.label("Model").classes("flex-1 px-2 py-1")
        for h in history:
            with ui.row().classes(
                "w-full gap-0 border-b border-gray-100 "
                "dark:border-slate-700/50 text-sm"
            ):
                ts = h.get("scanned_at")
                date_str = ts.strftime("%Y-%m-%d %H:%M:%S") if ts else "—"
                ui.label(date_str).classes("w-[160px] px-2 py-1 text-xs")
                ui.html(status_badge(h.get("overall_status"))).classes(
                    "w-[100px] px-2 py-1 text-center"
                )
                ui.label(f"{h.get('health_score', 0):.0f}").classes(
                    "w-[60px] px-2 py-1 text-center font-bold"
                )
                ui.label(h.get("model_used", "—")).classes(
                    "flex-1 px-2 py-1"
                )


async def _add_and_scan_site(
    bot: QABot,
    scheduler: ScanScheduler | None,
    url_input: ui.input,
    sites_container: ui.column,
    page_detail_container: ui.column,
) -> None:
    url = url_input.value.strip()
    if not url:
        ui.notify("Enter a URL", type="warning")
        return

    valid_url = validate_single_url(url)
    if not valid_url:
        ui.notify("Invalid URL. Must start with http:// or https://", type="warning")
        return

    url_input.set_value("")
    ui.notify(f"Scanning {valid_url}...", type="info")

    with contextlib.suppress(Exception):
        await bot.scan_url(valid_url)

    await _load_sites(bot, scheduler, sites_container, page_detail_container)
    ui.notify(f"Added {valid_url}", type="positive")


async def _rescan_all(
    bot: QABot,
    scheduler: ScanScheduler | None,
    sites_container: ui.column,
    page_detail_container: ui.column,
) -> None:
    if bot._database is None:
        return
    sites = await bot._database.get_sites()
    urls = [p["url"] for site in sites for p in site.get("pages", [])]
    if not urls:
        ui.notify("No pages to rescan", type="info")
        return
    ui.notify(f"Rescanning {len(urls)} pages...", type="info")
    await bot.scan_urls(urls)
    await _load_sites(bot, scheduler, sites_container, page_detail_container)
    ui.notify("Rescan complete", type="positive")


async def _delete_page(
    bot: QABot,
    scheduler: ScanScheduler | None,
    page_id: int,
    sites_container: ui.column,
    page_detail_container: ui.column,
) -> None:
    if bot._database is None:
        return
    try:
        detail = await bot._database.get_page_with_latest_scan(page_id)
        if detail:
            from sqlalchemy import delete as sa_delete

            from qa_bot.db_models import Page, ScanResult

            async with bot._database._async_session_factory() as session:
                await session.execute(
                    sa_delete(ScanResult).where(ScanResult.page_id == page_id)
                )
                await session.execute(
                    sa_delete(Page).where(Page.id == page_id)
                )
                await session.commit()

            if scheduler:
                scheduler.unschedule(page_id)

            label = detail.get("url", f"Page #{page_id}")
            ui.notify(f"Deleted {label}", type="info")
            await _load_sites(bot, scheduler, sites_container, page_detail_container)
        else:
            ui.notify("Page not found", type="warning")
    except Exception:
        ui.notify("Failed to delete page", type="negative")


async def _go_back_to_sites(
    bot: QABot,
    scheduler: ScanScheduler | None,
    sites_container: ui.column,
    page_detail_container: ui.column,
) -> None:
    page_detail_container.clear()
    sites_container.set_visibility(True)
    await _load_sites(bot, scheduler, sites_container, page_detail_container)


@ui.page("/sites")
async def sites_page():
    from nicegui import app

    create_layout(active="sites")
    bot: QABot | None = app.storage.general.get("bot")
    scheduler: ScanScheduler | None = app.storage.general.get("scheduler")

    if bot is None:
        ui.label("Bot not initialized").classes("text-red-500 p-8")
        return

    with ui.column().classes("w-full max-w-6xl mx-auto px-6 py-6 gap-4"):
        with ui.row().classes("items-center gap-2 w-full"):
            add_url_input = ui.input(
                placeholder="https://example.com",
            ).classes("flex-1").props("outlined dense")
            ui.button(
                "Add & Scan",
                icon="add",
                on_click=lambda: _add_and_scan_site(
                    bot, scheduler, add_url_input, sites_container, page_detail_container
                ),
            ).props("color=primary")
            ui.button(
                "Rescan All",
                icon="refresh",
                on_click=lambda: _rescan_all(
                    bot, scheduler, sites_container, page_detail_container
                ),
            ).props("outline")
            ui.button(
                icon="sync",
                on_click=lambda: _load_sites(
                    bot, scheduler, sites_container, page_detail_container
                ),
            ).props("flat round")

        sites_container = ui.column().classes("w-full")
        page_detail_container = ui.column().classes("w-full")

        await _load_sites(bot, scheduler, sites_container, page_detail_container)
