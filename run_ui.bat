@echo off
echo Iniciando la Interfaz UI del TTS LatAm a traves de WSLg...
wsl -d Ubuntu -e bash -c "cd /home/openclaw/.openclaw/workspace/tts-wsl-app && chmod +x run_ui.sh && ./run_ui.sh"
echo.
echo [ATENCION] La interfaz se ha cerrado.
pause
