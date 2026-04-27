from datetime import datetime

import pytest
from pydantic import ValidationError

from qa_bot.domain.models import (
    CheckResult,
    FormInfo,
    HeadingInfo,
    HistoricalContext,
    ImageInfo,
    LinkInfo,
    LLMEvaluation,
    LLMFinding,
    OverallStatus,
    PageSnapshot,
    PreprocessedPage,
    ScanBatch,
    ScanReport,
    Severity,
    URLInput,
)

NOW = datetime(2026, 4, 25, 12, 0, 0)


@pytest.fixture
def sample_preprocessed() -> PreprocessedPage:
    return PreprocessedPage(
        title="Test Page",
        text_content="Hello world",
        images=[ImageInfo(src="/img.png", alt="pic")],
        links=[LinkInfo(href="https://example.com", text="Go")],
        forms=[FormInfo(inputs_count=3, has_labels=True)],
        meta_tags={"description": "test"},
        headings=[HeadingInfo(level=1, text="Title")],
    )


@pytest.fixture
def sample_snapshot() -> PageSnapshot:
    return PageSnapshot(
        url="https://example.com",
        html="<html></html>",
        screenshot=b"valid_utf8",
        text_content="Hello",
        console_errors=[],
        load_time_ms=150,
        status_code=200,
        fetched_at=NOW,
    )


@pytest.fixture
def sample_llm_evaluation() -> LLMEvaluation:
    return LLMEvaluation(
        model="openai/gpt-4",
        findings=[
            LLMFinding(
                category="seo",
                passed=True,
                confidence=0.9,
                evidence="Meta description present",
                recommendation=None,
            )
        ],
        raw_response='{"ok": true}',
        evaluated_at=NOW,
    )


@pytest.fixture
def sample_report(sample_llm_evaluation: LLMEvaluation) -> ScanReport:
    return ScanReport(
        url="https://example.com",
        overall_status=OverallStatus.HEALTHY,
        health_score=95.0,
        rule_results=[
            CheckResult(
                check_name="meta_description",
                severity=Severity.PASS,
                message="Meta description found",
                category="seo",
            ),
            CheckResult(
                check_name="missing_h1",
                severity=Severity.CRITICAL,
                message="No H1 tag",
                evidence="<body> without h1",
                category="accessibility",
            ),
        ],
        llm_evaluation=sample_llm_evaluation,
        summary="Page looks good",
        scanned_at=NOW,
    )


@pytest.fixture
def sample_degraded_report() -> ScanReport:
    return ScanReport(
        url="https://broken.com",
        overall_status=OverallStatus.DEGRADED,
        health_score=45.0,
        rule_results=[
            CheckResult(
                check_name="slow_load",
                severity=Severity.WARNING,
                message="Load time exceeded 3s",
                category="performance",
            ),
        ],
        llm_evaluation=None,
        summary="Some issues",
        scanned_at=NOW,
    )


class TestEnums:
    def test_severity_values(self):
        assert Severity.CRITICAL == "critical"
        assert Severity.WARNING == "warning"
        assert Severity.INFO == "info"
        assert Severity.PASS == "pass"

    def test_overall_status_values(self):
        assert OverallStatus.HEALTHY == "healthy"
        assert OverallStatus.DEGRADED == "degraded"
        assert OverallStatus.BROKEN == "broken"


class TestHappyPath:
    def test_image_info(self):
        img = ImageInfo(src="/a.png", alt="hello")
        assert img.src == "/a.png"
        assert img.alt == "hello"

    def test_image_info_none_alt(self):
        img = ImageInfo(src="/a.png", alt=None)
        assert img.alt is None

    def test_link_info(self):
        link = LinkInfo(href="https://x.com", text="Link")
        assert link.href == "https://x.com"
        assert link.text == "Link"

    def test_form_info(self):
        form = FormInfo(inputs_count=5, has_labels=False)
        assert form.inputs_count == 5
        assert form.has_labels is False

    def test_heading_info(self):
        h = HeadingInfo(level=2, text="Subtitle")
        assert h.level == 2
        assert h.text == "Subtitle"

    def test_preprocessed_page(self, sample_preprocessed: PreprocessedPage):
        p = sample_preprocessed
        assert p.title == "Test Page"
        assert len(p.images) == 1
        assert len(p.links) == 1
        assert len(p.forms) == 1
        assert p.meta_tags == {"description": "test"}
        assert len(p.headings) == 1

    def test_page_snapshot(self, sample_snapshot: PageSnapshot):
        s = sample_snapshot
        assert s.url == "https://example.com"
        assert s.status_code == 200
        assert s.load_time_ms == 150

    def test_check_result(self):
        cr = CheckResult(
            check_name="test", severity=Severity.INFO, message="ok", evidence="data", category="seo"
        )
        assert cr.evidence == "data"

    def test_check_result_default_evidence(self):
        cr = CheckResult(
            check_name="test", severity=Severity.PASS, message="ok", category="seo"
        )
        assert cr.evidence is None

    def test_llm_finding(self):
        f = LLMFinding(category="seo", passed=False, confidence=0.5, evidence="none")
        assert f.recommendation is None

    def test_llm_evaluation(self, sample_llm_evaluation: LLMEvaluation):
        e = sample_llm_evaluation
        assert e.model == "openai/gpt-4"
        assert len(e.findings) == 1

    def test_scan_report(self, sample_report: ScanReport):
        r = sample_report
        assert r.health_score == 95.0
        assert len(r.rule_results) == 2
        assert r.llm_evaluation is not None

    def test_scan_batch(self, sample_report: ScanReport, sample_degraded_report: ScanReport):
        batch = ScanBatch(
            urls=["https://example.com", "https://broken.com"],
            reports=[sample_report, sample_degraded_report],
            generated_at=NOW,
        )
        assert len(batch.urls) == 2
        assert len(batch.reports) == 2

    def test_url_input(self):
        u = URLInput(url="https://example.com", label="Example")
        assert str(u.url).rstrip("/") == "https://example.com"
        assert u.label == "Example"

    def test_url_input_default_label(self):
        u = URLInput(url="https://example.com")
        assert u.label is None


