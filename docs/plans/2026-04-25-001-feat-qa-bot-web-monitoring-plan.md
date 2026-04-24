---
title: "feat: QA Bot for Web Product Monitoring"
type: feat
status: active
date: 2026-04-25
---

# feat: QA Bot for Web Product Monitoring

## Overview

Build a prototype QA bot that crawls web pages, runs deterministic rule checks and subjective LLM-based evaluations, and produces human-readable reports about page health. The key architectural decision is the boundary between deterministic rules (objective checks) and LLM evaluation (subjective UX quality assessment).

---

## Problem Frame

We have multiple public web products and discover breakages through user complaints. We need an automated tool that proactively visits our pages, evaluates their health (both objectively and subjectively), and produces clear reports. The boundary between what a rule can check vs. what needs an LLM's judgment is the core design challenge.

---

## Requirements Trace

- R1. Accept URL(s) as input (single URL or list)
- R2. Fetch pages using real browser (Playwright) — capture HTML and screenshot
- R3. Preprocess DOM — parse, normalize, strip scripts/noise
- R4. Run deterministic rule checks (HTTP, structure, accessibility, assets)
- R5. Route: if critical rule failures exist, skip LLM; otherwise proceed to LLM evaluation
- R6. Run LLM evaluation via OpenRouter for subjective UX analysis
- R7. Aggregate rule + LLM results with severity assignment
- R8. Output structured JSON report and human-readable summary
- R9. Provide Gradio web UI to trigger scans and view reports
- R10. LLM prompts must be structured to minimize hallucination — specific questions, evidence-based reasoning, structured JSON output

---

## Scope Boundaries

- This is a prototype — single-user, no authentication required
- No historical trend analysis or diffing between scans
- No scheduled/cron execution (manual trigger via UI or CLI)
- No alerting or notification integrations
- Single-page scanning only (no recursive site crawling)

### Deferred to Follow-Up Work

- Database persistence of scan results (sqlalchemy + asyncpg + alembic infrastructure exists in deps)
- Authentication layer (pyjwt + passlib in deps, not needed for prototype)
- Redis caching of fetch results and rate limiting state
- pgvector embeddings for anomaly detection against historical baselines
- Scheduled/recurring scans
- Multi-page recursive crawling
- Alerting integration (email, Slack, etc.)

---

## Context & Research

### Relevant Code and Patterns

- Truly greenfield — no existing source code. All patterns to be established fresh.
- `pyproject.toml` defines all dependency versions. No `[build-system]` section yet.
- JetBrains IDE with Black formatter plugin suggests intent for Black-compatible code style.

### External References

- OpenRouter Python SDK: context-manager based, `chat.send()` / `chat.send_async()`, structured output via `response_format` with JSON schema, no built-in retries
- Playwright Python: async API, `page.goto()`, `page.content()`, `page.screenshot()`, console error capture via `page.on("console", ...)`
- Gradio: `gr.Interface` or `gr.Blocks` for web UI

---

## Key Technical Decisions

1. **Rule vs LLM boundary:** Objective, programmable checks (HTTP status, element presence, asset loading, accessibility basics) live in the rule engine. Subjective assessments (layout quality, content coherence, visual anomalies, placeholder text) go to the LLM. The decision router skips LLM when critical rule failures already prove the page is broken — saving cost and avoiding LLM confusion on clearly broken pages.

2. **LLM anti-hallucination strategy:** Use structured JSON output via OpenRouter's `response_format` with a strict Pydantic-derived schema. Give the LLM the screenshot (base64) + cleaned text + rule results as context. Ask specific yes/no questions per category rather than open-ended "is this page good?". Require evidence citations for each finding.

3. **Project layout:** `src/qa_bot/` layout (recommended for Python packages with many modules). Tests in `tests/` at repo root.

4. **Async-first:** Playwright, httpx, and OpenRouter all support async. Build the pipeline as async throughout for efficiency when scanning multiple URLs.

