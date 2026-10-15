@echo off
setlocal
echo Iniciando Servidor Backend TTS en WSL...
echo Si es la primera vez, instalara dependencias de IA (puede demorar unos minutos).

set "WIN_DIR=%~dp0"
if "%WIN_DIR:~-1%"=="\" set "WIN_DIR=%WIN_DIR:~0,-1%"

wsl bash -c "cd \"$(wslpath -u '%WIN_DIR%')\" && chmod +x run_backend.sh && ./run_backend.sh"

echo.
echo [ATENCION] El servidor se ha detenido o la ventana de WSL se cerro.
pause
