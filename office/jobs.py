"""Backtest jobs. The worker calls hedge_fund.backtesting.fund.backtest_fund.

Cancellation is checked before the run and on each valuation. A cancelled
job does not write a research file.
"""

from __future__ import annotations

from hedge_fund.backtesting import backtest_fund
from hedge_fund.backtesting.research import save_result
from hedge_fund.data.sessions import completed_through
from hedge_fund.fund import FundSpec
from hedge_fund.scorecard import score

from office.config import Config
from office.db import connect, dumps, loads, row_dict, transaction, utcnow
from office.research import Cancelled
from office.staffing import ConfigurationRequired, build_fund, data_client


class CancelGuard:
    def __init__(self, inner, should_cancel):
        self._inner = inner
        self._should_cancel = should_cancel

    def __getattr__(self, name):
        attr = getattr(self._inner, name)
        if not callable(attr):
            return attr

        def wrapped(*args, **kwargs):
            if self._should_cancel():
                raise Cancelled("cancelled")
            return attr(*args, **kwargs)

        return wrapped


def _job(config: Config, job_id: str) -> dict:
    conn = connect(config)
    try:
        row = conn.execute("SELECT * FROM jobs WHERE id=?", (job_id,)).fetchone()
    finally:
        conn.close()
    if row is None:
        raise KeyError(job_id)
    data = row_dict(row)
    data["request"] = loads(data.pop("request_json"))
    data["result"] = loads(data.get("result_json"))
    data["progress"] = loads(data.get("progress_json"))
    return data


def _cancelled(config: Config, job_id: str) -> bool:
    conn = connect(config)
    try:
        row = conn.execute("SELECT cancel_requested, status FROM jobs WHERE id=?", (job_id,)).fetchone()
    finally:
        conn.close()
    return row is not None and (row["cancel_requested"] or row["status"] == "cancelled")


def run_backtest(config: Config, job_id: str) -> None:
    job = _job(config, job_id)
    if job["status"] in {"completed", "cancelled", "interrupted"}:
        return
    request = job["request"]
    mode = job["execution_mode"]
    try:
        if _cancelled(config, job_id):
            raise Cancelled("cancelled")
        spec = FundSpec.model_validate(request["spec"])
        fund = build_fund(config, spec, mode=mode, blind=True)
        end = min(request["end"], completed_through())
        progress = {"sessions": 0, "total": None, "nav": None}

        def on_valuation(index, total, value):
            progress["sessions"] = index + 1
            progress["total"] = total
            progress["nav"] = value.nav
            with transaction(config) as conn:
                conn.execute(
                    "UPDATE jobs SET progress_json=?, updated_at=? WHERE id=?",
                    (dumps(progress), utcnow(), job_id),
                )
            if _cancelled(config, job_id):
                raise Cancelled("cancelled")

        with data_client(config, mode) as client:
            guarded = CancelGuard(client, lambda: _cancelled(config, job_id))
            result = backtest_fund(
                fund, request["start"], end, guarded, request["universe"],
                on_valuation=on_valuation,
            )
        path = _save(config, result)
        try:
            card = score(result.records).model_dump()
        except ValueError:
            card = None
        summary = {
            "fixture": mode == "fixture",
            "execution_mode": mode,
            "path": str(path),
            "fund": result.fund,
            "start": result.start,
            "end": result.end,
            "rebalance": result.rebalance,
            "benchmark": result.benchmark,
            "universe": result.universe,
            "dates": result.dates,
            "nav": result.nav,
            "benchmark_nav": result.benchmark_nav,
            "metrics": result.metrics.model_dump(),
            "metrics_source": "hedge_fund.backtesting.fund.performance_metrics",
            "n_records": len(result.records),
            "scorecard": card,
            "decisions": [
                {
                    "session": record.session,
                    "nav": record.nav,
                    "rebalance": record.rebalance,
                    "final_weights": None if record.decision is None else record.decision.final_weights,
                    "orders": 0 if record.executed is None else len(record.executed.orders),
                    "clamps": [] if record.decision is None else [c.model_dump() for c in record.decision.clamps],
                }
                for record in result.records
            ],
        }
        with transaction(config) as conn:
            conn.execute(
                """UPDATE jobs SET status='completed', result_ref=?, result_json=?, error=NULL, updated_at=?
                   WHERE id=?""",
                (str(path), dumps(summary), utcnow(), job_id),
            )
    except Cancelled:
        with transaction(config) as conn:
            conn.execute(
                "UPDATE jobs SET status='cancelled', error=NULL, updated_at=? WHERE id=?",
                (utcnow(), job_id),
            )
    except ConfigurationRequired as exc:
        with transaction(config) as conn:
            conn.execute(
                "UPDATE jobs SET status='failed', error=?, updated_at=? WHERE id=?",
                (str(exc), utcnow(), job_id),
            )
    except Exception as exc:
        from office.redact import redact
        message = redact(f"{type(exc).__name__}: {exc}")
        with transaction(config) as conn:
            conn.execute(
                "UPDATE jobs SET status='failed', error=?, updated_at=? WHERE id=?",
                (message, utcnow(), job_id),
            )


def _save(config: Config, result):
    from hedge_fund import paths
    previous = paths.RESEARCH_DIR
    paths.RESEARCH_DIR = config.research_dir
    try:
        return save_result(result)
    finally:
        paths.RESEARCH_DIR = previous
