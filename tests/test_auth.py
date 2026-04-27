from __future__ import annotations

import logging
from dataclasses import dataclass, field
from unittest.mock import AsyncMock

import pytest
from starlette.datastructures import URL

from qa_bot.config import Settings
from qa_bot.db.database import Database
from qa_bot.services.auth import AuthService, login_form_response


def _make_settings(database_url: str = "sqlite+aiosqlite:///:memory:") -> Settings:
    return Settings.model_construct(
        openrouter_api_key="test-key",
        database_url=database_url,
        auth_session_secret="test-auth-session-secret",
        auth_session_ttl_hours=24,
        auth_session_absolute_ttl_hours=72,
        auth_login_max_attempts=5,
        auth_login_attempt_window_seconds=900,
        auth_login_block_seconds=900,
    )


@dataclass
class _DummyClient:
    host: str = "127.0.0.1"


@dataclass
class _DummyRequest:
    session: dict = field(default_factory=dict)
    headers: dict = field(default_factory=lambda: {"user-agent": "pytest"})
    client: _DummyClient = field(default_factory=_DummyClient)
    url: URL = field(default_factory=lambda: URL("http://testserver/login"))

    async def body(self) -> bytes:
        return b""


@dataclass
class _FormRequest(_DummyRequest):
    raw_body: bytes = b""

    async def body(self) -> bytes:
        return self.raw_body


@pytest.fixture
async def auth_stack():
    settings = _make_settings()
    database = Database(settings)
    await database.init()
    service = AuthService(settings=settings, database=database)

    password_hash = service.hash_password("correct horse battery staple")
    admin = await database.create_user(
        email="admin@example.com",
        password_hash=password_hash,
        role="admin",
        is_active=True,
    )

    yield service, database, admin
    await database.close()


class TestAuthFlow:
    async def test_valid_login_creates_session(self, auth_stack):
        service, database, admin = auth_stack
        request = _DummyRequest()

        ok, message = await service.login(
            request=request,
            email="admin@example.com",
            password="correct horse battery staple",
        )

        assert ok is True
        assert message == "ok"
        assert "auth_session_token" in request.session

        user = await service.current_user(request)
        assert user is not None
        assert user.id == admin.id
        assert user.email == "admin@example.com"
        assert user.is_admin is True

        sessions = await database.revoke_auth_sessions_for_user(admin.id)
        assert sessions >= 1

    async def test_login_normalizes_email_without_changing_password(self, auth_stack):
        service, _, admin = auth_stack
        request = _DummyRequest()

        ok, message = await service.login(
            request=request,
            email="  ADMIN@EXAMPLE.COM  ",
            password="correct horse battery staple",
        )

        assert ok is True
        assert message == "ok"

        user = await service.current_user(request)
        assert user is not None
        assert user.id == admin.id

    async def test_password_is_matched_exactly(self, auth_stack):
        service, _, _ = auth_stack
        request = _DummyRequest()

        ok, message = await service.login(
            request=request,
            email="admin@example.com",
            password=" correct horse battery staple ",
        )

        assert ok is False
        assert message == "Invalid email or password"
        assert "auth_session_token" not in request.session

    async def test_invalid_password_returns_generic_message(self, auth_stack):
        service, _, _ = auth_stack
        request = _DummyRequest()

        ok, message = await service.login(
            request=request,
            email="admin@example.com",
            password="bad-password",
        )

        assert ok is False
        assert message == "Invalid email or password"

        ok2, message2 = await service.login(
            request=request,
            email="missing@example.com",
            password="bad-password",
        )
        assert ok2 is False
        assert message2 == "Invalid email or password"

    async def test_inactive_user_returns_generic_message(self, auth_stack):
        service, database, admin = auth_stack
        request = _DummyRequest()
        assert await database.set_user_active(admin.id, False) is True

        ok, message = await service.login(
            request=request,
            email="admin@example.com",
            password="correct horse battery staple",
        )

        assert ok is False
        assert message == "Invalid email or password"
        assert "auth_session_token" not in request.session

    async def test_login_logs_redact_submitted_email(self, auth_stack, caplog):
        service, _, _ = auth_stack
        request = _DummyRequest()
        caplog.set_level(logging.INFO, logger="qa_bot.services.auth")

        ok, message = await service.login(
            request=request,
            email="missing@example.com",
            password="bad-password",
        )

        assert ok is False
        assert message == "Invalid email or password"
        assert "missing@example.com" not in caplog.text
        assert "email_hash=" in caplog.text

    async def test_login_form_response_redirects_success_with_session(self, auth_stack):
        service, _, _ = auth_stack
        request = _FormRequest(
            raw_body=b"email=admin%40example.com&password=correct+horse+battery+staple"
        )

        response = await login_form_response(service, request)

        assert response.status_code == 303
        assert response.headers["location"] == "/"
        assert "auth_session_token" in request.session

    async def test_login_form_response_redirects_invalid_without_session(self, auth_stack):
        service, _, _ = auth_stack
        request = _FormRequest(raw_body=b"email=admin%40example.com&password=wrong")

        response = await login_form_response(service, request)

        assert response.status_code == 303
        assert response.headers["location"] == "/login?error=invalid"
        assert "auth_session_token" not in request.session

    async def test_login_form_response_preserves_rate_limit_message(self, auth_stack):
        service, _, _ = auth_stack
        request = _FormRequest(raw_body=b"email=admin%40example.com&password=wrong")
        service.login = AsyncMock(
            return_value=(False, "Too many failed login attempts. Try again later.")
        )

        response = await login_form_response(service, request)

        assert response.status_code == 303
        assert response.headers["location"] == "/login?error=rate_limited"

    async def test_logout_revokes_session_and_clears_request_session(self, auth_stack):
        service, _, _ = auth_stack
        request = _DummyRequest()

        ok, _ = await service.login(
            request=request,
            email="admin@example.com",
            password="correct horse battery staple",
        )
        assert ok is True

        await service.logout(request)

        assert "auth_session_token" not in request.session
        assert await service.current_user(request) is None
