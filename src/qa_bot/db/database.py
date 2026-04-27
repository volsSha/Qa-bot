from __future__ import annotations

import json
import logging
from datetime import UTC, datetime
from typing import Any
from urllib.parse import urlparse

from sqlalchemy import delete, func, select, text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import selectinload

from qa_bot.config import Settings
from qa_bot.db.models import AuthSession, Base, Page, ScanResult, Site, User
from qa_bot.domain.models import ScanReport

logger = logging.getLogger(__name__)


class Database:
    def __init__(self, settings: Settings) -> None:
        self._database_url = settings.database_url
        self._engine = create_async_engine(self._database_url, echo=False)
        self._async_session_factory = async_sessionmaker(
            self._engine, class_=AsyncSession, expire_on_commit=False
        )

    async def init(self) -> None:
        async with self._engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
            await self._migrate_screenshot_path(conn)

    async def _migrate_screenshot_path(self, conn) -> None:
        if "aiosqlite" in self._database_url:
            result = await conn.execute(text("PRAGMA table_info(scan_results)"))
            columns = {row[1] for row in result}
            if "screenshot_path" not in columns:
                await conn.execute(
                    text(
                        "ALTER TABLE scan_results ADD COLUMN screenshot_path VARCHAR(512)"
                    )
                )
                logger.info("Added screenshot_path column to scan_results")

    async def close(self) -> None:
        await self._engine.dispose()

    async def has_admin_user(self) -> bool:
        async with self._async_session_factory() as session:
            stmt = select(func.count(User.id)).where(
                User.role == "admin",
                User.is_active.is_(True),
            )
            count = await session.scalar(stmt)
            return bool(count and count > 0)

    async def create_user(
        self,
        email: str,
        password_hash: str,
        role: str = "user",
        is_active: bool = True,
    ) -> User:
        normalized_email = email.strip().lower()
        async with self._async_session_factory() as session:
            user = User(
                email=normalized_email,
                password_hash=password_hash,
                role=role,
                is_active=is_active,
            )
            session.add(user)
            await session.commit()
            await session.refresh(user)
            return user

    async def ensure_bootstrap_admin(self, email: str, password_hash: str) -> User | None:
        normalized_email = email.strip().lower()
        async with self._async_session_factory() as session:
            admin_stmt = select(User).where(User.role == "admin", User.is_active.is_(True))
            existing_admin = (await session.execute(admin_stmt)).scalar_one_or_none()
            if existing_admin is not None:
                return None

            email_stmt = select(User).where(User.email == normalized_email)
            existing_user = (await session.execute(email_stmt)).scalar_one_or_none()
            if existing_user is None:
                existing_user = User(
                    email=normalized_email,
                    password_hash=password_hash,
                    role="admin",
                    is_active=True,
                )
                session.add(existing_user)
            else:
                existing_user.password_hash = password_hash
                existing_user.role = "admin"
                existing_user.is_active = True
                existing_user.updated_at = datetime.now(UTC)

            await session.commit()
            await session.refresh(existing_user)
            return existing_user

    async def get_user_by_email(self, email: str) -> User | None:
        normalized_email = email.strip().lower()
        async with self._async_session_factory() as session:
            stmt = select(User).where(User.email == normalized_email)
            result = await session.execute(stmt)
            return result.scalar_one_or_none()

    async def get_user_by_id(self, user_id: int) -> User | None:
        async with self._async_session_factory() as session:
            stmt = select(User).where(User.id == user_id)
            result = await session.execute(stmt)
            return result.scalar_one_or_none()

    async def list_users(self) -> list[dict[str, Any]]:
        async with self._async_session_factory() as session:
            stmt = select(User).order_by(User.email)
            users = (await session.execute(stmt)).scalars().all()
            return [
                {
                    "id": u.id,
                    "email": u.email,
                    "role": u.role,
                    "is_active": u.is_active,
                    "last_login_at": u.last_login_at,
                    "created_at": u.created_at,
                }
                for u in users
            ]

    async def count_active_admins(self) -> int:
        async with self._async_session_factory() as session:
            stmt = select(func.count(User.id)).where(
                User.role == "admin", User.is_active.is_(True)
            )
            count = await session.scalar(stmt)
            return int(count or 0)

    async def update_user_password(self, user_id: int, password_hash: str) -> bool:
        async with self._async_session_factory() as session:
            user = (
                await session.execute(select(User).where(User.id == user_id))
            ).scalar_one_or_none()
            if user is None:
                return False
            user.password_hash = password_hash
            user.updated_at = datetime.now(UTC)
            await session.commit()
            return True

    async def set_user_active(self, user_id: int, is_active: bool) -> bool:
        async with self._async_session_factory() as session:
            user = (
                await session.execute(select(User).where(User.id == user_id))
            ).scalar_one_or_none()
            if user is None:
                return False
            user.is_active = is_active
            user.updated_at = datetime.now(UTC)
            await session.commit()
            return True

    async def mark_user_logged_in(self, user_id: int) -> None:
        async with self._async_session_factory() as session:
            user = (
                await session.execute(select(User).where(User.id == user_id))
            ).scalar_one_or_none()
            if user is None:
                return
            user.last_login_at = datetime.now(UTC)
            user.updated_at = datetime.now(UTC)
            await session.commit()

    async def create_auth_session(
        self,
        user_id: int,
        token_hash: str,
        expires_at: datetime,
        ip_address: str | None,
        user_agent: str | None,
    ) -> AuthSession:
        async with self._async_session_factory() as session:
            auth_session = AuthSession(
                user_id=user_id,
                token_hash=token_hash,
                expires_at=expires_at,
                ip_address=ip_address,
                user_agent=user_agent,
                last_seen_at=datetime.now(UTC),
            )
            session.add(auth_session)
            await session.commit()
            await session.refresh(auth_session)
            return auth_session

    async def get_auth_session(self, token_hash: str) -> AuthSession | None:
        async with self._async_session_factory() as session:
            stmt = (
                select(AuthSession)
                .options(selectinload(AuthSession.user))
                .where(AuthSession.token_hash == token_hash)
            )
            result = await session.execute(stmt)
            return result.scalar_one_or_none()

    async def touch_auth_session(self, session_id: int) -> None:
        async with self._async_session_factory() as session:
            stmt = select(AuthSession).where(AuthSession.id == session_id)
            auth_session = (await session.execute(stmt)).scalar_one_or_none()
            if auth_session is None:
                return
            auth_session.last_seen_at = datetime.now(UTC)
            await session.commit()

    async def revoke_auth_session_by_hash(self, token_hash: str) -> bool:
        async with self._async_session_factory() as session:
            stmt = select(AuthSession).where(AuthSession.token_hash == token_hash)
            auth_session = (await session.execute(stmt)).scalar_one_or_none()
            if auth_session is None:
                return False
            auth_session.revoked_at = datetime.now(UTC)
            await session.commit()
            return True

    async def revoke_auth_sessions_for_user(self, user_id: int) -> int:
        async with self._async_session_factory() as session:
            stmt = select(AuthSession).where(
                AuthSession.user_id == user_id,
                AuthSession.revoked_at.is_(None),
            )
            sessions = (await session.execute(stmt)).scalars().all()
            now = datetime.now(UTC)
            for auth_session in sessions:
                auth_session.revoked_at = now
            await session.commit()
            return len(sessions)

    async def delete_expired_auth_sessions(self) -> int:
        async with self._async_session_factory() as session:
            now = datetime.now(UTC)
            stmt = delete(AuthSession).where(
                AuthSession.expires_at < now,
            )
            result = await session.execute(stmt)
            await session.commit()
            return result.rowcount or 0

    async def upsert_site(self, domain: str, label: str | None = None) -> Site:
        async with self._async_session_factory() as session:
            stmt = select(Site).where(Site.domain == domain)
            result = await session.execute(stmt)
            site = result.scalar_one_or_none()
            if site is None:
                site = Site(domain=domain, label=label)
                session.add(site)
            elif label is not None:
                site.label = label
                site.updated_at = datetime.now(UTC)
            await session.commit()
            await session.refresh(site)
            return site

    async def upsert_page(self, site_id: int, url: str, path: str | None = None) -> Page:
        async with self._async_session_factory() as session:
            stmt = select(Page).where(Page.url == url)
            result = await session.execute(stmt)
            page = result.scalar_one_or_none()
            if page is None:
                page = Page(site_id=site_id, url=url, path=path)
                session.add(page)
            elif path is not None:
                page.path = path
                page.updated_at = datetime.now(UTC)
            await session.commit()
            await session.refresh(page)
            return page

    async def save_scan(
        self, page_id: int, report: ScanReport, screenshot_path: str | None = None
    ) -> ScanResult:
        rule_results_json = json.dumps(
            [r.model_dump(mode="json") for r in report.rule_results]
        )
        llm_eval_json = (
            json.dumps(report.llm_evaluation.model_dump(mode="json"))
            if report.llm_evaluation
            else None
        )
        model_used = (
            report.llm_evaluation.model if report.llm_evaluation else "rules-only"
        )

        async with self._async_session_factory() as session:
            scan_result = ScanResult(
                page_id=page_id,
                overall_status=report.overall_status.value,
                health_score=report.health_score,
                rule_results=rule_results_json,
                llm_evaluation=llm_eval_json,
                model_used=model_used,
                summary=report.summary,
                screenshot_path=screenshot_path,
                scanned_at=report.scanned_at,
            )
            session.add(scan_result)
            await session.commit()
            await session.refresh(scan_result)
            return scan_result

    async def save_scan_for_url(
        self, report: ScanReport, screenshot_path: str | None = None
    ) -> None:
        parsed = urlparse(report.url)
        domain = parsed.netloc
        path = parsed.path or "/"

        site = await self.upsert_site(domain)
        page = await self.upsert_page(site.id, report.url, path)
        await self.save_scan(page.id, report, screenshot_path)

    async def get_sites(self) -> list[dict[str, Any]]:
        async with self._async_session_factory() as session:
            stmt = (
                select(Site)
                .options(selectinload(Site.pages).selectinload(Page.scan_results))
                .order_by(Site.domain)
            )
            result = await session.execute(stmt)
            sites = result.scalars().unique().all()

            grouped: list[dict[str, Any]] = []
            for site in sites:
                pages_data = []
                for page in site.pages:
                    latest_scan = page.scan_results[0] if page.scan_results else None
                    pages_data.append({
                        "id": page.id,
                        "url": page.url,
                        "path": page.path,
                        "latest_status": latest_scan.overall_status if latest_scan else None,
                        "latest_score": latest_scan.health_score if latest_scan else None,
                        "latest_scanned_at": latest_scan.scanned_at if latest_scan else None,
                        "scan_count": len(page.scan_results),
                    })
                grouped.append({
                    "id": site.id,
                    "domain": site.domain,
                    "label": site.label,
                    "pages": pages_data,
                })
            return grouped

    async def get_scan_history(
        self, page_id: int, limit: int = 20
    ) -> list[dict[str, Any]]:
        async with self._async_session_factory() as session:
            stmt = (
                select(ScanResult)
                .where(ScanResult.page_id == page_id)
                .order_by(ScanResult.scanned_at.desc())
                .limit(limit)
            )
            result = await session.execute(stmt)
            scans = result.scalars().all()
            return [
                {
                    "id": s.id,
                    "overall_status": s.overall_status,
                    "health_score": s.health_score,
                    "model_used": s.model_used,
                    "summary": s.summary,
                    "scanned_at": s.scanned_at,
                }
                for s in scans
            ]

    async def get_scan_result(self, scan_id: int) -> dict[str, Any] | None:
        async with self._async_session_factory() as session:
            stmt = select(ScanResult).where(ScanResult.id == scan_id)
            result = await session.execute(stmt)
            scan = result.scalar_one_or_none()
            if scan is None:
                return None
            return {
                "id": scan.id,
                "page_id": scan.page_id,
                "overall_status": scan.overall_status,
                "health_score": scan.health_score,
                "rule_results": json.loads(scan.rule_results),
                "llm_evaluation": (
                    json.loads(scan.llm_evaluation) if scan.llm_evaluation else None
                ),
                "model_used": scan.model_used,
                "summary": scan.summary,
                "screenshot_path": scan.screenshot_path,
                "scanned_at": scan.scanned_at,
            }

    async def get_previous_scans(
        self, page_id: int, limit: int = 2
    ) -> list[dict[str, Any]]:
        async with self._async_session_factory() as session:
            stmt = (
                select(ScanResult)
                .where(
                    ScanResult.page_id == page_id,
                    ScanResult.overall_status != "broken",
                    ScanResult.health_score > 0,
                )
                .order_by(ScanResult.scanned_at.desc())
                .limit(limit)
            )
            result = await session.execute(stmt)
            scans = result.scalars().all()
            return [
                {
                    "id": s.id,
                    "overall_status": s.overall_status,
                    "health_score": s.health_score,
                    "summary": s.summary,
                    "screenshot_path": s.screenshot_path,
                    "scanned_at": s.scanned_at,
                    "llm_evaluation": (
                        json.loads(s.llm_evaluation) if s.llm_evaluation else None
                    ),
                }
                for s in scans
            ]

    async def get_page_with_latest_scan(self, page_id: int) -> dict[str, Any] | None:
        async with self._async_session_factory() as session:
            stmt = (
                select(Page)
                .options(selectinload(Page.site), selectinload(Page.scan_results))
                .where(Page.id == page_id)
            )
            result = await session.execute(stmt)
            page = result.scalar_one_or_none()
            if page is None:
                return None
            latest = page.scan_results[0] if page.scan_results else None
            return {
                "id": page.id,
                "url": page.url,
                "path": page.path,
                "site_domain": page.site.domain,
                "site_label": page.site.label,
                "latest_scan": (
                    {
                        "id": latest.id,
                        "overall_status": latest.overall_status,
                        "health_score": latest.health_score,
                        "rule_results": json.loads(latest.rule_results),
                        "llm_evaluation": (
                            json.loads(latest.llm_evaluation)
                            if latest.llm_evaluation
                            else None
                        ),
                        "model_used": latest.model_used,
                        "summary": latest.summary,
                        "screenshot_path": latest.screenshot_path,
                        "scanned_at": latest.scanned_at,
                    }
                    if latest
                    else None
                ),
                "scan_count": len(page.scan_results),
            }

    async def get_health_stats(self) -> dict[str, int]:
        async with self._async_session_factory() as session:
            stmt = select(Site).options(
                selectinload(Site.pages).selectinload(Page.scan_results)
            )
            result = await session.execute(stmt)
            sites = result.scalars().unique().all()
            stats = {"total": 0, "healthy": 0, "degraded": 0, "broken": 0, "not_scanned": 0}
            for site in sites:
                for page in site.pages:
                    stats["total"] += 1
                    if page.scan_results:
                        latest = page.scan_results[0]
                        s = latest.overall_status
                        if s in stats:
                            stats[s] += 1
                        else:
                            stats["not_scanned"] += 1
                    else:
                        stats["not_scanned"] += 1
            return stats

    async def get_scan_trend(self, days: int = 30) -> list[dict[str, Any]]:
        from datetime import timedelta

        cutoff = datetime.now(UTC) - timedelta(days=days)
        async with self._async_session_factory() as session:
            stmt = (
                select(
                    func.date(ScanResult.scanned_at).label("scan_date"),
                    func.avg(ScanResult.health_score).label("avg_score"),
                    func.count(ScanResult.id).label("scan_count"),
                )
                .where(ScanResult.scanned_at >= cutoff)
                .group_by(func.date(ScanResult.scanned_at))
                .order_by(func.date(ScanResult.scanned_at))
            )
            result = await session.execute(stmt)
            return [
                {
                    "date": str(row.scan_date),
                    "avg_score": round(float(row.avg_score), 1),
                    "scan_count": row.scan_count,
                }
                for row in result
            ]

    async def get_recent_scans(self, limit: int = 10) -> list[dict[str, Any]]:
        async with self._async_session_factory() as session:
            stmt = (
                select(ScanResult, Page.url)
                .join(Page, ScanResult.page_id == Page.id)
                .order_by(ScanResult.scanned_at.desc())
                .limit(limit)
            )
            result = await session.execute(stmt)
            return [
                {
                    "id": scan.id,
                    "url": url,
                    "overall_status": scan.overall_status,
                    "health_score": scan.health_score,
                    "scanned_at": scan.scanned_at,
                }
                for scan, url in result.all()
            ]

    async def delete_site(self, site_id: int) -> str | None:
        async with self._async_session_factory() as session:
            stmt = select(Site).where(Site.id == site_id)
            result = await session.execute(stmt)
            site = result.scalar_one_or_none()
            if site is None:
                return None
            domain = site.domain
            await session.delete(site)
            await session.commit()
            return domain

    async def get_page_health_history(
        self, page_id: int, limit: int = 10
    ) -> list[dict[str, Any]]:
        async with self._async_session_factory() as session:
            stmt = (
                select(ScanResult.health_score, ScanResult.scanned_at)
                .where(ScanResult.page_id == page_id)
                .order_by(ScanResult.scanned_at.desc())
                .limit(limit)
            )
            result = await session.execute(stmt)
            return [
                {"score": row.health_score, "scanned_at": row.scanned_at}
                for row in result
            ]
