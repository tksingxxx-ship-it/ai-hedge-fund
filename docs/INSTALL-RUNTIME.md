# Install the virtual office from the wheel

This file is the runtime delivery. It does not require a git checkout.
The wheel was built and checked on the build machine. It has not been installed on the destination computer yet.

Supported Python: 3.11 or 3.12. The clean install below used CPython 3.12.3.

Wheel (one file, pure Python, includes `hedge_fund`, `office`, the built UI, and the universe snapshot):

- Path: `/opt/cursor/artifacts/aihf-2.7.0-py3-none-any.whl`
- sha256: `4d93c5ddaced8e62c6d78f1239193b7bcf505540050e76b6ff1999937e2b24ff`

No `.git`, secrets, `.env`, user databases, API keys, or `node_modules` are in the wheel.

## Install

From any directory, with a virtual environment:

```bash
python3 -m venv ~/aihf-office-venv
~/aihf-office-venv/bin/pip install --upgrade pip
~/aihf-office-venv/bin/pip install '/opt/cursor/artifacts/aihf-2.7.0-py3-none-any.whl[office]'
```

`[office]` installs FastAPI and uvicorn. The engine's other dependencies come with the wheel. Do not install the `x402` extra.

## Fixture-only preview

This mode does not read `~/.hedge-fund/.env`, drops inherited provider and data keys from the process, refuses `execution_mode=live`, and refuses universe refresh (that would call Nasdaq and iShares). Prices and model text are the built-in fixtures. They are not live market or provider results.

The working directory does not matter. Data defaults to `~/.hedge-fund-office-preview/`, not a real paper book.

```bash
env -i \
  HOME="$HOME" \
  PATH="$HOME/aihf-office-venv/bin:/usr/bin:/bin" \
  LANG=C.UTF-8 \
  OFFICE_FIXTURE_ONLY=1 \
  OFFICE_HOST=127.0.0.1 \
  OFFICE_PORT=8765 \
  python -m office
```

Open http://127.0.0.1:8765

`OFFICE_EAGER=1` is optional. It runs a clicked job in the request instead of a background thread. Leave it unset for normal use.

Do not set `OFFICE_ALLOW_REMOTE`. The process binds to `127.0.0.1` only. Do not put it on a public address.

## Where state is written

With `OFFICE_FIXTURE_ONLY=1` and no path overrides:

| What | Path |
| --- | --- |
| SQLite (missions, tasks, events, approvals) | `~/.hedge-fund-office-preview/office.sqlite3` |
| Paper ledgers and broker files | `~/.hedge-fund-office-preview/paper/<name>/` |
| Backtest JSON | `~/.hedge-fund-office-preview/research/` |
| Mandates | `~/.hedge-fund-office-preview/mandates/` |

Override with `OFFICE_HOME`, `OFFICE_DB`, `OFFICE_PAPER_ROOT`, `OFFICE_RESEARCH_DIR`, or `OFFICE_MANDATES_DIR` if those directories should live somewhere else. Fixture-only still will not load API keys.

## Clean-install check already run on the build machine

Not on the destination computer. A new virtualenv at `/tmp/aihf-runtime` installed the artifact wheel. From an empty directory `/tmp/aihf-launch`, `python -m office` was started with fixture-only and with fake `ANTHROPIC_API_KEY` and `FINANCIAL_DATASETS_API_KEY` values in the environment.

- `GET /api/health` returned `fixture_only: true`, `external_calls: "disabled"`, `data_configured: false`, `live_brokers_enabled: false`.
- `GET /` returned the office HTML. `GET /assets/index-BYewF3gf.js` and the CSS asset returned the built files from `site-packages/office/static`, not from a repository path.
- `POST /api/cio/coordinate` with `execution_mode=fixture` and strategy `earnings-drift` completed a PEAD task. That is fixture engine execution, not a paid data or model call.
- `execution_mode=live` returned HTTP 400 `fixture_disabled`.
- `POST /api/universes/refresh` returned HTTP 403 `fixture_only`.
- SQLite and paper directories were created under `/tmp/aihf-runtime-home/.hedge-fund-office-preview/`.
