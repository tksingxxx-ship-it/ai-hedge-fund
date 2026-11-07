"""Run a research mission on native analysts.

Tasks, attempts, findings, and messages are stored before the worker moves
on, so a restart can see how far the mission got.
"""

from __future__ import annotations

import uuid
from datetime import date

from hedge_fund.data.sessions import completed_through
from hedge_fund.fund import FundSpec
from hedge_fund.models import Signal
from hedge_fund.risk.limits import RiskLimits

from office import cio
from office.config import Config
from office.db import (
    add_event, add_message, connect, dumps, loads, row_dict, set_agent_state, transaction, utcnow,
)
from office.fixtures import FixtureDisabled
from office.staffing import ConfigurationRequired, build_fund, data_client

# A follow-up is depth 1. Depth 2 is refused so tasks cannot chain forever.
_MAX_DEPTH = 1


class Cancelled(Exception):
    pass


def _mission(config: Config, mission_id: str) -> dict:
    conn = connect(config)
    try:
        row = conn.execute("SELECT * FROM missions WHERE id=?", (mission_id,)).fetchone()
    finally:
        conn.close()
    if row is None:
        raise KeyError(mission_id)
    data = row_dict(row)
    data["universe"] = loads(data.pop("universe_json"))
    data["strategies"] = loads(data.pop("strategies_json"))
    data["risk"] = loads(data.pop("risk_json"))
    data["budget"] = loads(data.pop("budget_json"))
    data["summary"] = loads(data.get("summary_json"))
    return data


def _tasks(config: Config, mission_id: str) -> list[dict]:
    conn = connect(config)
    try:
        rows = conn.execute(
            "SELECT * FROM tasks WHERE mission_id=? ORDER BY created_at, id", (mission_id,)
        ).fetchall()
    finally:
        conn.close()
    out = []
    for row in rows:
        item = row_dict(row)
        item["depends_on"] = loads(item.pop("depends_on_json"), [])
        item["payload"] = loads(item.get("payload_json"))
        item["result"] = loads(item.get("result_json"))
        out.append(item)
    return out


def _spec(mission: dict) -> FundSpec:
    return FundSpec(
        schema_version=2,
        name=f"research-{mission['id'][:8]}",
        strategies=mission["strategies"],
        risk=mission["risk"],
        capital=mission["capital"],
        rebalance=mission["rebalance"],
        benchmark=mission["benchmark"],
    )


def _cancelled(config: Config, mission_id: str) -> bool:
    conn = connect(config)
    try:
        row = conn.execute("SELECT cancel_requested, status FROM missions WHERE id=?", (mission_id,)).fetchone()
    finally:
        conn.close()
    return row is None or row["cancel_requested"] or row["status"] in {"cancelled", "interrupted"}


def _calls_used(tasks: list[dict]) -> int:
    return sum(1 for t in tasks if t["kind"] == "analyze" and t["status"] in {"working", "completed", "failed"})


def run_mission(config: Config, mission_id: str) -> None:
    mission = _mission(config, mission_id)
    mode = mission["execution_mode"]
    try:
        spec = _spec(mission)
        fund = build_fund(config, spec, mode=mode, blind=False)
        with data_client(config, mode) as client:
            _execute(config, mission, fund, client)
    except Cancelled:
        _finish(config, mission_id, "cancelled", error=None, summary={"cancelled": True})
    except (ConfigurationRequired, FixtureDisabled) as exc:
        _finish(config, mission_id, "failed", error=str(exc), summary=None)
    except Exception as exc:
        from office.redact import redact
        _finish(config, mission_id, "failed", error=redact(f"{type(exc).__name__}: {exc}"), summary=None)


