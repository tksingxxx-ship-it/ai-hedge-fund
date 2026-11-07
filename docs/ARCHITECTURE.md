# Virtual Office architecture

Audited commit: `e8655f10453f0c7c0874c8d691ef5ae2d74dab5c` (tag line: "Bump version to 2.7.0", package `aihf` 2.7.0).

This document records what is in the tree at that commit and how the virtual office calls it. The office is an additional process. It does not replace the engine, the Textual TUI, or the `aihf` CLI.

Educational software only. The office never enables a live broker and never submits a brokerage order.

## Documents present and absent

Present at the audit commit:

| Path | Role |
| --- | --- |
| `README.md` | Install and run `aihf`. Educational disclaimer. |
| `VISION.md` | Fund hierarchy, one `advance` verb, three modes. Live mode is described as future. |
| `ROADMAP.md` | Capability map. Several rows are ahead of, or behind, the code. The code wins. |
| `LICENSE` | MIT, Copyright (c) 2024 Virat Singh. |
| `hedge_fund/README.md` | v2 module map. It mentions a v1 tree at `src/` and `app/` that is **not in this fork**. |
| `.env.example` | Names of provider environment variables. Placeholder values only. |

Absent at the audit commit (no file, no stub):

- `CONTRIBUTING.md`, `CHANGELOG`, `SECURITY.md`, `docs/`
- `src/`, `app/`, and any web frontend. `ROADMAP.md` says "frontend scaffold exists; still runs on the v1 engine". That scaffold is not in this tree.
- An HTTP API
- CPCV / PBO implementation (`hedge_fund/validation/__init__.py` is a docstring only)
- A live broker (Interactive Brokers, Alpaca, or otherwise)
- Ollama or any local model client
- A market-calendar daemon beyond `hedge_fund.paper.runner.serve` (CLI `aihf paper run`)

## Verified engine

Package root: `hedge_fund/`. CLI entry: `hedge_fund.run:main`, script name `aihf` (`pyproject.toml`).

### Agents

`hedge_fund/signals/__init__.py` `ALPHA_MODEL_REGISTRY` maps:

| Key | Class | Module | Kind | `investment_approach` | `horizon_days` |
| --- | --- | --- | --- | --- | --- |
| `pead` | `PEADModel` | `signals/pead.py` | Quant `QuantModel` | `long_short` | 60 |
| `buffett` | `BuffettAgent` | `signals/buffett.py` | `LLMAgent` | `long_only` | 252 |
| `munger` | `MungerAgent` | `signals/munger.py` | `LLMAgent` | `long_only` | 252 |
| `graham` | `GrahamAgent` | `signals/graham.py` | `LLMAgent` | `long_only` | 252 |
| `lynch` | `LynchAgent` | `signals/lynch.py` | `LLMAgent` | `long_only` | 252 |
| `druckenmiller` | `DruckenmillerAgent` | `signals/druckenmiller.py` | `LLMAgent` | `long_short` | 126 |

Contract: `AlphaModel.predict(ticker, date, data_client) -> Signal` in `signals/base.py`. `Signal` is `hedge_fund/models.py` (`value` in [-1, 1], `reasoning`, `metadata`).

`LLMAgent.predict` (`signals/llm_agent.py`) builds a point-in-time `FundamentalsSnapshot` (`features/snapshot.py` `build_snapshot`). Data errors propagate. LLM call or parse failures abstain (`metadata["abstained"]=True`). Prompts are cached by `hedge_fund.llm.cache.PromptCache`. Personas are system prompts, not separate runtimes. `VISION.md` states they are stylized approximations, not the people and not endorsements.

There is no CIO class, no task queue, and no inter-agent message bus in the engine. Allocation across strategies is `FundSpec.allocation` (`scorecard/allocation.py` `allocate` / `current_allocation`): a static slice adjusted by scorecard t-stats after `min_evidence`. `ROADMAP.md` still lists an LLM CIO as planned. The office CIO below is new and is not registered in `ALPHA_MODEL_REGISTRY`.

### Models and providers

