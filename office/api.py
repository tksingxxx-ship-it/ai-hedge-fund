"""HTTP routes. The handlers validate input and call the engine. They do not size trades themselves."""

from __future__ import annotations

import re
import uuid
from datetime import date

from fastapi import APIRouter, FastAPI, Request
import json
import queue

from fastapi.responses import JSONResponse, StreamingResponse
from pydantic import BaseModel, ConfigDict, Field

from hedge_fund.data.client import has_data_credential
from hedge_fund.data.sessions import completed_through
from hedge_fund.fund import FundSpec, discover_funds, load_spec, save_spec
from hedge_fund.fund.spec import load_strategy
from hedge_fund.paper import Ledger
from hedge_fund.risk.limits import RiskLimits
from hedge_fund.tui.shared import STRATEGY_DIR, VERSION

from office import redact
from office.catalog import analyst_catalog, provider_catalog, strategy_library
from office.config import Config
from office.bus import subscribe, unsubscribe
from office.db import (
    add_event, add_message, connect, dumps, loads, row_dict, set_setting, transaction, utcnow,
)
from office.fixtures import FixtureDisabled
from office.jobs import run_backtest
from office.paperflow import (
    approve, build_plan, clear_halt, create_fund, execute, execute_catch_up, execution_mode, fund_dir, list_funds, set_halt,
)
from office.portfolio import snapshot
from office.research import queue_analyses, run_mission, validate_as_of
from office.runner import submit
from office.secrets import MasterKeyMissing, delete_secret, master_configured, store_secret, stored_names
from office.staffing import agent_model, default_model, live_blockers
from office.universes import parse_universe, swing_preset

router = APIRouter(prefix="/api")


class _Model(BaseModel):
    model_config = ConfigDict(extra="forbid")


def _config(request: Request) -> Config:
    return request.app.state.config


def _error(status: int, code: str, message: str, **extra):
    body = {"error": {"code": code, "message": redact.redact(message), **extra}}
    return JSONResponse(status_code=status, content=body)


def _strategies(names: list[str]) -> list[dict]:
    library = {row["name"]: row for row in strategy_library()}
    chosen = []
    for name in names:
        if name not in library:
            raise ValueError(f"unknown strategy {name}")
        path = STRATEGY_DIR / f"{name}.yaml"
        chosen.append(load_strategy(path).model_dump())
    if not chosen:
        raise ValueError("select at least one strategy")
    return chosen


def _risk(data: dict | None) -> dict:
    base = {
        "max_position_pct": 0.25,
        "max_gross_exposure": 1.0,
        "halve_drawdown_pct": 0.10,
        "max_drawdown_pct": 0.20,
    }
    if data:
        base.update(data)
    return RiskLimits.model_validate(base).model_dump()


_SAFE_NAME = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,63}")


def _safe_name(name: str) -> str:
    if not _SAFE_NAME.fullmatch(name):
        raise ValueError("name must be letters, digits, '.', '_' or '-'")
    return name


def _spec_from_parts(*, name: str, strategies: list[dict], risk: dict, capital: float,
                     rebalance: str, benchmark: str) -> FundSpec:
    _safe_name(name)
    return FundSpec.model_validate({
        "schema_version": 2,
        "name": name,
        "strategies": strategies,
        "risk": risk,
        "capital": capital,
        "rebalance": rebalance,
        "benchmark": benchmark,
    })


class MissionIn(_Model):
    title: str = Field(min_length=1, max_length=160)
    brief: str = ""
    strategies: list[str] = Field(min_length=1)
    tickers: list[str] = []
    preset: str | None = None
    as_of: str
    capital: float = 100_000
    rebalance: str = "weekly"
    benchmark: str = "SPY"
    risk: dict | None = None
    execution_mode: str = "live"
    max_calls: int = Field(default=24, ge=1, le=200)
    max_rounds: int = Field(default=2, ge=1, le=2)
    max_symbols: int = Field(default=20, ge=1, le=80)
    timeout_seconds: int = Field(default=180, ge=5, le=3600)
    discovery: bool = True
    start: bool = False


class MessageIn(_Model):
    body: str = Field(min_length=1, max_length=4000)
    mission_id: str | None = None


class MandateIn(_Model):
    name: str
    strategies: list[str]
    capital: float = 100_000
    rebalance: str = "weekly"
    benchmark: str = "SPY"
    risk: dict | None = None


class BacktestIn(_Model):
    mandate_name: str | None = None
    spec: dict | None = None
    tickers: list[str] = []
    preset: str | None = None
    start: str
    end: str
    execution_mode: str = "live"
    idempotency_key: str | None = None
    max_symbols: int = Field(default=30, ge=1, le=80)


