"""Portfolio figures derived from the engine ledger.

Nothing here is a second set of books. If the broker file and the ledger
disagree, both are shown and the derived P&L is withheld.
"""

from __future__ import annotations

import json
from collections import deque
from pathlib import Path

from hedge_fund.backtesting.fund import performance_metrics
from hedge_fund.data.bars import bars_per_day
from hedge_fund.paper import Ledger, LedgerError, load_deployed
from hedge_fund.paper.deployed import BROKER_FILE
from hedge_fund.scorecard import score

DEFINITIONS = {
    "nav": "Latest SessionRecord.nav: cash plus shares marked at that session's closes. Before any session this is deployed capital, not a return.",
    "total_pnl": "Latest NAV minus deployed capital, when a session exists. Trading costs are already inside NAV. Null when no session has been recorded.",
    "realized_pnl": "FIFO P&L of lots closed by fills in the ledger, using fill prices. Null when the reconstructed share counts do not match the ledger.",
    "unrealized_pnl": "Open FIFO lots marked at the latest session's marks. Null when reconstruction does not match the ledger or a mark is missing.",
    "trading_cost": "Sum of CycleRecord.trading_cost on executed sessions. This is the engine's cost figure, not an estimate.",
    "drawdown": "Peak-to-trough of recorded NAV, the same definition as performance_metrics.",
    "exposure": "Gross is the sum of absolute share-times-mark divided by NAV. Net is signed share-times-mark divided by NAV.",
    "benchmark": "Benchmark closes on the session records, scaled to deployed capital by performance_metrics.",
    "analyst_scores": "hedge_fund.scorecard.score on the ledger. Hit rate and IC are not a per-agent dollar P&L.",
}


def _broker(directory: Path) -> dict:
    raw = json.loads((directory / BROKER_FILE).read_text())
    return {"cash": float(raw["cash"]), "shares": {k: int(v) for k, v in raw.get("shares", {}).items()}}


def _fifo(records):
    lots: dict[str, deque] = {}
    realized = 0.0

    def apply(ticker: str, side: str, qty: int, price: float) -> None:
        nonlocal realized
        signed = qty if side == "buy" else -qty
        book = lots.setdefault(ticker, deque())
        remaining = signed
        while remaining and book and (book[0][0] > 0) != (remaining > 0):
            lot_qty, lot_price = book[0]
            match = min(abs(lot_qty), abs(remaining))
            if lot_qty > 0:
                realized += (price - lot_price) * match
                new_qty = lot_qty - match
                remaining += match
            else:
                realized += (lot_price - price) * match
                new_qty = lot_qty + match
                remaining -= match
            if new_qty == 0:
                book.popleft()
            else:
                book[0] = (new_qty, lot_price)
        if remaining:
            book.append((remaining, price))

    for record in records:
        if record.executed is None:
            continue
        for fill in record.executed.fills:
            apply(fill.ticker, fill.side, fill.quantity, fill.price)
    positions = {ticker: sum(qty for qty, _ in book) for ticker, book in lots.items()}
    positions = {ticker: qty for ticker, qty in positions.items() if qty}
    return realized, positions, lots


def _unrealized(lots, marks) -> float | None:
    total = 0.0
    for ticker, book in lots.items():
        if ticker not in marks:
            return None
        mark = marks[ticker]
        for qty, cost in book:
            if qty > 0:
                total += (mark - cost) * qty
            elif qty < 0:
                total += (cost - mark) * abs(qty)
    return total


