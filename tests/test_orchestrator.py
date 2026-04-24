from __future__ import annotations

from datetime import datetime
from unittest.mock import AsyncMock, MagicMock

import pytest

from qa_bot.config import Settings
from qa_bot.models import (
    CheckResult,
    LLMEvaluation,
    LLMFinding,
    OverallStatus,
    PageSnapshot,
    PreprocessedPage,
    ScanBatch,
    Severity,
)
from qa_bot.orchestrator import QABot

_NOW = datetime(2026, 1, 1, 0, 0, 0)

_SETTINGS = Settings(
    openrouter_api_key="sk-test",
    health_score_critical_penalty=30,
    health_score_warning_penalty=10,
    health_score_info_penalty=2,
    health_healthy_threshold=80,
    health_degraded_threshold=50,
    max_concurrent_scans=2,
)


def _snapshot(url: str = "https://example.com") -> PageSnapshot:
    return PageSnapshot(
        url=url,
        html="<html><head><title>Test</title></head><body><h1>Hello</h1></body></html>",
        screenshot=b"img",
        text_content="Hello",
        console_errors=[],
        load_time_ms=100,
        status_code=200,
        fetched_at=_NOW,
    )


def _preprocessed() -> PreprocessedPage:
    return PreprocessedPage(
        title="Test",
        text_content="Hello",
        images=[],
        links=[],
        forms=[],
        meta_tags={"viewport": "width=device-width"},
        headings=[{"level": 1, "text": "Hello"}],
    )


def _pass_rules(count: int = 10) -> list[CheckResult]:
    return [
        CheckResult(
            check_name=f"rule_{i}",
            severity=Severity.PASS,
            message="ok",
            category="test",
        )
        for i in range(count)
    ]


def _llm_eval() -> LLMEvaluation:
    return LLMEvaluation(
        model="openai/gpt-4",
        findings=[
            LLMFinding(
                category="layout_quality",
                passed=True,
                confidence=0.9,
                evidence="Looks good",
                recommendation=None,
            )
        ],
        raw_response="{}",
        evaluated_at=_NOW,
    )


def _make_bot() -> tuple[QABot, AsyncMock, AsyncMock]:
    bot = QABot(_SETTINGS)
    mock_fetcher = AsyncMock(return_value=_snapshot())
    mock_llm = AsyncMock(return_value=_llm_eval())
    bot._fetcher.fetch = mock_fetcher
    bot._llm_evaluator.evaluate = mock_llm
    return bot, mock_fetcher, mock_llm


def _make_bot_with_rules(rules: list[CheckResult]) -> QABot:
    bot = QABot(_SETTINGS)
    mock_fetcher = AsyncMock(return_value=_snapshot())
    mock_llm = AsyncMock(return_value=_llm_eval())
    bot._fetcher.fetch = mock_fetcher
    bot._llm_evaluator.evaluate = mock_llm
    bot._rule_engine.evaluate = MagicMock(return_value=rules)
    return bot


class TestHappyPath:
    @pytest.mark.asyncio
    async def test_healthy_page(self):
        bot = _make_bot_with_rules(_pass_rules())
        report = await bot.scan_url("https://example.com")

        assert report.overall_status == OverallStatus.HEALTHY
        assert report.health_score == 100.0
        assert report.llm_evaluation is not None
        assert "Healthy" in report.summary


class TestDecisionRouter:
    @pytest.mark.asyncio
    async def test_critical_failure_skips_llm(self):
        rules = [
            CheckResult(
                check_name="http_status",
                severity=Severity.CRITICAL,
                message="HTTP 500",
                category="accessibility",
            ),
            CheckResult(
                check_name="title_present",
                severity=Severity.CRITICAL,
                message="Missing title",
                category="seo",
            ),
        ]
        bot = _make_bot_with_rules(rules)

        report = await bot.scan_url("https://example.com")

        assert report.overall_status == OverallStatus.BROKEN
        assert report.llm_evaluation is None

    @pytest.mark.asyncio
    async def test_all_rules_pass_calls_llm(self):
        bot = _make_bot_with_rules(_pass_rules())

        report = await bot.scan_url("https://example.com")

        assert report.llm_evaluation is not None


class TestHealthScore:
    @pytest.mark.asyncio
    async def test_mixed_severities(self):
        rules = [
            CheckResult(check_name="c1", severity=Severity.CRITICAL, message="c", category="x"),
            CheckResult(check_name="c2", severity=Severity.CRITICAL, message="c", category="x"),
            CheckResult(check_name="w1", severity=Severity.WARNING, message="w", category="x"),
            CheckResult(check_name="w2", severity=Severity.WARNING, message="w", category="x"),
            CheckResult(check_name="i1", severity=Severity.INFO, message="i", category="x"),
        ]
        bot = _make_bot_with_rules(rules)

        report = await bot.scan_url("https://example.com")

        expected = 100 - (2 * 30) - (2 * 10) - 2
        assert report.health_score == expected


class TestStatusThresholds:
    @pytest.mark.asyncio
    async def test_score_85_healthy(self):
        rules = _pass_rules()
        rules.append(
            CheckResult(check_name="i1", severity=Severity.INFO, message="i", category="x")
        )
        bot = _make_bot_with_rules(rules)

        report = await bot.scan_url("https://example.com")
        assert report.overall_status == OverallStatus.HEALTHY

    @pytest.mark.asyncio
    async def test_score_60_degraded(self):
        rules = [
            CheckResult(check_name="c1", severity=Severity.CRITICAL, message="c", category="x"),
            CheckResult(check_name="w1", severity=Severity.WARNING, message="w", category="x"),
        ]
        bot = _make_bot_with_rules(rules)

        report = await bot.scan_url("https://example.com")
        assert report.health_score == 60
        assert report.overall_status == OverallStatus.DEGRADED

    @pytest.mark.asyncio
    async def test_score_30_broken(self):
        rules = [
            CheckResult(check_name="c1", severity=Severity.CRITICAL, message="c", category="x"),
            CheckResult(check_name="c2", severity=Severity.CRITICAL, message="c", category="x"),
            CheckResult(check_name="c3", severity=Severity.CRITICAL, message="c", category="x"),
        ]
        bot = _make_bot_with_rules(rules)

        report = await bot.scan_url("https://example.com")
        assert report.health_score == 10
        assert report.overall_status == OverallStatus.BROKEN


class TestEdgeCases:
    @pytest.mark.asyncio
    async def test_empty_url_list(self):
        bot, _, _ = _make_bot()
        batch = await bot.scan_urls([])

        assert isinstance(batch, ScanBatch)
        assert batch.urls == []
        assert batch.reports == []


class TestScanUrls:
    @pytest.mark.asyncio
    async def test_processes_multiple_urls(self):
        bot, mock_fetcher, _ = _make_bot()
        mock_fetcher.side_effect = [
            _snapshot("https://a.com"),
            _snapshot("https://b.com"),
            _snapshot("https://c.com"),
        ]
        bot._rule_engine.evaluate = MagicMock(return_value=_pass_rules())

        batch = await bot.scan_urls(["https://a.com", "https://b.com", "https://c.com"])

        assert len(batch.reports) == 3
        assert batch.urls == ["https://a.com", "https://b.com", "https://c.com"]
        for report in batch.reports:
            assert report.overall_status == OverallStatus.HEALTHY
