#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "$0")"
echo "============================================================"
echo " Studio TTS LatAm - Instalador Automatico (Linux / WSL2 / macOS)"
echo "============================================================"

if ! command -v python3 &>/dev/null; then
    echo "Error: Python 3 no esta instalado. Instalalo con: sudo apt install python3 python3-venv python3-tk"
    exit 1
fi

if [ ! -d "backend/venv" ]; then
    echo "Creando entorno virtual unificado en backend/venv..."
    python3 -m venv --system-site-packages backend/venv
fi

source backend/venv/bin/activate
python3 -m pip install --upgrade pip

if command -v nvidia-smi &>/dev/null; then
    echo "GPU NVIDIA detectada. Instalando PyTorch con soporte CUDA 12.1..."
    pip install torch torchvision torchaudio --index-url https://download.pytorch.org/whl/cu121
    CMAKE_ARGS="-DGGML_CUDA=on" pip install llama-cpp-python
elif [ "$(uname -s)" = "Darwin" ]; then
    echo "macOS detectado. Instalando PyTorch y llama-cpp-python con soporte Metal..."
    pip install torch torchvision torchaudio
    CMAKE_ARGS="-DGGML_METAL=on" pip install llama-cpp-python
else
    echo "Instalando PyTorch y llama-cpp-python (CPU)..."
    pip install torch torchvision torchaudio
    pip install llama-cpp-python
fi

echo "Instalando dependencias del Backend y Frontend..."
pip install \
    fastapi uvicorn python-multipart pydantic requests \
    huggingface-hub transformers accelerate snac \
    soundfile numpy scipy tqdm psutil \
    customtkinter pygame
pip install --no-deps omnivoice

touch backend/venv/.deps_installed
echo "Instalacion completada con exito."
echo "Para iniciar el servidor Backend: ./run_backend.sh"
echo "Para iniciar la interfaz Desktop: ./run_ui.sh"
