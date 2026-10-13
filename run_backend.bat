@echo off
echo Iniciando Servidor Backend TTS en WSL...
wsl -d Ubuntu -e bash -c "cd /home/openclaw/.openclaw/workspace/tts-wsl-app && source .venv/bin/activate && cd backend && python3 -m uvicorn app:app --host 0.0.0.0 --port 8000"
pause
