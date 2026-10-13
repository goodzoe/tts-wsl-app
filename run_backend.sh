#!/bin/bash
echo "Iniciando Servidor Backend TTS..."
cd backend
python3 -m venv venv
./venv/bin/pip install --upgrade pip
./venv/bin/pip install fastapi uvicorn python-multipart pydantic huggingface-hub requests soundfile
./venv/bin/pip install torch torchaudio --index-url https://download.pytorch.org/whl/cpu
./venv/bin/pip install encodec llama-cpp-python

# Aqui esta el cambio: no corremos en background directamente en el bash
# Asi evitamos que el script termine y mate al proceso (o devuelva a la shell)
./venv/bin/python3 -m uvicorn app:app --host 0.0.0.0 --port 8000
