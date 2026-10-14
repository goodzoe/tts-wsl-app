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
    ./venv/bin/pip install fastapi uvicorn python-multipart pydantic huggingface-hub requests soundfile tqdm numpy
    ./venv/bin/pip install torch torchvision torchaudio --index-url https://download.pytorch.org/whl/cu121
    ./venv/bin/pip install snac llama-cpp-python accelerate librosa
    ./venv/bin/pip install --no-deps omnivoice pydub
    touch venv/.deps_installed
fi

# Liberar el puerto 8000 si quedó algún proceso uvicorn colgado antes
pkill -9 -f "[u]vicorn app:app" 2>/dev/null || true

echo "Levantando servidor FastAPI en http://0.0.0.0:8000 ..."
exec ./venv/bin/python3 -m uvicorn app:app --host 0.0.0.0 --port 8000
