#!/bin/bash
echo "Iniciando la Interfaz UI del TTS LatAm..."
cd "$(dirname "$0")/frontend" || exit 1

if [ ! -d "venv" ]; then
    python3 -m venv --system-site-packages venv
fi

if [ ! -f "venv/.deps_installed" ]; then
    ./venv/bin/pip install -q customtkinter requests pygame
    touch venv/.deps_installed
fi

# Configurar audio WSLg (PulseAudio) para evitar errores ALSA card 0
if [ -S "/mnt/wslg/PulseServer" ]; then
    export PULSE_SERVER="unix:/mnt/wslg/PulseServer"
    export SDL_AUDIODRIVER="pulseaudio"
fi

PYGAME_LIBS="$(pwd)/venv/lib/python3.12/site-packages/pygame.libs"
if [ -d "$PYGAME_LIBS" ]; then
    export LD_LIBRARY_PATH="$PYGAME_LIBS:${LD_LIBRARY_PATH:-}"
fi

export DISPLAY="${DISPLAY:-:0}"
export WAYLAND_DISPLAY="${WAYLAND_DISPLAY:-wayland-0}"
exec ./venv/bin/python3 main.py