class PaperIn(_Model):
    name: str
    mandate_name: str | None = None
    spec: dict | None = None
    tickers: list[str] = []
    preset: str | None = None
    execution_mode: str = "live"
    max_symbols: int = Field(default=30, ge=1, le=80)


class ApprovalIn(_Model):
    action: str
    sessions: int = 1


class TickIn(_Model):
    approval_id: str


class HaltIn(_Model):
    reason: str = Field(min_length=1, max_length=400)


class ModelIn(_Model):
    model_id: str


class AgentModelIn(_Model):
    agent: str
    model_id: str | None = None


class CredentialIn(_Model):
    env_var: str
    value: str = Field(min_length=1, max_length=4096)


def _mode(config: Config, mode: str) -> str:
    if mode not in {"live", "fixture"}:
        raise ValueError("execution_mode must be live or fixture")
    if mode == "fixture" and not config.allow_fixtures:
        raise FixtureDisabled(
            "Fixture mode is disabled. Start the office with OFFICE_ALLOW_FIXTURES=1 to use it. "
            "Fixture output is not a live market or model run."
        )
    return mode


def _span(start: str, end: str, cap: int) -> None:
    a, b = date.fromisoformat(start), date.fromisoformat(end)
    if a > b:
        raise ValueError("start is after end")
    if end > __import__("hedge_fund.data.sessions", fromlist=["completed_through"]).completed_through():
        raise ValueError("end is not a completed session")
    sessions = sum(1 for i in range((b - a).days + 1) if (a.toordinal() + i) and date.fromordinal(a.toordinal() + i).weekday() < 5)
    if sessions > cap:
        raise ValueError(f"about {sessions} weekday sessions exceeds the office cap of {cap}")


@router.get("/health")
def health(request: Request):
    config = _config(request)
    return {
        "status": "ok",
        "engine_version": VERSION,
        "office": "0.1.0",
        "fixtures_allowed": config.allow_fixtures,
        "live_brokers_enabled": False,
        "data_configured": has_data_credential(),
        "master_key_configured": master_configured(),
        "completed_through": completed_through(),
    }


@router.get("/meta")
def meta(request: Request):
    return {
        "audited_commit": "e8655f10453f0c7c0874c8d691ef5ae2d74dab5c",
        "engine": "hedge_fund",
        "cli": "aihf",
        "cio": "office layer, not an AlphaModel",
        "live_brokers_enabled": False,
        "fixtures_allowed": _config(request).allow_fixtures,
        "architecture": "docs/ARCHITECTURE.md",
    }


@router.get("/agents")
def agents(request: Request):
    return {"agents": _with_runtime(request), "cio": _cio(request)}


@router.get("/agents/{name}")
def agent_detail(name: str, request: Request):
    found = next((row for row in _with_runtime(request) if row["name"] == name), None)
    if found is None:
        return _error(404, "not_found", f"unknown analyst {name}")
    config = _config(request)
    conn = connect(config)
    try:
        tasks = [row_dict(r) for r in conn.execute(
            "SELECT id, mission_id, strategy, kind, ticker, status, error, created_at, started_at, finished_at FROM tasks WHERE agent=? ORDER BY created_at DESC LIMIT 50",
            (name,),
        )]
        findings = []
        for task in tasks:
            full = conn.execute("SELECT result_json, payload_json FROM tasks WHERE id=?", (task["id"],)).fetchone()
            task["result"] = loads(full["result_json"]) if full else None
            if task["result"]:
                findings.append({"task_id": task["id"], "ticker": task["ticker"], "result": task["result"]})
    finally:
        conn.close()
    found["tasks"] = tasks
    found["findings"] = findings
    found["performance_note"] = (
        "Per-agent dollar P&L is not invented. Open a paper fund or backtest scorecard for hit rate and IC."
    )
    return found


@router.get("/tasks/{task_id}")
def task_detail(task_id: str, request: Request):
    config = _config(request)
    conn = connect(config)
    try:
        row = conn.execute("SELECT * FROM tasks WHERE id=?", (task_id,)).fetchone()
        if row is None:
            return _error(404, "not_found", "task not found")
        task = row_dict(row)
        task["depends_on"] = loads(task.pop("depends_on_json"), [])
        task["payload"] = loads(task.pop("payload_json"))
        task["result"] = loads(task.pop("result_json"))
        events = [_event(r) for r in conn.execute(
            "SELECT * FROM events WHERE entity_id=? ORDER BY id", (task_id,)
        )]
    finally:
        conn.close()
    task["events"] = events
    return task


