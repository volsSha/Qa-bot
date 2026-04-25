from __future__ import annotations

import contextlib
from typing import TYPE_CHECKING
from urllib.parse import urlparse

from nicegui import ui

from qa_bot.orchestrator import QABot
from qa_bot.reporter import format_batch_summary, format_report_markdown

if TYPE_CHECKING:
    pass


_STATUS_BADGE: dict[str | None, tuple[str, str]] = {
    "healthy": (
        "bg-green-100 text-green-800 dark:bg-green-900 dark:text-green-200",
        "Healthy",
    ),
    "degraded": (
        "bg-yellow-100 text-yellow-800 dark:bg-yellow-900 dark:text-yellow-200",
        "Degraded",
    ),
    "broken": (
        "bg-red-100 text-red-800 dark:bg-red-900 dark:text-red-200",
        "Broken",
    ),
    None: (
        "bg-gray-100 text-gray-500 dark:bg-gray-700 dark:text-gray-300",
        "Not scanned",
    ),
}


def _parse_urls(text: str) -> list[str]:
    urls = [line.strip() for line in text.strip().splitlines() if line.strip()]
    valid = []
    for u in urls:
        parsed = urlparse(u)
        if parsed.scheme in ("http", "https") and parsed.netloc:
            valid.append(u)
    return valid


def _validate_single_url(text: str) -> str | None:
    parsed = urlparse(text.strip())
    if parsed.scheme in ("http", "https") and parsed.netloc:
        return text.strip()
    return None


def _status_badge(status: str | None) -> str:
    color_classes, label = _STATUS_BADGE.get(status, _STATUS_BADGE[None])
    return (
        f'<span class="{color_classes} px-2 py-0.5 rounded-full text-xs">'
        f"{label}</span>"
    )


def _score_badge(score: float | None) -> str:
    if score is None:
        return ""
    if score >= 80:
        color = "text-green-600 dark:text-green-400"
    elif score >= 50:
        color = "text-yellow-600 dark:text-yellow-400"
    else:
        color = "text-red-600 dark:text-red-400"
    return f'<span class="{color} font-bold">{score:.0f}</span>'


def _severity_badge(severity: str | None) -> str:
    mapping = {
        "pass": "bg-green-100 text-green-800 dark:bg-green-900 dark:text-green-200",
        "critical": "bg-red-100 text-red-800 dark:bg-red-900 dark:text-red-200",
        "warning": (
            "bg-yellow-100 text-yellow-800 dark:bg-yellow-900 dark:text-yellow-200"
        ),
        "info": "bg-blue-100 text-blue-800 dark:bg-blue-900 dark:text-blue-200",
    }
    cls = mapping.get(severity, "bg-gray-100 text-gray-800 dark:bg-gray-700 dark:text-gray-200")
    label = severity.capitalize() if severity else "?"
    return f'<span class="{cls} px-2 py-0.5 rounded text-xs">{label}</span>'


def _plural(n: int) -> str:
    return "s" if n != 1 else ""


async def _scan(bot: QABot, text: str):
    urls = _parse_urls(text)
    if not urls:
        ui.notify("No valid URLs provided", type="warning")
        return

    with scan_result_container:
        scan_result_container.clear()
        with scan_result_container:
            ui.label("Scanning...").classes("text-lg")

    batch = await bot.scan_urls(urls)

    with scan_result_container:
        scan_result_container.clear()
        summary_md = format_batch_summary(batch)
        ui.markdown(summary_md)
        for report in batch.reports:
            with ui.expansion(report.url):
                ui.markdown(format_report_markdown(report))

    ui.notify(f"Scanned {len(batch.reports)} URLs")


async def _load_sites(bot: QABot):
    if bot._database is None:
        sites_container.clear()
        with sites_container:
            ui.label("Database not configured")
        return

    sites = await bot._database.get_sites()

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
                    "bg-gray-50 dark:bg-gray-800 px-4 py-2"
                ):
                    ui.label(f"Domain: {domain}").classes("text-lg font-semibold")
                    if label:
                        ui.label(label).classes(
                            "text-gray-500 dark:text-gray-400 text-sm ml-2"
                        )
                    page_count = len(pages)
                    ui.badge(
                        f"{page_count} page{_plural(page_count)}",
                        color="blue",
                    ).props("color=blue")

                if not pages:
                    continue

                with ui.row().classes("gap-2 flex-wrap w-full"):
                    for p in pages:
                        _render_page_card(bot, p)


