#!/usr/bin/env bash
# Idempotent Codespace setup. Installs the engine and office extra and builds
# the UI. Does not start the preview server, create a mission, tick a fund,
# or download a new universe.
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

if ! command -v python3 >/dev/null 2>&1; then
  echo "python3 is required (3.11 or 3.12)." >&2
  exit 1
fi
PY_MAJOR="$(python3 -c 'import sys; print(sys.version_info[0])')"
PY_MINOR="$(python3 -c 'import sys; print(sys.version_info[1])')"
if [[ "$PY_MAJOR" -ne 3 || "$PY_MINOR" -lt 11 || "$PY_MINOR" -gt 12 ]]; then
  echo "This preview expects Python 3.11 or 3.12. Found $(python3 --version)." >&2
  exit 1
fi

export PATH="${HOME}/.local/bin:${PATH}"
if ! command -v poetry >/dev/null 2>&1; then
  python3 -m pip install --user "poetry>=2,<3"
fi

if ! command -v npm >/dev/null 2>&1; then
  echo "npm is required to build the UI. The devcontainer Node feature should provide it." >&2
  exit 1
fi

poetry install --no-interaction --extras office

STAMP_DIR="${ROOT}/.office-preview"
mkdir -p "$STAMP_DIR"
LOCK_HASH="$(sha256sum web/package-lock.json | awk '{print $1}')"
STAMP="${STAMP_DIR}/npm-lock.sha256"
if [[ ! -d web/node_modules || ! -f "$STAMP" || "$(cat "$STAMP")" != "$LOCK_HASH" ]]; then
  (cd web && npm ci)
  printf '%s\n' "$LOCK_HASH" > "$STAMP"
fi

(cd web && npm run build)
rm -rf office/static
mkdir -p office/static
cp -a web/dist/. office/static/

echo "Setup finished. The preview is not running."
echo "Start it with: bash .devcontainer/preview.sh"
echo "Stop it with Ctrl+C in that terminal, or: bash .devcontainer/preview.sh stop"
