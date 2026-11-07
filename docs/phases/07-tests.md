# Phase 7 — tests and instructions

Status: complete. Numbers are in `docs/ACCEPTANCE.md`.

- `poetry run pytest office/tests`
- `poetry run pytest hedge_fund`
- `cd web && npx playwright test` against a running office
- `docs/RUNBOOK.md` and `docs/DEPLOYMENT.md`

`hedge_fund/tui/fixtures.py` now passes both width and height into Rich. Rich 14.3.4 (the locked version) ignores an explicit width on a dumb terminal unless height is set too, which failed two scorecard view tests. The TUI screens themselves are unchanged.
