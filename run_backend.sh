#!/bin/bash
echo "Iniciando Servidor Backend TTS..."
cd backend
python3 -m venv venv
./venv/bin/pip install --upgrade pip
./venv/bin/pip install fastapi uvicorn python-multipart pydantic huggingface-hub requests soundfile
# Instalar Torch (CPU) para evitar problemas de dependencias
./venv/bin/pip install torch torchaudio --index-url https://download.pytorch.org/whl/cpu
# Instalar dependencias de IA
./venv/bin/pip install encodec llama-cpp-python
./venv/bin/python3 -m uvicorn app:app --host 0.0.0.0 --port 8000
