# Residual Review Findings

Source review context: `ce-code-review mode:autofix plan:docs/plans/2026-04-27-006-fix-login-browser-local-heroku-plan.md` on `master` at `1beef0d`.

- P1 `src/qa_bot/services/auth.py:261` POST login endpoint has no CSRF protection. No tracker sink available because `gh` is not installed; this fallback file is the durable record. The endpoint now accepts a plain form POST and creates an authenticated session cookie, but no CSRF token is validated. Add CSRF protection to the login form and endpoint, or use an existing framework-supported submission path that provides equivalent CSRF/session binding.
- P2 `docs/plans/2026-04-27-006-fix-login-browser-local-heroku-plan.md:224` Heroku browser regression scenarios still require final production verification evidence. No tracker sink available because `gh` is not installed; this fallback file is the durable record. Verify Heroku `/login` accepts intended admin credentials, rejects a wrong password generically, and the authenticated session survives protected-route navigation after deployment.
