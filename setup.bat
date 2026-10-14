@echo off
title Studio TTS LatAm - Instalador Automatico (Windows)
echo ==================================================================
echo  Studio TTS LatAm - Instalador Automatico (Windows Nativo / WSL2)
echo ==================================================================

where python >nul 2>nul
if %ERRORLEVEL% NEQ 0 (
    echo [INFO] Ejecutando instalador dentro de WSL2...
    wsl.exe bash -lc "chmod +x setup.sh && ./setup.sh"
    pause
    exit /b 0
)

if not exist "backend\venv" (
    echo Creando entorno virtual en backend\venv...
    python -m venv backend\venv
)

call backend\venv\Scripts\activate.bat
python -m pip install --upgrade pip
pip install torch torchvision torchaudio --index-url https://download.pytorch.org/whl/cu121
pip install fastapi uvicorn soundfile numpy scipy tqdm requests pydantic python-multipart customtkinter pygame huggingface_hub transformers accelerate snac omnivoice llama-cpp-python

echo.
echo Instalacion completada!
echo Ejecuta run_backend.bat y run_ui.bat para comenzar.
pause
