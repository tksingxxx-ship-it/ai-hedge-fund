"""Office API against the real engine, with fixture inputs where noted."""

from __future__ import annotations

import os
import stat
import subprocess
import sys

import pytest
from fastapi.testclient import TestClient

from hedge_fund.data.sessions import completed_through
from office.redact import redact


def test_health_reports_no_live_broker(client):
    body = client.get("/api/health").json()
    assert body["status"] == "ok"
    assert body["live_brokers_enabled"] is False
    assert body["fixtures_allowed"] is True
    assert body["data_configured"] is False


def test_agents_are_the_native_registry(client):
    body = client.get("/api/agents").json()
    names = [row["name"] for row in body["agents"]]
    assert names == ["pead", "buffett", "munger", "graham", "lynch", "druckenmiller"]
    assert all(row["layer"] == "native" for row in body["agents"])
    assert body["cio"]["native"] is False
    assert all(row["state"] == "idle" for row in body["agents"])
    buffett = client.get("/api/agents/buffett").json()
    assert "Warren Buffett" in buffett["system_prompt"]
    assert "api_key" not in buffett


def test_fixture_research_runs_native_agents_and_persists(client):
    as_of = completed_through()
    created = client.post("/api/cio/coordinate", json={
        "title": "Two-name check",
        "brief": "Compare the desk on two symbols.",
        "strategies": ["fundamental-ls", "earnings-drift"],
        "tickers": ["AAPL", "MSFT"],
        "as_of": as_of,
        "execution_mode": "fixture",
        "max_calls": 20,
        "max_symbols": 5,
        "timeout_seconds": 60,
    })
    assert created.status_code == 200, created.text
    mission = created.json()
    assert mission["status"] == "completed"
    assert mission["fixture"] is True
    assert mission["summary"]["proposal"]["orders_placed"] is False
    signals = [
        task["result"]["signal"]
        for task in mission["tasks"]
        if task["kind"] == "analyze" and task["status"] == "completed"
    ]
    assert {s["model_name"] for s in signals} >= {"buffett", "druckenmiller", "pead"}
    assert any(s["reasoning"] and "Fixture response" in s["reasoning"] for s in signals if s["model_name"] == "buffett")
    assert any(task["kind"] == "challenge" for task in mission["tasks"])
    assert mission["summary"]["conflicts"]
    events = client.get("/api/events").json()["events"]
    states = [e["state"] for e in events if e["source"] == "buffett"]
    assert "working" in states and "completed" in states
    again = client.get(f"/api/missions/{mission['id']}").json()
    assert again["status"] == "completed"
    floor = client.get("/api/office/floor").json()
    desk = next(d for d in floor["desks"] if d["name"] == "buffett")
    assert desk["state"] == "completed"


def test_live_research_without_keys_is_configuration_required(office_env, monkeypatch):
    monkeypatch.setenv("OFFICE_ALLOW_FIXTURES", "0")
    from office.app import create_app
    from office.config import Config

    with TestClient(create_app(Config.from_env())) as blocked:
        response = blocked.post("/api/missions", json={
            "title": "Live",
            "strategies": ["deep-value"],
            "tickers": ["AAPL"],
            "as_of": completed_through(),
            "execution_mode": "live",
            "max_symbols": 5,
        })
    assert response.status_code == 409
    assert response.json()["error"]["code"] == "configuration_required"
    assert "sk-" not in response.text


def test_fixture_off_is_rejected(office_env, monkeypatch):
    monkeypatch.setenv("OFFICE_ALLOW_FIXTURES", "0")
    from office.app import create_app
    from office.config import Config

    with TestClient(create_app(Config.from_env())) as blocked:
        response = blocked.post("/api/missions", json={
            "title": "Nope",
            "strategies": ["earnings-drift"],
            "tickers": ["AAPL"],
            "as_of": completed_through(),
            "execution_mode": "fixture",
            "max_symbols": 5,
        })
    assert response.status_code == 400


def test_backtest_uses_engine_and_is_idempotent(client):
    mandate = client.post("/api/mandates", json={
        "name": "swing-desk",
        "strategies": ["deep-value"],
        "rebalance": "weekly",
        "capital": 100000,
    })
    assert mandate.status_code == 200, mandate.text
    payload = {
        "mandate_name": "swing-desk",
        "tickers": ["AAPL", "MSFT"],
        "start": "2024-06-03",
        "end": "2024-06-21",
        "execution_mode": "fixture",
        "idempotency_key": "same-study",
        "max_symbols": 5,
    }
    first = client.post("/api/backtests", json=payload)
    assert first.status_code == 200, first.text
    job = first.json()
    assert job["status"] == "completed"
    assert job["fixture"] is True
    assert job["result"]["metrics_source"].endswith("performance_metrics")
    assert job["result"]["nav"][0] > 0
    assert job["result"]["n_records"] >= 2
    second = client.post("/api/backtests", json=payload)
    assert second.json()["id"] == job["id"]
    listed = client.get("/api/backtests").json()["backtests"]
    assert any(row["id"] == job["id"] for row in listed)


