from __future__ import annotations

import contextlib
from typing import TYPE_CHECKING
from urllib.parse import urlparse

import gradio as gr

from qa_bot.orchestrator import QABot
from qa_bot.reporter import format_batch_summary, format_report_markdown

if TYPE_CHECKING:
    pass


_STATUS_BADGE: dict[str | None, str] = {
    "healthy": "🟢 Healthy",
    "degraded": "🟡 Degraded",
    "broken": "🔴 Broken",
    None: "⬜ Not scanned",
}


def _parse_urls(text: str) -> list[str]:
    urls = [line.strip() for line in text.strip().splitlines() if line.strip()]
    valid = []
    for u in urls:
        parsed = urlparse(u)
        if parsed.scheme in ("http", "https") and parsed.netloc:
            valid.append(u)
    return valid


def _validate_single_url(text: str) -> str | None:
    parsed = urlparse(text.strip())
    if parsed.scheme in ("http", "https") and parsed.netloc:
        return text.strip()
    return None


def _format_score(score: float | None) -> str:
    if score is None:
        return "—"
    return f"{score:.0f}"


def _build_sites_markdown(sites: list[dict]) -> str:
    if not sites:
        return "### No sites tracked yet\n\nAdd a site URL to start monitoring."

    lines: list[str] = []
    for site in sites:
        domain = site["domain"]
        label = site.get("label")
        header = f"**{domain}**" + (f" ({label})" if label else "")
        lines.append(f"#### {header}\n")

        pages = site.get("pages", [])
        if not pages:
            lines.append("_No pages tracked._\n")
            continue

        lines.append("| Path | Status | Score | Scans | Last Scan |")
        lines.append("|------|--------|-------|-------|-----------|")
        for p in pages:
            status_badge = _STATUS_BADGE.get(p.get("latest_status"), "⬜ Unknown")
            score = _format_score(p.get("latest_score"))
            scan_count = p.get("scan_count", 0)
            scanned_at = (
                p["latest_scanned_at"].strftime("%Y-%m-%d %H:%M")
                if p.get("latest_scanned_at")
                else "—"
            )
            path = p.get("path") or p.get("url", "—")
            lines.append(f"| {path} | {status_badge} | {score} | {scan_count} | {scanned_at} |")

        lines.append("")

    return "\n".join(lines)


def _build_page_detail_markdown(page_data: dict | None) -> str:
    if page_data is None:
        return "### Select a page to view details"

    lines = [
        f"### {page_data['url']}",
        f"**Domain:** {page_data.get('site_domain', '—')}",
        f"**Scans:** {page_data.get('scan_count', 0)}",
        "",
    ]

    latest = page_data.get("latest_scan")
    if latest is None:
        lines.append("_No scans yet._")
        return "\n".join(lines)

    lines.append("#### Latest Scan")
    status_val = latest["overall_status"]
    lines.append(f"- **Status:** {_STATUS_BADGE.get(status_val, status_val)}")
    lines.append(f"- **Score:** {latest['health_score']:.0f}")
    lines.append(f"- **Model:** {latest.get('model_used', '—')}")
    lines.append(f"- **Scanned at:** {latest['scanned_at'].strftime('%Y-%m-%d %H:%M:%S')}")
    lines.append("")
    lines.append("##### Rule Results")

    rule_results = latest.get("rule_results", [])
    if rule_results:
        lines.append("| Check | Severity | Message |")
        lines.append("|-------|----------|---------|")
        for r in rule_results:
            sev = r.get("severity", "pass")
            if sev == "pass":
                sev_display = "✅ Pass"
            elif sev == "critical":
                sev_display = "🔴 Critical"
            elif sev == "warning":
                sev_display = "🟡 Warning"
            else:
                sev_display = "i Info"
            name = r.get("check_name", "—")
            msg = r.get("message", "—")
            lines.append(f"| {name} | {sev_display} | {msg} |")
    else:
        lines.append("_No rule results._")
    lines.append("")

    llm_eval = latest.get("llm_evaluation")
    if llm_eval:
        lines.append("##### LLM Evaluation")
        findings = llm_eval.get("findings", [])
        if findings:
            lines.append("| Category | Passed | Confidence | Evidence |")
            lines.append("|----------|--------|------------|----------|")
            for f in findings:
                passed = "✅ Yes" if f.get("passed") else "❌ No"
                conf = f"{f.get('confidence', 0):.0%}"
                evidence = f.get("evidence", "—")
                lines.append(f"| {f.get('category', '—')} | {passed} | {conf} | {evidence} |")
        else:
            lines.append("_No findings._")
        lines.append("")

    lines.append(f"**Summary:** {latest.get('summary', '—')}")
    return "\n".join(lines)


def _build_history_markdown(history: list[dict]) -> str:
    if not history:
        return "_No scan history._"

    lines = ["| Date | Status | Score | Model |", "|------|--------|-------|-------|"]
    for h in history:
        status_badge = _STATUS_BADGE.get(h.get("overall_status"), h.get("overall_status", "—"))
        score = _format_score(h.get("health_score"))
        model = h.get("model_used", "—")
        date = h["scanned_at"].strftime("%Y-%m-%d %H:%M:%S") if h.get("scanned_at") else "—"
        lines.append(f"| {date} | {status_badge} | {score} | {model} |")
    return "\n".join(lines)


