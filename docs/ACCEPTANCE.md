# Acceptance

Audited engine commit: `e8655f10453f0c7c0874c8d691ef5ae2d74dab5c`.
Office work is on branch `cursor/virtual-office-685a`.

Fixture means `OFFICE_ALLOW_FIXTURES=1` and `execution_mode=fixture`: the real agent classes and the real `backtest_fund` / `tick` functions, with `office/fixtures.py` supplying prices and model text. It is not a live market and not a provider call.

| # | Criterion | Status | Evidence |
| --- | --- | --- | --- |
| 1 | App launches locally | Verified | `poetry run python -m office` served `web/dist` on `127.0.0.1:8765`. `GET /api/health` returned `status=ok`, `live_brokers_enabled=false`. Browser test loaded the shell. |
| 2 | Frontend talks to the Python backend | Verified | Playwright drove the built UI. Missions, backtests, and paper funds appeared only after the API accepted them. |
| 3 | Actual investment agents run through the UI | Partial | Fixture path verified: Deep Value ran `graham`, `buffett`, and `munger` (`BuffettAgent` and the other real classes) and stored their signals. Live provider calls are blocked until keys exist (`409 configuration_required`). |
| 4 | Actual execution states | Verified | States are rows written when a task starts and finishes. API test asserts `working` then `completed` for Buffett. The floor shows `completed` / `idle` from those rows. Nothing is advanced on a timer. |
| 5 | Research tasks are created and tracked | Verified | `POST /api/cio/coordinate` inserts tasks, runs them, and returns them. The mission page lists each finding. |
| 6 | Outputs persist and can be viewed | Verified | Signals, proposals, and ledger sessions are readable after the run. Restart test opens a new process on the same SQLite file and paper directory. |
| 7 | CIO coordinates real workflows | Partial | The office CIO queues native analysts, records conflicts, and writes a proposal with `blend_signals` and `apply_limits`. It does not place orders. There is still no LLM CIO in `ALPHA_MODEL_REGISTRY`; this layer does not pretend to be one. |
| 8 | Existing backtest is accessible | Partial | UI and API call `backtest_fund` and `performance_metrics`. Verified on fixture prices. A live backtest returns `configuration_required` without a data key and a model key when the mandate staffs an LLM agent. |
| 9 | Existing paper trading is accessible | Partial | UI deploys with `deploy`, previews with `next_session`, and runs `tick` only after an approval hash matches. Halt uses `Ledger.halt`. Verified on fixture data. Live tick needs credentials. Minute-bar `aihf paper run` is not started here. |
| 10 | Portfolio and research survive restart | Verified | `test_restart_keeps_mission_and_ledger`. |
| 11 | Original CLI still works | Verified | `python -m hedge_fund.run --help`, `backtest --help`, `paper --help`. Engine suite result below. |
| 12 | Automated tests pass | Verified | Counts below. One pre-existing Rich rendering failure was fixed in the test helper only. |

## Commands and results

Office API (fixture where the test says so; live-without-keys covered), after the follow-up on this branch:

```text
poetry run pytest office/tests -q
18 passed
```

Original engine suite:

```text
poetry run pytest hedge_fund -q
789 passed, 37 skipped
```

Together: 807 passed, 37 skipped. The 37 skips are the engine's own skips (network and credential tests). No failures.

Browser, against the built UI and a fixture-enabled office:

```text
cd web && npx playwright test --reporter=line
1 passed
```

Screenshots from that run are in `docs/evidence/` and are fixture-labelled on screen.

## Limits, stated as they are

- No Financial Datasets key and no model key were available. Nothing here is a live price or a live model completion.
- The office will not store a credential unless `OFFICE_MASTER_KEY` is set. Settings shows that state and does not echo values.
- Factor caps (`max_beta`, `max_sector_pct`, `max_volatility`) are not applied on the research proposal, because that path does not fit `exposures`. The omission is in the proposal payload. A backtest or paper tick still uses `assess_fund`, which does fit them.
- Office backtests refuse windows above `OFFICE_MAX_BACKTEST_SESSIONS` (default 800). The CLI does not.
- CPCV / PBO is still only a docstring in `hedge_fund/validation/`.
- The swing universe is the Nasdaq list dated Nov 6, 2026 and SOXX equities dated Nov 5, 2026, parsed from those publishers. It is not labelled current. Cash and derivatives are excluded. Historical use is survivorship bias.
- Per-agent model overrides apply only when the office builds the `Fund`. `aihf` still uses one `make_llm()` model.
