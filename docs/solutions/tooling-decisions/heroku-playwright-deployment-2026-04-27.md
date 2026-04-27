---
title: "Deploying Playwright Chromium on Heroku heroku-24 Stack"
date: 2026-04-27
category: tooling-decisions
module: deployment
problem_type: tooling_decision
component: tooling
severity: high
applies_when:
  - "Deploying Python apps with Playwright to Heroku heroku-24 stack"
  - "Headless browser required for scraping, screenshots, or QA automation"
tags:
  - heroku
  - playwright
  - chromium
  - buildpack
  - aptfile
  - headless-browser
  - deployment
---

# Deploying Playwright Chromium on Heroku heroku-24 Stack

## Context

Deploying a Python web app that uses Playwright for headless browser rendering (e.g., QA scanning, screenshot capture) to Heroku fails silently or with missing shared library errors. The app works locally but crashes on Heroku's dynos because Chromium requires dozens of native system dependencies that aren't present in the slug, and browsers downloaded during build aren't included in the runtime slug by default. The problem is compounded by heroku-24 (Ubuntu 24.04) lacking support for existing community buildpacks like `mxschmitt/heroku-playwright-buildpack`.

## Guidance

### Buildpack setup (order matters)

```bash
heroku buildpacks:clear
heroku buildpacks:add --index 1 https://github.com/heroku/heroku-buildpack-apt.git
heroku buildpacks:add --index 2 heroku/python
```

### Aptfile (root of repo)

```
libatk1.0-0
libatk-bridge2.0-0
libcups2
libdrm2
libxkbcommon0
libxcomposite1
libxdamage1
libxfixes3
libxrandr2
libgbm1
libpango-1.0-0
libcairo2
libasound2t64
libnspr4
libnss3
```

### bin/post_compile (executable)

```bash
#!/usr/bin/env bash
set -euo pipefail
PLAYWRIGHT_BROWSERS_PATH="$BUILD_DIR/.playwright" playwright install chromium
```

### Config var

```bash
heroku config:set PLAYWRIGHT_BROWSERS_PATH=/app/.playwright
```

### Key details

- `bin/post_compile` must use `BUILD_DIR`, not `/app` — during build the app is staged in a temporary directory; `BUILD_DIR` resolves correctly and its contents end up in the slug
- The Apt buildpack must be **first** so its packages are available to the Python buildpack
- On heroku-24, the package is `libasound2t64` (not `libasound2` as on older Ubuntu)

## Why This Matters

Without this setup, Chromium either won't download into the slug (post_compile writes outside BUILD_DIR) or downloads but can't run (missing `.so` libraries). The three pieces are interdependent: the Apt buildpack provides native libs, post_compile provides the browser binary in the slug, and the config var tells Playwright where to find it at runtime. Missing any one causes a different failure mode.

## When to Apply

- Any Python app using Playwright on Heroku heroku-24 stack
- App uses `playwright install chromium` (or firefox/webkit with adjusted package lists)
- Deployment fails with errors like `libatk-1.0.so.0: cannot open shared object file` or Chromium fails to launch silently
- Community Playwright buildpacks are incompatible (stack version mismatch)

## What Didn't Work

| Approach | Why it failed |
|---|---|
| `post_compile` with `su` to run `apt-get` | post_compile runs as non-root; `su` auth fails on Heroku |
| `post_compile` downloading to `/app/.playwright/` | `/app/.playwright/` is outside BUILD_DIR, so browsers aren't in the slug |
| `PLAYWRIGHT_BROWSERS_PATH` config alone | Pointless without browsers actually in the slug |
| `mxschmitt/heroku-playwright-buildpack` | Only supports heroku-18/20/22, rejects heroku-24 |
| `ldd` check on one-off dyno | Misleading — one-off dynos have different libs than web dynos; passed but runtime still failed |

## Examples

### Before (broken deployment)

```
heroku buildpacks:add heroku/python
# post_compile: PLAYWRIGHT_BROWSERS_PATH=/app/.playwright playwright install chromium
# PLAYWRIGHT_BROWSERS_PATH=/app/.playwright set in config
# → Build succeeds, browsers download, but missing at runtime
# → RuntimeError: libatk-1.0.so.0: cannot open shared object file
```

### After (working deployment)

```
heroku buildpacks:add --index 1 https://github.com/heroku/heroku-buildpack-apt.git
heroku buildpacks:add --index 2 heroku/python
# Aptfile present with 14 system packages
# bin/post_compile uses BUILD_DIR to install into slug
# PLAYWRIGHT_BROWSERS_PATH=/app/.playwright set in config
# → Build succeeds, browsers in slug, all native libs present
# → Playwright launches Chromium successfully on web dyno
```

## Related

- [Playwright Heroku deployment guide](https://playwright.dev/docs/ci) (official docs, covers Docker but not heroku-24 buildpacks)
- [heroku-buildpack-apt GitHub](https://github.com/heroku/heroku-buildpack-apt)