5. **Severity model:** Three levels — `critical` (page is broken/unusable), `warning` (degraded experience), `info` (minor observation). Critical rule failures gate LLM invocation.

6. **Report format:** Dual output — machine-readable JSON (`ScanReport` model) and human-readable Markdown summary rendered in Gradio.

7. **Configuration via environment:** `.env` file for API keys, model selection, thresholds. `pydantic-settings` `BaseSettings` class.

---

## Open Questions

### Resolved During Planning

- **Database for MVP?** Resolved: defer to follow-up. Prototype produces reports in-memory.
- **Auth for MVP?** Resolved: defer. Single-user prototype.
- **Redis for MVP?** Resolved: defer. No caching needed for single-scan prototype.

### Deferred to Implementation

- Exact Playwright browser launch args for headless operation in various environments
- Specific LLM model selection and cost/quality tradeoff tuning
- Exact threshold values for rule checks (page size, load time, etc.)

---

## Output Structure

```
.
├── src/
│   └── qa_bot/
│       ├── __init__.py
│       ├── main.py              # CLI / Gradio entry point
│       ├── config.py            # pydantic-settings configuration
│       ├── models.py            # Pydantic domain models
│       ├── fetcher.py           # Playwright fetch layer
│       ├── preprocessor.py      # HTML normalization
│       ├── rules.py             # Deterministic rule engine
│       ├── llm_evaluator.py     # OpenRouter LLM evaluation
│       ├── orchestrator.py      # Pipeline orchestrator + decision router
│       ├── reporter.py          # Report generation (JSON + Markdown)
│       └── ui.py                # Gradio web interface
├── tests/
│   ├── __init__.py
│   ├── test_models.py
│   ├── test_preprocessor.py
│   ├── test_rules.py
│   ├── test_llm_evaluator.py
│   ├── test_orchestrator.py
│   └── test_reporter.py
├── .env.example
├── .gitignore
├── pyproject.toml
└── docs/
    └── plans/
        └── 2026-04-25-001-feat-qa-bot-web-monitoring-plan.md
```

---

## High-Level Technical Design

> *This illustrates the intended approach and is directional guidance for review, not implementation specification. The implementing agent should treat it as context, not code to reproduce.*

```
INPUT (URL list)
   |
   v
+--------------+
|  Fetcher     |  Playwright async -> HTML + screenshot + console errors
+------+-------+
       |
       v
+--------------+
| Preprocessor |  BS4/lxml -> strip scripts/styles/nav noise,
|              |  extract text content, structure summary
+------+-------+
       |
       v
+--------------+
|  Rule Engine |  Deterministic checks -> CheckResult[] with severity
|              |  HTTP status, element presence, assets, accessibility
+------+-------+
       |
       v
+--------------+     critical failures?
|   Decision   |---- YES --> skip LLM, aggregate with rule results only
|   Router     |
|              |---- NO  --> proceed to LLM
+------+-------+
       |
       v
+--------------+
| LLM Evaluator|  OpenRouter -> screenshot + text + rule context
|              |  Structured JSON output with evidence citations
+------+-------+
       |
       v
+--------------+
|  Aggregator  |  Merge rule + LLM results, assign overall severity
|              |  Deduplicate findings, compute page health score
+------+-------+
       |
       v
OUTPUT: ScanReport (JSON) + Markdown summary (Gradio display)
```

**LLM prompt design pattern:**
- System prompt: "You are a QA analyst. Evaluate this web page based on the screenshot and text content. For each category, answer yes/no and cite specific evidence."
- User prompt: structured blocks — page URL, rule results summary, cleaned text excerpt, [screenshot as base64 image]
- Categories: layout_quality, content_coherence, visual_anomalies, placeholder_detection, navigation_logic
- Output: strict JSON schema via `response_format` with Pydantic model

---

## Implementation Units

- U1. **Project Scaffolding & Configuration**

**Goal:** Establish project structure, configuration, and tooling foundation.

**Requirements:** R1

**Dependencies:** None

