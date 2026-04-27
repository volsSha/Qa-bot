from __future__ import annotations

from nicegui import ui

from qa_bot.services import state
from qa_bot.services.auth import require_authenticated_user
from qa_bot.ui.layout import create_layout


@ui.page("/admin/users")
async def admin_users_page() -> None:
    current_user = await require_authenticated_user(admin_only=True)
    if current_user is None:
        return

    create_layout(
        active="admin_panel_settings",
        user_email=current_user.email,
        is_admin=True,
    )

    auth_service = state.auth_service
    bot = state.bot
    if auth_service is None or bot is None or bot._database is None:
        ui.label("Required services are not initialized").classes("text-red-500 p-8")
        return

    database = bot._database

    with ui.column().classes("w-full max-w-5xl mx-auto px-6 py-6 gap-4"):
        ui.label("User Management").classes(
            "text-2xl font-bold text-slate-800 dark:text-white"
        )
        ui.label("Manage dashboard users and access.").classes(
            "text-sm text-slate-500 dark:text-slate-400"
        )

        users_container = ui.column().classes("w-full")

        async def _refresh_users() -> None:
            users = await database.list_users()
            users_container.clear()
            with users_container:
                if not users:
                    ui.label("No users found").classes("text-slate-500")
                    return

                with ui.card().classes("w-full").tight():
                    with ui.row().classes(
                        "w-full px-4 py-2 bg-gray-50 dark:bg-slate-800 "
                        "border-b dark:border-slate-700"
                    ):
                        ui.label("Users").classes(
                            "text-sm font-semibold text-slate-700 dark:text-slate-300"
                        )
                    with ui.column().classes("w-full gap-0"):
                        for user in users:
                            with ui.row().classes(
                                "w-full items-center gap-3 px-4 py-2 border-b "
                                "dark:border-slate-700/50"
                            ):
                                ui.label(user["email"]).classes("flex-1 text-sm")
                                role_color = "blue" if user["role"] == "admin" else "grey"
                                ui.badge(user["role"], color=role_color)
                                active = bool(user["is_active"])
                                active_label = "active" if active else "inactive"
                                active_color = "green" if active else "red"
                                ui.badge(active_label, color=active_color)

                                async def _toggle(
                                    uid=user["id"],
                                    currently_active=active,
                                    role=user["role"],
                                ) -> None:
                                    if currently_active and role == "admin":
                                        active_admins = await database.count_active_admins()
                                        if active_admins <= 1:
                                            ui.notify(
                                                "Cannot deactivate the last active admin",
                                                type="warning",
                                            )
                                            return

                                    await database.set_user_active(uid, not currently_active)
                                    if currently_active:
                                        await database.revoke_auth_sessions_for_user(uid)
                                    await _refresh_users()

                                ui.button(
                                    "Deactivate" if active else "Activate",
                                    on_click=_toggle,
                                ).props("flat dense")

                                async def _rotate_password(uid=user["id"]) -> None:
                                    dialog = ui.dialog()
                                    with dialog, ui.card().classes("min-w-[360px]"):
                                        ui.label("Rotate Password").classes("text-lg font-semibold")
                                        pwd_input = ui.input(
                                            "New password",
                                            password=True,
                                            password_toggle_button=True,
                                        ).classes("w-full")

                                        async def _confirm_rotate() -> None:
                                            new_password = (pwd_input.value or "").strip()
                                            if len(new_password) < 12:
                                                ui.notify(
                                                    "Password must be at least 12 characters",
                                                    type="warning",
                                                )
                                                return
                                            password_hash = auth_service.hash_password(new_password)
                                            await database.update_user_password(uid, password_hash)
                                            await database.revoke_auth_sessions_for_user(uid)
                                            dialog.close()
                                            ui.notify("Password rotated", type="positive")
                                            await _refresh_users()

                                        with ui.row().classes("justify-end gap-2"):
                                            ui.button("Cancel", on_click=dialog.close).props(
                                                "flat"
                                            )
                                            ui.button(
                                                "Rotate",
                                                on_click=_confirm_rotate,
                                            ).props("color=primary")

                                    dialog.open()

                                ui.button("Rotate password", on_click=_rotate_password).props(
                                    "flat dense"
                                )

        with ui.card().classes("w-full p-4"):
            ui.label("Create user").classes("text-base font-semibold")
            with ui.row().classes("w-full items-end gap-3"):
                email_input = ui.input("Email").props("type=email outlined").classes("flex-1")
                password_input = ui.input(
                    "Password",
                    password=True,
                    password_toggle_button=True,
                ).props("outlined").classes("flex-1")
                role_input = ui.select(["user", "admin"], value="user", label="Role").classes(
                    "w-[160px]"
                )

                async def _create_user() -> None:
                    email = (email_input.value or "").strip().lower()
                    password = (password_input.value or "").strip()
                    role = role_input.value or "user"
                    if not email or "@" not in email:
                        ui.notify("Enter a valid email", type="warning")
                        return
                    if len(password) < 12:
                        ui.notify("Password must be at least 12 characters", type="warning")
                        return
                    existing = await database.get_user_by_email(email)
                    if existing is not None:
                        ui.notify("User with this email already exists", type="warning")
                        return
                    password_hash = auth_service.hash_password(password)
                    await database.create_user(
                        email=email,
                        password_hash=password_hash,
                        role=role,
                    )
                    email_input.set_value("")
                    password_input.set_value("")
                    role_input.set_value("user")
                    ui.notify("User created", type="positive")
                    await _refresh_users()

                ui.button("Create", on_click=_create_user, icon="person_add").props(
                    "color=primary"
                )

        await _refresh_users()
