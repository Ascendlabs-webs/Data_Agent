#!/usr/bin/env bash
# Data AI Agent - one-click launcher (macOS / Linux)
set -e
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$SCRIPT_DIR/backend"

export PYTHONPATH="$SCRIPT_DIR:$PYTHONPATH"

echo
echo "=============================================="
echo "  Data AI Agent - one-click launcher"
echo "=============================================="
echo

if [ ! -d venv ]; then
    echo "[1/4] Creating Python virtual environment..."
    python3 -m venv venv
fi
source venv/bin/activate

echo "[2/4] Installing dependencies..."
pip install -q -r requirements.txt

if [ ! -f .env ]; then
    cp .env.example .env
    echo
    echo "============================================================="
    echo "  FIRST-TIME SETUP - one step needed:"
    echo "  Edit backend/.env and set OPENROUTER_API_KEY=..."
    echo "  Get a FREE key at:  https://openrouter.ai/keys"
    echo "  Then run ./run.sh again."
    echo "============================================================="
    echo
    exit 1
fi

echo "[3/4] Starting server..."
(open http://localhost:8000 2>/dev/null || xdg-open http://localhost:8000 2>/dev/null) || true
echo "[4/4] Server running at http://localhost:8000  (press Ctrl+C to stop)"
echo
exec python -m uvicorn app:app --port 8000
