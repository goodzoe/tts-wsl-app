import os
import time
import threading
import shutil
import numpy as np
import soundfile as sf
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
    from snac import SNAC
    AI_AVAILABLE = True
except ImportError as e:
    AI_AVAILABLE = False
    print(f"⚠️  [ADVERTENCIA] Faltan librerías de IA: {e}", flush=True)

class TTSRequest(BaseModel):
    text: str
    speed: float = 1.0
    temperature: float = 0.65
    top_k: int = 50

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
MODEL_REPO = "Jhonito45/orpheus-spanish-tts-finetuned-new-one-epoch-10-Q4_K_M-GGUF"
MODEL_FILE = "orpheus-spanish-tts-finetuned-new-one-epoch-10-q4_k_m.gguf"
MODEL_PATH = os.path.join(BASE_DIR, "models", MODEL_FILE)
SNAC_REPO = "hubertsiuzdak/snac_24khz"
DEFAULT_REF_AUDIO = os.path.join(BASE_DIR, "reference_audio", "base_voice.mp3")
OUT_AUDIO_PATH = os.path.join(BASE_DIR, "output_audio.wav")

llm = None
snac_model = None
llm_lock = threading.Lock()
cached_ref_tokens = None
cached_ref_mtime = None

backend_state = {
    "status": "INITIALIZING",
    "message": "Iniciando servidor backend...",
    "default_reference_path": DEFAULT_REF_AUDIO,
}