**Files:**
- Create: `.gitignore`
- Create: `src/qa_bot/__init__.py`
- Create: `src/qa_bot/config.py`
- Create: `.env.example`
- Modify: `pyproject.toml` (add `[build-system]`, add dev dependencies: pytest, pytest-asyncio, ruff)

**Approach:**
- Add `[build-system]` with hatchling to `pyproject.toml`
- Add pytest, pytest-asyncio, ruff as dev dependencies
- Create `.gitignore` excluding `.venv/`, `__pycache__/`, `.env`, `.idea/`, `*.pyc`
- Create `config.py` with pydantic-settings `BaseSettings`: `OPENROUTER_API_KEY`, `LLM_MODEL` (default: `openai/gpt-4`), `PAGE_LOAD_TIMEOUT` (default: 30s), `MAX_PAGE_SIZE_KB` (default: 5000), `RATE_LIMIT_RPM` (default: 10)
- Create `.env.example` with all config vars documented

**Patterns to follow:**
- pydantic-settings `BaseSettings` pattern for env-based configuration

**Test scenarios:**
- Happy path: config loads from env vars with valid values
- Edge case: missing optional vars use defaults
- Error path: missing required `OPENROUTER_API_KEY` raises validation error

**Verification:**
- `uv run python -c "from qa_bot.config import Settings; print(Settings())"` loads without error
- `.gitignore` covers all common Python artifacts

---

- U2. **Core Domain Models**

**Goal:** Define all Pydantic models for the pipeline data flow.

**Requirements:** R4, R7, R8

**Dependencies:** U1

**Files:**
- Create: `src/qa_bot/models.py`
- Create: `tests/test_models.py`

**Approach:**
- `URLInput`: url (HttpUrl), label (optional str)
- `PageSnapshot`: url, html (str), screenshot (bytes), text_content (str), console_errors (list[str]), load_time_ms (int), status_code (int), fetched_at (datetime)
- `CheckResult`: check_name (str), severity (Critical|Warning|Info|Pass), message (str), evidence (str | None), category (str)
- `LLMFinding`: category (str), passed (bool), confidence (float 0-1), evidence (str), recommendation (str | None)
- `LLMEvaluation`: model (str), findings (list[LLMFinding]), raw_response (str), evaluated_at (datetime)
- `ScanReport`: url, overall_status (Healthy|Degraded|Broken), health_score (float 0-100), rule_results (list[CheckResult]), llm_evaluation (LLMEvaluation | None), summary (str), scanned_at (datetime)
- `ScanBatch`: urls (list[str]), reports (list[ScanReport]), total_critical (int), total_warning (int), total_healthy (int), generated_at (datetime)
- All models use Pydantic v2 with `model_config = ConfigDict(strict=True)`

**Patterns to follow:**
- Pydantic v2 patterns: `BaseModel`, `ConfigDict`, enum classes with `StrEnum`

**Test scenarios:**
- Happy path: all models instantiate with valid data
- Edge case: `PageSnapshot` with empty console_errors list
- Edge case: `ScanReport` with `llm_evaluation=None` (rule-only scan)
- Error path: invalid severity value raises `ValidationError`
- Error path: invalid URL in `URLInput` raises `ValidationError`

**Verification:**
- All models instantiate without error
- Round-trip serialization: `model.model_dump_json()` -> `Model.model_validate_json()` preserves data

---

- U3. **Fetch Layer (Playwright)**

**Goal:** Fetch web pages using Playwright to capture HTML, screenshots, console errors, and timing.

**Requirements:** R2

**Dependencies:** U2

**Files:**
- Create: `src/qa_bot/fetcher.py`
- Create: `tests/test_fetcher.py`