def _render_page_card(bot: QABot, p: dict):
    page_id = p["id"]
    status = p.get("latest_status")
    score = p.get("latest_score")
    scan_count = p.get("scan_count", 0)
    path = p.get("path") or p.get("url", "—")

    card_classes = (
        "cursor-pointer hover:shadow-md transition-shadow "
        "min-w-[200px] max-w-[280px]"
    )
    with ui.button(on_click=lambda pid=page_id: show_page_detail(pid)).props(
        "flat no-caps padding-none"
    ).classes(card_classes), ui.card().classes("w-full").tight():
        with ui.row().classes("items-center justify-between"):
            ui.label(path).classes("font-medium text-sm truncate")
            ui.button(
                icon="delete",
                on_click=lambda pid=page_id: _delete_page(bot, pid),
            ).props("flat round dense color=negative size=sm").classes(
                "w-6 h-6"
            ).on("click.stop")
        with ui.row().classes("items-center gap-2 mt-1"):
            ui.html(_status_badge(status))
            ui.html(_score_badge(score))
            ui.label(f"{scan_count} scan{_plural(scan_count)}").classes(
                "text-xs text-gray-400 dark:text-gray-500"
            )


async def _delete_page(bot: QABot, page_id: int):
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

            label = detail.get("url", f"Page #{page_id}")
            ui.notify(f"Deleted {label}", type="info")
            await _load_sites(bot)
        else:
            ui.notify("Page not found", type="warning")
    except Exception as e:
        ui.notify(f"Failed to delete: {e}", type="negative")


async def _add_and_scan_site(bot: QABot, url_input):
    url = url_input.value.strip()
    if not url:
        ui.notify("Enter a URL", type="warning")
        return

    valid_url = _validate_single_url(url)
    if not valid_url:
        ui.notify("Invalid URL. Must start with http:// or https://", type="warning")
        return

    url_input.set_value("")
    ui.notify(f"Scanning {valid_url}...", type="info")

    with contextlib.suppress(Exception):
        await bot.scan_url(valid_url)

    await _load_sites(bot)
    ui.notify(f"Added {valid_url}")


bot_instance: QABot | None = None


async def show_page_detail(page_id: int):
    if bot_instance is None:
        return
    sites_container.clear()
    await _load_page_detail(bot_instance, page_id)


async def _load_page_detail(bot: QABot, page_id: int):
    page_detail_container.clear()
    with page_detail_container:
        if bot._database is None:
            ui.label("Database not configured")
            return

        detail = await bot._database.get_page_with_latest_scan(page_id)
        if detail is None:
            ui.label("Page not found")
            return

        with ui.card().classes("w-full"):
            with ui.row().classes(
                "flex items-center justify-between "
                "bg-gray-50 dark:bg-gray-800 px-4 py-2"
            ):
                ui.label(detail["url"]).classes(
                    "text-lg font-semibold truncate"
                )
                ui.button(
                    "Back", icon="arrow_back",
                    on_click=_go_back_to_sites,
                ).props("flat color=primary")

            ui.label(f"Domain: {detail.get('site_domain', '—')}").classes(
                "text-sm text-gray-500 dark:text-gray-400"
            )
            ui.label(f"Total scans: {detail.get('scan_count', 0)}").classes(
                "text-sm text-gray-500 dark:text-gray-400"
            )

            latest = detail.get("latest_scan")
            if latest:
                _render_latest_scan(bot, latest)
            else:
                ui.label("No scans yet.").classes(
                    "text-gray-400 dark:text-gray-500"
                )

            history = []
            if bot._database:
                history = await bot._database.get_scan_history(
                    page_id, limit=20
                )
            if history:
                _render_scan_history(history)


