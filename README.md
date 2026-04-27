# QA Bot

Automated web page quality assurance tool with rule-based checks and LLM-powered evaluation.

QA Bot scans web pages using a headless browser, runs 10 built-in quality rules across 6 categories, then sends screenshots and extracted content to an LLM for visual and semantic analysis. The result is a health score (0–100) with a clear status: **Healthy**, **Degraded**, or **Broken**.

[Українська ↓](#українська)

## Features

- **Rule-based checks** — HTTP status, page title, H1 heading, viewport meta, load time, console errors, broken images, form labels, empty links, page size across categories: accessibility, SEO, mobile, performance, content, JavaScript
- **LLM-powered evaluation** — Uses OpenRouter API to evaluate layout quality, content coherence, visual anomalies, placeholder detection, and navigation logic via screenshot analysis
- **Health scoring** — 0–100 score with three statuses (Healthy / Degraded / Broken), configurable penalties and thresholds
- **Scheduled scanning** — Configurable intervals (1h, 6h, 12h, 24h, 7d) with pause/resume for automated re-scanning
- **Web UI** — NiceGUI-based dashboard with scan management, site/page management, and settings
- **Screenshots & reports** — Automatic full-page screenshot capture and JSON report generation
- **Database persistence** — SQLite (default) or PostgreSQL with SQLAlchemy async
- **Concurrent scanning** — Configurable concurrency via semaphore

## How It Works

1. **UI trigger** - You start a scan from the NiceGUI dashboard (`/scan`) or rely on scheduled scans.
2. **Fetch** - `services/fetcher.py` loads the page in Playwright, captures HTML/text/screenshot, and collects console errors.
3. **Preprocess** - `services/preprocessor.py` extracts structured signals (title, links, forms, images, headings, meta tags).
4. **Rules engine** - `services/rules.py` runs deterministic checks (HTTP status, SEO, performance, accessibility-like checks).
5. **LLM evaluation** - `services/llm_evaluator.py` analyzes visual/content quality and returns structured findings.
6. **Scoring** - `services/orchestrator.py` combines rule + LLM results into a health score and status (Healthy/Degraded/Broken).
7. **Persistence and reporting** - `db/database.py` stores scan results, while `services/reporter.py` writes JSON/markdown reports and screenshot artifacts.

```text
User/UI (/scan, scheduler)
        |
        v
services/fetcher.py (Playwright snapshot)
        |
        v
services/preprocessor.py (structured page signals)
        |
        v
services/rules.py + services/llm_evaluator.py
        |            (deterministic + semantic checks)
        v
services/orchestrator.py (health score + status)
        |
        +--> db/database.py (persist results)
        +--> services/reporter.py (reports + screenshots)
```

## Tech Stack

| Component | Technology |
|---|---|
| Language | Python 3.13+ |
| Web UI | NiceGUI |
| Browser automation | Playwright |
| Database | SQLAlchemy + aiosqlite / asyncpg |
| LLM integration | OpenRouter API |
| Data models | Pydantic |
| Package manager | uv |

## Prerequisites

- Python >= 3.13
- [uv](https://docs.astral.sh/uv/) (or pip)
- Playwright browsers
- OpenRouter API key

## Installation

```bash
git clone <repo-url>
cd Qa-bot

uv sync

uv run playwright install chromium

cp .env.example .env
# Edit .env and set your OPENROUTER_API_KEY
```

## Configuration

All settings are configured via environment variables or the `.env` file.

### Core Settings

| Variable | Default | Description |
|---|---|---|
| `APP_ENV` | `development` | Runtime environment (`development` or `production`) |
| `APP_HOST` | `0.0.0.0` | Bind host for NiceGUI server |
| `APP_PORT` / `PORT` | `7860` | Bind port (Heroku sets `PORT` automatically) |
| `OPENROUTER_API_KEY` | *(required)* | Your OpenRouter API key |
| `LLM_MODEL` | `openai/gpt-4` | LLM model in provider/model format (e.g. `anthropic/claude-sonnet-4-5-20250929`, `openrouter/openai/gpt-4`) |
| `LLM_API_KEY` | *(optional)* | Override API key (if different from OpenRouter) |
| `LLM_API_BASE` | *(optional)* | Override API base URL |
| `DATABASE_URL` | `sqlite+aiosqlite:///data/qa_bot.db` | Database URL (`postgres://...` and `postgresql://...` are normalized to asyncpg) |

### Authentication Settings

| Variable | Default | Description |
|---|---|---|
| `AUTH_SESSION_SECRET` | *(required for production)* | Session signing secret (minimum 24 chars) |
| `AUTH_SESSION_COOKIE_NAME` | `qa_bot_session` | Session cookie name |
| `AUTH_SESSION_COOKIE_SECURE` | auto by env | Force secure cookie behavior (`true/false`), defaults to `true` when `APP_ENV=production` |
| `AUTH_SESSION_TTL_HOURS` | `24` | Idle session timeout in hours |
| `AUTH_SESSION_ABSOLUTE_TTL_HOURS` | `168` | Absolute max session age in hours |
| `ADMIN_BOOTSTRAP_EMAIL` | *(required on first boot)* | Bootstrap admin email if no active admin exists |
| `ADMIN_BOOTSTRAP_PASSWORD` | *(required on first boot)* | Bootstrap admin password (minimum 12 chars) |
| `AUTH_LOGIN_MAX_ATTEMPTS` | `5` | Failed login attempts allowed per identity window |
| `AUTH_LOGIN_ATTEMPT_WINDOW_SECONDS` | `900` | Window size for counting login attempts |
| `AUTH_LOGIN_BLOCK_SECONDS` | `900` | Temporary lock duration after threshold is exceeded |
| `AUTH_TRUST_PROXY_HEADERS` | `true` | Indicates deployment behind proxy HTTPS termination |

### Admin Login and Heroku Deployment

- Dashboard routes are now login-protected.
- On first startup, the app requires bootstrap credentials (`ADMIN_BOOTSTRAP_EMAIL`, `ADMIN_BOOTSTRAP_PASSWORD`) when no active admin exists.
- For Heroku, set `AUTH_SESSION_SECRET` as a strong random value (minimum 24 chars in production) and run behind HTTPS (Heroku terminates TLS at the router).
- After first login, rotate or remove bootstrap credentials from your environment.

### Playwright Runtime Readiness

- QA Bot runs a Playwright readiness check at startup and logs an actionable warning if browser/runtime dependencies are missing.
- If Chromium binaries or OS dependencies are unavailable, scans return a clear readiness error instead of ambiguous partial results.
- Local setup command:

```bash
uv run playwright install chromium
```

### Scanning Settings

| Variable | Default | Range | Description |
|---|---|---|---|
| `PAGE_LOAD_TIMEOUT` | `30` | 5–120 | Page load timeout in seconds |
| `MAX_PAGE_SIZE_KB` | `5000` | 100–50000 | Maximum acceptable page size in KB |
| `MAX_CONCURRENT_SCANS` | `3` | 1–20 | Maximum number of concurrent scan tasks |
| `RATE_LIMIT_RPM` | `10` | 1–60 | LLM API rate limit (requests per minute) |
| `SCREENSHOT_WIDTH` | `1280` | 640–1920 | Viewport width for screenshots in pixels |
| `TEXT_CONTENT_MAX_CHARS` | `4000` | 500–10000 | Maximum characters of text content sent to LLM |

### Health Score Settings

| Variable | Default | Range | Description |
|---|---|---|---|
| `HEALTH_SCORE_CRITICAL_PENALTY` | `30` | 1–50 | Points deducted per CRITICAL finding |
| `HEALTH_SCORE_WARNING_PENALTY` | `10` | 1–30 | Points deducted per WARNING finding |
| `HEALTH_SCORE_INFO_PENALTY` | `2` | 0–10 | Points deducted per INFO finding |
| `HEALTH_HEALTHY_THRESHOLD` | `80` | 50–100 | Score >= this value means Healthy |
| `HEALTH_DEGRADED_THRESHOLD` | `50` | 20–80 | Score >= this value means Degraded (below = Broken) |

## Usage

```bash
uv run python -m qa_bot.main
```

The web UI is available at **http://localhost:7860**.

### UI Sections

- **Dashboard** — Overview of scan results, health scores, and recent activity
- **Scan** — Trigger manual scans and view detailed reports with screenshots
- **Sites** — Manage monitored sites and pages, configure scan intervals
- **Settings** — View and modify application configuration

The `data/` directory (screenshots, reports, database) is auto-created on first run and is gitignored.

## Project Structure

```
Qa-bot/
├── src/qa_bot/
│   ├── main.py              # App entry point
│   ├── config.py            # Backward-compatible config re-export
│   ├── core/
│   │   ├── __init__.py
│   │   └── config.py        # Centralized settings model & env normalization
│   ├── domain/
│   │   ├── __init__.py
│   │   └── models.py        # Domain/Pydantic models
│   ├── db/
│   │   ├── __init__.py
│   │   ├── database.py      # SQLAlchemy async DB layer
│   │   └── models.py        # SQLAlchemy ORM models
│   ├── services/
│   │   ├── __init__.py
│   │   ├── auth.py
│   │   ├── fetcher.py
│   │   ├── llm_evaluator.py
│   │   ├── orchestrator.py
│   │   ├── preprocessor.py
│   │   ├── reporter.py
│   │   ├── rules.py
│   │   ├── scheduler.py
│   │   ├── settings_manager.py
│   │   └── state.py
│   └── ui/
│       ├── __init__.py
│       ├── admin_users.py
│       ├── auth.py
│       ├── dashboard.py
│       ├── helpers.py
│       ├── layout.py
│       ├── scan.py
│       ├── settings.py
│       └── sites.py
├── data/                    # Auto-created: screenshots, reports, DB
├── tests/                   # Test suite
├── pyproject.toml           # Project metadata & dependencies
└── .env.example             # Environment variable template
```

## Heroku Deployment (PostgreSQL)

1. Create Heroku app and attach Postgres:

```bash
heroku create <app-name>
heroku addons:create heroku-postgresql:essential-0
```

2. Set required config vars:

```bash
heroku config:set APP_ENV=production
heroku config:set AUTH_SESSION_SECRET=<long-random-secret>
heroku config:set ADMIN_BOOTSTRAP_EMAIL=<admin-email>
heroku config:set ADMIN_BOOTSTRAP_PASSWORD=<strong-password>
heroku config:set OPENROUTER_API_KEY=<openrouter-key>
```

`DATABASE_URL` and `PORT` are provided by Heroku; the app consumes both automatically.

3. Deploy:

```bash
git push heroku <your-branch>:main
heroku ps:scale web=1
```

The `Procfile` uses:

```bash
web: python -m qa_bot.main
```

Heroku runtime is pinned in `runtime.txt`.

4. Verify first boot:

- Open the app URL and confirm login page loads.
- Sign in with bootstrap admin credentials.
- Run one scan and confirm report generation.
- If scan fails with Playwright readiness error, ensure browser binaries and system dependencies are present in the slug/runtime.

See full checklist in `docs/deploy/heroku-runbook.md`.

## Development

```bash
uv sync --extra dev

uv run pytest

uv run ruff check .
```

## License

Licensed under the [Apache License 2.0](http://www.apache.org/licenses/LICENSE-2.0).

---

## Українська

# QA Bot

Інструмент автоматизованого контролю якості веб-сторінок з перевірками на основі правил та оцінкою за допомогою LLM.

QA Bot сканує веб-сторінки за допомогою безголового браузера, виконує 10 вбудованих перевірок якості у 6 категоріях, а потім надсилає скріншоти та витягнутий контент до LLM для візуального та семантичного аналізу. Результат — оцінка здоров'я (0–100) зі статусом: **Healthy** (Здоровий), **Degraded** (Деградований) або **Broken** (Зламаний).

[English ↑](#qa-bot)

## Можливості

- **Перевірки на основі правил** — HTTP статус, заголовок сторінки, тег H1, viewport meta, час завантаження, помилки консолі, пошкоджені зображення, мітки форм, порожні посилання, розмір сторінки у категоріях: доступність, SEO, мобільність, продуктивність, контент, JavaScript
- **Оцінка за допомогою LLM** — Використовує OpenRouter API для оцінки якості макету, узгодженості контенту, візуальних аномалій, виявлення плейсхолдерів та логіки навігації через аналіз скріншотів
- **Оцінка здоров'я** — шкала 0–100 з трьома статусами (Healthy / Degraded / Broken), настроювані штрафи та пороги
- **Планове сканування** — настроювані інтервали (1г, 6г, 12г, 24г, 7д) з паузою/відновленням для автоматичного повторного сканування
- **Веб-інтерфейс** — панель управління на основі NiceGUI з керуванням скануваннями, управлінням сайтами/сторінками та налаштуваннями
- **Скріншоти та звіти** — автоматичний захват повносторінкових скріншотів та генерація JSON-звітів
- **Збереження в базі даних** — SQLite (за замовчуванням) або PostgreSQL з SQLAlchemy async
- **Паралельне сканування** — настроюваний рівень паралелізму через семафор

## Як це працює

1. **Запуск із UI** - Ви запускаєте сканування з NiceGUI-інтерфейсу (`/scan`) або використовуєте планувальник.
2. **Отримання сторінки** - `services/fetcher.py` відкриває сторінку в Playwright, збирає HTML/текст/скріншот і помилки консолі.
3. **Попередня обробка** - `services/preprocessor.py` витягує структуровані сигнали (title, links, forms, images, headings, meta tags).
4. **Правила** - `services/rules.py` виконує детерміновані перевірки (HTTP-статус, SEO, продуктивність, базова доступність).
5. **LLM-оцінка** - `services/llm_evaluator.py` аналізує візуальну та контентну якість і повертає структуровані висновки.
6. **Підрахунок оцінки** - `services/orchestrator.py` об'єднує результати правил і LLM у health score та статус.
7. **Збереження і звіти** - `db/database.py` зберігає результати, а `services/reporter.py` формує JSON/markdown звіти та артефакти скріншотів.

```text
Користувач/UI (/scan, scheduler)
           |
           v
services/fetcher.py (Playwright snapshot)
           |
           v
services/preprocessor.py (структуровані сигнали сторінки)
           |
           v
services/rules.py + services/llm_evaluator.py
           |            (детерміновані + семантичні перевірки)
           v
services/orchestrator.py (health score + статус)
           |
           +--> db/database.py (збереження результатів)
           +--> services/reporter.py (звіти + скріншоти)
```

## Технологічний стек

| Компонент | Технологія |
|---|---|
| Мова | Python 3.13+ |
| Веб-інтерфейс | NiceGUI |
| Автоматизація браузера | Playwright |
| База даних | SQLAlchemy + aiosqlite / asyncpg |
| LLM інтеграція | OpenRouter API |
| Моделі даних | Pydantic |
| Менеджер пакетів | uv |

## Вимоги

- Python >= 3.13
- [uv](https://docs.astral.sh/uv/) (або pip)
- Браузери Playwright
| Ключ API OpenRouter

## Встановлення

```bash
git clone <repo-url>
cd Qa-bot

uv sync

uv run playwright install chromium

cp .env.example .env
# Відредагуйте .env та встановіть ваш OPENROUTER_API_KEY
```

## Конфігурація

Всі налаштування конфігуруються через змінні середовища або файл `.env`.

### Основні налаштування

| Змінна | За замовчуванням | Опис |
|---|---|---|
| `OPENROUTER_API_KEY` | *(обов'язково)* | Ваш ключ API OpenRouter |
| `LLM_MODEL` | `openai/gpt-4` | Модель LLM у форматі провайдер/модель (напр. `anthropic/claude-sonnet-4-5-20250929`, `openrouter/openai/gpt-4`) |
| `LLM_API_KEY` | *(необов'язково)* | Перевизначити ключ API (якщо відрізняється від OpenRouter) |
| `LLM_API_BASE` | *(необов'язково)* | Перевизначити базову URL API |
| `DATABASE_URL` | `sqlite+aiosqlite:///data/qa_bot.db` | URL підключення до бази даних (підтримує PostgreSQL через `postgresql+asyncpg://...`) |

### Налаштування сканування

| Змінна | За замовч. | Діапазон | Опис |
|---|---|---|---|
| `PAGE_LOAD_TIMEOUT` | `30` | 5–120 | Тайм-аут завантаження сторінки в секундах |
| `MAX_PAGE_SIZE_KB` | `5000` | 100–50000 | Максимальний прийнятний розмір сторінки в КБ |
| `MAX_CONCURRENT_SCANS` | `3` | 1–20 | Максимальна кількість паралельних задач сканування |
| `RATE_LIMIT_RPM` | `10` | 1–60 | Обмеження частоти запитів до LLM API (запитів на хвилину) |
| `SCREENSHOT_WIDTH` | `1280` | 640–1920 | Ширина viewport для скріншотів у пікселях |
| `TEXT_CONTENT_MAX_CHARS` | `4000` | 500–10000 | Максимальна кількість символів текстового контенту, що надсилається до LLM |

### Налаштування оцінки здоров'я

| Змінна | За замовч. | Діапазон | Опис |
|---|---|---|---|
| `HEALTH_SCORE_CRITICAL_PENALTY` | `30` | 1–50 | Бали, що вираховуються за кожне CRITICAL знаходження |
| `HEALTH_SCORE_WARNING_PENALTY` | `10` | 1–30 | Бали, що вираховуються за кожне WARNING знаходження |
| `HEALTH_SCORE_INFO_PENALTY` | `2` | 0–10 | Бали, що вираховуються за кожне INFO знаходження |
| `HEALTH_HEALTHY_THRESHOLD` | `80` | 50–100 | Оцінка >= це значення означає Healthy |
| `HEALTH_DEGRADED_THRESHOLD` | `50` | 20–80 | Оцінка >= це значення означає Degraded (нижче = Broken) |

## Використання

```bash
uv run python -m qa_bot.main
```

Веб-інтерфейс доступний за адресою **http://localhost:7860**.

### Розділи інтерфейсу

- **Панель управління** — Огляд результатів сканування, оцінок здоров'я та нещодавньої активності
- **Сканування** — Запуск ручних сканувань та перегляд детальних звітів зі скріншотами
- **Сайти** — Управління сайтами та сторінками, що моніторяться, налаштування інтервалів сканування
- **Налаштування** — Перегляд та зміна конфігурації додатку

Директорія `data/` (скріншоти, звіти, база даних) створюється автоматично при першому запуску і додана до `.gitignore`.

## Структура проєкту

```
Qa-bot/
├── src/qa_bot/
│   ├── main.py              # Точка входу додатку
│   ├── config.py            # Сумісний реекспорт конфігурації
│   ├── core/
│   │   ├── __init__.py
│   │   └── config.py        # Центральна модель налаштувань і normalizer env
│   ├── domain/
│   │   ├── __init__.py
│   │   └── models.py        # Доменні/Pydantic моделі
│   ├── db/
│   │   ├── __init__.py
│   │   ├── database.py      # Асинхронний DB-шар SQLAlchemy
│   │   └── models.py        # ORM-моделі SQLAlchemy
│   ├── services/
│   │   ├── __init__.py
│   │   ├── auth.py
│   │   ├── fetcher.py
│   │   ├── llm_evaluator.py
│   │   ├── orchestrator.py
│   │   ├── preprocessor.py
│   │   ├── reporter.py
│   │   ├── rules.py
│   │   ├── scheduler.py
│   │   ├── settings_manager.py
│   │   └── state.py
│   └── ui/
│       ├── __init__.py
│       ├── admin_users.py
│       ├── auth.py
│       ├── dashboard.py
│       ├── helpers.py
│       ├── layout.py
│       ├── scan.py
│       ├── settings.py
│       └── sites.py
├── data/                    # Створюється автоматично: скріншоти, звіти, БД
├── tests/                   # Набір тестів
├── pyproject.toml           # Метадані проєкту та залежності
└── .env.example             # Шаблон змінних середовища
```

## Розробка

```bash
uv sync --extra dev

uv run pytest

uv run ruff check .
```

## Ліцензія

Ліцензовано за [Apache License 2.0](http://www.apache.org/licenses/LICENSE-2.0).