**Approach:**
- `PageFetcher` class with async context manager pattern
- `async fetch(url: str) -> PageSnapshot` — navigates to URL, waits for network idle, captures HTML content, full-page screenshot (PNG bytes), console errors, load timing
- Uses `async with async_playwright() as p:` for browser lifecycle
- Headless Chromium with sensible defaults
- Wrap navigation in `tenacity` retry (3 attempts, exponential backoff) for transient network errors
- Screenshot as PNG bytes (for LLM vision input)
- Capture console errors via `page.on("console", handler)` filtering for `error` level
- Return `PageSnapshot` model

**Execution note:** Test with mock Playwright page; integration test against a real HTTP test server.

**Patterns to follow:**
- Async context manager for resource cleanup
- tenacity retry decorator on the network call

**Test scenarios:**
- Happy path: fetch returns PageSnapshot with html, screenshot, status 200
- Happy path: console errors captured from JS execution
- Edge case: page with slow assets triggers timeout -> retry or graceful failure
- Error path: DNS failure returns PageSnapshot with error status
- Error path: HTTP 500 captured in status_code field
- Integration: full fetch against local test HTTP server returns valid snapshot

**Verification:**
- `fetch("https://example.com")` returns a valid `PageSnapshot` with non-empty html and screenshot

---

- U4. **Preprocessing Pipeline**

**Goal:** Parse and normalize HTML to extract clean text and structural summary for rules and LLM.

**Requirements:** R3

**Dependencies:** U2

**Files:**
- Create: `src/qa_bot/preprocessor.py`
- Create: `tests/test_preprocessor.py`

**Approach:**
- `preprocess(html: str) -> PreprocessedPage` function
- Parse with BeautifulSoup using lxml backend
- Remove: `<script>`, `<style>`, `<nav>`, `<footer>`, `<header>`, `<iframe>`, comments
- Extract: visible text content (cleaned), list of images (src + alt), list of links (href + text), list of forms, meta tags, heading structure (h1-h6)
- `PreprocessedPage` model: text_content, images, links, forms, meta_tags, headings, title
- Text normalization: collapse whitespace, remove empty lines

**Patterns to follow:**
- Pure function — no side effects, easy to test
- BS4 + lxml for performance

**Test scenarios:**
- Happy path: well-formed HTML produces clean text, extracted images/links/headings
- Edge case: empty HTML returns empty PreprocessedPage
- Edge case: HTML with only scripts/styles returns minimal text
- Edge case: malformed HTML is handled gracefully by lxml's parser
- Happy path: unicode/international characters preserved in text content

**Verification:**
- Known HTML input produces expected text and structural extraction

---

- U5. **Rule Engine (Deterministic Checks)**

**Goal:** Run all deterministic page health checks and produce structured results.

**Requirements:** R4

**Dependencies:** U2, U4

**Files:**
- Create: `src/qa_bot/rules.py`
- Create: `tests/test_rules.py`

**Approach:**
- `RuleEngine` class with `evaluate(snapshot: PageSnapshot, preprocessed: PreprocessedPage) -> list[CheckResult]`
- Individual rule functions, each returning a `CheckResult`:
  - `check_http_status`: non-2xx -> critical
  - `check_title_present`: missing `<title>` -> critical
  - `check_h1_present`: missing `<h1>` -> warning
  - `check_viewport_meta`: missing viewport meta -> warning
  - `check_load_time`: exceeds threshold -> warning
  - `check_console_errors`: JS errors present -> warning (count in evidence)
  - `check_broken_images`: img with missing/empty src -> warning
  - `check_form_labels`: form inputs without associated labels -> warning
  - `check_empty_links`: links with empty/placeholder href -> info
  - `check_page_size`: exceeds threshold -> warning
- Each rule is a pure function: `(snapshot, preprocessed) -> CheckResult`
- `has_critical_failure(results)` helper for the decision router

**Patterns to follow:**
- Strategy pattern — each rule is an independent, testable function
- Rules are stateless and composable

**Test scenarios:**
- Happy path: healthy page returns all Pass results
- Each rule individually: trigger condition produces expected severity
  - HTTP 404 -> critical
  - Missing title -> critical
  - Missing h1 -> warning
  - Missing viewport -> warning
  - Slow load -> warning
  - Console errors -> warning with error count in evidence
  - Missing image src -> warning
  - Unlabeled form input -> warning
  - Empty link -> info
  - Oversized page -> warning
