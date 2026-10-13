@echo off
echo Iniciando la Interfaz UI en Windows Nativo...
REM Requiere tener Python instalado en Windows
python -m venv venv_win
call venv_win\Scripts\activate.bat
pip install customtkinter requests
python frontend\main.py
pause