def _execute(config, mission, fund, client) -> None:
    mission_id = mission["id"]
    budget = mission["budget"]
    deadline = _seconds_from_now(budget.get("timeout_seconds") or 120)
    with transaction(config) as conn:
        set_agent_state(conn, "cio", "working", detail=f"mission {mission_id}")
        from office.db import _insert_event
        _insert_event(conn, channel="system", source="cio", entity_type="mission", entity_id=mission_id,
                      state="working", message="CIO started the mission on native analysts.",
                      execution_mode=mission["execution_mode"])
    staff = {strategy.name: models for strategy, models in fund.strategies}
    tasks = _tasks(config, mission_id)
    for task in tasks:
        if task["kind"] != "analyze" or task["status"] != "queued":
            continue
        _check(config, mission_id, deadline)
        model = _find_model(staff, task["strategy"], task["agent"])
        _run_analyze(config, mission, task, model, client)

    tasks = _tasks(config, mission_id)
    _check(config, mission_id, deadline)
    followups = _review(config, mission, tasks, budget, staff)
    for task in followups:
        _check(config, mission_id, deadline)
        model = _find_model(staff, task["strategy"], task["agent"])
        _run_analyze(config, mission, task, model, client)

    _consolidate(config, mission, fund)


def _check(config, mission_id, deadline) -> None:
    if _cancelled(config, mission_id):
        raise Cancelled()
    import time
    if time.monotonic() > deadline:
        raise TimeoutError("mission exceeded its data-budget timeout")


def _seconds_from_now(seconds: int) -> float:
    import time
    return time.monotonic() + seconds


def _find_model(staff, strategy: str | None, agent: str):
    for model in staff.get(strategy) or []:
        if model.name == agent:
            return model
    for models in staff.values():
        for model in models:
            if model.name == agent:
                return model
    raise KeyError(agent)


def _run_analyze(config, mission, task, model, client) -> None:
    stamp = utcnow()
    with transaction(config) as conn:
        conn.execute(
            "UPDATE tasks SET status='working', started_at=?, attempt=1 WHERE id=?",
            (stamp, task["id"]),
        )
        set_agent_state(conn, task["agent"], "working", task_id=task["id"], detail=task.get("ticker"))
        from office.db import _insert_event
        _insert_event(conn, channel="system", source=task["agent"], entity_type="task", entity_id=task["id"],
                      state="working", message=f"{task['agent']} analyzing {task.get('ticker')}",
                      execution_mode=mission["execution_mode"],
                      payload={"ticker": task.get("ticker"), "strategy": task.get("strategy")})
    try:
        signal = model.predict(task["ticker"], mission["as_of"], client)
        if not isinstance(signal, Signal):
            raise TypeError("analyst did not return a Signal")
        price = _price(client, task["ticker"], mission["as_of"])
        result = {
            "fixture": mission["execution_mode"] == "fixture",
            "execution_mode": mission["execution_mode"],
            "signal": signal.model_dump(),
            "data": {
                "source": "fixture" if mission["execution_mode"] == "fixture" else "financialdatasets",
                "as_of": mission["as_of"],
                "price": price,
                "coverage": "ok" if price is not None else "missing",
                "note": "Price is the fixture series." if mission["execution_mode"] == "fixture"
                        else "Price is the provider close on the as-of date, when one was returned.",
            },
        }
        with transaction(config) as conn:
            from office.redact import redact
            conn.execute(
                "UPDATE tasks SET status='completed', finished_at=?, result_json=?, error=NULL WHERE id=?",
                (utcnow(), redact(dumps(result)), task["id"]),
            )
            set_agent_state(conn, task["agent"], "completed", task_id=task["id"],
                            detail=f"{task.get('ticker')} {signal.value:+.2f}")
            from office.db import _insert_event
            _insert_event(conn, channel="system", source=task["agent"], entity_type="task", entity_id=task["id"],
                          state="completed", message=f"{task['agent']} finished {task.get('ticker')}",
                          execution_mode=mission["execution_mode"],
                          payload={"value": signal.value, "abstained": bool(signal.metadata.get("abstained"))})
        if signal.reasoning:
            add_message(config, channel="model", author=task["agent"], body=signal.reasoning,
                        mission_id=mission["id"], task_id=task["id"],
                        execution_mode=mission["execution_mode"])
    except Exception as exc:
        from office.redact import redact
        message = redact(f"{type(exc).__name__}: {exc}")
        with transaction(config) as conn:
            conn.execute(
                "UPDATE tasks SET status='failed', finished_at=?, error=? WHERE id=?",
                (utcnow(), message, task["id"]),
            )
            set_agent_state(conn, task["agent"], "failed", task_id=task["id"], detail=message[:240])
            from office.db import _insert_event
            _insert_event(conn, channel="system", source=task["agent"], entity_type="task", entity_id=task["id"],
                          state="failed", message=message, execution_mode=mission["execution_mode"])