`hedge_fund/llm/registry.py` loads `hedge_fund/llm/api_models.json`. `make_llm` in `hedge_fund/llm/client.py` routes `Anthropic`, `OpenAI`, `DeepSeek`, `Google`, `xAI`, `Kimi`, and `TypeSafe`. Keys come from the environment variables in `PROVIDER_ENV_VARS`. `hedge_fund/tui/keys.py` `apply_credentials` / `save_credential` load and write `~/.hedge-fund/.env` (mode `0600`). The shell environment wins over the file.

The engine has one model for every LLM agent in a process: `HEDGE_FUND_LLM_MODEL`, else `DEFAULT_MODEL` (`claude-opus-5-5`). `ModelSpec.params` can pass constructor kwargs, but a YAML mandate cannot name a different provider per analyst. Per-agent model assignment is an office-only override used when the office builds the `Fund`. The CLI path `Fund(spec)` is unchanged.

### Strategies and mandates

Library YAML: `hedge_fund/strategies/{fundamental-ls,deep-value,inflections,earnings-drift}.yaml`, loaded by `fund/spec.py` `load_strategy`. Example mandate: `hedge_fund/fund/example.yaml`, copied to `~/.hedge-fund/mandates/` by `paths.ensure_mandates_dir`.

`FundSpec` (schema version 2) holds strategies, `RiskLimits`, `TradingCosts`, optional `AllocationPolicy`, capital, cadence, benchmark. It names no tickers. `normalize_universe` fixes the universe per run. `Fund.__init__` constructs one `AlphaModel` instance per strategy model so caches survive the run. `blind=True` (used by `run._backtest`) strips identifying fields from LLM prompts.

`custom_strategy` builds a desk from analyst names and derives `long_only` vs `long_short` from `get_investment_approach`. It never infers dollar neutrality.

### Portfolio, risk, and the session

`portfolio/construction.py` `blend_signals` turns signals into sleeve weights. `risk/limits.py` `apply_limits` clamps them. Clamps only shrink. `risk/exposures.py` `exposures` feeds beta, sector, and volatility caps when those limits are set.

`pipeline/stages.py`:

- `assess_fund` — analysts, blend, net sleeves, risk. Returns `DecisionRecord`. No orders.
- `execute_decision` — sizes the pending decision at a later session. Returns `CycleRecord`.
- `stop_out_decision` — drawdown stop, flat book, analysts not asked.

`pipeline/session.py` `advance` is the one session verb: refuse if `FundState.halted`, reconcile broker vs state (`BookMismatch`), execute the pending decision, mark, maybe assess, return a hash-chained `SessionRecord`. Decide at T, execute at T+1. `next_state` folds a record into state.

`pipeline/execution.py` `build_orders` is deterministic. The LLM never places an order.

### Backtest and paper

`backtesting/fund.py` `backtest_fund` loops `advance` on a `SimBroker` with state in memory. `performance_metrics` computes return, Sharpe, drawdown, and benchmark fields. `backtesting/research.py` `save_result` writes `~/.hedge-fund/research/<fund>-<start>-<end>-<stamp>.json`.

`paper/deployed.py` `deploy` snapshots the mandate into `paper/<name>/fund.yaml`, seeds `PaperBroker`, and inits a `Ledger`. `paper/tick.py` `tick` advances exactly one due session and is idempotent when that session is already recorded. `redo` replaces the latest record. `NothingDue` and `FundHalted` are the refusal errors. Any other failure inside `advance` calls `Ledger.halt`.

`paper/ledger.py` `Ledger` is append-only and hash-chained. `halt` / `resume` / `halted` are the kill switch (`control.json`). `events` reads `events.jsonl`. Replay rebuilds `FundState`. The broker book is a second file (`brokers/paper.py`); a mismatch is not repaired.

`paper/runner.py` `serve` / `run` is the unattended loop used by `aihf paper run`. The office does not start it. Unattended bars would skip the office's per-session approval.

`scorecard/__init__.py` `score` grades analysts and strategies from `SessionRecord`s. That is the only per-analyst performance number the office will show, and only for a ledger or backtest that exists.

### Data

