#!/usr/bin/env bash
# Start the office on 127.0.0.1:8765 in fixture-only mode.
# Does not enable remote bind, read API keys, refresh the universe, or run a mission.
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"
PREVIEW="${ROOT}/.office-preview"
PIDFILE="${PREVIEW}/preview.pid"

port_open() {
  python3 - <<'PY'
import socket
import sys
sock = socket.socket()
sock.settimeout(0.2)
code = sock.connect_ex(("127.0.0.1", 8765))
sys.exit(0 if code == 0 else 1)
PY
}

if [[ "${1:-}" == "stop" ]]; then
  if [[ -f "$PIDFILE" ]]; then
    old="$(cat "$PIDFILE")"
    if kill -0 "$old" 2>/dev/null; then
      kill "$old"
      echo "Stopped preview process ${old}."
    else
      echo "No running preview process for pid ${old}."
    fi
    rm -f "$PIDFILE"
  else
    echo "No preview pid file. If a terminal is still running it, press Ctrl+C there."
  fi
  exit 0
fi

unset OFFICE_ALLOW_REMOTE OFFICE_API_TOKEN \
  FINANCIAL_DATASETS_API_KEY X402_WALLET_PRIVATE_KEY \
  ANTHROPIC_API_KEY OPENAI_API_KEY DEEPSEEK_API_KEY GOOGLE_API_KEY \
  TYPESAFE_API_KEY XAI_API_KEY MOONSHOT_API_KEY KIMI_API_KEY \
  OFFICE_MASTER_KEY HEDGE_FUND_LLM_MODEL || true

export OFFICE_FIXTURE_ONLY=1
export OFFICE_HOST=127.0.0.1
export OFFICE_PORT=8765
export OFFICE_HOME="${PREVIEW}"
export OFFICE_DB="${PREVIEW}/office.sqlite3"
export OFFICE_SECRETS="${PREVIEW}/secrets.json"
export OFFICE_PAPER_ROOT="${PREVIEW}/paper"
export OFFICE_RESEARCH_DIR="${PREVIEW}/research"
export OFFICE_MANDATES_DIR="${PREVIEW}/mandates"
export PATH="${HOME}/.local/bin:${PATH}"

if [[ "${PREVIEW_CHECK:-}" == "1" ]]; then
  echo "OFFICE_FIXTURE_ONLY=${OFFICE_FIXTURE_ONLY}"
  echo "OFFICE_HOST=${OFFICE_HOST}"
  echo "OFFICE_PORT=${OFFICE_PORT}"
  echo "OFFICE_HOME=${OFFICE_HOME}"
  echo "OFFICE_PAPER_ROOT=${OFFICE_PAPER_ROOT}"
  if [[ -n "${OFFICE_ALLOW_REMOTE:-}" ]]; then
    echo "OFFICE_ALLOW_REMOTE=${OFFICE_ALLOW_REMOTE}"
  else
    echo "OFFICE_ALLOW_REMOTE=unset"
  fi
  if [[ -n "${ANTHROPIC_API_KEY:-}" || -n "${FINANCIAL_DATASETS_API_KEY:-}" ]]; then
    echo "CREDENTIALS=present"
  else
    echo "CREDENTIALS=absent"
  fi
  exit 0
fi

mkdir -p "$PREVIEW"

if [[ -f "$PIDFILE" ]]; then
  old="$(cat "$PIDFILE")"
  if kill -0 "$old" 2>/dev/null; then
    echo "Preview already running (pid ${old}) on 127.0.0.1:8765."
    echo "Stop it with Ctrl+C in that terminal, or: bash .devcontainer/preview.sh stop"
    exit 0
  fi
  rm -f "$PIDFILE"
fi

if port_open; then
  echo "127.0.0.1:8765 is already in use. Not starting a second preview."
  echo "Stop the existing process, or run: bash .devcontainer/preview.sh stop"
  exit 0
fi

if ! command -v poetry >/dev/null 2>&1; then
  echo "poetry is not on PATH. Run bash .devcontainer/setup.sh first." >&2
  exit 1
fi

echo "$$" > "$PIDFILE"
trap 'rm -f "$PIDFILE"' EXIT
echo "Fixture-only preview on http://127.0.0.1:8765"
echo "Stop this terminal with Ctrl+C. State stays in ${PREVIEW}."
exec poetry run python -m office
