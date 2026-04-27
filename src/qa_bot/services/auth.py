from __future__ import annotations

import hashlib
import logging
import secrets
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from urllib.parse import parse_qs

import bcrypt
from nicegui import app, ui
from starlette.requests import Request
from starlette.responses import RedirectResponse

from qa_bot.config import Settings
from qa_bot.db.database import Database

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class AuthenticatedUser:
    id: int
    email: str
    role: str
    is_active: bool

    @property
    def is_admin(self) -> bool:
        return self.role == "admin"


class AuthService:
    def __init__(self, settings: Settings, database: Database) -> None:
        self._settings = settings
        self._database = database
        self._attempts: dict[str, list[datetime]] = {}
        self._blocked_until: dict[str, datetime] = {}

    def hash_password(self, password: str) -> str:
        encoded = password.encode("utf-8")
        return bcrypt.hashpw(encoded, bcrypt.gensalt()).decode("utf-8")

    def verify_password(self, password: str, password_hash: str) -> bool:
        return bcrypt.checkpw(password.encode("utf-8"), password_hash.encode("utf-8"))

    async def bootstrap_admin_if_needed(self) -> None:
        if await self._database.has_admin_user():
            return

        email = self._settings.admin_bootstrap_email
        password_secret = self._settings.admin_bootstrap_password
        if not email or password_secret is None:
            raise RuntimeError(
                "No admin user exists. Set ADMIN_BOOTSTRAP_EMAIL and ADMIN_BOOTSTRAP_PASSWORD."
            )

        password = password_secret.get_secret_value().strip()
        if len(password) < 12:
            raise RuntimeError("ADMIN_BOOTSTRAP_PASSWORD must be at least 12 characters")

        password_hash = self.hash_password(password)
        await self._database.ensure_bootstrap_admin(email, password_hash)

    def _token_hash(self, token: str) -> str:
        return hashlib.sha256(token.encode("utf-8")).hexdigest()

    def _now(self) -> datetime:
        return datetime.now(UTC)

    def _as_utc(self, value: datetime) -> datetime:
        if value.tzinfo is None:
            return value.replace(tzinfo=UTC)
        return value.astimezone(UTC)

    def _identity_keys(self, email: str, ip: str | None) -> list[str]:
        keys = [f"email:{email.strip().lower()}"]
        if ip:
            keys.append(f"ip:{ip}")
        return keys

    def _is_rate_limited(self, keys: list[str], now: datetime) -> bool:
        for key in keys:
            blocked_until = self._blocked_until.get(key)
            if blocked_until and blocked_until > now:
                return True
        return False

    def _record_failure(self, keys: list[str], now: datetime) -> None:
        window_start = now - timedelta(seconds=self._settings.auth_login_attempt_window_seconds)
        for key in keys:
            attempts = self._attempts.get(key, [])
            attempts = [attempt for attempt in attempts if attempt >= window_start]
            attempts.append(now)
            self._attempts[key] = attempts
            if len(attempts) >= self._settings.auth_login_max_attempts:
                self._blocked_until[key] = now + timedelta(
                    seconds=self._settings.auth_login_block_seconds
                )

    def _record_success(self, keys: list[str]) -> None:
        for key in keys:
            self._attempts.pop(key, None)
            self._blocked_until.pop(key, None)

    async def login(
        self,
        request,
        email: str,
        password: str,
    ) -> tuple[bool, str]:
        now = self._now()
        ip = getattr(getattr(request, "client", None), "host", None)
        keys = self._identity_keys(email, ip)

        if self._is_rate_limited(keys, now):
            logger.info(
                "Login rejected: rate_limited ip_present=%s email_hash=%s",
                bool(ip),
                self._identity_hash(email),
            )
            return False, "Too many failed login attempts. Try again later."

        normalized_email = email.strip().lower()
        user = await self._database.get_user_by_email(normalized_email)
        if user is None:
            logger.info(
                "Login rejected: unknown_user ip_present=%s email_hash=%s",
                bool(ip),
                self._identity_hash(normalized_email),
            )
            self._record_failure(keys, now)
            return False, "Invalid email or password"

        if not user.is_active:
            logger.info(
                "Login rejected: inactive user_id=%s ip_present=%s",
                user.id,
                bool(ip),
            )
            self._record_failure(keys, now)
            return False, "Invalid email or password"

        if not self.verify_password(password, user.password_hash):
            logger.info(
                "Login rejected: password_mismatch user_id=%s ip_present=%s",
                user.id,
                bool(ip),
            )
            self._record_failure(keys, now)
            return False, "Invalid email or password"

        self._record_success(keys)
        await self._database.delete_expired_auth_sessions()

        token = secrets.token_urlsafe(48)
        expires_at = now + timedelta(hours=self._settings.auth_session_ttl_hours)
        await self._database.create_auth_session(
            user_id=user.id,
            token_hash=self._token_hash(token),
            expires_at=expires_at,
            ip_address=ip,
            user_agent=request.headers.get("user-agent"),
        )
        await self._database.mark_user_logged_in(user.id)

        request.session["auth_session_token"] = token
        request.session["auth_session_started_at"] = now.isoformat()
        logger.info(
            "Login accepted: user_id=%s ip_present=%s",
            user.id,
            bool(ip),
        )
        return True, "ok"

    def _identity_hash(self, email: str) -> str:
        return hashlib.sha256(email.strip().lower().encode("utf-8")).hexdigest()[:12]

    async def logout(self, request) -> None:
        token = request.session.get("auth_session_token")
        if token:
            await self._database.revoke_auth_session_by_hash(self._token_hash(token))
        request.session.pop("auth_session_token", None)
        request.session.pop("auth_session_started_at", None)

    async def current_user(self, request) -> AuthenticatedUser | None:
        token = request.session.get("auth_session_token")
        if not token:
            return None

        session = await self._database.get_auth_session(self._token_hash(token))
        now = self._now()
        if session is None or session.user is None:
            request.session.pop("auth_session_token", None)
            request.session.pop("auth_session_started_at", None)
            return None

        started_at_raw = request.session.get("auth_session_started_at")
        started_at = None
        if isinstance(started_at_raw, str):
            try:
                started_at = datetime.fromisoformat(started_at_raw)
            except ValueError:
                started_at = None

        absolute_expired = False
        if started_at is not None:
            if started_at.tzinfo is None:
                started_at = started_at.replace(tzinfo=UTC)
            absolute_expired = now >= started_at + timedelta(
                hours=self._settings.auth_session_absolute_ttl_hours
            )

        expires_at = self._as_utc(session.expires_at)

        if (
            session.revoked_at is not None
            or expires_at <= now
            or absolute_expired
            or not session.user.is_active
        ):
            await self.logout(request)
            return None

        if session.user.role not in {"admin", "user"}:
            await self.logout(request)
            return None

        await self._database.touch_auth_session(session.id)
        return AuthenticatedUser(
            id=session.user.id,
            email=session.user.email,
            role=session.user.role,
            is_active=session.user.is_active,
        )