async def _scan(bot: QABot, text: str):
    urls = _parse_urls(text)
    if not urls:
        msg = "No valid URLs provided. Enter one URL per line (must start with http:// or https://)."
        return msg, []

    batch = await bot.scan_urls(urls)
    summary_md = format_batch_summary(batch)
    tabs = [(report.url, format_report_markdown(report)) for report in batch.reports]
    return summary_md, tabs


async def _load_sites(bot: QABot) -> str:
    if bot._database is None:
        return "### Database not configured"
    sites = await bot._database.get_sites()
    return _build_sites_markdown(sites)


async def _add_and_scan_site(bot: QABot, url: str) -> str:
    valid_url = _validate_single_url(url)
    if not valid_url:
        return "❌ Invalid URL. Must start with http:// or https://"

    with contextlib.suppress(Exception):
        await bot.scan_url(valid_url)

    sites = await bot._database.get_sites() if bot._database else []
    return _build_sites_markdown(sites)


async def _refresh_sites(bot: QABot) -> str:
    return await _load_sites(bot)


async def _load_page_detail(bot: QABot, page_id_str: str) -> tuple[str, str]:
    if not page_id_str or not page_id_str.strip():
        return "### Select a page to view details", ""

    try:
        page_id = int(page_id_str.strip().split(":")[0].strip())
    except (ValueError, IndexError):
        return "### Invalid page ID", ""

    if bot._database is None:
        return "### Database not configured", ""

    page_data = await bot._database.get_page_with_latest_scan(page_id)
    detail_md = _build_page_detail_markdown(page_data)

    history = []
    if page_data:
        history = await bot._database.get_scan_history(page_id, limit=20)
    history_md = _build_history_markdown(history)

    return detail_md, history_md


def create_app(bot: QABot) -> gr.Blocks:
    with gr.Blocks(title="QA Bot") as app:
        gr.Markdown("# QA Bot - Web Page Health Monitor")

        with gr.Tabs() as _main_tabs:
            with gr.Tab("Scan"):
                url_input = gr.Textbox(
                    label="URLs to scan",
                    lines=5,
                    placeholder="Enter URLs, one per line\nhttps://example.com\nhttps://another-site.com",
                )
                run_btn = gr.Button("Run Scan", variant="primary")
                summary_output = gr.Markdown(label="Batch Summary")
                with gr.Tabs(visible=False) as report_tabs:
                    pass

                dynamic_tabs: list[gr.Tab] = []

                async def run_scan(text: str):
                    summary_md, tabs = await _scan(bot, text)
                    if not tabs:
                        return gr.update(value=summary_md), gr.update(visible=False)

                    report_tabs.visible = True
                    for t in dynamic_tabs:
                        t.visible = False
                    dynamic_tabs.clear()

                    for label, content in tabs:
                        with report_tabs:
                            tab = gr.Tab(label=label, visible=True)
                            with tab:
                                gr.Markdown(value=content)
                            dynamic_tabs.append(tab)

                    return gr.update(value=summary_md), gr.update(visible=True)

                run_btn.click(fn=run_scan, inputs=url_input, outputs=[summary_output, report_tabs])

            with gr.Tab("Sites"):
                with gr.Row():
                    add_url_input = gr.Textbox(
                        label="Add Site URL",
                        placeholder="https://example.com",
                        scale=4,
                    )
                    add_btn = gr.Button("Add & Scan", variant="primary", scale=1)

                sites_output = gr.Markdown(value="Loading sites...")

                with gr.Accordion("Page Detail", open=False):
                    page_selector = gr.Dropdown(
                        label="Select page",
                        choices=[],
                        interactive=True,
                    )
                    page_detail_output = gr.Markdown()

                    with gr.Accordion("Scan History", open=False):
                        history_output = gr.Markdown()

                refresh_btn = gr.Button("🔄 Refresh Sites")

                async def on_add_site(url: str):
                    return await _add_and_scan_site(bot, url)

                async def on_refresh():
                    return await _refresh_sites(bot)

                async def on_page_select(page_id_str: str):
                    detail, history = await _load_page_detail(bot, page_id_str)
                    return detail, history

                async def on_refresh_with_choices():
                    sites_md = await _load_sites(bot)
                    choices = await _get_page_choices(bot)
                    return sites_md, gr.update(choices=choices)

                async def on_add_with_choices(url: str):
                    sites_md = await _add_and_scan_site(bot, url)
                    choices = await _get_page_choices(bot)
                    return sites_md, gr.update(choices=choices)

                async def _get_page_choices(bot_obj):
                    if bot_obj._database is None:
                        return []
                    sites = await bot_obj._database.get_sites()
                    choices = []
                    for site in sites:
                        for page in site.get("pages", []):
                            label = f"{site['domain']}{page.get('path', '/')}"
                            choices.append(f"{page['id']}: {label}")
                    return choices

                add_btn.click(
                    fn=on_add_with_choices,
                    inputs=add_url_input,
                    outputs=[sites_output, page_selector],
                )
                refresh_btn.click(
                    fn=on_refresh_with_choices,
                    outputs=[sites_output, page_selector],
                )
                page_selector.change(
                    fn=on_page_select,
                    inputs=page_selector,
                    outputs=[page_detail_output, history_output],
                )

                app.load(fn=on_refresh, outputs=sites_output)

    return app
