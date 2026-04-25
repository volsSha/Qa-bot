from __future__ import annotations

from typing import TYPE_CHECKING

from nicegui import ui

from qa_bot.ui_helpers import score_badge, status_badge
from qa_bot.ui_layout import create_layout

if TYPE_CHECKING:
    from qa_bot.orchestrator import QABot


async def _load_stats(bot: QABot, stats_container: ui.column) -> None:
    stats_container.clear()
    with stats_container:
        if bot._database is None:
            ui.label("Database not configured").classes("text-gray-400")
            return
        stats = await bot._database.get_health_stats()
        cards_data = [
            ("pages", "Total Pages", stats["total"], "blue"),
            ("healthy", "Healthy", stats["healthy"], "green"),
            ("degraded", "Degraded", stats["degraded"], "yellow"),
            ("broken", "Broken", stats["broken"], "red"),
        ]
        with ui.row().classes("w-full gap-4 flex-wrap"):
            for _key, label, count, color in cards_data:
                with (
                    ui.card().classes("flex-1 min-w-[140px]").tight(),
                    ui.row().classes("items-center gap-3 px-4 py-3"),
                ):
                    icon_map = {
                        "blue": "description",
                        "green": "check_circle",
                        "yellow": "warning",
                        "red": "error",
                    }
                    ui.icon(icon_map[color]).classes(
                        f"text-3xl text-{color}-500"
                    )
                    with ui.column().classes("gap-0"):
                        ui.label(str(count)).classes(
                            "text-2xl font-bold text-slate-800 dark:text-white"
                        )
                        ui.label(label).classes(
                            "text-xs text-slate-500 dark:text-slate-400"
                        )


async def _load_charts(bot: QABot, charts_container: ui.column) -> None:
    charts_container.clear()
    with charts_container:
        if bot._database is None:
            return

        with ui.row().classes("w-full gap-4 flex-wrap"):
            with ui.card().classes("flex-1 min-w-[300px]"):
                ui.label("Health Distribution").classes(
                    "text-sm font-semibold text-slate-700 dark:text-slate-300 mb-2"
                )
                stats = await bot._database.get_health_stats()
                pie_data = [
                    {
                        "value": stats["healthy"],
                        "name": "Healthy",
                        "itemStyle": {"color": "#22c55e"},
                    },
                    {
                        "value": stats["degraded"],
                        "name": "Degraded",
                        "itemStyle": {"color": "#eab308"},
                    },
                    {
                        "value": stats["broken"],
                        "name": "Broken",
                        "itemStyle": {"color": "#ef4444"},
                    },
                    {
                        "value": stats["not_scanned"],
                        "name": "Not Scanned",
                        "itemStyle": {"color": "#94a3b8"},
                    },
                ]
                pie_data = [d for d in pie_data if d["value"] > 0]
                if pie_data:
                    ui.echart({
                        "backgroundColor": "transparent",
                        "tooltip": {"trigger": "item", "formatter": "{b}: {c} ({d}%)"},
                        "legend": {
                            "bottom": "0",
                            "left": "center",
                            "textStyle": {"color": "#94a3b8", "fontSize": 11},
                        },
                        "series": [{
                            "type": "pie",
                            "radius": ["35%", "65%"],
                            "center": ["50%", "45%"],
                            "label": {"show": False},
                            "data": pie_data,
                        }],
                    }).classes("h-[250px]")
                else:
                    ui.label("No data yet").classes(
                        "text-gray-400 dark:text-gray-500 h-[250px] "
                        "flex items-center justify-center"
                    )

            with ui.card().classes("flex-1 min-w-[300px]"):
                ui.label("Health Score Trend (30 days)").classes(
                    "text-sm font-semibold text-slate-700 dark:text-slate-300 mb-2"
                )
                trend = await bot._database.get_scan_trend(days=30)
                if trend:
                    dates = [t["date"] for t in trend]
                    scores = [t["avg_score"] for t in trend]
                    ui.echart({
                        "backgroundColor": "transparent",
                        "tooltip": {"trigger": "axis"},
                        "xAxis": {
                            "type": "category",
                            "data": dates,
                            "axisLabel": {"color": "#94a3b8", "fontSize": 10},
                            "axisLine": {"lineStyle": {"color": "#334155"}},
                        },
                        "yAxis": {
                            "type": "value",
                            "min": 0,
                            "max": 100,
                            "axisLabel": {"color": "#94a3b8"},
                            "splitLine": {"lineStyle": {"color": "#1e293b"}},
                        },
                        "series": [{
                            "type": "line",
                            "data": scores,
                            "smooth": True,
                            "symbol": "circle",
                            "symbolSize": 6,
                            "lineStyle": {"width": 2, "color": "#3b82f6"},
                            "areaStyle": {"opacity": 0.15, "color": "#3b82f6"},
                            "itemStyle": {"color": "#3b82f6"},
                        }],
                    }).classes("h-[250px]")
                else:
                    ui.label("No trend data yet").classes(
                        "text-gray-400 dark:text-gray-500 h-[250px] "
                        "flex items-center justify-center"
                    )


async def _load_recent(bot: QABot, recent_container: ui.column) -> None:
    recent_container.clear()
    with recent_container:
        if bot._database is None:
            return
        scans = await bot._database.get_recent_scans(limit=10)
        if not scans:
            ui.label("No recent scans").classes(
                "text-gray-400 dark:text-gray-500 text-sm"
            )
            return
        with ui.card().classes("w-full").tight():
            with ui.row().classes(
                "w-full px-4 py-2 bg-gray-50 dark:bg-slate-800 border-b dark:border-slate-700"
            ):
                ui.label("Recent Scans").classes(
                    "text-sm font-semibold text-slate-700 dark:text-slate-300"
                )
            with ui.column().classes("w-full gap-0"):
                for scan in scans:
                    with ui.row().classes(
                        "w-full items-center gap-3 px-4 py-2 border-b dark:border-slate-700/50 "
                        "hover:bg-gray-50 dark:hover:bg-slate-800/50 transition-colors"
                    ):
                        ui.html(status_badge(scan["overall_status"]))
                        ui.html(score_badge(scan["health_score"]))
                        ui.label(scan["url"]).classes(
                            "flex-1 text-sm truncate text-slate-700 dark:text-slate-300"
                        )
                        ts = scan["scanned_at"]
                        date_str = ts.strftime("%Y-%m-%d %H:%M") if ts else "—"
                        ui.label(date_str).classes(
                            "text-xs text-slate-400 dark:text-slate-500"
                        )


@ui.page("/")
async def dashboard_page():
    from nicegui import app

    create_layout(active="dashboard")
    bot: QABot | None = app.storage.general.get("bot")
    app.storage.general.get("scheduler")

    if bot is None:
        ui.label("Bot not initialized").classes("text-red-500 p-8")
        return

    with ui.column().classes("w-full max-w-6xl mx-auto px-6 py-6 gap-6"):
        stats_container = ui.column().classes("w-full")
        charts_container = ui.column().classes("w-full")
        recent_container = ui.column().classes("w-full")

        await _load_stats(bot, stats_container)
        await _load_charts(bot, charts_container)
        await _load_recent(bot, recent_container)

        async def _refresh():
            await _load_stats(bot, stats_container)
            await _load_charts(bot, charts_container)
            await _load_recent(bot, recent_container)

        ui.button("Refresh", icon="refresh", on_click=_refresh).props(
            "flat"
        ).classes("self-center")