@router.get("/office/floor")
def floor(request: Request):
    return {
        "fixtures_allowed": _config(request).allow_fixtures,
        "cio": _cio(request),
        "desks": _with_runtime(request),
        "note": "Desk state changes only when a task event is stored.",
    }


def _with_runtime(request: Request) -> list[dict]:
    config = _config(request)
    rows = analyst_catalog()
    conn = connect(config)
    try:
        states = {r["agent"]: r for r in conn.execute("SELECT * FROM agent_runtime")}
    finally:
        conn.close()
    for row in rows:
        runtime = states.get(row["name"])
        row["state"] = runtime["state"] if runtime else "idle"
        row["task_id"] = runtime["task_id"] if runtime else None
        row["detail"] = runtime["detail"] if runtime else None
        row["updated_at"] = runtime["updated_at"] if runtime else None
        override = agent_model(config, row["name"])
        row["model"] = {
            "native_default": default_model(config),
            "office_override": override,
            "effective": override or default_model(config),
            "override_layer": "office" if override else "native-default",
        } if row["kind"] == "llm" else {"effective": None, "kind": "quant"}
    return rows


def _cio(request: Request) -> dict:
    config = _config(request)
    conn = connect(config)
    try:
        runtime = conn.execute("SELECT * FROM agent_runtime WHERE agent='cio'").fetchone()
    finally:
        conn.close()
    return {
        "name": "cio",
        "display_name": "Chief Investment Officer",
        "layer": "office",
        "native": False,
        "summary": "Coordinates native analysts and writes proposals. Not a member of ALPHA_MODEL_REGISTRY and cannot place orders.",
        "state": runtime["state"] if runtime else "idle",
        "task_id": runtime["task_id"] if runtime else None,
        "detail": runtime["detail"] if runtime else None,
    }


@router.get("/strategies")
def strategies():
    return {"strategies": strategy_library(), "layer": "native"}


def _preset_path(config: Config):
    return config.home / "universes" / "us-swing-ndx-soxx.json"


@router.get("/universes")
def universes(request: Request):
    preset = swing_preset(_preset_path(_config(request)))
    if preset is None:
        return {
            "presets": [],
            "disabled_reason": (
                "No verified universe is loaded. The office will not offer a hand-written "
                "Nasdaq-100 or SOXX list. Refresh from the publisher files or type symbols."
            ),
        }
    return {"presets": [preset], "disabled_reason": None}


@router.post("/universes/refresh")
def refresh_universe(request: Request):
    """Download the publisher files again. A failed download leaves the previous file."""
    from office.universe_sources import UniverseUnverified, refresh_file
    dest = _preset_path(_config(request))
    try:
        preset = refresh_file(dest)
    except (UniverseUnverified, OSError, ValueError) as exc:
        return _error(502, "refresh_failed", str(exc))
    except Exception as exc:
        return _error(502, "refresh_failed", f"{type(exc).__name__}: {exc}")
    return {"preset": preset, "current": False}


@router.get("/providers")
def providers(request: Request):
    catalog = provider_catalog()
    catalog["default_model"] = default_model(_config(request))
    catalog["stored_credentials"] = stored_names(_config(request).secrets_path)
    catalog["master_key_configured"] = master_configured()
    catalog["data_configured"] = has_data_credential()
    catalog["values_included"] = False
    return catalog


class ParametersIn(_Model):
    timeout_seconds: float = Field(ge=5, le=120)
    max_tokens: int = Field(ge=256, le=8192)


@router.get("/settings/parameters")
def get_parameters(request: Request):
    from office.staffing import llm_parameters
    params = llm_parameters(_config(request))
    return {
        "timeout_seconds": params["timeout"],
        "max_tokens": params["max_tokens"],
        "supported": ["timeout", "max_tokens"],
        "unsupported": ["temperature"],
        "note": "make_llm accepts timeout and max_tokens. It has no temperature argument. These values apply only when the office builds a fund.",
    }


@router.put("/settings/parameters")
def put_parameters(body: ParametersIn, request: Request):
    set_setting(_config(request), "llm_timeout", str(body.timeout_seconds))
    set_setting(_config(request), "llm_max_tokens", str(body.max_tokens))
    return get_parameters(request)


@router.put("/settings/model")
def set_model(body: ModelIn, request: Request):
    known = {row["model_id"] for row in provider_catalog()["models"]}
    if body.model_id not in known:
        return _error(400, "unknown_model", "model is not in the engine registry")
    set_setting(_config(request), "default_model", body.model_id)
    add_event(_config(request), channel="system", source="settings", message=f"Office default model set to {body.model_id}. The CLI is unchanged.")
    return {"default_model": body.model_id, "layer": "office"}


