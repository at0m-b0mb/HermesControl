#!/usr/bin/env bash
# Launch Hermes Control, creating its virtual environment on first run.
set -euo pipefail
here="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$here"
if [ ! -d .venv ]; then
    echo "First run: creating .venv and installing dependencies…"
    python3 -m venv .venv
    ./.venv/bin/python -m pip install --quiet --upgrade pip
    ./.venv/bin/python -m pip install --quiet -r requirements.txt
fi
exec ./.venv/bin/python -m hermes_control "$@"