async def require_authenticated_user(admin_only: bool = False) -> AuthenticatedUser | None:
    from qa_bot import state

    auth_service = state.auth_service
    if auth_service is None:
        ui.label("Authentication is not initialized").classes("text-red-500 p-8")
        return None

    request = ui.context.client.request
    user = await auth_service.current_user(request)
    if user is None:
        ui.navigate.to("/login")
        return None

    if admin_only and not user.is_admin:
        ui.notify("Admin access required", type="warning")
        ui.navigate.to("/")
        return None

    return user


def register_auth_routes(auth_service: AuthService) -> None:
    @app.post("/auth/login")
    async def _login(request: Request) -> RedirectResponse:
        return await login_form_response(auth_service, request)


async def login_form_response(auth_service: AuthService, request: Request) -> RedirectResponse:
    body = (await request.body()).decode("utf-8")
    form = parse_qs(body, keep_blank_values=True)
    ok, message = await auth_service.login(
        request=request,
        email=form.get("email", [""])[0],
        password=form.get("password", [""])[0],
    )

    if ok:
        return RedirectResponse("/", status_code=303)
    if message == "Too many failed login attempts. Try again later.":
        return RedirectResponse("/login?error=rate_limited", status_code=303)
    return RedirectResponse("/login?error=invalid", status_code=303)
