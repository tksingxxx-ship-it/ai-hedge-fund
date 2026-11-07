# Phase 1 — audit and architecture

Status: complete.

Audited commit: `e8655f10453f0c7c0874c8d691ef5ae2d74dab5c` on `main` of `tksingxxx-ship-it/ai-hedge-fund` before this branch.

## What was read

- `README.md`, `VISION.md`, `ROADMAP.md`, `LICENSE`, `hedge_fund/README.md`, `pyproject.toml`, `Makefile`, `.env.example`, `.gitignore`
- Engine modules under `hedge_fund/`: `run.py`, `models.py`, `paths.py`, `signals/`, `llm/`, `fund/`, `strategies/`, `portfolio/`, `risk/`, `pipeline/`, `backtesting/`, `paper/`, `brokers/`, `data/`, `features/`, `scorecard/`, `tui/` (approval and credential paths), `validation/`

## Verified

- CLI is `aihf` → `hedge_fund.run:main`. There is no separate `aihf` package outside `hedge_fund/`.
- Six native analysts in `ALPHA_MODEL_REGISTRY`. No CIO type in the engine.
- Backtest is `backtest_fund` → `advance`. Paper is `deploy` / `tick` / `Ledger.halt`.
- One LLM model per process via `make_llm`. Providers listed in `llm/registry.py`.
- Financial state lives in the hash-chained ledger and `broker.json`, not in an application database.
- `src/` and `app/` are referenced by docs and are not in the tree.
- `hedge_fund/validation/` has no algorithm.

## Artifact

`docs/ARCHITECTURE.md` maps those symbols to the office routes implemented in later phases.

## Not done in this phase

No application code. Later phases implement the office against this map.
