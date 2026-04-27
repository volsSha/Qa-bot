from __future__ import annotations

from urllib.parse import parse_qs

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

    query = parse_qs(request.url.query)

    with ui.column().classes(
        "w-full min-h-screen items-center justify-center px-4"
    ), ui.card().classes("w-full max-w-md p-6"):
        ui.label("QA Bot Login").classes("text-2xl font-semibold mb-2")
        ui.label("Sign in to access the dashboard").classes(
            "text-sm text-slate-500 mb-4"
        )
        if query.get("error") == ["invalid"]:
            ui.label("Invalid email or password").classes("text-sm text-red-600 mb-2")
        elif query.get("error") == ["rate_limited"]:
            ui.label("Too many failed login attempts. Try again later.").classes(
                "text-sm text-red-600 mb-2"
            )

        ui.html(
            """
            <form action="/auth/login" method="post" class="w-full flex flex-col gap-4">
              <label class="flex flex-col gap-1 text-sm font-medium text-slate-700">
                Email
                <input name="email" type="email" aria-label="Email" required
                  autocomplete="username" class="q-field__native rounded border px-3 py-2">
              </label>
              <label class="flex flex-col gap-1 text-sm font-medium text-slate-700">
                Password
                <input name="password" type="password" aria-label="Password" required
                  autocomplete="current-password" class="q-field__native rounded border px-3 py-2">
              </label>
              <button type="submit" class="bg-primary text-white rounded px-4 py-2 w-full mt-3">
                Login
              </button>
            </form>
            """,
        )