def _price(client, ticker: str, as_of: str):
    try:
        bars = client.get_prices(ticker, as_of, as_of)
    except Exception:
        return None
    matches = [bar for bar in bars if str(bar.time)[:10] == as_of[:10]]
    if not matches:
        return None
    return matches[-1].close


def _review(config, mission, tasks, budget, staff) -> list[dict]:
    """Compare findings, ask each side once, escalate, then maybe one follow-up."""
    analyses = [t for t in tasks if t["kind"] == "analyze" and t["status"] == "completed" and t["result"]]
    by_ticker: dict[str, list] = {}
    for task in analyses:
        by_ticker.setdefault(task["ticker"], []).append(task)
    used = _calls_used(tasks)
    created = []
    conflicts = []
    with transaction(config) as conn:
        set_agent_state(conn, "cio", "reviewing", detail="comparing native signals")
        from office.db import _insert_event
        _insert_event(conn, channel="system", source="cio", entity_type="mission", entity_id=mission["id"],
                      state="reviewing", message="CIO is comparing analyst signals.",
                      execution_mode=mission["execution_mode"])
    for ticker, group in by_ticker.items():
        signals = [Signal.model_validate(t["result"]["signal"]) for t in group]
        if not cio.conflicting(signals):
            continue
        detail = [{
            "agent": s.model_name, "value": s.value,
            "reasoning": s.reasoning, "abstained": bool(s.metadata.get("abstained")),
        } for s in signals]
        conflicts.append({"ticker": ticker, "signals": detail})
        replies = []
        asked = cio.representatives(signals)
        for own in asked:
            if used >= int(budget.get("max_calls") or 0):
                replies.append({
                    "agent": own.model_name, "ticker": ticker, "llm_called": False,
                    "skipped": "data budget exhausted before the challenge",
                })
                continue
            model = _find_model(staff, None, own.model_name)
            if getattr(model, "_llm", None) is not None:
                used += 1
            reply = cio.challenge_view(model, ticker, own, signals)
            reply["fixture"] = mission["execution_mode"] == "fixture"
            replies.append(reply)
            if reply.get("response"):
                add_message(
                    config, channel="model", author=own.model_name, body=reply["response"],
                    mission_id=mission["id"], execution_mode=mission["execution_mode"],
                )
        # Both sides stay on the record. A concession does not delete the original signal.
        already = {t["agent"] for t in tasks if t["ticker"] == ticker and t["kind"] == "analyze"}
        extra = None
        if used < int(budget.get("max_calls") or 0):
            for strategy in mission["strategies"]:
                for model_spec in strategy["models"]:
                    if model_spec["name"] not in already:
                        extra = (strategy["name"], model_spec["name"])
                        break
                if extra:
                    break
        challenge_id = str(uuid.uuid4())
        payload = {
            "conflicts": detail,
            "replies": replies,
            "escalated": True,
            "additional_analyst": extra[1] if extra else None,
            "orders_placed": False,
        }
        with transaction(config) as conn:
            conn.execute(
                """INSERT INTO tasks(id, mission_id, parent_id, agent, strategy, kind, ticker, status,
                     depends_on_json, attempt, max_attempts, depth, payload_json, result_json, created_at, finished_at)
                   VALUES (?, ?, NULL, 'cio', NULL, 'challenge', ?, 'completed', '[]', 1, 1, 1, ?, ?, ?, ?)""",
                (challenge_id, mission["id"], ticker, dumps(payload), dumps(payload), utcnow(), utcnow()),
            )
            from office.db import _insert_event
            _insert_event(conn, channel="system", source="cio", entity_type="task", entity_id=challenge_id,
                          state="reviewing",
                          message=f"Conflict on {ticker}: each side was asked at most once, then escalated to the CIO.",
                          execution_mode=mission["execution_mode"],
                          payload={"ticker": ticker, "replies": len(replies)})
        decision_id = str(uuid.uuid4())
        with transaction(config) as conn:
            conn.execute(
                """INSERT INTO cio_decisions(id, mission_id, kind, body, payload_json, execution_mode, created_at)
                   VALUES (?, ?, 'escalation', ?, ?, ?, ?)""",
                (decision_id, mission["id"],
                 f"Escalated {ticker}. Original signals were not overwritten.",
                 dumps(payload), mission["execution_mode"], utcnow()),
            )
        if extra and int(budget.get("max_rounds") or 1) >= 2:
            follow_id = str(uuid.uuid4())
            with transaction(config) as conn:
                conn.execute(
                    """INSERT INTO tasks(id, mission_id, parent_id, agent, strategy, kind, ticker, status,
                         depends_on_json, attempt, max_attempts, depth, payload_json, created_at)
                       VALUES (?, ?, ?, ?, ?, 'analyze', ?, 'queued', ?, 1, 1, 1, NULL, ?)""",
                    (follow_id, mission["id"], challenge_id, extra[1], extra[0], ticker,
                     dumps([challenge_id]), utcnow()),
                )
            created.append({
                "id": follow_id, "agent": extra[1], "strategy": extra[0], "ticker": ticker,
                "kind": "analyze", "status": "queued",
            })
            used += 1
            add_event(config, channel="system", source="cio", entity_type="task", entity_id=follow_id,
                      state="waiting", message=f"CIO requested {extra[1]} on {ticker} after a conflict.",
                      execution_mode=mission["execution_mode"])
    if conflicts:
        add_message(
            config, channel="system", author="cio",
            body="Conflicting native signals were escalated. No order was created. "
                 + "; ".join(c["ticker"] for c in conflicts),
            mission_id=mission["id"], execution_mode=mission["execution_mode"],
        )
    return created