def encode_reference_audio_to_tokens(audio_path: str, max_seconds: float = 3.0) -> list[int]:
    """Codifica los primeros segundos del audio de referencia en tokens SNAC para condicionamiento Zero-Shot."""
    global snac_model, cached_ref_tokens, cached_ref_mtime
    if snac_model is None or not os.path.exists(audio_path):
        return []
    try:
        mtime = os.path.getmtime(audio_path)
        if cached_ref_tokens is not None and cached_ref_mtime == mtime:
            return cached_ref_tokens

        waveform, sr = torchaudio.load(audio_path)
        if waveform.shape[0] > 1:
            waveform = waveform.mean(dim=0, keepdim=True)
        if sr != 24000:
            waveform = torchaudio.functional.resample(waveform, sr, 24000)
        max_samples = int(24000 * max_seconds)
        waveform = waveform[:, :max_samples]

        with torch.no_grad():
            codes = snac_model.encode(waveform.unsqueeze(0))

        c0 = codes[0].squeeze(0).cpu().tolist()
        c1 = codes[1].squeeze(0).cpu().tolist()
        c2 = codes[2].squeeze(0).cpu().tolist()

        AUDIO_TOKEN_OFFSET = 128266
        interleaved = []
        n_frames = min(len(c0), len(c1) // 2, len(c2) // 4)
        for i in range(n_frames):
            interleaved.extend([
                int(c0[i]) + AUDIO_TOKEN_OFFSET,
                int(c1[2 * i]) + AUDIO_TOKEN_OFFSET + 4096,
                int(c2[4 * i]) + AUDIO_TOKEN_OFFSET + 2 * 4096,
                int(c2[4 * i + 1]) + AUDIO_TOKEN_OFFSET + 3 * 4096,
                int(c1[2 * i + 1]) + AUDIO_TOKEN_OFFSET + 4 * 4096,
                int(c2[4 * i + 2]) + AUDIO_TOKEN_OFFSET + 5 * 4096,
                int(c2[4 * i + 3]) + AUDIO_TOKEN_OFFSET + 6 * 4096,
            ])

        cached_ref_tokens = interleaved
        cached_ref_mtime = mtime
        return interleaved
    except Exception as e:
        print(f"⚠️ No se pudo codificar referencia para condicionamiento ({e}), usando generación directa.", flush=True)
        return []

def decode_snac_tokens_to_wav(token_ids: list[int], out_path: str, speed: float = 1.0) -> bool:
    """Decodifica los tokens generados por Orpheus en un archivo WAV PCM_16 real a 24kHz."""
    global snac_model
    AUDIO_TOKEN_OFFSET = 128266
    valid = [int(t) - AUDIO_TOKEN_OFFSET for t in token_ids if 128266 <= int(t) < 128266 + 7 * 4096]
    n_frames = len(valid) // 7
    if n_frames == 0 or snac_model is None:
        return False

    layer_1, layer_2, layer_3 = [], [], []
    for i in range(n_frames):
        b = 7 * i
        t0 = valid[b + 0]
        t1 = valid[b + 1] - 4096
        t2 = valid[b + 2] - 2 * 4096
        t3 = valid[b + 3] - 3 * 4096
        t4 = valid[b + 4] - 4 * 4096
        t5 = valid[b + 5] - 5 * 4096
        t6 = valid[b + 6] - 6 * 4096
        if all(0 <= x < 4096 for x in (t0, t1, t2, t3, t4, t5, t6)):
            layer_1.append(t0)
            layer_2.extend([t1, t4])
            layer_3.extend([t2, t3, t5, t6])

    if not layer_1:
        return False

    dev_snac = next(snac_model.parameters()).device
    layers = [
        torch.tensor(layer_1, dtype=torch.long, device=dev_snac).unsqueeze(0),
        torch.tensor(layer_2, dtype=torch.long, device=dev_snac).unsqueeze(0),
        torch.tensor(layer_3, dtype=torch.long, device=dev_snac).unsqueeze(0),
    ]

    with torch.no_grad():
        audio_hat = snac_model.decode(layers).squeeze().cpu().numpy()

    audio_hat = np.clip(audio_hat, -1.0, 1.0)
    target_sr = int(24000 * max(0.5, min(2.0, float(speed))))
    sf.write(out_path, audio_hat, target_sr, subtype="PCM_16")
    return True

def load_models_background():
    global llm, snac_model, backend_state
    if not AI_AVAILABLE:
        backend_state["status"] = "SIMULATION"
        backend_state["message"] = "Modo simulación activo"
        return

    try:
        os.makedirs(os.path.join(BASE_DIR, "models"), exist_ok=True)

        if not os.path.exists(MODEL_PATH):
            backend_state["status"] = "DOWNLOADING"
            backend_state["message"] = "Descargando modelo GGUF (1.8GB)..."
            print("⏳ Descargando modelo GGUF (1.8GB)...", flush=True)
            hf_hub_download(repo_id=MODEL_REPO, filename=MODEL_FILE, local_dir=os.path.join(BASE_DIR, "models"))

        backend_state["status"] = "LOADING"
        backend_state["message"] = "Cargando Orpheus GGUF + Vocoder SNAC 24kHz..."
        print("🧠 Cargando modelo GGUF con llama.cpp (use_mmap=False)...", flush=True)
        llm = Llama(
            model_path=MODEL_PATH,
            n_gpu_layers=-1,
            n_ctx=2048,
            use_mmap=False,
            verbose=False,
        )

        print("🎵 Cargando decodificador neuronal SNAC 24kHz...", flush=True)
        snac_model = SNAC.from_pretrained(SNAC_REPO).eval()

        backend_state["status"] = "READY"
        backend_state["message"] = "Motor TTS Zero-Shot Listo"
        print("✅ ¡Orpheus GGUF + SNAC 24kHz listos! Estado: READY", flush=True)
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

app = FastAPI(title="LatAm TTS Backend (GGUF Q4 + SNAC)", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

@app.get("/")
async def root():
    return {"status": "ok", "state": backend_state}

@app.get("/status")
async def get_status():
    return backend_state

# Endpoint SINCRÓNICO (def en vez de async def) para que FastAPI lo ejecute en un Worker Thread
# y NO bloquee las respuestas de GET /status mientras genera el audio
@app.post("/tts")
def generate_tts(request: TTSRequest):
    if backend_state["status"] not in ["READY", "SIMULATION", "GENERATING"]:
        raise HTTPException(status_code=503, detail="El modelo aún se está descargando o cargando en memoria.")

    text = request.text.strip()
    if not text:
        raise HTTPException(status_code=400, detail="Texto vacío")

    with llm_lock:
        prev_status = backend_state["status"]
        backend_state["status"] = "GENERATING"
        backend_state["message"] = "Generando voz con IA..."
        try:
            if not AI_AVAILABLE or llm is None or snac_model is None:
                waveform, sr = torchaudio.load(DEFAULT_REF_AUDIO)
                sf.write(OUT_AUDIO_PATH, waveform.t().numpy(), sr, subtype="PCM_16")
                return {"status": "success", "message": "Audio generado (Simulado)", "audio_url": "/download"}

            print(f"🧠 Sintetizando voz para ({len(text)} chars): {text[:60]}...", flush=True)
            text_bytes = text.encode("utf-8")
            text_tokens = llm.tokenize(text_bytes, add_bos=True)

            # Estructura de tokens oficial de Orpheus 3B:
            # [128259 (SOH)] + text_tokens + [128009 (EOT), 128260 (EOH), 128261 (SOA), 128257 (SOS)]
            input_tokens = [128259] + text_tokens + [128009, 128260, 128261, 128257]

            # Estimar cantidad máxima de tokens de audio (~84 tokens por segundo de voz, múltiplo de 7)
            est_frames = max(25, min(220, int(len(text) * 1.8)))
            max_audio_tokens = est_frames * 7

            generated_tokens = []
            for tok in llm.generate(
                input_tokens,
                top_k=max(10, int(request.top_k)),
                temp=max(0.1, float(request.temperature)),
                repeat_penalty=1.1,
            ):
                if tok in (128258, 128009, 128262):
                    break
                if 128266 <= tok < 128266 + 7 * 4096:
                    generated_tokens.append(tok)
                if len(generated_tokens) >= max_audio_tokens:
                    break

            print(f"🎵 Decodificando {len(generated_tokens)} tokens SNAC a WAV PCM_16 (24kHz)...", flush=True)
            ok = decode_snac_tokens_to_wav(generated_tokens, OUT_AUDIO_PATH, speed=request.speed)
            if not ok:
                raise RuntimeError("No se generaron suficientes tokens de audio válidos.")

            print("✅ Audio WAV PCM_16 generado exitosamente.", flush=True)
            return {"status": "success", "message": "Audio generado correctamente", "audio_url": "/download"}
        except Exception as e:
            print(f"❌ Error en inferencia: {e}", flush=True)
            raise HTTPException(status_code=500, detail=str(e))
        finally:
            backend_state["status"] = "READY" if AI_AVAILABLE and llm is not None else prev_status
            backend_state["message"] = "Motor TTS Zero-Shot Listo"

@app.get("/download")
async def download_audio():
    if os.path.exists(OUT_AUDIO_PATH):
        return FileResponse(OUT_AUDIO_PATH, media_type="audio/wav", filename="resultado.wav")
    raise HTTPException(status_code=404, detail="Audio no encontrado")

@app.post("/upload_reference")
async def upload_reference(file: UploadFile = File(...)):
    global cached_ref_mtime
    os.makedirs(os.path.join(BASE_DIR, "reference_audio"), exist_ok=True)
    with open(DEFAULT_REF_AUDIO, "wb+") as f:
        f.write(await file.read())
    cached_ref_mtime = None
    return {"info": "Voz base guardada con éxito", "path": DEFAULT_REF_AUDIO}

if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=8000)
