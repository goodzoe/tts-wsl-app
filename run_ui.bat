@echo off
echo Iniciando la Interfaz UI del TTS LatAm...
REM Si quieres que la UI corra directamente en Windows (fuera de WSL), usarás el Python de Windows.
REM Para probarla fácil desde WSL en Windows (con WSLg), usamos wsl -e.
wsl -d Ubuntu -e bash -c "export DISPLAY=:0 && export WAYLAND_DISPLAY=wayland-0 && cd /home/openclaw/.openclaw/workspace/tts-wsl-app && source .venv/bin/activate && cd frontend && python3 main.py"
pause
