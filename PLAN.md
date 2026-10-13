# TTS WSL App Architecture & Plan (Updated Oct 2026 - LatAm Focus)

## 1. Engine Selection (The Core)
The requirement demands a 2026 model, fitting within 5GB VRAM, supporting zero-shot cloning, and explicitly excelling in Latin American/Argentine Spanish (not Castilian Spanish/Chinese-accented models like Qwen).

**Primary Choice: `Orpheus-TTS-Cml-Spanish` (Quantized GGUF / ONNX)**
- Released and heavily trending in late 2026 on HuggingFace.
- It is a fine-tuned conversational Spanish model. A quantized version (`Jhonito45/orpheus-spanish-tts-finetuned-new-one-epoch-10-Q4_K_M-GGUF`) is available, meaning it runs extremely fast and uses **less than 2GB of VRAM**, well below your 5GB limit.
- Supports zero-shot styling based on audio reference.
- Highly adaptable to LatAm accents based on the reference audio you provide.

**Alternative Fallback: `OmniVoice-FastAPI`**
- Released in 2026, supports 600+ languages including robust Latin American Spanish dialects.
- Fits in small VRAM footprints using its Nano/CPU-optimized versions.

## 2. Architecture
- **Backend (Python 3.12+):** A local REST API built with `FastAPI` running inside WSL2. We will use the `llama.cpp` ecosystem or `onnxruntime` to load the Orpheus GGUF/ONNX model into VRAM, expose endpoints to receive text + parameters, and return an audio stream/file.
- **Frontend (UI - Python / CustomTkinter):** A modern, dark-themed native Python desktop app using `CustomTkinter`. It runs on Windows natively (or WSLg) connecting to the local backend.
  - Includes a text input area.
  - Sliders for voice parameters (temperature, speed).
  - A section to upload the reference audio file.
- **Brave Extension (JavaScript):** A Chrome/Brave Manifest V3 extension.
  - Injects a "Listen" floating button in `wtr-lab.com`.
  - Scrapes the chapter text and sends a POST request to `http://127.0.0.1:8000/tts`.

## 3. Execution Steps
1. **Repository Setup:** Ensure `goodzoe/tts-wsl-app` structure is ready.
2. **Backend Development:** Write `FastAPI` wrapper to load the Orpheus GGUF model and handle the inference.
3. **Brave Extension Development:** Write the `content.js` and `manifest.json`.
4. **UI Development:** Write the `CustomTkinter` local control panel.