def _consolidate(config, mission, fund) -> None:
    tasks = _tasks(config, mission["id"])
    grouped: dict[str, list[Signal]] = {}
    for task in tasks:
        if task["kind"] != "analyze" or task["status"] != "completed" or not task.get("result"):
            continue
        grouped.setdefault(task["strategy"], []).append(Signal.model_validate(task["result"]["signal"]))
    risk = RiskLimits.model_validate(mission["risk"])
    proposal = cio.propose(mission["strategies"], grouped, risk)
    proposal["fixture"] = mission["execution_mode"] == "fixture"
    proposal["execution_mode"] = mission["execution_mode"]
    conflicts = [
        loads(t["payload_json"]) if isinstance(t.get("payload_json"), str) else t.get("payload")
        for t in tasks if t["kind"] == "challenge"
    ]
    # tasks from _tasks already parsed payload
    conflicts = [t["payload"] for t in tasks if t["kind"] == "challenge"]
    stored = []
    for group in grouped.values():
        stored.extend(group)
    covered = {t["ticker"] for t in tasks if t["kind"] == "analyze" and t["status"] == "completed"}
    uncovered = [t for t in mission["universe"] if t not in covered]
    discovery = bool(mission["budget"].get("discovery", True))
    summary = {
        "proposal": proposal,
        "conflicts": conflicts,
        "discovery": discovery,
        "opportunities": cio.opportunities(stored) if discovery else [],
        "uncovered": uncovered,
        "discovery_note": (
            "No technical screen. Opportunities are native signals outside the neutral band. "
            "Names past the data budget are listed as uncovered and were not analyzed."
            if discovery else
            "Opportunity list was not requested. The analysts still ran only on the selected symbols. No technical screen was applied."
        ),
        "tasks": len(tasks),
        "completed": sum(1 for t in tasks if t["status"] == "completed"),
        "failed": sum(1 for t in tasks if t["status"] == "failed"),
        "fixture": mission["execution_mode"] == "fixture",
        "cio": (
            "The office CIO compared stored signals, asked at most one language client on each "
            "side of a conflict, and wrote this proposal with blend_signals and apply_limits. "
            "It is not an AlphaModel and it did not call the broker."
        ),
    }
    decision_id = str(uuid.uuid4())
    body = "CIO recorded an allocation proposal from stored signals. No order was sent."
    with transaction(config) as conn:
        conn.execute(
            """INSERT INTO cio_decisions(id, mission_id, kind, body, payload_json, execution_mode, created_at)
               VALUES (?, ?, 'proposal', ?, ?, ?, ?)""",
            (decision_id, mission["id"], body, dumps(proposal), mission["execution_mode"], utcnow()),
        )
        set_agent_state(conn, "cio", "completed", detail="proposal recorded")
        from office.db import _insert_event
        _insert_event(conn, channel="system", source="cio", entity_type="decision", entity_id=decision_id,
                      state="completed", message=body, execution_mode=mission["execution_mode"])
    add_message(config, channel="system", author="cio", body=body, mission_id=mission["id"],
                execution_mode=mission["execution_mode"])
    _finish(config, mission["id"], "completed", error=None, summary=summary)


