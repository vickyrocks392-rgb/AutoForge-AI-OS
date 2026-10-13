#!/usr/bin/env bash
# PolicyDesk Knowledge Assistant — Launcher Script
set -e

DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$DIR"

# Source virtual environment if present
if [ -d ".venv" ]; then
    source ".venv/bin/activate"
fi

export PYTHONPATH="src:$PYTHONPATH"
PORT="${POLICYDESK_PORT:-8080}"

echo "=========================================================="
echo " Starting PolicyDesk Knowledge Assistant on port ${PORT}..."
echo " Web UI: http://127.0.0.1:${PORT}"
echo "=========================================================="

python3 src/app.py
