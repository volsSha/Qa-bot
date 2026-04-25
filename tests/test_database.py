from __future__ import annotations

import json
from datetime import UTC, datetime

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from qa_bot.config import Settings
from qa_bot.database import Database
from qa_bot.db_models import Base
from qa_bot.models import (
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
