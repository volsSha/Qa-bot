from __future__ import annotations

from datetime import UTC, datetime

import pytest

from qa_bot.config import Settings
from qa_bot.db.database import Database
from qa_bot.domain.models import (
    CheckResult,
    LLMEvaluation,
    LLMFinding,
    OverallStatus,
    ScanReport,
    Severity,
)


def _make_settings(database_url: str = "sqlite+aiosqlite:///:memory:") -> Settings:
    return Settings.model_construct(
        openrouter_api_key="test-key",
        database_url=database_url,
        auth_session_secret="test-secret-at-least-16",
    )


def _make_report(
    url: str = "https://example.com/",
    status: OverallStatus = OverallStatus.HEALTHY,
    score: float = 100.0,
    with_llm: bool = True,
) -> ScanReport:
    rule = CheckResult(
        check_name="http_status",
        severity=Severity.PASS,
        message="OK",
        category="http",
    )
    llm = (
        LLMEvaluation(
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
            raw_response="{}",
            evaluated_at=datetime.now(UTC),
        )
        if with_llm
        else None
    )
    return ScanReport(
        url=url,
        overall_status=status,
        health_score=score,
        rule_results=[rule],
        llm_evaluation=llm,
        summary="Test summary",
        scanned_at=datetime.now(UTC),
    )


@pytest.fixture
async def db():
    settings = _make_settings()
    database = Database(settings)
    await database.init()
    yield database
    await database.close()


class TestUpsertSite:
    async def test_create_new_site(self, db):
        site = await db.upsert_site("example.com", "Example")
        assert site.id is not None
        assert site.domain == "example.com"
        assert site.label == "Example"

    async def test_update_existing_site_label(self, db):
        await db.upsert_site("example.com", "Old Label")
        site = await db.upsert_site("example.com", "New Label")
        assert site.label == "New Label"

    async def test_create_without_label(self, db):
        site = await db.upsert_site("example.com")
        assert site.label is None


class TestUpsertPage:
    async def test_create_new_page(self, db):
        site = await db.upsert_site("example.com")
        page = await db.upsert_page(site.id, "https://example.com/", "/")
        assert page.id is not None
        assert page.url == "https://example.com/"
        assert page.path == "/"

    async def test_update_existing_page_path(self, db):
        site = await db.upsert_site("example.com")
        await db.upsert_page(site.id, "https://example.com/", None)
        page = await db.upsert_page(site.id, "https://example.com/", "/")
        assert page.path == "/"


class TestSaveScan:
    async def test_save_scan_with_llm(self, db):
        site = await db.upsert_site("example.com")
        page = await db.upsert_page(site.id, "https://example.com/", "/")
        report = _make_report(with_llm=True)

        result = await db.save_scan(page.id, report)
        assert result.id is not None
        assert result.overall_status == "healthy"
        assert result.health_score == 100.0
        assert result.llm_evaluation is not None
        assert result.model_used == "openai/gpt-4"

    async def test_save_scan_without_llm(self, db):
        site = await db.upsert_site("example.com")
        page = await db.upsert_page(site.id, "https://example.com/", "/")
        report = _make_report(with_llm=False)

        result = await db.save_scan(page.id, report)
        assert result.llm_evaluation is None
        assert result.model_used == "rules-only"

    async def test_rule_results_json_roundtrip(self, db):
        site = await db.upsert_site("example.com")
        page = await db.upsert_page(site.id, "https://example.com/", "/")
        report = _make_report()

        result = await db.save_scan(page.id, report)
        scan_data = await db.get_scan_result(result.id)
        assert scan_data is not None
        rules = [CheckResult.model_validate(r, strict=False) for r in scan_data["rule_results"]]
        assert len(rules) == 1
        assert rules[0].check_name == "http_status"


class TestSaveScanForUrl:
    async def test_full_chain(self, db):
        report = _make_report("https://example.com/about")
        await db.save_scan_for_url(report)

        sites = await db.get_sites()
        assert len(sites) == 1
        assert sites[0]["domain"] == "example.com"
        assert len(sites[0]["pages"]) == 1
        assert sites[0]["pages"][0]["url"] == "https://example.com/about"
        assert sites[0]["pages"][0]["latest_status"] == "healthy"

    async def test_db_failure_does_not_raise(self, db):
        report = _make_report("https://example.com/about")
        await db.save_scan_for_url(report)


