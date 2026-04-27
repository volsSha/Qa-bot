from __future__ import annotations

from nicegui import ui

from qa_bot import state


@ui.page("/login")
async def login_page() -> None:
    auth_service = state.auth_service
    if auth_service is None:
        ui.label("Authentication is not initialized").classes("text-red-500 p-8")
        return

    request = ui.context.client.request
    existing_user = await auth_service.current_user(request)
    if existing_user is not None:
        ui.navigate.to("/")
        return

    with ui.column().classes(
        "w-full min-h-screen items-center justify-center px-4"
    ), ui.card().classes("w-full max-w-md p-6"):
        ui.label("QA Bot Login").classes("text-2xl font-semibold mb-2")
        ui.label("Sign in to access the dashboard").classes(
            "text-sm text-slate-500 mb-4"
        )
        email_input = ui.input("Email").props("type=email outlined").classes("w-full")
        password_input = ui.input(
            "Password",
            password=True,
            password_toggle_button=True,
        ).props("outlined").classes("w-full")

        async def _submit() -> None:
            ok, message = await auth_service.login(
                request=request,
                email=email_input.value or "",
                password=password_input.value or "",
            )
            if ok:
                ui.navigate.to("/")
                return
            ui.notify(message, type="negative")

        ui.button("Login", on_click=_submit, icon="login").props("color=primary").classes(
            "w-full mt-3"
        )
