# Phase 5 — research and portfolio

Status: complete against the ledger and stored signals.

Research proposals call `blend_signals` and `apply_limits` and set `orders_placed` false. Portfolio snapshots call `performance_metrics` and `score` on ledger records. Empty books leave P&L null. A broker/ledger mismatch is reported instead of repaired.

The US swing preset is `office/data/us_swing_ndx_soxx.json` and carries a survivorship warning.
