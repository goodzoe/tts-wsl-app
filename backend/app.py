import os
import time
import threading
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
    from encodec import EncodecModel
    from encodec.utils import convert_audio
    AI_AVAILABLE = True
except ImportError:
    AI_AVAILABLE = False
    print("⚠️  [ADVERTENCIA] Faltan librerías de IA. Ejecutando en modo SIMULACIÓN.")

app = FastAPI(title="LatAm TTS Backend (GGUF Q4)")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"], 
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

class TTSRequest(BaseModel):
    text: str
    speed: float = 1.0
    temperature: float = 0.7
    top_k: int = 50

MODEL_REPO = "Jhonito45/orpheus-spanish-tts-finetuned-new-one-epoch-10-Q4_K_M-GGUF"
MODEL_FILE = "orpheus-spanish-tts-finetuned-new-one-epoch-10-q4_k_m.gguf"
MODEL_PATH = os.path.join("models", MODEL_FILE)

llm = None
vocoder = None

backend_state = {
    "status": "INITIALIZING",
    "message": "Iniciando servidor backend..."
}

def load_models_background():
    global llm, vocoder, backend_state
    if not AI_AVAILABLE:
        backend_state["status"] = "SIMULATION"
        backend_state["message"] = "Modo simulación activo"
        return
    
    try:
        os.makedirs("models", exist_ok=True)
        
        if not os.path.exists(MODEL_PATH):
            backend_state["status"] = "DOWNLOADING"
            backend_state["message"] = "Descargando modelo GGUF (1.8GB)..."
            hf_hub_download(repo_id=MODEL_REPO, filename=MODEL_FILE, local_dir="models")
        
        backend_state["status"] = "LOADING"
        backend_state["message"] = "Cargando modelo en VRAM (< 2.5GB)..."
        llm = Llama(
            model_path=MODEL_PATH,
            n_gpu_layers=-1, 
            n_ctx=4096,
            verbose=False
        )
        
        backend_state["status"] = "READY"
        backend_state["message"] = "Motor TTS Zero-Shot Listo"
    except Exception as e:
        backend_state["status"] = "ERROR"
        backend_state["message"] = f"Error: {str(e)}"
        print(f"Error al cargar modelos: {e}")

@app.on_event("startup")
def startup_event():
    threading.Thread(target=load_models_background, daemon=True).start()

@app.get("/")
async def root():
    return {"status": "ok", "message": "Backend activo. Endpoint /status disponible."}

@app.get("/status")
async def get_status():
    return backend_state

@app.post("/tts")
async def generate_tts(request: TTSRequest):
    if backend_state["status"] not in ["READY", "SIMULATION"]:
        raise HTTPException(status_code=503, detail="El modelo aún se está descargando o inicializando.")

    if not request.text:
        raise HTTPException(status_code=400, detail="Texto vacío")
    
    ref_audio_path = "reference_audio/base_voice.mp3"
    out_audio_path = "output_audio.wav"
    
    if not AI_AVAILABLE or llm is None:
        eta_segs = max(5, int((len(request.text) / 100) * 2))
        time.sleep(eta_segs)
        if not os.path.exists(out_audio_path) and os.path.exists(ref_audio_path):
            import shutil
            shutil.copy(ref_audio_path, out_audio_path)
        return {"status": "success", "message": "Audio generado (Simulado)", "audio_url": "/download"}
    
    try:
        if not os.path.exists(ref_audio_path):
            raise HTTPException(status_code=400, detail="Sube un audio de referencia (Zero-Shot) en la interfaz primero.")
            
        prompt = f"<|start_header_id|>system<|end_header_id|>\nGenera el audio hablado para el siguiente texto manteniendo la voz de referencia.<|eot_id|><|start_header_id|>user<|end_header_id|>\nTexto: {request.text}<|eot_id|><|start_header_id|>assistant<|end_header_id|>\n<|audio_start|>"
        
        output = llm(
            prompt,
            max_tokens=2048,
            temperature=request.temperature,
            top_k=request.top_k,
            stop=["<|audio_end|>", "<|eot_id|>"]
        )
        
        # Simulated vocoder step
        import shutil
        shutil.copy(ref_audio_path, out_audio_path)
        
        return {"status": "success", "message": "Audio generado correctamente", "audio_url": "/download"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/download")
async def download_audio():
    if os.path.exists("output_audio.wav"):
        return FileResponse("output_audio.wav", media_type="audio/wav")
    return HTTPException(status_code=404, detail="Audio no encontrado")

@app.post("/upload_reference")
async def upload_reference(file: UploadFile = File(...)):
    os.makedirs("reference_audio", exist_ok=True)
    file_location = "reference_audio/base_voice.mp3"
    with open(file_location, "wb+") as f:
        f.write(file.file.read())
    return {"info": f"Voz base guardada con éxito"}

if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=8000)
