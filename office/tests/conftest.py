"""Isolated office tests. Fixture mode is explicit and labelled."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from office.redact import SECRET_ENV_VARS


@pytest.fixture
def office_env(tmp_path, monkeypatch):
    home = tmp_path / "home"
    monkeypatch.setenv("OFFICE_HOME", str(home))
    monkeypatch.setenv("OFFICE_DB", str(home / "office.sqlite3"))
    monkeypatch.setenv("OFFICE_SECRETS", str(home / "secrets.json"))
    monkeypatch.setenv("OFFICE_PAPER_ROOT", str(tmp_path / "paper"))
    monkeypatch.setenv("OFFICE_RESEARCH_DIR", str(tmp_path / "research"))
    monkeypatch.setenv("OFFICE_MANDATES_DIR", str(tmp_path / "mandates"))
    monkeypatch.setenv("OFFICE_ALLOW_FIXTURES", "1")
    monkeypatch.setenv("OFFICE_EAGER", "1")
    monkeypatch.delenv("OFFICE_MASTER_KEY", raising=False)
    for name in SECRET_ENV_VARS:
        monkeypatch.delenv(name, raising=False)
    return tmp_path


@pytest.fixture
def client(office_env):
    from office.app import create_app
    from office.config import Config

    app = create_app(Config.from_env())
    with TestClient(app) as test:
        yield test
