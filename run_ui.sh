#!/bin/bash
echo "Iniciando la Interfaz UI del TTS LatAm..."
cd frontend
# Asegurar dependencias de UI
python3 -m venv venv
./venv/bin/pip install customtkinter requests
./venv/bin/python3 main.py