def _finish(config, mission_id, status, error, summary) -> None:
    with transaction(config) as conn:
        conn.execute(
            "UPDATE missions SET status=?, error=?, summary_json=?, updated_at=? WHERE id=?",
            (status, error, dumps(summary) if summary is not None else None, utcnow(), mission_id),
        )
        from office.db import _insert_event
        _insert_event(conn, channel="system", source="cio", entity_type="mission", entity_id=mission_id,
                      state=status, message=error or f"mission {status}", execution_mode=None)


def queue_analyses(config: Config, mission_id: str, strategies: list[dict], universe: list[str], budget: dict) -> int:
    """Insert analyze tasks up to max_calls. Returns how many were inserted."""
    max_calls = int(budget.get("max_calls") or 0)
    rows = []
    for strategy in strategies:
        for model in strategy["models"]:
            for ticker in universe:
                if len(rows) >= max_calls:
                    break
                rows.append((strategy["name"], model["name"], ticker))
            if len(rows) >= max_calls:
                break
        if len(rows) >= max_calls:
            break
    stamp = utcnow()
    with transaction(config) as conn:
        for strategy, agent, ticker in rows:
            conn.execute(
                """INSERT INTO tasks(id, mission_id, parent_id, agent, strategy, kind, ticker, status,
                     depends_on_json, attempt, max_attempts, depth, created_at)
                   VALUES (?, ?, NULL, ?, ?, 'analyze', ?, 'queued', '[]', 0, 1, 0, ?)""",
                (str(uuid.uuid4()), mission_id, agent, strategy, ticker, stamp),
            )
    return len(rows)


def validate_as_of(value: str) -> str:
    if len(value) != 10:
        raise ValueError("as_of must be YYYY-MM-DD")
    day = date.fromisoformat(value)
    if day.weekday() >= 5:
        raise ValueError("as_of must be a weekday session")
    if value > completed_through():
        raise ValueError(f"as_of {value} is not a completed session (through {completed_through()})")
    return value
