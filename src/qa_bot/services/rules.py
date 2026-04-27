from __future__ import annotations

from qa_bot.config import Settings
from qa_bot.domain.models import CheckResult, PageSnapshot, PreprocessedPage, Severity

EMPTY_HREFS = {"", "/", "#", "javascript:void(0)"}


def check_http_status(
    snapshot: PageSnapshot, preprocessed: PreprocessedPage, settings: Settings
) -> CheckResult:
    if 200 <= snapshot.status_code < 300:
        return CheckResult(
            check_name="http_status",
            severity=Severity.PASS,
            message=f"HTTP status {snapshot.status_code}",
            category="accessibility",
        )
    if snapshot.status_code == 0 and preprocessed.text_content.strip():
        return CheckResult(
            check_name="http_status",
            severity=Severity.WARNING,
            message="HTTP status unavailable after page content was captured",
            evidence="0",
            category="accessibility",
        )
    return CheckResult(
        check_name="http_status",
        severity=Severity.CRITICAL,
        message=f"HTTP status {snapshot.status_code} is not 2xx",
        evidence=str(snapshot.status_code),
        category="accessibility",
    )


def check_title_present(
    snapshot: PageSnapshot, preprocessed: PreprocessedPage, settings: Settings
) -> CheckResult:
    if preprocessed.title:
        return CheckResult(
            check_name="title_present",
            severity=Severity.PASS,
            message="Page title is present",
            category="seo",
        )
    return CheckResult(
        check_name="title_present",
        severity=Severity.CRITICAL,
        message="Page title is missing",
        category="seo",
    )


def check_h1_present(
    snapshot: PageSnapshot, preprocessed: PreprocessedPage, settings: Settings
) -> CheckResult:
    has_h1 = any(h.level == 1 for h in preprocessed.headings)
    if has_h1:
        return CheckResult(
            check_name="h1_present",
            severity=Severity.PASS,
            message="H1 heading is present",
            category="seo",
        )
    return CheckResult(
        check_name="h1_present",
        severity=Severity.WARNING,
        message="No H1 heading found",
        category="seo",
    )


def check_viewport_meta(
    snapshot: PageSnapshot, preprocessed: PreprocessedPage, settings: Settings
) -> CheckResult:
    if "viewport" in preprocessed.meta_tags:
        return CheckResult(
            check_name="viewport_meta",
            severity=Severity.PASS,
            message="Viewport meta tag is present",
            category="mobile",
        )
    return CheckResult(
        check_name="viewport_meta",
        severity=Severity.WARNING,
        message="Viewport meta tag is missing",
        category="mobile",
    )


def check_load_time(
    snapshot: PageSnapshot, preprocessed: PreprocessedPage, settings: Settings
) -> CheckResult:
    threshold_ms = settings.page_load_timeout * 1000
    if snapshot.load_time_ms <= threshold_ms:
        return CheckResult(
            check_name="load_time",
            severity=Severity.PASS,
            message=f"Page loaded in {snapshot.load_time_ms}ms",
            category="performance",
        )
    return CheckResult(
        check_name="load_time",
        severity=Severity.WARNING,
        message=f"Page load time {snapshot.load_time_ms}ms exceeds threshold",
        evidence=f"{snapshot.load_time_ms}ms",
        category="performance",
    )


def check_console_errors(
    snapshot: PageSnapshot, preprocessed: PreprocessedPage, settings: Settings
) -> CheckResult:
    count = len(snapshot.console_errors)
    if count == 0:
        return CheckResult(
            check_name="console_errors",
            severity=Severity.PASS,
            message="No console errors",
            category="javascript",
        )
    return CheckResult(
        check_name="console_errors",
        severity=Severity.WARNING,
        message=f"{count} console error(s) detected",
        evidence=str(count),
        category="javascript",
    )


def check_broken_images(
    snapshot: PageSnapshot, preprocessed: PreprocessedPage, settings: Settings
) -> CheckResult:
    broken = [img for img in preprocessed.images if not img.src]
    if not broken:
        return CheckResult(
            check_name="broken_images",
            severity=Severity.PASS,
            message="No broken images detected",
            category="content",
        )
    return CheckResult(
        check_name="broken_images",
        severity=Severity.WARNING,
        message=f"{len(broken)} image(s) with empty/missing src",
        evidence=str(len(broken)),
        category="content",
    )


def check_form_labels(
    snapshot: PageSnapshot, preprocessed: PreprocessedPage, settings: Settings
) -> CheckResult:
    unlabeled = [f for f in preprocessed.forms if not f.has_labels]
    if not unlabeled:
        return CheckResult(
            check_name="form_labels",
            severity=Severity.PASS,
            message="All forms have labels",
            category="accessibility",
        )
    return CheckResult(
        check_name="form_labels",
        severity=Severity.WARNING,
        message=f"{len(unlabeled)} form(s) without labels",
        evidence=str(len(unlabeled)),
        category="accessibility",
    )


def check_empty_links(
    snapshot: PageSnapshot, preprocessed: PreprocessedPage, settings: Settings
) -> CheckResult:
    empty = [lnk for lnk in preprocessed.links if lnk.href in EMPTY_HREFS]
    if not empty:
        return CheckResult(
            check_name="empty_links",
            severity=Severity.PASS,
            message="No empty links detected",
            category="content",
        )
    return CheckResult(
        check_name="empty_links",
        severity=Severity.INFO,
        message=f"{len(empty)} empty link(s) detected",
        evidence=str(len(empty)),
        category="content",
    )


def check_page_size(
    snapshot: PageSnapshot, preprocessed: PreprocessedPage, settings: Settings
) -> CheckResult:
    size = len(snapshot.html)
    limit = settings.max_page_size_kb * 1024
    if size <= limit:
        return CheckResult(
            check_name="page_size",
            severity=Severity.PASS,
            message=f"Page size {size} bytes is within limit",
            category="performance",
        )
    return CheckResult(
        check_name="page_size",
        severity=Severity.WARNING,
        message=f"Page size {size} bytes exceeds {limit} bytes limit",
        evidence=f"{size} bytes",
        category="performance",
    )


ALL_RULES = [
    check_http_status,
    check_title_present,
    check_h1_present,
    check_viewport_meta,
    check_load_time,
    check_console_errors,
    check_broken_images,
    check_form_labels,
    check_empty_links,
    check_page_size,
]


class RuleEngine:
    def __init__(self, settings: Settings):
        self._settings = settings

    def evaluate(
        self, snapshot: PageSnapshot, preprocessed: PreprocessedPage
    ) -> list[CheckResult]:
        results: list[CheckResult] = []
        for rule in ALL_RULES:
            results.append(rule(snapshot, preprocessed, settings=self._settings))
        return results


def has_critical_failure(results: list[CheckResult]) -> bool:
    return any(r.severity == Severity.CRITICAL for r in results)
