from __future__ import annotations

from nicegui import ui

_NAV_ITEMS = [
    ("Dashboard", "dashboard", "/"),
    ("Scan", "search", "/scan"),
    ("Sites", "language", "/sites"),
    ("Settings", "settings", "/settings"),
]


def create_layout(active: str = "dashboard") -> ui.dark_mode:
    dark = ui.dark_mode(True)

    with ui.header().classes(
        "w-full bg-white dark:bg-slate-900 shadow-sm px-6 py-3 items-center justify-between"
    ):
        with ui.row().classes("items-center gap-3"):
            ui.icon("fact_check").classes("text-2xl text-blue-600 dark:text-blue-400")
            ui.label("QA Bot").classes(
                "text-xl font-bold text-slate-800 dark:text-white"
            )
        with ui.row().classes("items-center gap-2"):
            ui.button(icon="dark_mode", on_click=dark.toggle).props(
                "flat round size=sm"
            ).classes("text-slate-600 dark:text-slate-300")

    with ui.left_drawer().classes(
        "bg-slate-800 dark:bg-slate-950 border-r-0"
    ).style("width: 220px"), ui.column().classes("w-full gap-0 px-2 py-4"):
        for label, key, path in _NAV_ITEMS:
            is_active = key == active
            btn_classes = (
                "w-full text-left no-caps px-4 py-2.5 rounded-lg text-sm font-medium "
                "transition-colors duration-150 "
            )
            if is_active:
                btn_classes += (
                    "bg-blue-600/20 text-blue-300 dark:bg-blue-500/30 dark:text-blue-300"
                )
            else:
                btn_classes += (
                    "text-slate-300 hover:bg-slate-700/50 hover:text-white"
                )
            with ui.button(
                icon=key,
                text=label,
                on_click=lambda p=path: ui.navigate.to(p),
            ).props("flat no-caps align=left").classes(btn_classes):
                pass

    return dark