@router.put("/settings/agent-model")
def set_agent_model(body: AgentModelIn, request: Request):
    names = {row["name"] for row in analyst_catalog()}
    if body.agent not in names:
        return _error(404, "not_found", "unknown analyst")
    if body.model_id:
        known = {row["model_id"] for row in provider_catalog()["models"]}
        if body.model_id not in known:
            return _error(400, "unknown_model", "model is not in the engine registry")
        set_setting(_config(request), f"agent_model:{body.agent}", body.model_id)
    else:
        from office.db import transaction as tx
        with tx(_config(request)) as conn:
            conn.execute("DELETE FROM settings WHERE key=?", (f"agent_model:{body.agent}",))
    return {"agent": body.agent, "model_id": body.model_id, "layer": "office"}


@router.post("/settings/credentials")
def put_credential(body: CredentialIn, request: Request):
    try:
        store_secret(_config(request).secrets_path, body.env_var, body.value)
    except MasterKeyMissing as exc:
        return _error(409, "configuration_required", str(exc), missing=["OFFICE_MASTER_KEY"])
    except ValueError as exc:
        return _error(400, "invalid", str(exc))
    add_event(_config(request), channel="system", source="settings",
              message=f"Stored {body.env_var}. The value is not recorded in the audit log.")
    return {"env_var": body.env_var, "stored": True, "value_returned": False}


@router.delete("/settings/credentials/{env_var}")
def remove_credential(env_var: str, request: Request):
    try:
        delete_secret(_config(request).secrets_path, env_var)
    except MasterKeyMissing as exc:
        return _error(409, "configuration_required", str(exc))
    return {"env_var": env_var, "stored": False}


@router.get("/mandates")
def mandates(request: Request):
    rows = []
    for saved in discover_funds(_config(request).mandates_dir):
        rows.append({
            "name": saved.path.stem,
            "path": str(saved.path),
            "error": saved.error,
            "spec": None if saved.spec is None else saved.spec.model_dump(),
        })
    return {"mandates": rows}


@router.post("/mandates")
def create_mandate(body: MandateIn, request: Request):
    try:
        spec = _spec_from_parts(
            name=body.name, strategies=_strategies(body.strategies), risk=_risk(body.risk),
            capital=body.capital, rebalance=body.rebalance, benchmark=body.benchmark,
        )
        path = save_spec(spec, _config(request).mandates_dir)
    except (ValueError, FileExistsError) as exc:
        return _error(400, "invalid", str(exc))
    return {"path": str(path), "spec": spec.model_dump()}


@router.post("/missions")
def create_mission(body: MissionIn, request: Request):
    config = _config(request)
    try:
        mode = _mode(config, body.execution_mode)
        as_of = validate_as_of(body.as_of)
        universe, preset = parse_universe(body.tickers, preset=body.preset, max_symbols=body.max_symbols)
        strategies = _strategies(body.strategies)
        risk = _risk(body.risk)
        spec = _spec_from_parts(
            name="research-draft", strategies=strategies, risk=risk, capital=body.capital,
            rebalance=body.rebalance, benchmark=body.benchmark,
        )
        if mode == "live":
            missing = live_blockers(config, spec)
            if missing:
                return _error(409, "configuration_required", "live research needs credentials", missing=missing)
    except (ValueError, FixtureDisabled) as exc:
        code = "fixture_disabled" if isinstance(exc, FixtureDisabled) else "invalid"
        return _error(400, code, str(exc))
    mission_id = str(uuid.uuid4())
    budget = {
        "max_calls": body.max_calls, "max_rounds": body.max_rounds,
        "max_symbols": body.max_symbols, "timeout_seconds": body.timeout_seconds,
        "discovery": body.discovery,
    }
    stamp = utcnow()
    with transaction(config) as conn:
        conn.execute(
            """INSERT INTO missions(id, title, brief, universe_json, universe_preset, strategies_json, risk_json,
                 capital, rebalance, benchmark, as_of, status, execution_mode, budget_json, created_at, updated_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'draft', ?, ?, ?, ?)""",
            (mission_id, body.title, body.brief, dumps(universe), preset, dumps(strategies), dumps(risk),
             body.capital, body.rebalance, body.benchmark.upper(), as_of, mode, dumps(budget), stamp, stamp),
        )
    if body.brief:
        add_message(config, channel="user", author="user", body=body.brief, mission_id=mission_id, execution_mode=mode)
    add_event(config, channel="system", source="cio", entity_type="mission", entity_id=mission_id,
              state="draft", message=f"Mission drafted over {len(universe)} symbols.", execution_mode=mode)
    queued = queue_analyses(config, mission_id, strategies, universe, budget)
    if body.start:
        return _start(config, mission_id)
    return _mission_out(config, mission_id) | {"queued_tasks": queued}


