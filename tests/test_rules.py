from __future__ import annotations

from datetime import datetime

import pytest

from qa_bot.config import Settings
from qa_bot.domain.models import (
    CheckResult,
    FormInfo,
    HeadingInfo,
    ImageInfo,
    LinkInfo,
    PageSnapshot,
    PreprocessedPage,
    Severity,
)
from qa_bot.services.rules import (
    RuleEngine,
    check_broken_images,
    check_console_errors,
    check_empty_links,
    check_form_labels,
    check_h1_present,
    check_http_status,
    check_load_time,
    check_page_size,
    check_title_present,
    check_viewport_meta,
    has_critical_failure,
)

_NOW = datetime(2026, 1, 1, 0, 0, 0)


def _healthy_snapshot(**overrides) -> PageSnapshot:
    defaults = dict(
        url="https://example.com",
        html=(
            "<html><head><meta name='viewport'"
            " content='width=device-width'></head>"
            "<body><h1>Hi</h1></body></html>"
        ),
        screenshot=b"img",
        text_content="Hi",
        console_errors=[],
        load_time_ms=100,
        status_code=200,
        fetched_at=_NOW,
    )
    defaults.update(overrides)
    return PageSnapshot(**defaults)


def _healthy_preprocessed(**overrides) -> PreprocessedPage:
    defaults = dict(
        title="Example",
        text_content="Hi",
        images=[ImageInfo(src="img.png", alt="pic")],
        links=[LinkInfo(href="https://example.com/page", text="link")],
        forms=[FormInfo(inputs_count=1, has_labels=True)],
        meta_tags={"viewport": "width=device-width"},
        headings=[HeadingInfo(level=1, text="Hi")],
    )
    defaults.update(overrides)
    return PreprocessedPage(**defaults)


_SETTINGS = Settings(
    openrouter_api_key="sk-test",
    page_load_timeout=5,
    max_page_size_kb=100,
)


# --- happy path ---


class TestHappyPath:
    def test_all_pass(self):
        snap = _healthy_snapshot()
        prep = _healthy_preprocessed()
        engine = RuleEngine(_SETTINGS)
        results = engine.evaluate(snap, prep)
        assert len(results) == 10
        assert all(r.severity == Severity.PASS for r in results)

    def test_no_critical_on_healthy(self):
        snap = _healthy_snapshot()
        prep = _healthy_preprocessed()
        engine = RuleEngine(_SETTINGS)
        assert not has_critical_failure(engine.evaluate(snap, prep))

    def test_unknown_status_with_captured_content_has_no_critical_failures(self):
        snap = _healthy_snapshot(status_code=0)
        prep = _healthy_preprocessed()
        engine = RuleEngine(_SETTINGS)

        results = engine.evaluate(snap, prep)

        http_result = next(r for r in results if r.check_name == "http_status")
        assert http_result.severity == Severity.WARNING
        assert not has_critical_failure(results)


# --- individual rule tests ---


class TestCheckHttpStatus:
    def test_pass_on_200(self):
        r = check_http_status(_healthy_snapshot(), _healthy_preprocessed(), settings=_SETTINGS)
        assert r.severity == Severity.PASS

    def test_critical_on_404(self):
        r = check_http_status(
            _healthy_snapshot(status_code=404), _healthy_preprocessed(), settings=_SETTINGS
        )
        assert r.severity == Severity.CRITICAL
        assert r.evidence == "404"

    def test_critical_on_500(self):
        r = check_http_status(
            _healthy_snapshot(status_code=500), _healthy_preprocessed(), settings=_SETTINGS
        )
        assert r.severity == Severity.CRITICAL

    def test_pass_on_201(self):
        r = check_http_status(
            _healthy_snapshot(status_code=201), _healthy_preprocessed(), settings=_SETTINGS
        )
        assert r.severity == Severity.PASS

    def test_warning_on_unknown_status_with_captured_content(self):
        r = check_http_status(
            _healthy_snapshot(status_code=0), _healthy_preprocessed(), settings=_SETTINGS
        )
        assert r.severity == Severity.WARNING
        assert r.evidence == "0"

    def test_critical_on_unknown_status_without_content(self):
        r = check_http_status(
            _healthy_snapshot(status_code=0, html=""),
            _healthy_preprocessed(text_content=""),
            settings=_SETTINGS,
        )
        assert r.severity == Severity.CRITICAL

    def test_critical_on_unknown_status_with_empty_document_shell(self):
        r = check_http_status(
            _healthy_snapshot(
                status_code=0,
                html="<html><head></head><body></body></html>",
                text_content="",
            ),
            _healthy_preprocessed(text_content=""),
            settings=_SETTINGS,
        )
        assert r.severity == Severity.CRITICAL


class TestCheckTitlePresent:
    def test_pass_with_title(self):
        r = check_title_present(_healthy_snapshot(), _healthy_preprocessed(), settings=_SETTINGS)
        assert r.severity == Severity.PASS

    def test_critical_missing(self):
        r = check_title_present(
            _healthy_snapshot(), _healthy_preprocessed(title=None), settings=_SETTINGS
        )
        assert r.severity == Severity.CRITICAL

    def test_critical_empty(self):
        r = check_title_present(
            _healthy_snapshot(), _healthy_preprocessed(title=""), settings=_SETTINGS
        )
        assert r.severity == Severity.CRITICAL