class TestGetSites:
    async def test_empty_database(self, db):
        sites = await db.get_sites()
        assert sites == []

    async def test_grouped_by_domain(self, db):
        await db.save_scan_for_url(_make_report("https://example.com/"))
        await db.save_scan_for_url(_make_report("https://example.com/about"))
        await db.save_scan_for_url(_make_report("https://other.com/"))

        sites = await db.get_sites()
        assert len(sites) == 2
        ex = next(s for s in sites if s["domain"] == "example.com")
        assert len(ex["pages"]) == 2
        other = next(s for s in sites if s["domain"] == "other.com")
        assert len(other["pages"]) == 1

    async def test_latest_scan_info(self, db):
        await db.save_scan_for_url(
            _make_report("https://example.com/", OverallStatus.HEALTHY, 100.0)
        )
        await db.save_scan_for_url(
            _make_report("https://example.com/", OverallStatus.DEGRADED, 60.0)
        )

        sites = await db.get_sites()
        ex = sites[0]
        page = ex["pages"][0]
        assert page["latest_status"] == "degraded"
        assert page["latest_score"] == 60.0
        assert page["scan_count"] == 2


class TestDeleteSite:
    async def test_delete_site_removes_pages_and_scans(self, db):
        await db.save_scan_for_url(_make_report("https://delete-me.example/"))
        sites = await db.get_sites()
        site = sites[0]
        page_id = site["pages"][0]["id"]

        deleted_domain = await db.delete_site(site["id"])

        assert deleted_domain == "delete-me.example"
        assert await db.get_sites() == []
        assert await db.get_page_with_latest_scan(page_id) is None

    async def test_delete_site_returns_none_for_missing_site(self, db):
        assert await db.delete_site(99999) is None


class TestGetScanHistory:
    async def test_history_ordered_by_time(self, db):
        await db.save_scan_for_url(_make_report("https://example.com/"))
        await db.save_scan_for_url(_make_report("https://example.com/"))

        sites = await db.get_sites()
        page_id = sites[0]["pages"][0]["id"]

        history = await db.get_scan_history(page_id)
        assert len(history) == 2
        assert history[0]["health_score"] >= history[1]["health_score"]

    async def test_limit(self, db):
        for _ in range(5):
            await db.save_scan_for_url(_make_report("https://example.com/"))

        sites = await db.get_sites()
        page_id = sites[0]["pages"][0]["id"]

        history = await db.get_scan_history(page_id, limit=3)
        assert len(history) == 3

    async def test_empty_history(self, db):
        site = await db.upsert_site("example.com")
        page = await db.upsert_page(site.id, "https://example.com/", "/")

        history = await db.get_scan_history(page.id)
        assert history == []


class TestGetScanResult:
    async def test_get_existing_scan(self, db):
        report = _make_report()
        site = await db.upsert_site("example.com")
        page = await db.upsert_page(site.id, report.url, "/")
        result = await db.save_scan(page.id, report)

        scan_data = await db.get_scan_result(result.id)
        assert scan_data is not None
        assert scan_data["overall_status"] == "healthy"
        assert scan_data["rule_results"] is not None

    async def test_get_nonexistent_scan(self, db):
        scan_data = await db.get_scan_result(99999)
        assert scan_data is None

    async def test_screenshot_path_roundtrip(self, db):
        report = _make_report()
        site = await db.upsert_site("example.com")
        page = await db.upsert_page(site.id, report.url, "/")
        result = await db.save_scan(
            page.id, report, screenshot_path="data/screenshots/test.png"
        )

        scan_data = await db.get_scan_result(result.id)
        assert scan_data is not None
        assert scan_data["screenshot_path"] == "data/screenshots/test.png"

    async def test_screenshot_path_none_default(self, db):
        report = _make_report()
        site = await db.upsert_site("example.com")
        page = await db.upsert_page(site.id, report.url, "/")
        result = await db.save_scan(page.id, report)

        scan_data = await db.get_scan_result(result.id)
        assert scan_data is not None
        assert scan_data["screenshot_path"] is None


