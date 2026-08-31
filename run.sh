#!/usr/bin/env bash
set -e

DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" >/dev/null 2>&1 && pwd )"
cd "$DIR"

PORT="${PORT:-8000}"

echo "=========================================================="
echo "⚡ Razorpay Autonomous Agent Merchant System"
echo "=========================================================="

if [ "$1" == "test" ]; then
    echo "Running automated test suite..."
    PYTHONPATH=. "$DIR/.venv/bin/pytest" tests/ -v
elif [ "$1" == "sim" ]; then
    echo "Running autonomous AI buyer agent multi-persona simulation..."
    PYTHONPATH=. "$DIR/.venv/bin/python3" simulation/ai_buyer_simulation.py
else
    # If user provided a numeric argument like `./run.sh 8080`, use it as port
    if [[ "$1" =~ ^[0-9]+$ ]]; then
        PORT="$1"
    fi

    # Free the port if an orphaned process is lingering
    if command -v fuser >/dev/null 2>&1; then
        fuser -k "${PORT}/tcp" 2>/dev/null || true
    fi

    echo "Starting FastAPI server on http://0.0.0.0:${PORT}..."
    PYTHONPATH=. "$DIR/.venv/bin/uvicorn" backend.app.main:app --host 0.0.0.0 --port "${PORT}" --reload
fi