class TestCheckH1Present:
    def test_pass(self):
        r = check_h1_present(_healthy_snapshot(), _healthy_preprocessed(), settings=_SETTINGS)
        assert r.severity == Severity.PASS

    def test_warning_no_h1(self):
        r = check_h1_present(
            _healthy_snapshot(), _healthy_preprocessed(headings=[]), settings=_SETTINGS
        )
        assert r.severity == Severity.WARNING

    def test_warning_only_h2(self):
        r = check_h1_present(
            _healthy_snapshot(),
            _healthy_preprocessed(headings=[HeadingInfo(level=2, text="Sub")]),
            settings=_SETTINGS,
        )
        assert r.severity == Severity.WARNING


class TestCheckViewportMeta:
    def test_pass(self):
        r = check_viewport_meta(_healthy_snapshot(), _healthy_preprocessed(), settings=_SETTINGS)
        assert r.severity == Severity.PASS

    def test_warning_missing(self):
        r = check_viewport_meta(
            _healthy_snapshot(), _healthy_preprocessed(meta_tags={}), settings=_SETTINGS
        )
        assert r.severity == Severity.WARNING


class TestCheckLoadTime:
    def test_pass_fast(self):
        r = check_load_time(
            _healthy_snapshot(load_time_ms=100),
            _healthy_preprocessed(),
            settings=_SETTINGS,
        )
        assert r.severity == Severity.PASS

    def test_warning_slow(self):
        r = check_load_time(
            _healthy_snapshot(load_time_ms=6000),
            _healthy_preprocessed(),
            settings=_SETTINGS,
        )
        assert r.severity == Severity.WARNING
        assert "6000ms" in r.evidence

    def test_pass_at_boundary(self):
        r = check_load_time(
            _healthy_snapshot(load_time_ms=5000),
            _healthy_preprocessed(),
            settings=_SETTINGS,
        )
        assert r.severity == Severity.PASS


class TestCheckConsoleErrors:
    def test_pass_no_errors(self):
        r = check_console_errors(_healthy_snapshot(), _healthy_preprocessed(), settings=_SETTINGS)
        assert r.severity == Severity.PASS

    def test_warning_with_errors(self):
        r = check_console_errors(
            _healthy_snapshot(console_errors=["err1", "err2"]),
            _healthy_preprocessed(),
            settings=_SETTINGS,
        )
        assert r.severity == Severity.WARNING
        assert r.evidence == "2"


class TestCheckBrokenImages:
    def test_pass(self):
        r = check_broken_images(_healthy_snapshot(), _healthy_preprocessed(), settings=_SETTINGS)
        assert r.severity == Severity.PASS

    def test_warning_empty_src(self):
        r = check_broken_images(
            _healthy_snapshot(),
            _healthy_preprocessed(
                images=[ImageInfo(src="", alt=""), ImageInfo(src="ok.png", alt="x")]
            ),
            settings=_SETTINGS,
        )
        assert r.severity == Severity.WARNING
        assert r.evidence == "1"


class TestCheckFormLabels:
    def test_pass(self):
        r = check_form_labels(_healthy_snapshot(), _healthy_preprocessed(), settings=_SETTINGS)
        assert r.severity == Severity.PASS

    def test_warning_no_labels(self):
        r = check_form_labels(
            _healthy_snapshot(),
            _healthy_preprocessed(
                forms=[FormInfo(inputs_count=2, has_labels=False)]
            ),
            settings=_SETTINGS,
        )
        assert r.severity == Severity.WARNING
        assert r.evidence == "1"


class TestCheckEmptyLinks:
    def test_pass(self):
        r = check_empty_links(_healthy_snapshot(), _healthy_preprocessed(), settings=_SETTINGS)
        assert r.severity == Severity.PASS

    @pytest.mark.parametrize("href", ["", "/", "#", "javascript:void(0)"])
    def test_info_empty_href(self, href):
        r = check_empty_links(
            _healthy_snapshot(),
            _healthy_preprocessed(links=[LinkInfo(href=href, text="click")]),
            settings=_SETTINGS,
        )
        assert r.severity == Severity.INFO
        assert r.evidence == "1"


class TestCheckPageSize:
    def test_pass_small_page(self):
        r = check_page_size(
            _healthy_snapshot(html="a" * 100),
            _healthy_preprocessed(),
            settings=_SETTINGS,
        )
        assert r.severity == Severity.PASS

    def test_warning_oversized(self):
        size = _SETTINGS.max_page_size_kb * 1024 + 1
        r = check_page_size(
            _healthy_snapshot(html="x" * size),
            _healthy_preprocessed(),
            settings=_SETTINGS,
        )
        assert r.severity == Severity.WARNING
        assert str(size) in r.evidence


# --- has_critical_failure ---


class TestHasCriticalFailure:
    def test_true_with_critical(self):
        results = [
            CheckResult(check_name="a", severity=Severity.PASS, message="ok", category="c"),
            CheckResult(
                check_name="b", severity=Severity.CRITICAL, message="bad", category="c"
            ),
        ]
        assert has_critical_failure(results)

    def test_false_without_critical(self):
        results = [
            CheckResult(check_name="a", severity=Severity.PASS, message="ok", category="c"),
            CheckResult(
                check_name="b", severity=Severity.WARNING, message="meh", category="c"
            ),
        ]
        assert not has_critical_failure(results)

    def test_false_all_pass(self):
        results = [
            CheckResult(check_name="a", severity=Severity.PASS, message="ok", category="c"),
        ]
        assert not has_critical_failure(results)
