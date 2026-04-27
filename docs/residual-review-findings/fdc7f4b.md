## Residual Review Findings

- P1 `src/qa_bot/database.py:33` - startup migration only handles SQLite for `scan_results.screenshot_path`; existing PostgreSQL tables may miss this column and fail writes after deploy.
- P1 `docs/plans/2026-04-27-001-feat-heroku-deployment-readiness-plan.md:91` - Plan gap (U1/R1) Procfile, runtime.txt, and tests/test_heroku_runtime_contract.py are untracked so startup contract is not reviewable.
- P1 `docs/plans/2026-04-27-001-feat-heroku-deployment-readiness-plan.md:160` - Plan gap (U3/R3) tests/test_playwright_runtime_readiness.py is untracked so runtime-readiness verification is incomplete.
- P1 `docs/plans/2026-04-27-001-feat-heroku-deployment-readiness-plan.md:195` - Plan gap (U4/R4) README.md and docs/deploy/heroku-runbook.md are untracked so docs-code alignment cannot be fully validated.

### Source Context

- Review skill: `ce-code-review mode:autofix`
- Plan: `docs/plans/2026-04-27-001-feat-heroku-deployment-readiness-plan.md`
- Review run artifact: `.context/compound-engineering/ce-code-review/20260427-024349-1ef3e1ce/run-artifact.md`
- Tracker defer mode: non-interactive (`references/tracker-defer.md`)
- Tracker structured result: `filed=4, failed=0, no_sink=0`
- PR sink attempt: `gh pr view --json number,url,body,state` failed (`gh` not installed), so this committed file is the durable fallback sink.