class TestGetPageWithLatestScan:
    async def test_page_detail(self, db):
        await db.save_scan_for_url(_make_report("https://example.com/about"))
        sites = await db.get_sites()
        page_id = sites[0]["pages"][0]["id"]

        detail = await db.get_page_with_latest_scan(page_id)
        assert detail is not None
        assert detail["url"] == "https://example.com/about"
        assert detail["site_domain"] == "example.com"
        assert detail["latest_scan"] is not None
        assert detail["latest_scan"]["overall_status"] == "healthy"
        assert detail["scan_count"] == 1

    async def test_page_without_scans(self, db):
        site = await db.upsert_site("example.com")
        page = await db.upsert_page(site.id, "https://example.com/", "/")

        detail = await db.get_page_with_latest_scan(page.id)
        assert detail is not None
        assert detail["latest_scan"] is None
        assert detail["scan_count"] == 0

    async def test_nonexistent_page(self, db):
        detail = await db.get_page_with_latest_scan(99999)
        assert detail is None


class TestGetPreviousScans:
    async def test_returns_up_to_limit(self, db):
        for i in range(4):
            await db.save_scan_for_url(
                _make_report("https://example.com/", score=float(80 + i))
            )
        sites = await db.get_sites()
        page_id = sites[0]["pages"][0]["id"]

        prev = await db.get_previous_scans(page_id, limit=2)
        assert len(prev) == 2

    async def test_returns_empty_for_new_page(self, db):
        site = await db.upsert_site("example.com")
        page = await db.upsert_page(site.id, "https://example.com/", "/")

        prev = await db.get_previous_scans(page.id, limit=2)
        assert prev == []

    async def test_excludes_broken_scans(self, db):
        await db.save_scan_for_url(
            _make_report("https://example.com/", OverallStatus.HEALTHY, 90.0)
        )
        await db.save_scan_for_url(
            _make_report("https://example.com/", OverallStatus.BROKEN, 10.0)
        )
        sites = await db.get_sites()
        page_id = sites[0]["pages"][0]["id"]

        prev = await db.get_previous_scans(page_id, limit=5)
        assert all(s["overall_status"] != "broken" for s in prev)

    async def test_includes_screenshot_path(self, db):
        report = _make_report("https://example.com/")
        await db.save_scan_for_url(report, screenshot_path="data/screenshots/test.png")
        sites = await db.get_sites()
        page_id = sites[0]["pages"][0]["id"]

        prev = await db.get_previous_scans(page_id, limit=1)
        assert len(prev) == 1
        assert prev[0]["screenshot_path"] == "data/screenshots/test.png"


class TestAuthPersistence:
    async def test_create_and_lookup_user(self, db):
        user = await db.create_user(
            email="Admin@Example.com",
            password_hash="hash-1",
            role="admin",
        )

        assert user.email == "admin@example.com"
        found = await db.get_user_by_email("ADMIN@example.com")
        assert found is not None
        assert found.id == user.id

    async def test_bootstrap_admin_is_idempotent(self, db):
        first = await db.ensure_bootstrap_admin("admin@example.com", "hash-1")
        second = await db.ensure_bootstrap_admin("admin@example.com", "hash-2")

        assert first is not None
        assert second is None
        users = await db.list_users()
        admins = [u for u in users if u["role"] == "admin" and u["is_active"]]
        assert len(admins) == 1

    async def test_session_lifecycle_create_revoke(self, db):
        user = await db.create_user(
            email="user@example.com",
            password_hash="hash-1",
            role="user",
        )
        expires_at = datetime.now(UTC)
        auth_session = await db.create_auth_session(
            user_id=user.id,
            token_hash="token-hash-1",
            expires_at=expires_at,
            ip_address="127.0.0.1",
            user_agent="pytest",
        )

        loaded = await db.get_auth_session("token-hash-1")
        assert loaded is not None
        assert loaded.id == auth_session.id
        assert loaded.user is not None
        assert loaded.user.id == user.id

        revoked = await db.revoke_auth_session_by_hash("token-hash-1")
        assert revoked is True
        loaded_after = await db.get_auth_session("token-hash-1")
        assert loaded_after is not None
        assert loaded_after.revoked_at is not None

    async def test_delete_expired_sessions(self, db):
        user = await db.create_user(
            email="cleanup@example.com",
            password_hash="hash-1",
            role="user",
        )
        await db.create_auth_session(
            user_id=user.id,
            token_hash="old-hash",
            expires_at=datetime(2000, 1, 1, tzinfo=UTC),
            ip_address=None,
            user_agent=None,
        )

        removed = await db.delete_expired_auth_sessions()
        assert removed >= 1
        assert await db.get_auth_session("old-hash") is None
