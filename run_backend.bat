@echo off
echo Iniciando Servidor Backend TTS en WSL e instalando dependencias de IA...
wsl -d Ubuntu -e bash -c "cd /home/openclaw/.openclaw/workspace/tts-wsl-app && chmod +x run_backend.sh && ./run_backend.sh"
echo El servidor se ha detenido.
pause