@router.get("/missions")
def missions(request: Request):
    config = _config(request)
    conn = connect(config)
    try:
        rows = [_mission_row(r) for r in conn.execute("SELECT * FROM missions ORDER BY created_at DESC")]
    finally:
        conn.close()
    return {"missions": rows}


@router.get("/missions/{mission_id}")
def mission_detail(mission_id: str, request: Request):
    try:
        return _mission_out(_config(request), mission_id, with_tasks=True)
    except KeyError:
        return _error(404, "not_found", "mission not found")


@router.post("/missions/{mission_id}/start")
def start_mission(mission_id: str, request: Request):
    return _start(_config(request), mission_id)


@router.post("/missions/{mission_id}/cancel")
def cancel_mission(mission_id: str, request: Request):
    config = _config(request)
    with transaction(config) as conn:
        cur = conn.execute(
            "UPDATE missions SET cancel_requested=1, updated_at=? WHERE id=? AND status IN ('draft', 'running')",
            (utcnow(), mission_id),
        )
        if cur.rowcount == 0:
            return _error(409, "not_running", "mission is not running")
        conn.execute(
            "UPDATE tasks SET status='cancelled', finished_at=? WHERE mission_id=? AND status='queued'",
            (utcnow(), mission_id),
        )
    add_event(config, channel="system", source="user", entity_type="mission", entity_id=mission_id,
              state="cancelled", message="Cancellation requested.")
    return {"id": mission_id, "cancel_requested": True}


@router.post("/cio/coordinate")
def coordinate(body: MissionIn, request: Request):
    body.start = True
    return create_mission(body, request)


@router.get("/cio/decisions")
def decisions(request: Request):
    conn = connect(_config(request))
    try:
        rows = []
        for row in conn.execute("SELECT * FROM cio_decisions ORDER BY created_at DESC LIMIT 100"):
            item = row_dict(row)
            item["payload"] = loads(item.pop("payload_json"))
            rows.append(item)
    finally:
        conn.close()
    return {"decisions": rows}


def _start(config: Config, mission_id: str):
    conn = connect(config)
    try:
        row = conn.execute("SELECT status FROM missions WHERE id=?", (mission_id,)).fetchone()
    finally:
        conn.close()
    if row is None:
        return _error(404, "not_found", "mission not found")
    if row["status"] == "running":
        return _mission_out(config, mission_id)
    if row["status"] not in {"draft"}:
        return _error(409, "not_draft", f"mission is {row['status']}")
    with transaction(config) as conn:
        conn.execute(
            "UPDATE missions SET status='running', updated_at=? WHERE id=? AND status='draft'",
            (utcnow(), mission_id),
        )
    add_event(config, channel="system", source="cio", entity_type="mission", entity_id=mission_id,
              state="working", message="Mission queued for native analysts.")
    with transaction(config) as conn:
        from office.db import set_agent_state
        agents = conn.execute(
            "SELECT DISTINCT agent FROM tasks WHERE mission_id=? AND status='queued'", (mission_id,)
        ).fetchall()
        for agent in agents:
            set_agent_state(conn, agent["agent"], "waiting", detail="mission accepted")
    submit(config, f"mission-{mission_id[:8]}", lambda: run_mission(config, mission_id))
    return _mission_out(config, mission_id, with_tasks=True)


def _mission_row(row) -> dict:
    item = row_dict(row)
    item["universe"] = loads(item.pop("universe_json"))
    item["strategies"] = loads(item.pop("strategies_json"))
    item["risk"] = loads(item.pop("risk_json"))
    item["budget"] = loads(item.pop("budget_json"))
    item["summary"] = loads(item.pop("summary_json"))
    item["fixture"] = item["execution_mode"] == "fixture"
    return item


def _mission_out(config: Config, mission_id: str, with_tasks: bool = False) -> dict:
    conn = connect(config)
    try:
        row = conn.execute("SELECT * FROM missions WHERE id=?", (mission_id,)).fetchone()
        if row is None:
            raise KeyError(mission_id)
        item = _mission_row(row)
        if with_tasks:
            tasks = []
            for task in conn.execute("SELECT * FROM tasks WHERE mission_id=? ORDER BY created_at", (mission_id,)):
                data = row_dict(task)
                data["depends_on"] = loads(data.pop("depends_on_json"), [])
                data["payload"] = loads(data.pop("payload_json"))
                data["result"] = loads(data.pop("result_json"))
                tasks.append(data)
            item["tasks"] = tasks
    finally:
        conn.close()
    return item


