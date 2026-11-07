"""Paper funds through the existing deploy / tick / halt functions.

Creating a fund does not tick it. Ticking requires an approval whose hash
still matches the plan. The kill switch is Ledger.halt, and advance refuses
a halted fund before it touches the broker.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

from hedge_fund.fund import FundSpec, normalize_universe
from hedge_fund.paper import (
    Ledger,
    LedgerError,
    NothingDue,
    deploy,
    list_deployed,
    load_deployed,
    next_session,
    redo,
    tick,
    validate_fund_name,
)
from hedge_fund.pipeline import FundHalted
from hedge_fund.paper.ledger import Ledger as LedgerCls

from office.config import Config
from office.db import connect, dumps, loads, row_dict, transaction, utcnow
from office.fixtures import FixtureDisabled
from office.staffing import ConfigurationRequired, build_fund, data_client, live_blockers

_MINUTE = (
    "This fund rebalances every bar. The office does not start the unattended "
    "runner, because that would trade without a fresh approval on each bar. "
    "Use `aihf paper run` on the CLI if you want that loop. Halt and resume still work here."
)


def fund_dir(config: Config, name: str) -> Path:
    validate_fund_name(name)
    directory = config.paper_root / name
    if not (directory / "fund.yaml").is_file():
        raise FileNotFoundError(name)
    return directory


def execution_mode(config: Config, name: str) -> str:
    conn = connect(config)
    try:
        row = conn.execute("SELECT execution_mode FROM paper_meta WHERE name=?", (name,)).fetchone()
    finally:
        conn.close()
    return row["execution_mode"] if row else "unspecified"


def list_funds(config: Config) -> list[dict]:
    rows = []
    for directory in list_deployed(config.paper_root):
        mode = execution_mode(config, directory.name)
        try:
            deployed = load_deployed(directory)
            ledger = Ledger(directory)
            latest = ledger.latest()
            halted = ledger.halted()
            rows.append({
                "name": deployed.name,
                "mandate": deployed.spec.name,
                "universe": deployed.universe,
                "capital": deployed.spec.capital,
                "rebalance": deployed.spec.rebalance,
                "execution_mode": mode,
                "fixture": mode == "fixture",
                "sessions": len(ledger.sessions()),
                "last_session": None if latest is None else latest.session,
                "nav": None if latest is None else latest.nav,
                "halted": halted,
                "intraday": deployed.spec.is_intraday,
            })
        except (ValueError, LedgerError) as exc:
            rows.append({"name": directory.name, "error": str(exc), "execution_mode": mode})
    return rows


def create_fund(config: Config, *, name: str, spec: FundSpec, universe: list[str], mode: str) -> dict:
    validate_fund_name(name)
    if spec.is_intraday:
        raise ValueError(_MINUTE)
    universe = normalize_universe(universe)
    if mode == "live":
        missing = live_blockers(config, spec)
        # Deploy itself does not call the network. Missing keys are recorded
        # so the first tick fails closed, but the fund can still be created.
        _ = missing
    elif mode == "fixture" and not config.allow_fixtures:
        raise FixtureDisabled("Fixture mode is off.")
    elif mode not in {"live", "fixture"}:
        raise ValueError("execution_mode must be live or fixture")
    directory = deploy(name, spec, universe, root=config.paper_root)
    with transaction(config) as conn:
        conn.execute(
            "INSERT INTO paper_meta(name, directory, execution_mode, created_at) VALUES (?, ?, ?, ?)",
            (name, str(directory), mode, utcnow()),
        )
    return {"name": name, "directory": str(directory), "execution_mode": mode, "ticked": False}


def build_plan(config: Config, name: str) -> dict:
    directory = fund_dir(config, name)
    deployed = load_deployed(directory)
    mode = execution_mode(config, name)
    ledger = LedgerCls(directory)
    try:
        state = ledger.replay(deployed.spec.capital)
        latest = ledger.latest()
    except LedgerError as exc:
        return {"name": name, "runnable": False, "reason": str(exc), "execution_mode": mode, "fixture": mode == "fixture"}
    plan = {
        "name": name,
        "execution_mode": mode,
        "fixture": mode == "fixture",
        "intraday": deployed.spec.is_intraday,
        "halted": state.halted,
        "last_session": state.last_session,
        "nav": None if latest is None else latest.nav,
        "cash": state.cash,
        "positions": state.positions,
        "universe": deployed.universe,
        "pending_as_of": None if state.pending is None else state.pending.as_of,
        "pending_weights": None if state.pending is None else state.pending.final_weights,
        "runnable": False,
        "action": None,
        "session": None,
        "reason": None,
    }
    if deployed.spec.is_intraday:
        plan["reason"] = _MINUTE
        plan["plan_hash"] = _hash(plan)
        return plan
    if state.halted:
        plan["reason"] = f"halted: {state.halted}"
        plan["plan_hash"] = _hash(plan)
        return plan
    if mode == "unspecified":
        plan["reason"] = (
            "This fund was not created by the office, so its data source is not labelled. "
            "The office will not tick it. Use the CLI, or deploy a new fund here."
        )
        plan["plan_hash"] = _hash(plan)
        return plan
    try:
        with data_client(config, mode) as client:
            due = next_session(client, deployed.spec, state.last_session)
    except (ConfigurationRequired, FixtureDisabled) as exc:
        plan["reason"] = str(exc)
        plan["configuration_required"] = True
        plan["plan_hash"] = _hash(plan)
        return plan
    if due is not None:
        plan["action"] = "tick"
        plan["session"] = due
        plan["runnable"] = True
        plan["reason"] = f"Next unrecorded session is {due}. Nothing has been sent to the broker."
    elif state.last_session is not None:
        plan["action"] = "redo"
        plan["session"] = state.last_session
        plan["runnable"] = True
        plan["reason"] = (
            f"No new session is due. Approving will redo {state.last_session} and replace that ledger record."
        )
    else:
        plan["reason"] = "No completed session is available to run."
    plan["plan_hash"] = _hash(plan)
    return plan


def _hash(plan: dict) -> str:
    body = {
        "name": plan["name"],
        "action": plan.get("action"),
        "session": plan.get("session"),
        "universe": plan.get("universe"),
        "halted": plan.get("halted"),
        "pending_weights": plan.get("pending_weights"),
        "nav": plan.get("nav"),
    }
    return hashlib.sha256(json.dumps(body, sort_keys=True, default=str).encode()).hexdigest()


def approve(config: Config, name: str, action: str) -> dict:
    plan = build_plan(config, name)
    if not plan.get("runnable") or plan.get("action") != action:
        raise ValueError(plan.get("reason") or "nothing to approve")
    approval_id = __import__("uuid").uuid4().hex
    with transaction(config) as conn:
        conn.execute(
            """INSERT INTO approvals(id, fund_name, action, session, plan_hash, plan_json, status, created_at)
               VALUES (?, ?, ?, ?, ?, ?, 'approved', ?)""",
            (approval_id, name, action, plan.get("session"), plan["plan_hash"], dumps(plan), utcnow()),
        )
    return {"id": approval_id, "status": "approved", "plan": plan}


def _approval(config: Config, approval_id: str) -> dict | None:
    conn = connect(config)
    try:
        row = conn.execute("SELECT * FROM approvals WHERE id=?", (approval_id,)).fetchone()
    finally:
        conn.close()
    if row is None:
        return None
    data = row_dict(row)
    data["plan"] = loads(data.pop("plan_json"))
    data["result"] = loads(data.get("result_json"))
    return data


def execute(config: Config, name: str, approval_id: str) -> dict:
    approval = _approval(config, approval_id)
    if approval is None or approval["fund_name"] != name:
        raise PermissionError("approval not found for this fund")
    if approval["status"] == "consumed" and approval.get("result"):
        return {"idempotent": True, "approval_id": approval_id, "record": approval["result"],
                "execution_mode": execution_mode(config, name), "fixture": execution_mode(config, name) == "fixture"}
    if approval["status"] != "approved":
        raise PermissionError(f"approval is {approval['status']}")
    plan = build_plan(config, name)
    if plan.get("plan_hash") != approval["plan_hash"] or plan.get("action") != approval["action"]:
        raise ValueError("the plan changed since approval; approve the current plan")
    if not plan.get("runnable"):
        raise ValueError(plan.get("reason") or "fund is not runnable")
    with transaction(config) as conn:
        cur = conn.execute(
            """UPDATE approvals SET status='consumed', consumed_at=?
               WHERE id=? AND status='approved' AND plan_hash=?""",
            (utcnow(), approval_id, approval["plan_hash"]),
        )
        if cur.rowcount != 1:
            raise PermissionError("approval was already used")
    directory = fund_dir(config, name)
    mode = execution_mode(config, name)
    deployed = load_deployed(directory)
    try:
        with data_client(config, mode, live_quotes=deployed.spec.is_intraday) as client:
            def builder(spec: FundSpec):
                return build_fund(config, spec, mode=mode, blind=False)
            if approval["action"] == "redo":
                record = redo(directory, client, build_fund=builder)
            else:
                record = tick(directory, client, build_fund=builder)
    except (FundHalted, NothingDue, LedgerError, ConfigurationRequired, FixtureDisabled, ValueError) as exc:
        from office.redact import redact
        message = redact(str(exc))
        with transaction(config) as conn:
            conn.execute("UPDATE approvals SET error=? WHERE id=?", (message, approval_id))
        raise
    payload = record.model_dump(mode="json")
    payload["fixture"] = mode == "fixture"
    payload["execution_mode"] = mode
    with transaction(config) as conn:
        conn.execute("UPDATE approvals SET result_json=? WHERE id=?", (dumps(payload), approval_id))
    return {"idempotent": False, "approval_id": approval_id, "record": payload,
            "execution_mode": mode, "fixture": mode == "fixture"}


def set_halt(config: Config, name: str, reason: str) -> dict:
    if not reason or not reason.strip():
        raise ValueError("a halt reason is required")
    directory = fund_dir(config, name)
    Ledger(directory).halt(reason.strip())
    return {"name": name, "halted": reason.strip()}


def clear_halt(config: Config, name: str) -> dict:
    directory = fund_dir(config, name)
    Ledger(directory).resume()
    return {"name": name, "halted": None}
