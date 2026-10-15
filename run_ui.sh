#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$ROOT_DIR/frontend"

if [ -x "$ROOT_DIR/backend/venv/bin/python3" ]; then
    VENV_DIR="$ROOT_DIR/backend/venv"
else
    VENV_DIR="$ROOT_DIR/frontend/venv"
    if [ ! -d "$VENV_DIR" ]; then
        python3 -m venv --system-site-packages "$VENV_DIR"
    fi
    if [ ! -f "$VENV_DIR/.deps_installed" ]; then
        "$VENV_DIR/bin/pip" install -q customtkinter requests pygame
        touch "$VENV_DIR/.deps_installed"
    fi
fi

if [ -S "/mnt/wslg/PulseServer" ]; then
    export PULSE_SERVER="unix:/mnt/wslg/PulseServer"
    export SDL_AUDIODRIVER="pulseaudio"
    export DISPLAY="${DISPLAY:-:0}"
    export WAYLAND_DISPLAY="${WAYLAND_DISPLAY:-wayland-0}"
fi

PYGAME_LIBS="$("$VENV_DIR/bin/python3" -c 'import os, pygame; print(os.path.join(os.path.dirname(pygame.__file__), "..", "pygame.libs"))' 2>/dev/null || true)"
if [ -n "$PYGAME_LIBS" ] && [ -d "$PYGAME_LIBS" ]; then
    export LD_LIBRARY_PATH="$(cd "$PYGAME_LIBS" && pwd):${LD_LIBRARY_PATH:-}"
fi

exec "$VENV_DIR/bin/python3" main.py
