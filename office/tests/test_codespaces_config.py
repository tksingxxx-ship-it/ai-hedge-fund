"""The Codespaces files stay fixture-only and do not start work by themselves."""

from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
DEVCONTAINER = ROOT / ".devcontainer" / "devcontainer.json"
SETUP = ROOT / ".devcontainer" / "setup.sh"
PREVIEW = ROOT / ".devcontainer" / "preview.sh"

SECRET_MARKERS = (
    "ANTHROPIC_API_KEY=",
    "OPENAI_API_KEY=",
    "FINANCIAL_DATASETS_API_KEY=",
    "X402_WALLET_PRIVATE_KEY=",
    "sk-ant-",
    "OFFICE_ALLOW_REMOTE=1",
)


def _load() -> dict:
    return json.loads(DEVCONTAINER.read_text())


def test_devcontainer_is_private_fixture_preview():
    spec = _load()
    assert "3.12" in spec["image"]
    assert spec["forwardPorts"] == [8765]
    assert spec["portsAttributes"]["8765"]["visibility"] == "private"
    assert spec["portsAttributes"]["8765"]["onAutoForward"] == "notify"
    assert spec["containerEnv"]["OFFICE_FIXTURE_ONLY"] == "1"
    assert spec["containerEnv"]["OFFICE_HOST"] == "127.0.0.1"
    assert spec["containerEnv"]["OFFICE_PORT"] == "8765"
    assert "OFFICE_ALLOW_REMOTE" not in spec["containerEnv"]
    assert spec["postCreateCommand"] == "bash .devcontainer/setup.sh"
    assert "postStartCommand" not in spec
    assert spec["hostRequirements"]["cpus"] == 2
    blob = DEVCONTAINER.read_text()
    for marker in SECRET_MARKERS:
        assert marker not in blob
    assert "preview.sh" not in spec["postCreateCommand"]


def test_shell_scripts_parse_and_preview_check_is_fixture_only():
    for script in (SETUP, PREVIEW):
        subprocess.run(["bash", "-n", str(script)], check=True)
    env = os.environ.copy()
    env["PREVIEW_CHECK"] = "1"
    env["OFFICE_ALLOW_REMOTE"] = "1"
    env["ANTHROPIC_API_KEY"] = "sk-ant-should-not-leak"
    env["FINANCIAL_DATASETS_API_KEY"] = "fd-should-not-leak"
    proc = subprocess.run(["bash", str(PREVIEW)], cwd=ROOT, env=env, check=True, capture_output=True, text=True)
    text = proc.stdout
    assert "OFFICE_FIXTURE_ONLY=1" in text
    assert "OFFICE_HOST=127.0.0.1" in text
    assert "OFFICE_PORT=8765" in text
    assert "OFFICE_ALLOW_REMOTE=unset" in text
    assert "CREDENTIALS=absent" in text
    assert ".office-preview" in text
    assert "sk-ant-should-not-leak" not in text
    assert "fd-should-not-leak" not in text


def test_preview_does_not_start_a_second_listener():
    import socket

    sock = socket.socket()
    sock.bind(("127.0.0.1", 8765))
    sock.listen(1)
    try:
        proc = subprocess.run(["bash", str(PREVIEW)], cwd=ROOT, capture_output=True, text=True)
    finally:
        sock.close()
    assert proc.returncode == 0
    assert "already in use" in proc.stdout