`data/protocol.py` `DataClient`. `data/client.py` `FDClient` talks to Financial Datasets. `get_financial_metrics` filters on `filing_date_lte` (point-in-time). `has_data_credential` is true when `FINANCIAL_DATASETS_API_KEY` or `X402_WALLET_PRIVATE_KEY` is set. `data/cached.py` `CachedDataClient` caches under `~/.hedge-fund/cache/`. `data/sessions.py` `completed_through` excludes the current New York date.

`ROADMAP.md` marks point-in-time correctness as in progress. The metrics and insider paths are point-in-time; company facts used for sector are documented in `features/snapshot.py` as a slow-moving approximation. The office does not weaken those rules.

### What the TUI already does

`tui/paper.py` `RunConfirmScreen` shows the next session and will not trade until the user confirms. `RunSessionScreen` then calls `tick` or `redo`. `tui/keys.py` stores keys in the env file. The office approval gate mirrors that boundary for HTTP. It does not add a gate to the CLI. `aihf paper tick` stays a direct engine call, which is the existing contract.

### Paths

`hedge_fund/paths.py`: `USER_DIR` `~/.hedge-fund`, plus `mandates`, `paper`, `research`, `cache`, `.env`. The ledger is the financial source of truth. The office database does not copy positions, cash, or NAV as a second book. It stores task and audit rows and pointers at ledger files.

## Office layer (new)

Code: `office/`. Process: `python -m office` or `aihf-office`. Default bind `127.0.0.1:8765`. UI: `web/` (Vite, React), built to `web/dist` and served by the same process.

```
Browser  -- HTTP/SSE -->  office FastAPI
                              |  sqlite (tasks, events, messages, approvals, job rows)
                              |  reads/writes engine files only through engine functions
                              v
                         hedge_fund.*
                              advance / backtest_fund / deploy / tick / Ledger.halt
                              AlphaModel.predict / blend_signals / apply_limits / score
```

### Persistence

SQLite file `OFFICE_HOME/office.sqlite3` (default `~/.hedge-fund/office/`). Schema is created in `office/db.py` and recorded in `schema_migrations`. Writes use transactions. `BEGIN IMMEDIATE` covers approval consumption.

On startup, rows left `running` / `working` are marked failed with the text `interrupted by process restart`, and an office event is appended. The engine ledger is not rewritten. A crash inside `tick` remains the engine's problem: `PaperBroker` saves each fill atomically, and the next `advance` raises `BookMismatch` and `tick` halts the fund.

### CIO (new, not an analyst)

`office/cio.py` and `office/research.py`. The CIO is the id `cio` in office runtime state. It is absent from `ALPHA_MODEL_REGISTRY` and has no `predict` method.

For a mission it:

1. Builds tasks for each native analyst staffed on the selected strategies, for each symbol, inside the mission's data budget.
2. Runs `AlphaModel.predict` on those instances (the real classes).
3. If two non-abstained views on one symbol disagree in sign beyond a fixed band, writes a conflict, escalates to a CIO decision, and may enqueue one additional native analyst for that symbol if the budget still has a call and the round cap allows it.
4. Stops after that single follow-up round. Tasks cannot spawn further tasks.
5. Combines stored signals with `blend_signals` and `apply_limits`. The result is a proposal. It is not passed to `build_orders`, `advance`, or `tick`.

Model text, user text, and system events are separate `channel` values on messages and events.

### UI to engine