def test_cancel_flag_stops_backtest_before_the_engine_finishes(office_env):
    from office.app import create_app
    from office.config import Config
    from office.db import transaction, utcnow, dumps
    from office.jobs import run_backtest

    app = create_app(Config.from_env())
    with TestClient(app):
        config = app.state.config
        spec = {
            "schema_version": 2,
            "name": "cancel-me",
            "strategies": [{
                "name": "earnings-drift",
                "models": [{"name": "pead"}],
                "blend": {"mode": "long_short", "method": "conviction_weighted", "gross_target": 1.0},
            }],
            "risk": {"max_position_pct": 0.25, "max_gross_exposure": 1.0},
            "capital": 100000,
            "rebalance": "daily",
            "benchmark": "SPY",
        }
        with transaction(config) as conn:
            conn.execute(
                """INSERT INTO jobs(id, kind, status, idempotency_key, request_json, cancel_requested,
                     execution_mode, created_at, updated_at)
                   VALUES ('job-cancel', 'backtest', 'running', NULL, ?, 1, 'fixture', ?, ?)""",
                (dumps({
                    "spec": spec, "universe": ["AAPL"], "start": "2024-06-03", "end": "2024-06-21",
                }), utcnow(), utcnow()),
            )
        run_backtest(config, "job-cancel")
        with TestClient(app) as again:
            body = again.get("/api/backtests/job-cancel").json()
        assert body["status"] == "cancelled"


def test_paper_requires_approval_and_halt_blocks(client):
    mandate = client.post("/api/mandates", json={
        "name": "paper-desk",
        "strategies": ["earnings-drift"],
        "rebalance": "daily",
    })
    assert mandate.status_code == 200, mandate.text
    created = client.post("/api/paper/funds", json={
        "name": "alpha",
        "mandate_name": "paper-desk",
        "tickers": ["AAPL", "MSFT"],
        "execution_mode": "fixture",
        "max_symbols": 5,
    })
    assert created.status_code == 200, created.text
    assert created.json()["ticked"] is False
    again = client.post("/api/paper/funds", json={
        "name": "alpha",
        "mandate_name": "paper-desk",
        "tickers": ["AAPL"],
        "execution_mode": "fixture",
        "max_symbols": 5,
    })
    assert again.status_code == 409

    refused = client.post("/api/paper/funds/alpha/tick", json={"approval_id": "nope"})
    assert refused.status_code == 403
    bypass = client.post("/api/paper/funds/alpha/tick", json={"approval_id": "nope", "force": True})
    assert bypass.status_code == 422
    assert "nope" not in bypass.text

    plan = client.get("/api/paper/funds/alpha/plan").json()
    assert plan["runnable"] is True
    assert plan["fixture"] is True
    assert plan["action"] == "tick"
    approval = client.post("/api/paper/funds/alpha/approvals", json={"action": "tick"})
    assert approval.status_code == 200, approval.text
    ran = client.post("/api/paper/funds/alpha/tick", json={"approval_id": approval.json()["id"]})
    assert ran.status_code == 200, ran.text
    record = ran.json()["record"]
    assert record["fixture"] is True
    assert record["nav"] > 0
    replay = client.post("/api/paper/funds/alpha/tick", json={"approval_id": approval.json()["id"]})
    assert replay.status_code == 200
    assert replay.json()["idempotent"] is True
    assert replay.json()["record"]["hash"] == record["hash"]

    halted = client.post("/api/paper/funds/alpha/halt", json={"reason": "risk review"})
    assert halted.status_code == 200
    second = client.post("/api/paper/funds/alpha/approvals", json={"action": "tick"})
    assert second.status_code == 409
    client.post("/api/paper/funds/alpha/resume")
    portfolio = client.get("/api/portfolio/alpha").json()
    assert portfolio["nav_is_marked"] is True
    assert portfolio["total_pnl"] is not None
    assert portfolio["metrics_source"].endswith("performance_metrics")
    assert portfolio["fixture"] is True
    sessions = client.get("/api/paper/funds/alpha/sessions").json()
    assert sessions["sessions"]


