# Phase 6 — backtest and paper

Status: complete on the existing engines.

Backtests call `hedge_fund.backtesting.fund.backtest_fund` and `save_result`. Cancellation is checked before the run and on each valuation.

Paper uses `deploy` and `tick` / `redo`. `tick` without a matching unconsumed approval returns 403. A body field `force` is rejected (422). A halted fund cannot be approved. The same approval returns the stored record the second time. `Ledger.halt` is the kill switch.

Minute-bar unattended running stays on `aihf paper run`.
