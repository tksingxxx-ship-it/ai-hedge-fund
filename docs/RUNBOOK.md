# Runbook

Educational software. The office does not submit brokerage orders.

## What you get

- `aihf` — the original terminal app and CLI. Unchanged entry point.
- `python -m office` — the virtual office. FastAPI on `127.0.0.1:8765`, serving `web/dist` when that build exists.

The engine under `hedge_fund/` remains the source of truth for signals, risk, backtests, and the paper ledger. Office rows (missions, tasks, approvals, audit) live in SQLite. Cash, positions, and NAV are read from the ledger, not copied into a second book.

## Install

Python 3.11+ and Node 20+ (the UI build was checked on Node 22).

```bash
poetry install -E office
cd web && npm install && npm run build && cd ..
```

`cryptography` is already in the locked dependency set and is what the credential file uses. `httpx` is what the API tests use.

If Poetry extras are awkward in a throwaway environment:

```bash
poetry install
poetry run pip install 'fastapi>=0.115' 'uvicorn[standard]>=0.32' 'cryptography>=44'
cd web && npm install && npm run build && cd ..
```

## Start

```bash
poetry run python -m office
```

Open http://127.0.0.1:8765 . The process binds to localhost. It does not deploy anywhere.

`make office` installs the UI dependencies, builds `web/dist`, and starts the same process.

### Useful environment variables

| Variable | Default | Meaning |
| --- | --- | --- |
| `OFFICE_HOST` | `127.0.0.1` | Bind address. Do not publish this. |
| `OFFICE_PORT` | `8765` | Port. |
| `OFFICE_HOME` | `~/.hedge-fund/office` | SQLite directory. Mode `0700`. |
| `OFFICE_PAPER_ROOT` | `~/.hedge-fund/paper` | Same paper funds the CLI sees, unless you point tests elsewhere. |
| `OFFICE_RESEARCH_DIR` | `~/.hedge-fund/research` | Where `save_result` writes backtests. |
| `OFFICE_MANDATES_DIR` | `~/.hedge-fund/mandates` | Mandate YAML. |
| `OFFICE_ALLOW_FIXTURES` | off | `1` allows `execution_mode=fixture`. Those runs are labelled and are not market or provider output. |
| `OFFICE_EAGER` | off | Run jobs inline. Used by tests. |
| `OFFICE_DEV_CORS` | off | Allow the Vite dev server on port 5173. |
| `OFFICE_MASTER_KEY` | unset | Required before the office will encrypt a credential. No default. |
| `OFFICE_MAX_BACKTEST_SESSIONS` | `800` | Office cap. The CLI is not capped. |
| `OFFICE_ALLOW_REMOTE` | off | Required together with a long `OFFICE_API_TOKEN` before a non-loopback bind is accepted. |
| `OFFICE_API_TOKEN` | unset | If set, every mutating request must send `Authorization: Bearer ...`. |

Provider and data keys are the ones in `.env.example`. The shell wins over `~/.hedge-fund/.env`, which wins over the encrypted office file. The UI never receives the values. Mutating requests from the UI send `X-Office-Request: 1`. A foreign `Origin` is rejected. Binding `0.0.0.0` exits unless remote access and a token are both set.

`POST /api/universes/refresh` re-downloads the Nasdaq list and the iShares SOXX CSV. The shipped file is the Nov 6 / Nov 5 2026 publisher snapshots. It is not labelled current.

### Frontend dev

```bash
OFFICE_DEV_CORS=1 poetry run python -m office
cd web && npm run dev
```

Vite proxies `/api` to port 8765.

## Tests

```bash
poetry run pytest office/tests -q          # office API, fixture-backed where noted
poetry run pytest hedge_fund -q            # original engine suite
cd web && npx playwright test              # browser, against a running office
```

The browser test expects the office on http://127.0.0.1:8765 with `OFFICE_ALLOW_FIXTURES=1`. Install the browser once with `npx playwright install chromium`.

A fixture run calls the real `AlphaModel` classes, `backtest_fund`, and `tick`. The data client and the LLM client are the fakes in `office/fixtures.py`. Do not read those results as live prices or live model output.

Without keys, a live research, backtest, or paper tick returns `configuration_required` and does not invent a book.

## CLI smoke

```bash
poetry run python -m hedge_fund.run --help
poetry run python -m hedge_fund.run backtest --help
poetry run python -m hedge_fund.run paper --help
```

## Restart

Stop the process and start it again. SQLite missions and the paper ledger directories are still there. Rows left `running` are marked failed with `interrupted by process restart`. A paper tick that died mid-fill is still the engine's problem: the next tick reconciles and halts on `BookMismatch`.