def test_restart_keeps_mission_and_ledger(office_env):
    from office.app import create_app
    from office.config import Config

    def new_client():
        return TestClient(create_app(Config.from_env()))

    with new_client() as first:
        response = first.post("/api/cio/coordinate", json={
            "title": "Persist",
            "strategies": ["earnings-drift"],
            "tickers": ["NVDA"],
            "as_of": completed_through(),
            "execution_mode": "fixture",
            "max_calls": 4,
            "max_symbols": 5,
        })
        assert response.status_code == 200, response.text
        mission_id = response.json()["id"]
        paper = first.post("/api/mandates", json={"name": "keep", "strategies": ["earnings-drift"], "rebalance": "daily"})
        assert paper.status_code == 200
        fund = first.post("/api/paper/funds", json={
            "name": "kept", "mandate_name": "keep", "tickers": ["NVDA"],
            "execution_mode": "fixture", "max_symbols": 5,
        })
        assert fund.status_code == 200, fund.text

    with new_client() as second:
        mission = second.get(f"/api/missions/{mission_id}")
        assert mission.status_code == 200
        assert mission.json()["status"] == "completed"
        listed = second.get("/api/paper/funds").json()["funds"]
        assert any(row["name"] == "kept" for row in listed)
        detail = second.get("/api/portfolio/kept").json()
        assert detail["capital"] == 100000
        assert detail["sessions"] == 0
        assert detail["total_pnl"] is None


def test_validation_and_messages_do_not_echo_secrets(client, monkeypatch):
    secret = "sk-ant-testsecretvalue123456"
    monkeypatch.setenv("ANTHROPIC_API_KEY", secret)
    rejected = client.post("/api/messages", json={"body": f"the key is {secret}", "token": secret})
    assert rejected.status_code == 422
    assert secret not in rejected.text
    saved = client.post("/api/messages", json={"body": f"the key is {secret}"})
    assert saved.status_code == 200
    assert secret not in saved.text
    listed = client.get("/api/messages").text
    assert secret not in listed
    assert "[REDACTED]" in listed
    hidden = redact(f"Authorization: Bearer {secret}")
    assert secret not in hidden
    assert "[REDACTED]" in hidden


def test_credential_store_requires_master_key_and_is_private(office_env, monkeypatch):
    from office.app import create_app
    from office.config import Config

    with TestClient(create_app(Config.from_env())) as bare:
        blocked = bare.post("/api/settings/credentials", json={
            "env_var": "ANTHROPIC_API_KEY", "value": "sk-ant-notstored0123456789",
        })
        assert blocked.status_code == 409
        assert "sk-ant-notstored" not in blocked.text

    monkeypatch.setenv("OFFICE_MASTER_KEY", "office-master-key-for-tests")
    with TestClient(create_app(Config.from_env())) as locked:
        stored = locked.post("/api/settings/credentials", json={
            "env_var": "ANTHROPIC_API_KEY", "value": "sk-ant-storedvalue0123456789",
        })
        assert stored.status_code == 200, stored.text
        assert stored.json()["value_returned"] is False
        assert "sk-ant-storedvalue" not in stored.text
        providers = locked.get("/api/providers").json()
        assert providers["values_included"] is False
        assert any(row["env_var"] == "ANTHROPIC_API_KEY" and row["configured"] for row in providers["models"])
        path = Config.from_env().secrets_path
        mode = stat.S_IMODE(os.stat(path).st_mode)
        assert mode & 0o077 == 0
        assert "sk-ant-storedvalue" not in path.read_text()


def test_universe_preset_warns_and_dedupes(client):
    preset = client.get("/api/universes").json()["presets"][0]
    assert preset["id"] == "us-swing-ndx-soxx"
    assert "survivorship" in preset["survivorship_warning"].lower()
    assert len(preset["tickers"]) == len(set(preset["tickers"]))
    assert "NVDA" in preset["tickers"] and "TSM" in preset["tickers"]


def test_cli_help_still_works():
    for args in (["--help"], ["backtest", "--help"], ["paper", "--help"], ["paper", "tick", "--help"]):
        proc = subprocess.run([sys.executable, "-m", "hedge_fund.run", *args], capture_output=True, text=True)
        assert proc.returncode == 0, proc.stderr
        assert "aihf" in proc.stdout


def test_skip_risk_is_not_a_field(client):
    response = client.post("/api/backtests", json={
        "mandate_name": "missing",
        "tickers": ["AAPL"],
        "start": "2024-06-03",
        "end": "2024-06-07",
        "execution_mode": "fixture",
        "skip_risk": True,
        "max_symbols": 5,
    })
    assert response.status_code == 422