@router.get("/portfolio")
def portfolio(request: Request):
    config = _config(request)
    funds = []
    for row in list_funds(config):
        if row.get("error"):
            funds.append(row)
            continue
        try:
            funds.append({
                "name": row["name"],
                "nav": row.get("nav"),
                "capital": row.get("capital"),
                "last_session": row.get("last_session"),
                "halted": row.get("halted"),
                "execution_mode": row["execution_mode"],
                "fixture": row["fixture"],
                "sessions": row.get("sessions"),
            })
        except Exception as exc:
            funds.append({"name": row["name"], "error": redact.redact(str(exc))})
    return {"funds": funds, "note": "Empty means no paper fund is deployed. Figures are not filled in."}


@router.get("/portfolio/{name}")
def portfolio_one(name: str, request: Request):
    config = _config(request)
    try:
        directory = fund_dir(config, name)
        return snapshot(directory, execution_mode=execution_mode(config, name), config=config)
    except FileNotFoundError:
        return _error(404, "not_found", "paper fund not found")
    except Exception as exc:
        return _error(500, "ledger", redact.redact(str(exc)))


@router.get("/paper/funds")
def paper_funds(request: Request):
    return {"funds": list_funds(_config(request))}


@router.post("/paper/funds")
def paper_create(body: PaperIn, request: Request):
    config = _config(request)
    try:
        mode = _mode(config, body.execution_mode)
        spec = _resolve_spec(config, body.mandate_name, body.spec)
        universe, _preset = parse_universe(body.tickers, preset=body.preset, max_symbols=body.max_symbols)
        created = create_fund(config, name=body.name, spec=spec, universe=universe, mode=mode)
    except FileExistsError as exc:
        return _error(409, "exists", str(exc))
    except (ValueError, FixtureDisabled) as exc:
        return _error(400, "invalid", str(exc))
    add_event(config, channel="system", source="paper", entity_type="fund", entity_id=body.name,
              message="Paper fund deployed. No session was run.", execution_mode=mode)
    created["ticked"] = False
    return created


@router.get("/paper/funds/{name}/plan")
def paper_plan(name: str, request: Request):
    try:
        return build_plan(_config(request), name)
    except FileNotFoundError:
        return _error(404, "not_found", "paper fund not found")
    except ValueError as exc:
        return _error(400, "invalid", str(exc))


@router.post("/paper/funds/{name}/approvals")
def paper_approve(name: str, body: ApprovalIn, request: Request):
    if body.action not in {"tick", "redo", "catch_up"}:
        return _error(400, "invalid", "action must be tick, redo, or catch_up")
    try:
        return approve(_config(request), name, body.action, body.sessions)
    except FileNotFoundError:
        return _error(404, "not_found", "paper fund not found")
    except ValueError as exc:
        return _error(409, "not_approvable", str(exc))


@router.post("/paper/funds/{name}/tick")
def paper_tick(name: str, body: TickIn, request: Request):
    try:
        result = execute(_config(request), name, body.approval_id)
    except FileNotFoundError:
        return _error(404, "not_found", "paper fund not found")
    except PermissionError as exc:
        return _error(403, "approval_required", str(exc))
    except ValueError as exc:
        return _error(409, "refused", str(exc))
    except Exception as exc:
        from hedge_fund.pipeline import FundHalted
        from hedge_fund.paper import NothingDue
        code = "halted" if isinstance(exc, FundHalted) else "not_due" if isinstance(exc, NothingDue) else "failed"
        status = 409 if code in {"halted", "not_due"} else 500
        return _error(status, code, str(exc))
    add_event(_config(request), channel="system", source="paper", entity_type="fund", entity_id=name,
              state="completed", message=f"Session {result['record'].get('session')} recorded.",
              execution_mode=result["execution_mode"],
              payload={"fixture": result["fixture"], "nav": result["record"].get("nav")})
    return result


@router.post("/paper/funds/{name}/catch-up")
def paper_catch_up(name: str, body: TickIn, request: Request):
    try:
        result = execute_catch_up(_config(request), name, body.approval_id)
    except FileNotFoundError:
        return _error(404, "not_found", "paper fund not found")
    except PermissionError as exc:
        return _error(403, "approval_required", str(exc))
    except ValueError as exc:
        return _error(409, "refused", str(exc))
    except Exception as exc:
        from hedge_fund.pipeline import FundHalted
        code = "halted" if isinstance(exc, FundHalted) else "failed"
        return _error(409 if code == "halted" else 500, code, str(exc))
    return result