| UI action | Office route | Engine call |
| --- | --- | --- |
| Agent directory | `GET /api/agents` | `ALPHA_MODEL_REGISTRY`, `get_investment_approach`, `get_horizon_days`, strategy YAML |
| Open a desk | `GET /api/agents/{name}` | Same, plus office task rows. No synthetic biography. |
| Start research | `POST /api/cio/coordinate` then the worker | `load_strategy`, `Fund` / `AlphaModel.predict`, then `blend_signals`, `apply_limits` |
| Save mandate | `POST /api/mandates` | `FundSpec` validation, `save_spec` |
| Run backtest | `POST /api/backtests` | `backtest_fund`, `save_result`, `score` |
| Deploy paper | `POST /api/paper/funds` | `deploy` only. No tick. |
| Preview session | `GET /api/paper/funds/{name}/plan` | `Ledger.replay`, `next_session`. No broker write. |
| Approve | `POST /api/paper/funds/{name}/approvals` | Office row. Still no tick. |
| Run session | `POST /api/paper/funds/{name}/tick` | Consumes the approval, then `tick` or `redo` |
| Halt / resume | `POST .../halt` and `.../resume` | `Ledger.halt` / `Ledger.resume` |
| Portfolio | `GET /api/portfolio/{name}` | `load_deployed`, `Ledger.records` / `replay`, `performance_metrics`, `score` |
| Settings | `GET /api/providers` | `load_api_models`, `PROVIDER_ENV_VARS`, `has_data_credential`. Booleans only. |

Unknown JSON fields are rejected (`extra=forbid`) so a client cannot pass `force`, `skip_risk`, or `broker=live`.

Paper `tick` without a matching unconsumed approval is refused. Halted funds are refused by the engine (`FundHalted`) even if an approval exists. The office does not call `paper.runner.serve`.

Live Financial Datasets and `make_llm` run only when the corresponding environment variable is set. Otherwise the route returns `configuration_required` and does not invent prices or theses.

`OFFICE_ALLOW_FIXTURES=1` enables an explicit `execution_mode=fixture` path for tests and local dry runs. Fixture responses are labelled `fixture: true`. The flag defaults off. Fixture mode uses `office/fixtures.py` (`FixtureDataClient`, `FixtureLLM`) injected into the real agent classes and the real `backtest_fund` / `tick` functions. It is not a second backtester.

### Universe snapshot

`office/data/us_swing_ndx_soxx.json` is the output of `office/universe_sources.py`, not a hand-written list.

- Nasdaq list endpoint `https://api.nasdaq.com/api/quote/list-type/nasdaq100`. The date is the payload's `data.date` (Nov 6, 2026 on the fetch that wrote the file). Row count must match `totalrecords`.
- iShares SOXX holdings CSV. The date is the `Fund Holdings as of` line (Nov 05, 2026). Only `Asset Class = Equity` is kept. Cash, collateral, money-market, and futures rows are dropped.

`current` is false. The research screen states both publisher dates and the survivorship warning. `POST /api/universes/refresh` downloads those two URLs again. A failed download does not write a file and does not invent tickers. `validate_preset` rejects a file that lacks either source or that still contains a cash row.

### Paper catch-up

One approved session still calls `tick`. `POST /api/paper/funds/{name}/catch-up` calls `tick` up to the approved count (1–5), checks `Ledger.halted` before each one, and stops if the job is cancelled. It does not call `paper.runner.serve`. That CLI loop waits on the clock and would keep trading without a new approval.

### Requests

Mutating `/api` calls need `X-Office-Request: 1`. An `Origin` outside the local office (and the Vite port when dev CORS is on) is rejected. A non-loopback bind exits unless `OFFICE_ALLOW_REMOTE=1` and `OFFICE_API_TOKEN` is at least 16 characters, and then the token is required on mutating calls.

### Secrets

API responses, validation errors, and office log lines pass through `office/redact.py`. Credential POST bodies are not echoed. Optional storage is `OFFICE_HOME/secrets.json`, mode `0600`, AES-GCM with a key derived from `OFFICE_MASTER_KEY`. There is no default master key. If it is unset, the office will not store a credential. Existing `~/.hedge-fund/.env` still loads through `apply_credentials`, and the shell still wins.

### Realtime

`GET /api/events/stream` is server-sent events fed by the same insert path as `events`. The UI does not synthesize desk activity on a timer.

### Limits of this layer

- No live broker and no code path that could place one.
- No CPCV/PBO gate (the engine does not have one).
- Office backtests are capped by `OFFICE_MAX_BACKTEST_SESSIONS` (default 800) so a request cannot run unbounded. The CLI is not capped by the office.
- Minute-cadence paper loops stay on the CLI.
- Per-agent models apply only to funds the office constructs.
- Fixture runs do not prove a provider or a market-data vendor.
