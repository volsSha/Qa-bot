from __future__ import annotations

from typing import TYPE_CHECKING

from nicegui import ui

from qa_bot.services.auth import require_authenticated_user
from qa_bot.services.settings_manager import (
    build_new_settings,
    get_current_settings,
    get_field_definitions,
    save_settings,
)
from qa_bot.ui.layout import create_layout

if TYPE_CHECKING:
    pass


@ui.page("/settings")
async def settings_page():
    user = await require_authenticated_user()
    if user is None:
        return

    create_layout(active="settings", user_email=user.email, is_admin=user.is_admin)
    from qa_bot.services.state import bot as _bot

    bot = _bot

    if bot is None:
        ui.label("Bot not initialized").classes("text-red-500 p-8")
        return

    field_groups, editable_fields, defaults = get_field_definitions()
    current = get_current_settings()

    with ui.column().classes("w-full max-w-3xl mx-auto px-6 py-6 gap-6"):
        ui.label("Settings").classes("text-2xl font-bold text-slate-800 dark:text-white")
        ui.label("Configure your QA Bot instance. Changes take effect on next scan.").classes(
            "text-sm text-slate-500 dark:text-slate-400"
        )

        field_inputs: dict[str, ui.input] = {}

        for group_title, field_keys in field_groups:
            with ui.card().classes("w-full").tight():
                with ui.row().classes(
                    "w-full px-4 py-2 bg-gray-50 dark:bg-slate-800 border-b dark:border-slate-700"
                ):
                    ui.label(group_title).classes(
                        "text-sm font-semibold text-slate-700 dark:text-slate-300"
                    )
                with ui.column().classes("w-full gap-3 p-4"):
                    for key in field_keys:
                        field_def = next((f for f in editable_fields if f[0] == key), None)
                        if field_def is None:
                            continue
                        _, label, _field_type = field_def
                        with ui.row().classes("items-center gap-4 w-full"):
                            ui.label(label).classes(
                                "w-[200px] text-sm text-slate-600 dark:text-slate-400"
                            )
                            inp = ui.input(
                                value=current.get(key, defaults.get(key, "")),
                            ).classes("flex-1").props("outlined dense")
                            field_inputs[key] = inp

        with ui.row().classes("gap-3"):
            async def _save():
                changes = {k: v.value for k, v in field_inputs.items()}
                errors = save_settings(changes)
                if errors:
                    for field_key, msgs in errors.items():
                        inp = field_inputs.get(field_key)
                        if inp:
                            inp.props("error")
                            inp.props(f'error-message="{"; ".join(msgs)}"')
                    ui.notify("Validation errors. Please fix and try again.", type="warning")
                else:
                    new_settings = build_new_settings()
                    bot._settings = new_settings
                    ui.notify("Settings saved successfully", type="positive")
                    for inp in field_inputs.values():
                        inp.props(remove="error")
                        inp.props(remove="error-message")

            ui.button("Save Settings", icon="save", on_click=_save).props("color=primary")

            def _reset():
                for key, inp in field_inputs.items():
                    inp.set_value(defaults.get(key, ""))

            ui.button("Reset to Defaults", icon="restart_alt", on_click=_reset).props("outline")