@router.post("/paper/funds/{name}/catch-up/{job_id}/cancel")
def paper_catch_up_cancel(name: str, job_id: str, request: Request):
    config = _config(request)
    with transaction(config) as conn:
        cur = conn.execute(
            """UPDATE jobs SET cancel_requested=1, updated_at=?
               WHERE id=? AND kind='paper_catch_up' AND status='running'""",
            (utcnow(), job_id),
        )
    if cur.rowcount == 0:
        return _error(409, "not_running", "that catch-up is not running")
    return {"id": job_id, "cancel_requested": True, "fund": name}


@router.post("/paper/funds/{name}/halt")
def paper_halt(name: str, body: HaltIn, request: Request):
    try:
        result = set_halt(_config(request), name, body.reason)
    except FileNotFoundError:
        return _error(404, "not_found", "paper fund not found")
    except ValueError as exc:
        return _error(400, "invalid", str(exc))
    add_event(_config(request), channel="system", source="paper", entity_type="fund", entity_id=name,
              state="failed", message=f"Kill switch set: {body.reason}")
    return result


@router.post("/paper/funds/{name}/resume")
def paper_resume(name: str, request: Request):
    try:
        result = clear_halt(_config(request), name)
    except FileNotFoundError:
        return _error(404, "not_found", "paper fund not found")
    add_event(_config(request), channel="system", source="paper", entity_type="fund", entity_id=name,
              message="Kill switch cleared. The next session still requires approval.")
    return result


@router.get("/paper/funds/{name}/sessions")
def paper_sessions(name: str, request: Request):
    try:
        directory = fund_dir(_config(request), name)
    except FileNotFoundError:
        return _error(404, "not_found", "paper fund not found")
    ledger = Ledger(directory)
    rows = [{"session": record.session, "nav": record.nav, "rebalance": record.rebalance,
             "hash": record.hash} for record in ledger.records()]
    return {"sessions": rows, "events": ledger.events(), "execution_mode": execution_mode(_config(request), name)}


@router.get("/paper/funds/{name}/sessions/{session}")
def paper_session(name: str, session: str, request: Request):
    try:
        directory = fund_dir(_config(request), name)
        record = Ledger(directory).read(session)
    except FileNotFoundError:
        return _error(404, "not_found", "paper fund not found")
    except Exception as exc:
        return _error(404, "not_found", redact.redact(str(exc)))
    payload = record.model_dump(mode="json")
    payload["execution_mode"] = execution_mode(_config(request), name)
    payload["fixture"] = payload["execution_mode"] == "fixture"
    return payload


@router.post("/backtests")
def create_backtest(body: BacktestIn, request: Request):
    config = _config(request)
    try:
        mode = _mode(config, body.execution_mode)
        spec = _resolve_spec(config, body.mandate_name, body.spec)
        universe, _preset = parse_universe(body.tickers, preset=body.preset, max_symbols=body.max_symbols)
        _span(body.start, body.end, config.max_backtest_sessions)
        if mode == "live":
            missing = live_blockers(config, spec)
            if missing:
                return _error(409, "configuration_required", "live backtest needs credentials", missing=missing)
    except (ValueError, FixtureDisabled) as exc:
        return _error(400, "invalid", str(exc))
    if body.idempotency_key:
        conn = connect(config)
        try:
            existing = conn.execute("SELECT * FROM jobs WHERE idempotency_key=?", (body.idempotency_key,)).fetchone()
        finally:
            conn.close()
        if existing:
            return _job_out(existing)
    job_id = str(uuid.uuid4())
    request_body = {
        "spec": spec.model_dump(), "universe": universe, "start": body.start, "end": body.end,
    }
    stamp = utcnow()
    with transaction(config) as conn:
        conn.execute(
            """INSERT INTO jobs(id, kind, status, idempotency_key, request_json, execution_mode, created_at, updated_at)
               VALUES (?, 'backtest', 'running', ?, ?, ?, ?, ?)""",
            (job_id, body.idempotency_key, dumps(request_body), mode, stamp, stamp),
        )
    add_event(config, channel="system", source="backtest", entity_type="job", entity_id=job_id,
              state="working", message="Backtest started on backtest_fund.", execution_mode=mode)
    submit(config, f"backtest-{job_id[:8]}", lambda: run_backtest(config, job_id))
    conn = connect(config)
    try:
        row = conn.execute("SELECT * FROM jobs WHERE id=?", (job_id,)).fetchone()
    finally:
        conn.close()
    return _job_out(row)


