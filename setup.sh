#!/usr/bin/env bash
set -e

cd "$(dirname "$0")"
echo "=================================================================="
echo " 🎙️ Studio TTS LatAm — Instalador Automático (Linux / WSL2 / macOS)"
echo "=================================================================="

if ! command -v python3 &>/dev/null; then
    echo "❌ Python 3 no está instalado. Instálalo con: sudo apt install python3 python3-venv python3-tk"
    exit 1
fi

if [ ! -d "backend/venv" ]; then
    echo "📦 Creando entorno virtual en backend/venv..."
    python3 -m venv backend/venv
fi

source backend/venv/bin/activate
pip install --upgrade pip

if command -v nvidia-smi &>/dev/null; then
    echo "⚡ GPU NVIDIA detectada. Instalando PyTorch con soporte CUDA 12.1..."
    pip install torch torchvision torchaudio --index-url https://download.pytorch.org/whl/cu121
else
    echo "🖥️ Instalando PyTorch (CPU / Apple Silicon)..."
    pip install torch torchvision torchaudio
fi

echo "📦 Instalando dependencias del Backend y Frontend..."
pip install fastapi uvicorn soundfile numpy scipy tqdm requests pydantic python-multipart customtkinter pygame huggingface_hub transformers accelerate snac omnivoice llama-cpp-python

echo "✅ Instalación completada con éxito."
echo "👉 Para iniciar el servidor Backend: ./run_backend.sh"
echo "👉 Para iniciar la interfaz Desktop: ./run_ui.sh"
