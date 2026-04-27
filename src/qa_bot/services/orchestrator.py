from __future__ import annotations

import asyncio
import logging
from datetime import UTC, datetime
from typing import TYPE_CHECKING
from urllib.parse import urlparse

from qa_bot.config import Settings
from qa_bot.domain.models import (
    HistoricalContext,
    OverallStatus,
    ScanBatch,
    ScanReport,
    Severity,
)
from qa_bot.services.fetcher import PageFetcher
from qa_bot.services.llm_evaluator import LLMEvaluator
from qa_bot.services.preprocessor import preprocess
from qa_bot.services.reporter import (
    generate_summary,
    save_batch_report,
    save_report,
    save_screenshot,
)
from qa_bot.services.rules import RuleEngine, has_critical_failure

if TYPE_CHECKING:
    from qa_bot.db.database import Database

logger = logging.getLogger(__name__)


class QABot:
    def __init__(self, settings: Settings, database: Database | None = None) -> None:
        self._settings = settings
        self._fetcher = PageFetcher(settings)
        self._rule_engine = RuleEngine(settings)
        self._llm_evaluator = LLMEvaluator(settings)
        self._database = database

    async def scan_url(self, url: str) -> ScanReport:
        snapshot = await self._fetcher.fetch(url)
        preprocessed = preprocess(snapshot.html)
        rule_results = self._rule_engine.evaluate(snapshot, preprocessed)

        screenshot_path = None
        if snapshot.screenshot:
            path = save_screenshot(url, snapshot.screenshot)
            screenshot_path = str(path)

        had_historical_context = False
        if has_critical_failure(rule_results):
            llm_evaluation = None
        else:
            historical_contexts = await self._load_historical_contexts(url)
            had_historical_context = len(historical_contexts) > 0
            llm_evaluation = await self._llm_evaluator.evaluate(
                snapshot, preprocessed, rule_results, historical_contexts
            )

        health_score = self._compute_health_score(
            rule_results, llm_evaluation, had_historical_context
        )

        if health_score >= self._settings.health_healthy_threshold:
            overall_status = OverallStatus.HEALTHY
        elif health_score >= self._settings.health_degraded_threshold:
            overall_status = OverallStatus.DEGRADED
        else:
            overall_status = OverallStatus.BROKEN

        summary = generate_summary(
            url=url,
            overall_status=overall_status,
            health_score=health_score,
            rule_results=rule_results,
            llm_evaluation=llm_evaluation,
        )
        report = ScanReport(
            url=url,
            overall_status=overall_status,
            health_score=health_score,
            rule_results=rule_results,
            llm_evaluation=llm_evaluation,
            summary=summary,
            scanned_at=datetime.now(UTC),
            screenshot_path=screenshot_path,
        )
        save_report(report)
        if self._database:
            try:
                await self._database.save_scan_for_url(report, screenshot_path)
            except Exception:
                logger.exception("Failed to persist scan for %s", url)
        return report

    def _compute_health_score(
        self,
        rule_results: list,
        llm_evaluation: object | None,
        had_historical_context: bool = False,
    ) -> float:
        health_score = 100.0
        for r in rule_results:
            if r.severity == Severity.CRITICAL:
                health_score -= self._settings.health_score_critical_penalty
            elif r.severity == Severity.WARNING:
                health_score -= self._settings.health_score_warning_penalty
            elif r.severity == Severity.INFO:
                health_score -= self._settings.health_score_info_penalty

        if (
            had_historical_context
            and llm_evaluation is not None
            and self._settings.visual_regression_enabled
            and self._settings.health_score_regression_penalty > 0
        ):
            for finding in llm_evaluation.findings:
                if finding.category in (
                    "visual_regression",
                    "layout_drift",
                    "content_consistency",
                ) and not finding.passed:
                    health_score -= self._settings.health_score_regression_penalty
                    break

        return max(0.0, min(100.0, health_score))

    async def _load_historical_contexts(self, url: str) -> list[HistoricalContext]:
        if not self._database or not self._settings.visual_regression_enabled:
            return []
        if self._settings.screenshot_history_depth <= 0:
            return []

        try:
            parsed = urlparse(url)
            domain = parsed.netloc
            path = parsed.path or "/"

            site = await self._database.upsert_site(domain)
            page = await self._database.upsert_page(site.id, url, path)

            previous_scans = await self._database.get_previous_scans(
                page.id, limit=self._settings.screenshot_history_depth
            )

            contexts = []
            for scan in previous_scans:
                contexts.append(
                    HistoricalContext(
                        previous_findings_summary=scan.get("summary", ""),
                        previous_health_score=scan.get("health_score"),
                        previous_scanned_at=scan.get("scanned_at"),
                        screenshot_path=scan.get("screenshot_path"),
                    )
                )
            return contexts
        except Exception:
            logger.warning("Failed to load historical context for %s", url, exc_info=True)
            return []

    async def scan_urls(self, urls: list[str]) -> ScanBatch:
        sem = asyncio.Semaphore(self._settings.max_concurrent_scans)

        async def _guarded(u: str) -> ScanReport:
            async with sem:
                return await self.scan_url(u)

        reports = await asyncio.gather(*[_guarded(u) for u in urls])
        batch = ScanBatch(
            urls=urls,
            reports=list(reports),
            generated_at=datetime.now(UTC),
        )
        save_batch_report(batch)
        return batch