class TestEdgeCases:
    def test_page_snapshot_empty_console_errors(self):
        s = PageSnapshot(
            url="https://example.com",
            html="",
            screenshot=b"",
            text_content="",
            console_errors=[],
            load_time_ms=0,
            status_code=200,
            fetched_at=NOW,
        )
        assert s.console_errors == []

    def test_scan_report_no_llm_evaluation(self):
        r = ScanReport(
            url="https://example.com",
            overall_status=OverallStatus.BROKEN,
            health_score=0.0,
            rule_results=[],
            llm_evaluation=None,
            summary="Down",
            scanned_at=NOW,
        )
        assert r.llm_evaluation is None

    def test_scan_report_with_screenshot_path(self):
        r = ScanReport(
            url="https://example.com",
            overall_status=OverallStatus.HEALTHY,
            health_score=90.0,
            rule_results=[],
            summary="Good",
            scanned_at=NOW,
            screenshot_path="data/screenshots/example.com_20260426_120000.png",
        )
        assert r.screenshot_path is not None

    def test_scan_report_screenshot_path_default_none(self):
        r = ScanReport(
            url="https://example.com",
            overall_status=OverallStatus.HEALTHY,
            health_score=90.0,
            rule_results=[],
            summary="Good",
            scanned_at=NOW,
        )
        assert r.screenshot_path is None

    def test_historical_context_full(self):
        ctx = HistoricalContext(
            previous_findings_summary="1 warning: slow load",
            previous_health_score=85.0,
            previous_scanned_at=NOW,
            screenshot_path="data/screenshots/example.com_20260425_120000.png",
        )
        assert ctx.previous_health_score == 85.0
        assert ctx.screenshot_path is not None

    def test_historical_context_minimal(self):
        ctx = HistoricalContext(
            previous_findings_summary="All checks passed.",
        )
        assert ctx.previous_health_score is None
        assert ctx.previous_scanned_at is None
        assert ctx.screenshot_path is None


class TestErrorPaths:
    def test_invalid_severity_raises(self):
        with pytest.raises(ValidationError):
            CheckResult(
                check_name="test", severity="urgent", message="bad", category="seo"
            )

    def test_invalid_url_raises(self):
        with pytest.raises(ValidationError):
            URLInput(url="not-a-url")

    def test_confidence_out_of_range(self):
        with pytest.raises(ValidationError):
            LLMFinding(
                category="seo", passed=True, confidence=1.5, evidence="test"
            )

    def test_health_score_out_of_range(self):
        with pytest.raises(ValidationError):
            ScanReport(
                url="https://example.com",
                overall_status=OverallStatus.HEALTHY,
                health_score=150.0,
                rule_results=[],
                summary="test",
                scanned_at=NOW,
            )


class TestRoundTrip:
    def test_check_result_round_trip(self):
        cr = CheckResult(
            check_name="meta",
            severity=Severity.WARNING,
            message="missing",
            evidence="<head>",
            category="seo",
        )
        json_str = cr.model_dump_json()
        restored = CheckResult.model_validate_json(json_str)
        assert restored == cr

    def test_scan_report_round_trip(self, sample_report: ScanReport):
        json_str = sample_report.model_dump_json()
        restored = ScanReport.model_validate_json(json_str)
        assert restored == sample_report

    def test_page_snapshot_round_trip(self, sample_snapshot: PageSnapshot):
        json_str = sample_snapshot.model_dump_json()
        restored = PageSnapshot.model_validate_json(json_str)
        assert restored == sample_snapshot

    def test_scan_batch_round_trip(
        self, sample_report: ScanReport, sample_degraded_report: ScanReport
    ):
        batch = ScanBatch(
            urls=["https://a.com", "https://b.com"],
            reports=[sample_report, sample_degraded_report],
            generated_at=NOW,
        )
        json_str = batch.model_dump_json()
        restored = ScanBatch.model_validate_json(json_str)
        assert restored == batch


class TestScanBatchComputed:
    def test_total_critical(self, sample_report: ScanReport, sample_degraded_report: ScanReport):
        batch = ScanBatch(
            urls=["https://a.com", "https://b.com"],
            reports=[sample_report, sample_degraded_report],
            generated_at=NOW,
        )
        assert batch.total_critical == 1

    def test_total_warning(self, sample_report: ScanReport, sample_degraded_report: ScanReport):
        batch = ScanBatch(
            urls=["https://a.com", "https://b.com"],
            reports=[sample_report, sample_degraded_report],
            generated_at=NOW,
        )
        assert batch.total_warning == 1

    def test_total_healthy(self, sample_report: ScanReport, sample_degraded_report: ScanReport):
        batch = ScanBatch(
            urls=["https://a.com", "https://b.com"],
            reports=[sample_report, sample_degraded_report],
            generated_at=NOW,
        )
        assert batch.total_healthy == 1

    def test_computed_empty_batch(self):
        batch = ScanBatch(urls=[], reports=[], generated_at=NOW)
        assert batch.total_critical == 0
        assert batch.total_warning == 0
        assert batch.total_healthy == 0
