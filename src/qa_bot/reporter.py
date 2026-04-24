from __future__ import annotations

from qa_bot.models import (
    OverallStatus,
    ScanBatch,
    ScanReport,
    Severity,
)

_STATUS_BADGE = {
    OverallStatus.HEALTHY: "🟢 Healthy",
    OverallStatus.DEGRADED: "🟡 Degraded",
    OverallStatus.BROKEN: "🔴 Broken",
}

_SEVERITY_ICON = {
    Severity.CRITICAL: "🔴",
    Severity.WARNING: "🟡",
    Severity.INFO: "🔵",
    Severity.PASS: "✅",
}


def generate_summary(
    url: str,
    overall_status: OverallStatus,
    health_score: float,
    rule_results: list,
    llm_evaluation: object = None,
) -> str:
    criticals = [r for r in rule_results if r.severity == Severity.CRITICAL]
    warnings = [r for r in rule_results if r.severity == Severity.WARNING]
    infos = [r for r in rule_results if r.severity == Severity.INFO]

    counts = []
    if criticals:
        counts.append(f"{len(criticals)} critical")
    if warnings:
        counts.append(f"{len(warnings)} warning")
    if infos:
        counts.append(f"{len(infos)} info")

    issue_str = ", ".join(counts) if counts else "no issues"

    status_label = _STATUS_BADGE[overall_status].split()[1]
    parts = [
        f"Page {url} is {status_label} "
        f"(score: {health_score:.0f}) with {issue_str}.",
    ]

    top_critical = [c.message for c in criticals[:2]]
    top_warning = [w.message for w in warnings[:2]]
    top = top_critical + top_warning
    if top:
        parts.append(f"Top issues: {'; '.join(top)}.")
    else:
        parts.append("All checks passed.")

    return " ".join(parts)


def format_report_markdown(report: ScanReport) -> str:
    badge = _STATUS_BADGE[report.overall_status]
    lines = [
        f"# QA Report: {report.url}",
        f"**Status:** {badge}  ",
        f"**Health Score:** {report.health_score:.0f}/100  ",
        f"**Scanned at:** {report.scanned_at:%Y-%m-%d %H:%M:%S}  ",
        "",
    ]

    lines.append("## Rule Check Results")
    lines.append("")
    lines.append("| Check | Severity | Message |")
    lines.append("|-------|----------|---------|")
    for r in report.rule_results:
        icon = _SEVERITY_ICON.get(r.severity, "")
        lines.append(f"| {r.check_name} | {icon} {r.severity} | {r.message} |")
    lines.append("")

    if report.llm_evaluation is not None:
        lines.append("## LLM Evaluation")
        lines.append("")
        lines.append(f"**Model:** {report.llm_evaluation.model}  ")
        lines.append(f"**Evaluated at:** {report.llm_evaluation.evaluated_at:%Y-%m-%d %H:%M:%S}  ")
        lines.append("")
        for f in report.llm_evaluation.findings:
            status = "✅ Passed" if f.passed else "❌ Failed"
            lines.append(f"### {f.category} — {status}")
            lines.append(f"- **Confidence:** {f.confidence:.0%}")
            lines.append(f"- **Evidence:** {f.evidence}")
            if f.recommendation:
                lines.append(f"- **Recommendation:** {f.recommendation}")
            lines.append("")
    else:
        lines.append("## LLM Evaluation")
        lines.append("")
        lines.append("*Skipped due to critical rule failures.*")
        lines.append("")

    lines.append("## Summary")
    lines.append("")
    lines.append(report.summary)
    lines.append("")

    return "\n".join(lines)


def format_batch_summary(batch: ScanBatch) -> str:
    healthy = sum(1 for r in batch.reports if r.overall_status == OverallStatus.HEALTHY)
    degraded = sum(1 for r in batch.reports if r.overall_status == OverallStatus.DEGRADED)
    broken = sum(1 for r in batch.reports if r.overall_status == OverallStatus.BROKEN)

    lines = [
        "# QA Batch Summary",
        "",
        f"**Total URLs scanned:** {len(batch.urls)}  ",
        f"**Healthy:** 🟢 {healthy}  ",
        f"**Degraded:** 🟡 {degraded}  ",
        f"**Broken:** 🔴 {broken}  ",
        "",
        "## Results",
        "",
        "| URL | Status | Score |",
        "|-----|--------|-------|",
    ]

    for report in batch.reports:
        badge = _STATUS_BADGE[report.overall_status]
        lines.append(f"| {report.url} | {badge} | {report.health_score:.0f} |")
    lines.append("")

    if batch.reports:
        lines.append("## Detailed Reports")
        lines.append("")
        for i, report in enumerate(batch.reports, 1):
            badge = _STATUS_BADGE[report.overall_status]
            lines.append(
                f"{i}. [{report.url}]({report.url}) "
                f"— {badge} ({report.health_score:.0f})"
            )
        lines.append("")

    return "\n".join(lines)
