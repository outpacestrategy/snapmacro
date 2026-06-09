#!/usr/bin/env bash
# SnapMacro launcher. Uses a local virtual environment so it never touches your
# system Python. First run creates the venv + installs deps; every run starts the server.
set -e
cd "$(dirname "$0")/backend"

VENV=".venv"

# 1) Create the virtual environment once.
#    The backend needs Python >= 3.10 (psycopg 3.2 binary wheels have no 3.9 build),
#    so pick the newest available interpreter rather than a bare `python3` (which on
#    macOS is often the system 3.9 and will fail dependency install).
if [ ! -d "$VENV" ]; then
  PYBIN=""
  for cand in python3.13 python3.12 python3.11 python3.10 python3; do
    if command -v "$cand" >/dev/null 2>&1; then
      ver=$("$cand" -c 'import sys;print("%d.%d"%sys.version_info[:2])' 2>/dev/null)
      major=${ver%%.*}; minor=${ver##*.}
      if [ "$major" = "3" ] && [ "${minor:-0}" -ge 10 ]; then PYBIN="$cand"; break; fi
    fi
  done
  if [ -z "$PYBIN" ]; then
    echo "ERROR: need Python >= 3.10 but none found. Install one (e.g. 'brew install python@3.12')." >&2
    exit 1
  fi
  echo "Creating virtual environment with $PYBIN ($($PYBIN --version 2>&1))…"
  "$PYBIN" -m venv "$VENV"
fi

# 2) Use the venv's python/pip directly (no need to 'activate').
PY="$VENV/bin/python"

# 3) Install deps into the venv if missing.
if ! "$PY" -c "import fastapi, pillow_heif, psycopg, psycopg_pool" 2>/dev/null; then
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
