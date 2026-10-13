#!/bin/bash
echo "Iniciando Servidor Backend TTS..."
cd "$(dirname "$0")/backend" || exit 1

if [ ! -d "venv" ]; then
    echo "Creando entorno virtual..."
    python3 -m venv venv
fi

if [ ! -f "venv/.deps_installed" ]; then
    echo "Instalando dependencias de IA..."
    ./venv/bin/pip install --upgrade pip
    ./venv/bin/pip install fastapi uvicorn python-multipart pydantic huggingface-hub requests soundfile
    ./venv/bin/pip install torch torchaudio --index-url https://download.pytorch.org/whl/cpu
    ./venv/bin/pip install encodec llama-cpp-python
    touch venv/.deps_installed
fi

# Liberar el puerto 8000 si quedó algún proceso colgado antes
pkill -9 -f "uvicorn app:app" 2>/dev/null || true

echo "Levantando servidor FastAPI en http://0.0.0.0:8000 ..."
exec ./venv/bin/python3 -m uvicorn app:app --host 0.0.0.0 --port 8000