@router.get("/backtests")
def backtests(request: Request):
    conn = connect(_config(request))
    try:
        rows = [_job_out(r) for r in conn.execute("SELECT * FROM jobs WHERE kind='backtest' ORDER BY created_at DESC")]
    finally:
        conn.close()
    return {"backtests": rows}


@router.get("/backtests/{job_id}")
def backtest_detail(job_id: str, request: Request):
    conn = connect(_config(request))
    try:
        row = conn.execute("SELECT * FROM jobs WHERE id=?", (job_id,)).fetchone()
    finally:
        conn.close()
    if row is None:
        return _error(404, "not_found", "backtest not found")
    return _job_out(row)


@router.post("/backtests/{job_id}/cancel")
def backtest_cancel(job_id: str, request: Request):
    config = _config(request)
    with transaction(config) as conn:
        cur = conn.execute(
            "UPDATE jobs SET cancel_requested=1, updated_at=? WHERE id=? AND status='running'",
            (utcnow(), job_id),
        )
    if cur.rowcount == 0:
        return _error(409, "not_running", "backtest is not running")
    add_event(config, channel="system", source="user", entity_type="job", entity_id=job_id,
              state="cancelled", message="Cancellation requested.")
    return {"id": job_id, "cancel_requested": True}


def _job_out(row) -> dict:
    item = row_dict(row)
    item["request"] = loads(item.pop("request_json"))
    item["result"] = loads(item.pop("result_json"))
    item["progress"] = loads(item.pop("progress_json"))
    item["fixture"] = item["execution_mode"] == "fixture"
    return item


def _resolve_spec(config: Config, mandate_name: str | None, spec: dict | None) -> FundSpec:
    if mandate_name and spec:
        raise ValueError("pass a mandate name or a spec, not both")
    if mandate_name:
        path = config.mandates_dir / f"{mandate_name}.yaml"
        if not path.is_file():
            raise ValueError(f"no mandate named {mandate_name}")
        return load_spec(path)
    if spec:
        parsed = FundSpec.model_validate(spec)
        _safe_name(parsed.name)
        return parsed
    raise ValueError("a mandate or a spec is required")


@router.get("/messages")
def messages(request: Request, mission_id: str | None = None):
    conn = connect(_config(request))
    try:
        if mission_id:
            rows = conn.execute("SELECT * FROM messages WHERE mission_id=? ORDER BY id", (mission_id,)).fetchall()
        else:
            rows = conn.execute("SELECT * FROM messages ORDER BY id DESC LIMIT 300").fetchall()
    finally:
        conn.close()
    return {"messages": [row_dict(r) for r in rows]}


@router.post("/messages")
def post_message(body: MessageIn, request: Request):
    config = _config(request)
    saved = add_message(config, channel="user", author="user", body=body.body, mission_id=body.mission_id)
    note = (
        "Recorded. No analyst was run and no order was sent. "
        "Start a research mission or approve a paper session to use the engine."
    )
    system = add_message(config, channel="system", author="cio", body=note, mission_id=body.mission_id)
    add_event(config, channel="user", source="user", entity_type="message", entity_id=str(saved["id"]),
              message=body.body[:240])
    return {"saved": saved, "cio": system}


@router.get("/events")
def events(request: Request, limit: int = 200):
    limit = max(1, min(limit, 500))
    conn = connect(_config(request))
    try:
        rows = conn.execute("SELECT * FROM events ORDER BY id DESC LIMIT ?", (limit,)).fetchall()
    finally:
        conn.close()
    return {"events": [_event(r) for r in reversed(rows)]}


@router.get("/events/stream")
def event_stream():
    def generate():
        listener = subscribe()
        try:
            yield "event: ready\ndata: {}\n\n"
            while True:
                try:
                    event = listener.get(timeout=15)
                except queue.Empty:
                    yield ": keepalive\n\n"
                    continue
                yield "data: " + json.dumps(event) + "\n\n"
        finally:
            unsubscribe(listener)

    return StreamingResponse(generate(), media_type="text/event-stream")


@router.get("/audit")
def audit(request: Request):
    config = _config(request)
    office_events = events(request, limit=300)["events"]
    engine = []
    for fund in list_funds(config):
        if fund.get("error"):
            continue
        try:
            directory = fund_dir(config, fund["name"])
            for item in Ledger(directory).events():
                engine.append({"fund": fund["name"], **item, "source_layer": "engine"})
        except Exception as exc:
            engine.append({"fund": fund["name"], "error": redact.redact(str(exc)), "source_layer": "engine"})
    return {"office": office_events, "engine": engine}


def _event(row) -> dict:
    item = row_dict(row)
    item["payload"] = loads(item.pop("payload_json"))
    return item


def register(app: FastAPI) -> None:
    app.include_router(router)