def snapshot(directory: Path, *, execution_mode: str) -> dict:
    deployed = load_deployed(directory)
    spec = deployed.spec
    ledger = Ledger(directory)
    error = None
    records = []
    try:
        records = ledger.records()
        state = ledger.replay(spec.capital)
    except LedgerError as exc:
        state = None
        error = str(exc)
    broker = None
    broker_error = None
    try:
        broker = _broker(directory)
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        broker_error = str(exc)

    base = {
        "name": deployed.name,
        "mandate": spec.name,
        "execution_mode": execution_mode,
        "fixture": execution_mode == "fixture",
        "layer": "engine ledger",
        "universe": deployed.universe,
        "benchmark": spec.benchmark,
        "capital": spec.capital,
        "rebalance": spec.rebalance,
        "strategies": [
            {"name": s.name, "display_name": s.title, "weight": s.weight,
             "models": [m.name for m in s.models], "mode": s.blend.mode}
            for s in spec.strategies
        ],
        "halted": None if state is None else state.halted,
        "ledger_error": error,
        "broker_error": broker_error,
        "definitions": DEFINITIONS,
        "sessions": len(records),
        "last_session": records[-1].session if records else None,
    }
    if error or not records or state is None:
        base.update({
            "nav": None if error else spec.capital,
            "nav_is_marked": False,
            "cash": None if error else (state.cash if state else spec.capital),
            "positions": [],
            "total_pnl": None,
            "realized_pnl": None,
            "unrealized_pnl": None,
            "trading_cost": None,
            "daily_returns": [],
            "drawdown": None,
            "exposure": None,
            "metrics": None,
            "scorecard": None,
            "allocation": _mandate_allocation(spec),
            "broker": broker,
            "mismatch": None,
        })
        return base

    latest = records[0] and records[-1]
    nav = latest.nav
    marks = latest.marks
    positions = []
    for ticker, shares in sorted(latest.positions.items()):
        mark = marks.get(ticker)
        positions.append({
            "ticker": ticker,
            "shares": shares,
            "mark": mark,
            "market_value": None if mark is None else shares * mark,
            "mark_session": latest.session,
        })
    gross_abs = sum(abs(p["market_value"]) for p in positions if p["market_value"] is not None)
    net = sum(p["market_value"] for p in positions if p["market_value"] is not None)
    exposure = None
    if nav:
        exposure = {
            "gross": gross_abs / nav,
            "net": net / nav,
            "as_of": latest.session,
        }
    realized, reconstructed, lots = _fifo(records)
    ledger_pos = {t: s for t, s in latest.positions.items() if s}
    matched = reconstructed == ledger_pos
    unrealized = _unrealized(lots, marks) if matched else None
    trading_cost = round(sum(r.executed.trading_cost for r in records if r.executed is not None), 2)
    returns = []
    prev = None
    peak = records[0].nav
    max_dd = 0.0
    underwater = []
    for record in records:
        ret = None if prev is None or prev == 0 else record.nav / prev - 1
        returns.append({"session": record.session, "nav": record.nav, "return": ret,
                        "benchmark_close": record.benchmark_close})
        prev = record.nav
        peak = max(peak, record.nav)
        dd = (peak - record.nav) / peak if peak else 0.0
        max_dd = max(max_dd, dd)
        underwater.append({"session": record.session, "drawdown": dd})
    dates = [r.session for r in records]
    navs = [r.nav for r in records]
    first_bench = records[0].benchmark_close or 1.0
    bench = [spec.capital * r.benchmark_close / first_bench for r in records]
    cycles = [r.executed for r in records if r.executed is not None]
    per_year = bars_per_day(spec.interval_seconds, spec.window) * 252 if spec.is_intraday else 252
    metrics = performance_metrics(spec.capital, dates, navs, bench, cycles, periods_per_year=per_year)
    try:
        card = score(records).model_dump()
    except ValueError:
        card = None
    mismatch = None
    if broker is not None:
        broker_pos = {t: s for t, s in broker["shares"].items() if s}
        if broker_pos != ledger_pos or abs(broker["cash"] - latest.cash) > 0.01:
            mismatch = "broker.json and the latest session record disagree. Figures below are the ledger. The broker is shown separately."
    target = None
    if latest.decision is not None:
        target = {
            "as_of": latest.decision.as_of,
            "final_weights": latest.decision.final_weights,
            "target_weights": latest.decision.target_weights,
            "clamps": [c.model_dump() for c in latest.decision.clamps],
            "strategies": [
                {"name": s.name, "slice": s.slice, "final_contribution": s.final_contribution}
                for s in latest.decision.strategies
            ],
        }
    base.update({
        "nav": nav,
        "nav_is_marked": True,
        "cash": latest.cash,
        "positions": positions,
        "total_pnl": nav - spec.capital,
        "realized_pnl": realized if matched else None,
        "unrealized_pnl": unrealized,
        "pnl_reconstruction": "matched" if matched else "withheld; fill replay does not match ledger positions",
        "trading_cost": trading_cost,
        "daily_returns": returns,
        "drawdown": {"max": max_dd, "series": underwater, "as_of": latest.session},
        "exposure": exposure,
        "metrics": metrics.model_dump(),
        "metrics_source": "hedge_fund.backtesting.fund.performance_metrics",
        "scorecard": card,
        "scorecard_source": "hedge_fund.scorecard.score" if card else None,
        "allocation": target or _mandate_allocation(spec),
        "allocation_source": "latest decision" if target else "mandate weights; no decision recorded",
        "broker": broker,
        "mismatch": mismatch,
        "marks_as_of": latest.session,
        "marks_note": "Marks are the session closes stored on the ledger record, not a live quote.",
    })
    return base


def _mandate_allocation(spec) -> dict:
    total = sum(s.weight for s in spec.strategies) or 1.0
    return {
        "source": "mandate",
        "strategies": [
            {"name": s.name, "slice": s.weight / total, "models": [m.name for m in s.models]}
            for s in spec.strategies
        ],
    }
