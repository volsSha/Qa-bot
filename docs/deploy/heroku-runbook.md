# Heroku Deployment Runbook

This runbook describes a production-safe deployment path for QA Bot on Heroku.

## 1) Prerequisites

- Heroku CLI installed and authenticated.
- A Heroku app created.
- Heroku Postgres attached.
- Python runtime pinned by `runtime.txt`.
- Web process defined in `Procfile` as `web: python -m qa_bot.main`.

## 2) Required config vars

Set required production variables:

- `APP_ENV`
- `OPENROUTER_API_KEY`
- `AUTH_SESSION_SECRET`
- `ADMIN_BOOTSTRAP_EMAIL`
- `ADMIN_BOOTSTRAP_PASSWORD`

```bash
heroku config:set APP_ENV=production
heroku config:set OPENROUTER_API_KEY=<openrouter-key>
heroku config:set AUTH_SESSION_SECRET=<long-random-secret-at-least-24-chars>
heroku config:set ADMIN_BOOTSTRAP_EMAIL=<admin-email>
heroku config:set ADMIN_BOOTSTRAP_PASSWORD=<strong-password-at-least-12-chars>
```

Notes:
- `PORT` and `DATABASE_URL` are provided by Heroku.
- Do not use placeholder secrets (for example `change-me-in-production`).

## 3) Deploy

```bash
git push heroku <your-branch>:main
heroku ps:scale web=1
```

Current `Procfile` command:

```bash
web: python -m qa_bot.main
```

## 4) First-boot checks

1. Open the app URL and confirm the login page loads.
2. Sign in with bootstrap admin credentials.
3. Trigger one manual scan from `/scan`.
4. Verify scan report appears and status/score are rendered.

## 5) Playwright readiness checks

At startup, QA Bot validates Playwright runtime readiness.

If scans fail with a readiness message, validate that:
- Chromium browser binaries are present (`playwright install chromium` equivalent in your build pipeline).
- Required OS dependencies for headless Chromium exist in runtime image/stack.

Expected behavior:
- App remains usable for authenticated navigation.
- Scan actions return a deterministic readiness error instead of silent/ambiguous failures.

## 6) Post-deploy security actions

1. Rotate or remove `ADMIN_BOOTSTRAP_PASSWORD` after first successful admin login.
2. Keep `AUTH_SESSION_SECRET` stable and confidential.
3. Review startup logs for validation warnings/errors.

## 7) Operational notes and limitations

- Heroku dyno filesystem is ephemeral; screenshots stored on local disk are not durable.
- Scale/restart events can remove local screenshot artifacts.
- This runbook does not include persistent object storage migration.

## 8) Rollback

If startup validation blocks release:

```bash
heroku releases
heroku rollback <previous-release-id>
```

Then fix config vars and redeploy.
