from __future__ import annotations

import json
from datetime import UTC, datetime

import pytest
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from qa_bot.db.models import AuthSession, Base, Page, ScanResult, Site, User
from qa_bot.domain.models import (
    CheckResult,
    LLMEvaluation,
    LLMFinding,
    Severity,
)


@pytest.fixture
async def engine():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield engine
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
    await engine.dispose()


@pytest.fixture
async def session(engine):
    factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with factory() as session:
        yield session


class TestSiteModel:
    async def test_create_site(self, session):
        site = Site(domain="example.com", label="Example")
        session.add(site)
        await session.commit()
        await session.refresh(site)

        assert site.id is not None
        assert site.domain == "example.com"
        assert site.label == "Example"
        assert site.created_at is not None

    async def test_unique_domain_constraint(self, engine):
        factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
        async with factory() as session:
            session.add(Site(domain="example.com"))
            await session.commit()

        async with factory() as session:
            session.add(Site(domain="example.com"))
            with pytest.raises(IntegrityError):
                await session.commit()

    async def test_label_nullable(self, session):
        site = Site(domain="example.com")
        session.add(site)
        await session.commit()
        await session.refresh(site)
        assert site.label is None


class TestPageModel:
    async def test_create_page(self, session):
        site = Site(domain="example.com")
        session.add(site)
        await session.commit()
        await session.refresh(site)

        page = Page(site_id=site.id, url="https://example.com/", path="/")
        session.add(page)
        await session.commit()
        await session.refresh(page)

        assert page.id is not None
        assert page.url == "https://example.com/"
        assert page.path == "/"

    async def test_unique_url_constraint(self, engine):
        factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
        async with factory() as session:
            site = Site(domain="example.com")
            session.add(site)
            await session.commit()
            await session.refresh(site)

            page = Page(site_id=site.id, url="https://example.com/", path="/")
            session.add(page)
            await session.commit()

        async with factory() as session:
            page2 = Page(site_id=site.id, url="https://example.com/", path="/")
            session.add(page2)
            with pytest.raises(IntegrityError):
                await session.commit()

    async def test_relationship_to_site(self, session):
        site = Site(domain="example.com")
        session.add(site)
        await session.flush()
        await session.refresh(site)

        page = Page(site_id=site.id, url="https://example.com/")
        session.add(page)
        await session.commit()
        await session.refresh(page)

        assert page.site_id == site.id


class TestScanResultModel:
    async def _create_full_chain(self, session):
        site = Site(domain="example.com")
        session.add(site)
        await session.flush()
        await session.refresh(site)

        page = Page(site_id=site.id, url="https://example.com/", path="/")
        session.add(page)
        await session.flush()
        await session.refresh(page)
        return site, page

    async def test_create_scan_result(self, session):
        _, page = await self._create_full_chain(session)

        rule_results = json.dumps([
            {"check_name": "http_status", "severity": "pass", "message": "OK", "category": "http"}
        ])
        scan = ScanResult(
            page_id=page.id,
            overall_status="healthy",
            health_score=100.0,
            rule_results=rule_results,
            llm_evaluation=None,
            model_used="openai/gpt-4",
            summary="All checks passed",
            scanned_at=datetime.now(UTC),
        )
        session.add(scan)
        await session.commit()
        await session.refresh(scan)

        assert scan.id is not None
        assert scan.overall_status == "healthy"
        assert scan.llm_evaluation is None

    async def test_json_roundtrip_rule_results(self, session):
        _, page = await self._create_full_chain(session)

        original = CheckResult(
            check_name="http_status",
            severity=Severity.PASS,
            message="OK",
            evidence="200",
            category="http",
        )
        rule_json = json.dumps([original.model_dump(mode="json")])

        scan = ScanResult(
            page_id=page.id,
            overall_status="healthy",
            health_score=100.0,
            rule_results=rule_json,
            model_used="openai/gpt-4",
            summary="OK",
            scanned_at=datetime.now(UTC),
        )
        session.add(scan)
        await session.commit()
        await session.refresh(scan)

        restored = [
            CheckResult.model_validate(r, strict=False)
            for r in json.loads(scan.rule_results)
        ]
        assert len(restored) == 1
        assert restored[0].check_name == "http_status"
        assert restored[0].severity == Severity.PASS

    async def test_json_roundtrip_llm_evaluation(self, session):
        _, page = await self._create_full_chain(session)

        original_eval = LLMEvaluation(
            model="openai/gpt-4",
            findings=[
                LLMFinding(
                    category="layout_quality",
                    passed=True,
                    confidence=0.9,
                    evidence="Clean layout",
                    recommendation=None,
                )
            ],
            raw_response='{"findings": [...]}',
            evaluated_at=datetime.now(UTC),
        )
        llm_json = json.dumps(original_eval.model_dump(mode="json"))

        scan = ScanResult(
            page_id=page.id,
            overall_status="healthy",
            health_score=100.0,
            rule_results="[]",
            llm_evaluation=llm_json,
            model_used="openai/gpt-4",
            summary="OK",
            scanned_at=datetime.now(UTC),
        )
        session.add(scan)
        await session.commit()
        await session.refresh(scan)

        restored = LLMEvaluation.model_validate(json.loads(scan.llm_evaluation), strict=False)
        assert restored.model == "openai/gpt-4"
        assert len(restored.findings) == 1
        assert restored.findings[0].category == "layout_quality"

    async def test_multiple_scans_per_page(self, session):
        _, page = await self._create_full_chain(session)

        for i, status in enumerate(["healthy", "degraded"]):
            scan = ScanResult(
                page_id=page.id,
                overall_status=status,
                health_score=100.0 - i * 30,
                rule_results="[]",
                model_used="openai/gpt-4",
                summary=f"Scan {i}",
                scanned_at=datetime.now(UTC),
            )
            session.add(scan)
        await session.commit()

        stmt = (
            ScanResult.__table__.select().where(ScanResult.page_id == page.id)
        )
        result = await session.execute(stmt)
        rows = result.fetchall()
        assert len(rows) == 2


class TestUserAndAuthSessionModels:
    async def test_create_user(self, session):
        user = User(
            email="admin@example.com",
            password_hash="$2b$12$examplehash",
            role="admin",
            is_active=True,
        )
        session.add(user)
        await session.commit()
        await session.refresh(user)

        assert user.id is not None
        assert user.email == "admin@example.com"
        assert user.role == "admin"
        assert user.is_active is True

    async def test_unique_user_email_constraint(self, engine):
        factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
        async with factory() as session:
            session.add(User(email="admin@example.com", password_hash="h1", role="admin"))
            await session.commit()

        async with factory() as session:
            session.add(User(email="admin@example.com", password_hash="h2", role="user"))
            with pytest.raises(IntegrityError):
                await session.commit()

    async def test_auth_session_relationship(self, session):
        user = User(email="admin@example.com", password_hash="h", role="admin")
        session.add(user)
        await session.flush()
        await session.refresh(user)

        auth_session = AuthSession(
            user_id=user.id,
            token_hash="token-hash",
            expires_at=datetime.now(UTC),
        )
        session.add(auth_session)
        await session.commit()
        await session.refresh(auth_session)

        assert auth_session.id is not None
        assert auth_session.user_id == user.id
