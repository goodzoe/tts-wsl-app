#!/bin/bash
echo "Iniciando la Interfaz UI del TTS LatAm..."
cd frontend
# --system-site-packages permite heredar python3-tk del sistema
python3 -m venv --system-site-packages venv
./venv/bin/pip install customtkinter requests
./venv/bin/python3 main.py
