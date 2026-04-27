from datetime import datetime
from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field, HttpUrl


class Severity(StrEnum):
    CRITICAL = "critical"
    WARNING = "warning"
    INFO = "info"
    PASS = "pass"


class OverallStatus(StrEnum):
    HEALTHY = "healthy"
    DEGRADED = "degraded"
    BROKEN = "broken"


class ImageInfo(BaseModel):
    model_config = ConfigDict(strict=True)

    src: str
    alt: str | None


class LinkInfo(BaseModel):
    model_config = ConfigDict(strict=True)

    href: str
    text: str


class FormInfo(BaseModel):
    model_config = ConfigDict(strict=True)

    inputs_count: int
    has_labels: bool


class HeadingInfo(BaseModel):
    model_config = ConfigDict(strict=True)

    level: int
    text: str


class PreprocessedPage(BaseModel):
    model_config = ConfigDict(strict=True)

    title: str | None
    text_content: str
    images: list[ImageInfo]
    links: list[LinkInfo]
    forms: list[FormInfo]
    meta_tags: dict[str, str]
    headings: list[HeadingInfo]


class PageSnapshot(BaseModel):
    model_config = ConfigDict(strict=True)

    url: str
    html: str
    screenshot: bytes
    text_content: str
    console_errors: list[str]
    load_time_ms: int
    status_code: int
    fetched_at: datetime


class CheckResult(BaseModel):
    model_config = ConfigDict(strict=True)

    check_name: str
    severity: Severity
    message: str
    evidence: str | None = None
    category: str


class LLMFinding(BaseModel):
    model_config = ConfigDict(strict=True)

    category: str
    passed: bool
    confidence: float = Field(ge=0, le=1)
    evidence: str
    recommendation: str | None = None


class LLMEvaluation(BaseModel):
    model_config = ConfigDict(strict=True)

    model: str
    findings: list[LLMFinding]
    raw_response: str
    evaluated_at: datetime


class HistoricalContext(BaseModel):
    model_config = ConfigDict(strict=True)

    previous_findings_summary: str
    previous_health_score: float | None = None
    previous_scanned_at: datetime | None = None
    screenshot_path: str | None = None


class ScanReport(BaseModel):
    model_config = ConfigDict(strict=True)

    url: str
    overall_status: OverallStatus
    health_score: float = Field(ge=0, le=100)
    rule_results: list[CheckResult]
    llm_evaluation: LLMEvaluation | None = None
    summary: str
    scanned_at: datetime
    screenshot_path: str | None = None


class ScanBatch(BaseModel):
    model_config = ConfigDict(strict=True)

    urls: list[str]
    reports: list[ScanReport]
    generated_at: datetime

    @property
    def total_critical(self) -> int:
        return sum(
            1
            for r in self.reports
            for cr in r.rule_results
            if cr.severity == Severity.CRITICAL
        )

    @property
    def total_warning(self) -> int:
        return sum(
            1
            for r in self.reports
            for cr in r.rule_results
            if cr.severity == Severity.WARNING
        )

    @property
    def total_healthy(self) -> int:
        return sum(1 for r in self.reports if r.overall_status == OverallStatus.HEALTHY)


class URLInput(BaseModel):
    model_config = ConfigDict(strict=True)

    url: HttpUrl
    label: str | None = None
