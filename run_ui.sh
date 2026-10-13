#!/bin/bash
echo "Iniciando la Interfaz UI del TTS LatAm..."
cd frontend
# --system-site-packages permite heredar python3-tk del sistema (para interfaces graficas en linux)
python3 -m venv --system-site-packages venv
./venv/bin/pip install customtkinter requests
export DISPLAY=:0
export WAYLAND_DISPLAY=wayland-0
./venv/bin/python3 main.py
