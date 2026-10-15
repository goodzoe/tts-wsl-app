#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$ROOT_DIR"

if [ ! -f "backend/venv/.deps_installed" ]; then
    echo "Entorno no inicializado. Ejecutando setup.sh..."
    chmod +x ./setup.sh
    ./setup.sh
fi

cd "$ROOT_DIR/backend"

if pgrep -f "[u]vicorn app:app" >/dev/null 2>&1; then
    echo "Deteniendo instancia previa de uvicorn..."
    pkill -15 -f "[u]vicorn app:app" 2>/dev/null || true
    sleep 1
    pkill -9 -f "[u]vicorn app:app" 2>/dev/null || true
fi

HOST="${TTS_BACKEND_HOST:-127.0.0.1}"
PORT="${TTS_BACKEND_PORT:-8000}"

echo "Levantando servidor FastAPI en http://${HOST}:${PORT} ..."
exec ./venv/bin/python3 -m uvicorn app:app --host "$HOST" --port "$PORT"