def _render_latest_scan(bot: QABot, latest: dict):
    with ui.separator():
        ui.label("Latest Scan").classes("text-base font-semibold mt-2")
        with ui.row().classes("items-center gap-3"):
            ui.html(_status_badge(latest["overall_status"]))
            score_html = (
                f'<span class="text-xl font-bold">'
                f'{latest["health_score"]:.0f}</span>'
            )
            ui.html(score_html)
            model = latest.get("model_used", "—")
            ui.label(f"Model: {model}").classes(
                "text-sm text-gray-500 dark:text-gray-400"
            )
        ts = latest["scanned_at"].strftime("%Y-%m-%d %H:%M:%S")
        ui.label(f"Scanned: {ts}").classes(
            "text-sm text-gray-500 dark:text-gray-400"
        )

    rule_results = latest.get("rule_results", [])
    if rule_results:
        with ui.expansion("Rule Results"):
            with ui.row().classes(
                "w-full gap-0 border-b border-gray-200 dark:border-gray-700 "
                "text-xs font-semibold text-gray-500 dark:text-gray-400"
            ):
                ui.label("Check").classes("w-[120px] px-2 py-1")
                ui.label("Severity").classes("w-[100px] px-2 py-1 text-center")
                ui.label("Message").classes("flex-1 px-2 py-1")
            for r in rule_results:
                with ui.row().classes(
                    "w-full gap-0 border-b border-gray-100 "
                    "dark:border-gray-700/50 text-sm"
                ):
                    ui.label(r.get("check_name", "—")).classes(
                        "w-[120px] px-2 py-1 font-mono text-xs"
                    )
                    ui.html(_severity_badge(r.get("severity"))).classes(
                        "w-[100px] px-2 py-1 text-center"
                    )
                    ui.label(r.get("message", "—")).classes(
                        "flex-1 px-2 py-1"
                    )
    else:
        ui.label("No rule results.").classes("text-gray-400 dark:text-gray-500")

    llm_eval = latest.get("llm_evaluation")
    if llm_eval:
        with ui.expansion("LLM Evaluation"):
            findings = llm_eval.get("findings", [])
            if findings:
                with ui.row().classes(
                    "w-full gap-0 border-b border-gray-200 dark:border-gray-700 "
                    "text-xs font-semibold text-gray-500 dark:text-gray-400"
                ):
                    ui.label("Category").classes("w-[120px] px-2 py-1")
                    ui.label("Passed").classes(
                        "w-[80px] px-2 py-1 text-center"
                    )
                    ui.label("Confidence").classes(
                        "w-[100px] px-2 py-1 text-center"
                    )
                    ui.label("Evidence").classes("flex-1 px-2 py-1")
                for f in findings:
                    with ui.row().classes(
                        "w-full gap-0 border-b border-gray-100 "
                        "dark:border-gray-700/50 text-sm"
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
            else:
                ui.label("No findings.").classes(
                    "text-gray-400 dark:text-gray-500"
                )

    summary = latest.get("summary", "")
    if summary:
        ui.label(summary).classes(
            "text-sm text-gray-600 dark:text-gray-400 mt-2 italic"
        )


def _render_scan_history(history: list[dict]):
    with ui.expansion("Scan History"):
        with ui.row().classes(
            "w-full gap-0 border-b border-gray-200 dark:border-gray-700 "
            "text-xs font-semibold text-gray-500 dark:text-gray-400"
        ):
            ui.label("Date").classes("w-[160px] px-2 py-1")
            ui.label("Status").classes("w-[100px] px-2 py-1 text-center")
            ui.label("Score").classes("w-[60px] px-2 py-1 text-center")
            ui.label("Model").classes("flex-1 px-2 py-1")
        for h in history:
            with ui.row().classes(
                "w-full gap-0 border-b border-gray-100 "
                "dark:border-gray-700/50 text-sm"
            ):
                date_str = (
                    h["scanned_at"].strftime("%Y-%m-%d %H:%M:%S")
                    if h.get("scanned_at")
                    else "—"
                )
                ui.label(date_str).classes("w-[160px] px-2 py-1 text-xs")
                ui.html(_status_badge(h.get("overall_status"))).classes(
                    "w-[100px] px-2 py-1 text-center"
                )
                ui.label(f"{h.get('health_score', 0):.0f}").classes(
                    "w-[60px] px-2 py-1 text-center font-bold"
                )
                ui.label(h.get("model_used", "—")).classes(
                    "flex-1 px-2 py-1"
                )


async def _go_back_to_sites():
    _show_sites_view()
    if bot_instance:
        await _load_sites(bot_instance)


def _show_sites_view():
    page_detail_container.clear()


scan_result_container: ui.column
sites_container: ui.column
page_detail_container: ui.column


def create_app(bot: QABot) -> None:
    global scan_result_container, sites_container, page_detail_container
    global bot_instance

    bot_instance = bot
    dark_mode = ui.dark_mode()

    with ui.row().classes("w-full items-center justify-between"):
        ui.label("QA Bot - Web Page Health Monitor").classes(
            "text-2xl font-bold"
        )
        ui.button(icon="dark_mode", on_click=dark_mode.toggle).props(
            "flat round size=sm"
        )

    with ui.tabs() as _tabs:
        scan_tab = ui.tab("Scan")
        sites_tab = ui.tab("Sites")

    with ui.tab_panels(_tabs, value=scan_tab).classes("w-full"):
        with ui.tab_panel(scan_tab):
            url_input = ui.textarea(
                placeholder=(
                    "Enter URLs, one per line\n"
                    "https://example.com\n"
                    "https://another-site.com"
                ),
            ).classes("w-full")
            scan_btn = ui.button(
                "Run Scan", icon="search", on_click=lambda: _scan(bot, url_input.value)
            )
            scan_btn.props("color=primary")
            scan_result_container = ui.column()

        with ui.tab_panel(sites_tab):
            with ui.row().classes("items-center gap-2 w-full"):
                add_url_input = ui.input(
                    placeholder="https://example.com",
                ).classes("flex-1")
                add_btn = ui.button(
                    "Add & Scan",
                    icon="add",
                    on_click=lambda: _add_and_scan_site(bot, add_url_input),
                )
                add_btn.props("color=primary")
                ui.space()
                refresh_btn = ui.button(
                    icon="refresh",
                    on_click=lambda: _load_sites(bot),
                )
                refresh_btn.props("flat round")

            sites_container = ui.column().classes("w-full")
            page_detail_container = ui.column().classes("w-full")

    ui.timer(0.1, lambda: _load_sites(bot), once=True)
