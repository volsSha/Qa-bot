from __future__ import annotations

from urllib.parse import urlparse

import gradio as gr

from qa_bot.orchestrator import QABot
from qa_bot.reporter import format_batch_summary, format_report_markdown


def _parse_urls(text: str) -> list[str]:
    urls = [line.strip() for line in text.strip().splitlines() if line.strip()]
    valid = []
    for u in urls:
        parsed = urlparse(u)
        if parsed.scheme in ("http", "https") and parsed.netloc:
            valid.append(u)
    return valid


async def _scan(bot: QABot, text: str):
    urls = _parse_urls(text)
    if not urls:
        msg = "No valid URLs provided. Enter one URL per line (must start with http:// or https://)."
        return msg, []

    batch = await bot.scan_urls(urls)
    summary_md = format_batch_summary(batch)
    tabs = [(report.url, format_report_markdown(report)) for report in batch.reports]
    return summary_md, tabs


def create_app(bot: QABot) -> gr.Blocks:
    with gr.Blocks(title="QA Bot") as app:
        gr.Markdown("# QA Bot - Web Page Health Monitor")
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

    return app
