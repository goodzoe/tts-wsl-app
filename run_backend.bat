@echo off
echo Iniciando Servidor Backend TTS en WSL...
echo Si es la primera vez, instalara dependencias de IA (puede demorar unos minutos).
wsl -d Ubuntu -e bash -c "cd /home/openclaw/.openclaw/workspace/tts-wsl-app && chmod +x run_backend.sh && ./run_backend.sh"
echo.
echo [ATENCION] El servidor se ha detenido o la ventana de WSL se cerro.
pause
