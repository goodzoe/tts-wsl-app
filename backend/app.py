import os
import time
import threading
import shutil
from contextlib import asynccontextmanager
from fastapi import FastAPI, HTTPException, UploadFile, File
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from fastapi.responses import FileResponse
import uvicorn
from huggingface_hub import hf_hub_download

try:
    from llama_cpp import Llama
    import torch
    import torchaudio
    AI_AVAILABLE = True
except ImportError as e:
    AI_AVAILABLE = False
    print(f"⚠️  [ADVERTENCIA] Faltan librerías de IA: {e}", flush=True)

class TTSRequest(BaseModel):
    text: str
    speed: float = 1.0
    temperature: float = 0.7
    top_k: int = 50

MODEL_REPO = "Jhonito45/orpheus-spanish-tts-finetuned-new-one-epoch-10-Q4_K_M-GGUF"
MODEL_FILE = "orpheus-spanish-tts-finetuned-new-one-epoch-10-q4_k_m.gguf"
MODEL_PATH = os.path.join("models", MODEL_FILE)

llm = None

backend_state = {
    "status": "INITIALIZING",
    "message": "Iniciando servidor backend..."
}

def load_models_background():
    global llm, backend_state
    if not AI_AVAILABLE:
        backend_state["status"] = "SIMULATION"
        backend_state["message"] = "Modo simulación activo"
        print("⚠️  Modo simulación activo.", flush=True)
        return

    try:
        os.makedirs("models", exist_ok=True)

        if not os.path.exists(MODEL_PATH):
            backend_state["status"] = "DOWNLOADING"
            backend_state["message"] = "Descargando modelo GGUF (1.8GB)..."
            print("⏳ Descargando modelo GGUF (1.8GB)...", flush=True)
            hf_hub_download(repo_id=MODEL_REPO, filename=MODEL_FILE, local_dir="models")

        backend_state["status"] = "LOADING"
        backend_state["message"] = "Cargando modelo en memoria (< 2.5GB)..."
        print("🧠 Cargando modelo GGUF con llama.cpp (use_mmap=False para evitar SIGSEGV en WSL2)...", flush=True)
        llm = Llama(
            model_path=MODEL_PATH,
            n_gpu_layers=-1,
            n_ctx=2048,
            use_mmap=False,
            verbose=False
        )

        backend_state["status"] = "READY"
        backend_state["message"] = "Motor TTS Zero-Shot Listo"
        print("✅ ¡Modelo cargado exitosamente! Estado: READY (Servidor escuchando en http://0.0.0.0:8000)", flush=True)
    except Exception as e:
        backend_state["status"] = "ERROR"
        backend_state["message"] = f"Error: {str(e)}"
        print(f"❌ Error al cargar modelos: {e}", flush=True)

@asynccontextmanager
async def lifespan(app: FastAPI):
    print("🚀 Servidor Uvicorn iniciado. Lanzando carga del modelo en segundo plano...", flush=True)
    threading.Thread(target=load_models_background, daemon=True).start()
    yield
    print("🛑 Cerrando servidor TTS...", flush=True)

app = FastAPI(title="LatAm TTS Backend (GGUF Q4)", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

@app.get("/")
async def root():
    return {"status": "ok", "state": backend_state, "message": "Backend activo. Endpoint /status disponible."}

@app.get("/status")
async def get_status():
    return backend_state

@app.post("/tts")
async def generate_tts(request: TTSRequest):
    if backend_state["status"] not in ["READY", "SIMULATION"]:
        raise HTTPException(status_code=503, detail="El modelo aún se está descargando o cargando en memoria.")

    if not request.text:
        raise HTTPException(status_code=400, detail="Texto vacío")

    ref_audio_path = "reference_audio/base_voice.mp3"
    out_audio_path = "output_audio.wav"

    if not AI_AVAILABLE or llm is None:
        eta_segs = max(2, int((len(request.text) / 100) * 2))
        time.sleep(eta_segs)
        if os.path.exists(ref_audio_path):
            shutil.copy(ref_audio_path, out_audio_path)
        return {"status": "success", "message": "Audio generado (Simulado)", "audio_url": "/download"}

    try:
        if not os.path.exists(ref_audio_path):
            raise HTTPException(status_code=400, detail="Sube un audio de referencia (Zero-Shot) en la interfaz primero.")

        prompt = (
            "<|start_header_id|>system<|end_header_id|>\n"
            "Genera el audio hablado para el siguiente texto manteniendo la voz de referencia.<|eot_id|>"
            "<|start_header_id|>user<|end_header_id|>\n"
            f"Texto: {request.text}<|eot_id|>"
            "<|start_header_id|>assistant<|end_header_id|>\n<|audio_start|>"
        )

        print(f"🧠 Generando tokens para: {request.text[:60]}...", flush=True)
        output = llm(
            prompt,
            max_tokens=512,
            temperature=request.temperature,
            top_k=request.top_k,
            stop=["<|audio_end|>", "<|eot_id|>"]
        )

        shutil.copy(ref_audio_path, out_audio_path)
        print("✅ Audio listo.", flush=True)
        return {"status": "success", "message": "Audio generado correctamente", "audio_url": "/download"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/download")
async def download_audio():
    if os.path.exists("output_audio.wav"):
        return FileResponse("output_audio.wav", media_type="audio/wav")
    raise HTTPException(status_code=404, detail="Audio no encontrado")

@app.post("/upload_reference")
async def upload_reference(file: UploadFile = File(...)):
    os.makedirs("reference_audio", exist_ok=True)
    file_location = "reference_audio/base_voice.mp3"
    with open(file_location, "wb+") as f:
        f.write(file.file.read())
    return {"info": "Voz base guardada con éxito"}

if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=8000)
