#!/bin/bash
echo "Iniciando Servidor Backend TTS..."
cd backend
python3 -m venv venv
./venv/bin/pip install fastapi uvicorn python-multipart pydantic
./venv/bin/python3 -m uvicorn app:app --host 127.0.0.1 --port 8000
