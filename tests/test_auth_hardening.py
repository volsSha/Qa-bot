from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime

import pytest
from sqlalchemy import select

from qa_bot.config import Settings
from qa_bot.db.database import Database
from qa_bot.db.models import AuthSession
from qa_bot.services.auth import AuthService


def _make_settings(database_url: str = "sqlite+aiosqlite:///:memory:") -> Settings:
    return Settings.model_construct(
        openrouter_api_key="test-key",
        database_url=database_url,
        auth_session_secret="test-auth-session-secret",
        auth_session_ttl_hours=1,
        auth_session_absolute_ttl_hours=2,
        auth_login_max_attempts=2,
        auth_login_attempt_window_seconds=300,
        auth_login_block_seconds=300,
    )


@dataclass
class _DummyClient:
    host: str = "127.0.0.1"


@dataclass
class _DummyRequest:
    session: dict = field(default_factory=dict)
    headers: dict = field(default_factory=lambda: {"user-agent": "pytest"})
    client: _DummyClient = field(default_factory=_DummyClient)


@pytest.fixture
async def auth_stack():
    settings = _make_settings()
    database = Database(settings)
    await database.init()
    service = AuthService(settings=settings, database=database)

    password_hash = service.hash_password("correct horse battery staple")
    await database.create_user(
        email="admin@example.com",
        password_hash=password_hash,
        role="admin",
        is_active=True,
    )

    yield service, database
    await database.close()


class TestAuthHardening:
    async def test_failed_login_throttling_blocks_after_threshold(self, auth_stack):
        service, _ = auth_stack
        request = _DummyRequest()

        ok1, _ = await service.login(request, "admin@example.com", "wrong")
        ok2, _ = await service.login(request, "admin@example.com", "wrong")
        ok3, message3 = await service.login(request, "admin@example.com", "wrong")

        assert ok1 is False
        assert ok2 is False
        assert ok3 is False
        assert message3 == "Too many failed login attempts. Try again later."

    async def test_successful_login_clears_prior_failures_for_identity(self, auth_stack):
        service, _ = auth_stack
        request = _DummyRequest()

        ok1, message1 = await service.login(request, "admin@example.com", "wrong")
        ok2, message2 = await service.login(
            request,
            "admin@example.com",
            "correct horse battery staple",
        )
        ok3, message3 = await service.login(request, "admin@example.com", "wrong")

        assert ok1 is False
        assert message1 == "Invalid email or password"
        assert ok2 is True
        assert message2 == "ok"
        assert ok3 is False
        assert message3 == "Invalid email or password"

    async def test_expired_session_is_rejected(self, auth_stack):
        service, database = auth_stack
        request = _DummyRequest()

        ok, _ = await service.login(request, "admin@example.com", "correct horse battery staple")
        assert ok is True
        token = request.session.get("auth_session_token")
        assert token

        token_hash = service._token_hash(token)
        async with database._async_session_factory() as db_session:
            loaded = (
                await db_session.execute(
                    select(AuthSession).where(AuthSession.token_hash == token_hash)
                )
            ).scalar_one()
            loaded.expires_at = datetime(2000, 1, 1, tzinfo=UTC)
            await db_session.commit()

        user = await service.current_user(request)
        assert user is None
        assert "auth_session_token" not in request.session
