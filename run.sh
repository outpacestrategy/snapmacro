#!/usr/bin/env bash
# SnapMacro launcher. Uses a local virtual environment so it never touches your
# system Python. First run creates the venv + installs deps; every run starts the server.
set -e
cd "$(dirname "$0")/backend"

VENV=".venv"

# 1) Create the virtual environment once.
if [ ! -d "$VENV" ]; then
  echo "Creating virtual environment (first run only)…"
  python3 -m venv "$VENV"
fi

# 2) Use the venv's python/pip directly (no need to 'activate').
PY="$VENV/bin/python"

# 3) Install deps into the venv if missing.
if ! "$PY" -c "import fastapi, pillow_heif" 2>/dev/null; then
  echo "Installing/updating dependencies into the virtual environment…"
  "$PY" -m pip install --upgrade pip >/dev/null
  "$PY" -m pip install -r requirements.txt
fi

# 4) Make sure a .env exists.
if [ ! -f .env ]; then
  cp .env.example .env
  echo "Created backend/.env — runs in MOCK mode until you add a GEMINI_API_KEY."
fi

PORT="${PORT:-8000}"
IP=$(ipconfig getifaddr en0 2>/dev/null || ipconfig getifaddr en1 2>/dev/null || echo "your-computer-ip")
echo ""
echo "  SnapMacro running:"
echo "    On this Mac   : http://localhost:$PORT"
echo "    On your phone : http://$IP:$PORT   (same Wi-Fi)"
echo ""
exec "$PY" -m uvicorn app:app --host 0.0.0.0 --port "$PORT"