- Edge case: page with all issues produces multiple non-Pass results
- Edge case: empty page snapshot handled gracefully

**Verification:**
- `has_critical_failure` returns `True` when any critical result exists
- Each rule function is independently testable

---

- U6. **LLM Evaluator (OpenRouter)**

**Goal:** Evaluate pages subjectively using OpenRouter LLM with structured output and anti-hallucination safeguards.

**Requirements:** R6, R10

**Dependencies:** U2

**Files:**
- Create: `src/qa_bot/llm_evaluator.py`
- Create: `tests/test_llm_evaluator.py`

**Approach:**
- `LLMEvaluator` class with async `evaluate(snapshot: PageSnapshot, preprocessed: PreprocessedPage, rule_results: list[CheckResult]) -> LLMEvaluation`
- Build prompt with:
  - System prompt defining QA analyst role with specific evaluation categories
  - User message with: page URL, rule results summary, cleaned text (truncated to ~4000 chars), screenshot as base64 image
- Use OpenRouter's `response_format` with strict JSON schema derived from Pydantic `LLMFinding` model
- Evaluation categories (each a yes/no finding with evidence):
  - `layout_quality`: Does the page layout look professional and correct?
  - `content_coherence`: Is the text content coherent and well-structured?
  - `visual_anomalies`: Are there any visual anomalies (overlapping, broken layout)?
  - `placeholder_detection`: Is there any placeholder or lorem ipsum text?
  - `navigation_logic`: Does the navigation structure make sense?
- Wrap call in tenacity retry (3 attempts, exponential backoff, retry on 429/5xx)
- Truncate text content to avoid exceeding model context window
- Use config for model selection and rate limiting

**Execution note:** Mock OpenRouter client in unit tests; integration test with real API requires `OPENROUTER_API_KEY`.

**Patterns to follow:**
- Async context manager for OpenRouter client
- Pydantic model -> JSON schema for `response_format`
- tenacity retry on the API call

**Test scenarios:**
- Happy path: mock LLM returns valid structured response -> LLMEvaluation parsed correctly
- Edge case: text content truncated to fit context window
- Error path: LLM returns malformed JSON -> retry, then graceful failure with error in LLMEvaluation
- Error path: API rate limit (429) -> retry with backoff
- Error path: API timeout -> retry, then graceful failure
- Integration: real API call returns valid evaluation (requires API key, marked slow)

**Verification:**
- Mock test confirms prompt construction includes all required elements (text, screenshot, rule context)
- Structured output schema validates against Pydantic model

---

- U7. **Pipeline Orchestrator**

**Goal:** Wire all pipeline stages together — fetch -> preprocess -> rules -> decision router -> (optional) LLM -> aggregate -> report.

**Requirements:** R5, R7

**Dependencies:** U3, U4, U5, U6

**Files:**
- Create: `src/qa_bot/orchestrator.py`
- Create: `tests/test_orchestrator.py`

**Approach:**
- `QABot` class as the main orchestrator with async `scan_url(url: str) -> ScanReport` and `scan_urls(urls: list[str]) -> ScanBatch`
- Pipeline steps:
  1. Fetch page -> `PageSnapshot`
  2. Preprocess -> `PreprocessedPage`
  3. Run rules -> `list[CheckResult]`
  4. Decision router: check `has_critical_failure(rule_results)`
     - If yes: skip LLM, set `llm_evaluation = None`
     - If no: run LLM evaluation -> `LLMEvaluation`
  5. Aggregate: merge results, compute health score
     - Health score: start at 100, subtract per severity (critical: -30, warning: -10, info: -2)
     - Overall status: score >= 80 -> Healthy, >= 50 -> Degraded, < 50 -> Broken
  6. Generate human-readable summary (Markdown string)
  7. Return `ScanReport`
