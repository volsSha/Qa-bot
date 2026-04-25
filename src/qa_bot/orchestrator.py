from __future__ import annotations

import asyncio
from datetime import UTC, datetime

from qa_bot.config import Settings
from qa_bot.fetcher import PageFetcher
from qa_bot.llm_evaluator import LLMEvaluator
from qa_bot.models import (
    OverallStatus,
    ScanBatch,
    ScanReport,
    Severity,
)
from qa_bot.preprocessor import preprocess
from qa_bot.reporter import generate_summary, save_batch_report, save_report, save_screenshot
from qa_bot.rules import RuleEngine, has_critical_failure


class QABot:
    def __init__(self, settings: Settings) -> None:
        self._settings = settings
        self._fetcher = PageFetcher(settings)
        self._rule_engine = RuleEngine(settings)
        self._llm_evaluator = LLMEvaluator(settings)

    async def scan_url(self, url: str) -> ScanReport:
        snapshot = await self._fetcher.fetch(url)
        preprocessed = preprocess(snapshot.html)
        rule_results = self._rule_engine.evaluate(snapshot, preprocessed)

        if has_critical_failure(rule_results):
            llm_evaluation = None
        else:
            llm_evaluation = await self._llm_evaluator.evaluate(
                snapshot, preprocessed, rule_results
            )

        health_score = 100.0
        for r in rule_results:
            if r.severity == Severity.CRITICAL:
                health_score -= self._settings.health_score_critical_penalty
            elif r.severity == Severity.WARNING:
                health_score -= self._settings.health_score_warning_penalty
            elif r.severity == Severity.INFO:
                health_score -= self._settings.health_score_info_penalty
        health_score = max(0.0, min(100.0, health_score))

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
        )
        if snapshot.screenshot:
            save_screenshot(url, snapshot.screenshot)
        save_report(report)
        return report

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