- `scan_urls` runs URLs concurrently with asyncio semaphore (limit from config)

**Patterns to follow:**
- Async pipeline with clear stage boundaries
- Semaphore-based concurrency control

**Test scenarios:**
- Happy path: full pipeline with passing rules + LLM returns Healthy ScanReport
- Decision router: critical rule failure skips LLM -> Broken report with `llm_evaluation=None`
- Decision router: all rules pass -> LLM is called
- Aggregation: correct health score computation from mixed severities
- Aggregation: status thresholds (80, 50) produce correct labels
- Edge case: empty URL list returns empty ScanBatch
- Integration: end-to-end scan of a test server (with mocked LLM)

**Verification:**
- `scan_url("https://example.com")` returns a complete `ScanReport` with all fields populated
- `scan_urls` handles multiple URLs concurrently

---

- U8. **Gradio Web Interface**

**Goal:** Provide a web UI for entering URLs, triggering scans, and viewing reports.

**Requirements:** R9

**Dependencies:** U7

**Files:**
- Create: `src/qa_bot/ui.py`
- Create: `src/qa_bot/main.py`

**Approach:**
- Gradio `Blocks` interface with:
  - Text input (or textbox) for URL entry (one per line)
  - "Run Scan" button
  - Output area: Markdown-rendered report summary + expandable JSON view
  - Progress indicator during scan
- `main.py` entry point: parse env config, create `QABot` instance, launch Gradio
- Report display: color-coded status badge, per-check expandable details, screenshot thumbnail
- Async scan execution via `QABot.scan_urls`

**Patterns to follow:**
- Gradio Blocks for composed UI
- Async function handling in Gradio

**Test scenarios:**
- Happy path: UI renders with URL input and scan button
- Happy path: scan button triggers pipeline and displays report
- Edge case: empty URL input shows validation message
- Edge case: invalid URL format shows error message

**Verification:**
- `uv run python -m qa_bot.main` launches Gradio server accessible at localhost
- Scanning a real URL produces visible report in the UI

---

## System-Wide Impact

- **Interaction graph:** Gradio UI -> Orchestrator -> Fetcher -> Preprocessor -> Rules -> (conditional) LLM -> Reporter. Linear pipeline with one conditional branch.
- **Error propagation:** Each stage catches and wraps errors in its output model. Fetcher failures produce a minimal `PageSnapshot` with error info. LLM failures produce `LLMEvaluation` with error status. The orchestrator never crashes — it always produces a `ScanReport`.
- **State lifecycle risks:** No persistent state in prototype. Each scan is independent.
- **API surface parity:** Both CLI and Gradio entry points call the same `QABot.scan_urls` method.
- **Integration coverage:** End-to-end test with real HTTP server and mocked LLM validates the full pipeline.

---

## Risks & Dependencies

| Risk | Mitigation |
|------|------------|
| LLM hallucination on page evaluation | Structured output with strict JSON schema; specific yes/no questions per category; require evidence citations; use rule results as grounding context |
| OpenRouter API cost for screenshots | Only send screenshot when rules pass (decision router gates LLM call); truncate text; configurable model selection |
| Playwright browser compatibility in CI/HEADLESS | Use standard headless Chromium; CI requires `playwright install --with-deps chromium` |
| Large pages overwhelming LLM context | Truncate text content to ~4000 chars; screenshot resolution capped at 1280px width |
| Rate limiting on bulk URL scanning | asyncio semaphore limits concurrency; pyrate-limiter for OpenRouter calls |

---

## Sources & References

- **OpenRouter Python SDK:** context-manager pattern, `chat.send_async()`, structured `response_format`
- **Playwright Python API:** `async_playwright()`, `page.goto()`, `page.screenshot()`, console event capture
- **Gradio:** `gr.Blocks` for composed async interfaces
- **Pydantic v2:** `BaseModel`, `ConfigDict(strict=True)`, `model_json_schema()` for LLM schema generation
