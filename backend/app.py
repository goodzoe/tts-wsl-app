import os
import gc
import glob
import time
import ctypes
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

# Limitar hilos de CPU para evitar congelamientos en la netbook / WSL2
os.environ.setdefault("OMP_NUM_THREADS", "2")
os.environ.setdefault("MKL_NUM_THREADS", "2")
os.environ.setdefault("OPENBLAS_NUM_THREADS", "2")

try:
    from llama_cpp import Llama
    import torch
    import torch.nn.functional as F
    from snac import SNAC
    torch.set_num_threads(2)
    AI_AVAILABLE = True
except ImportError as e:
    AI_AVAILABLE = False
    print(f"⚠️  [ADVERTENCIA] Faltan librerías de IA: {e}", flush=True)


def release_os_memory():
    """Fuerza al recolector de basura de Python, PyTorch y glibc (Linux) a devolver RAM al sistema."""
    gc.collect()
    if AI_AVAILABLE:
        try:
            if torch.cuda.is_available():
                torch.cuda.empty_cache()
        except Exception:
            pass
    try:
        libc = ctypes.CDLL("libc.so.6")
        libc.malloc_trim(0)
    except Exception:
        pass


def get_memory_stats() -> dict:
    """Lee el uso real de RAM del sistema y del proceso actual sin depender de librerías pesadas."""
    mem_total_mb = 0.0
    mem_avail_mb = 0.0
    proc_rss_mb = 0.0
    try:
        if os.path.exists("/proc/meminfo"):
            with open("/proc/meminfo", "r") as f:
                info = {}
                for line in f:
                    parts = line.split(":")
                    if len(parts) == 2:
                        k = parts[0].strip()
                        v = int(parts[1].strip().split()[0]) / 1024.0
                        info[k] = v
                mem_total_mb = info.get("MemTotal", 0.0)
                mem_avail_mb = info.get("MemAvailable", info.get("MemFree", 0.0))
        if os.path.exists("/proc/self/status"):
            with open("/proc/self/status", "r") as f:
                for line in f:
                    if line.startswith("VmRSS:"):
                        proc_rss_mb = int(line.split()[1]) / 1024.0
                        break
    except Exception:
        pass

    mem_used_mb = max(0.0, mem_total_mb - mem_avail_mb)
    pct = (mem_used_mb / mem_total_mb * 100.0) if mem_total_mb > 0 else 0.0
    return {
        "process_ram_mb": round(proc_rss_mb, 1),
        "system_used_gb": round(mem_used_mb / 1024.0, 2),
        "system_total_gb": round(mem_total_mb / 1024.0, 2),
        "system_percent": round(pct, 1),
    }


BASE_DIR = os.path.dirname(os.path.abspath(__file__))
MODELS_DIR = os.path.join(BASE_DIR, "models")
REF_DIR = os.path.join(BASE_DIR, "reference_audio")
DEFAULT_REF_AUDIO = os.path.join(REF_DIR, "base_voice.mp3")
OUT_AUDIO_PATH = os.path.join(BASE_DIR, "output_audio.wav")
SNAC_REPO = "hubertsiuzdak/snac_24khz"

# Catálogo de modelos seleccionables desde la UI
MODEL_CATALOG = {
    "orpheus-es-conversacional-q4": {
        "id": "orpheus-es-conversacional-q4",
        "name": "Orpheus Español Conversacional Q4_K_M (2.0 GB)",
        "repo_id": "Jhonito45/orpheus-spanish-tts-finetuned-new-one-epoch-10-Q4_K_M-GGUF",
        "filename": "orpheus-spanish-tts-finetuned-new-one-epoch-10-q4_k_m.gguf",
        "size_gb": 2.0,
        "default_speaker": "ninguna",
        "speakers": ["ninguna", "maria", "tara", "leah", "javi"],
        "description": "Ya descargado localmente. Prosodia natural conversacional en español.",
    },
    "canopy-es-multivoz-q4": {
        "id": "canopy-es-multivoz-q4",
        "name": "Canopy Orpheus Español Multi-Voz Femenina Nativa Q4 (2.0 GB)",
        "repo_id": "freddyaboulton/3b-es_it-ft-research_release-Q4_K_M-GGUF",
        "filename": "3b-es_it-ft-research_release-q4_k_m.gguf",
        "size_gb": 2.0,
        "default_speaker": "maria",
        "speakers": ["maria", "javi", "tara", "leah", "ninguna"],
        "description": "Incluye voz femenina nativa ('maria') sin necesidad de forzar DSP de tono.",
    },
    "canopy-es-ultralight-q2": {
        "id": "canopy-es-ultralight-q2",
        "name": "Canopy Orpheus Español Ultra-Ligero Q2_K (1.25 GB - Ahorro RAM)",
        "repo_id": "GianDiego/3b-es_it-ft-research_release-Q2-K-GGUF",
        "filename": "3b-es_it-ft-research_release-q2_k.gguf",
        "size_gb": 1.25,
        "default_speaker": "maria",
        "speakers": ["maria", "javi", "ninguna"],
        "description": "Versión ultra liviana (1.25 GB) con voz femenina 'maria' para cuidar la RAM.",
    },
}


class TTSRequest(BaseModel):
    text: str
    model_id: str = "orpheus-es-conversacional-q4"
    reference_file: str = "base_voice.mp3"
    reference_text: str = ""
    use_zero_shot_tokens: bool = False
    ref_duration: float = 1.5
    speaker_hint: str = "maria"
    auto_clone_voice: bool = False
    pitch_semitones: float = 0.0
    formant_shift: float = 1.05
    timbre_strength: float = 0.0
    speed: float = 1.0
    temperature: float = 0.60
    top_k: int = 50
    top_p: float = 0.90
    repeat_penalty: float = 1.12
    max_audio_tokens: int = 700
    seed: int = -1


class ModelActionRequest(BaseModel):
    model_id: str


llm = None
snac_model = None
loaded_model_id = None
llm_lock = threading.Lock()

backend_state = {
    "status": "INITIALIZING",
    "message": "Iniciando servidor backend...",
    "loaded_model_id": None,
    "loaded_model_name": "Ninguno (Memoria libre)",
    "default_reference_path": DEFAULT_REF_AUDIO,
    "active_reference_path": DEFAULT_REF_AUDIO,
    "reference_f0_hz": 203.4,
}


def resolve_ref_path(ref_file_or_path: str) -> str:
    if not ref_file_or_path:
        return DEFAULT_REF_AUDIO
    if os.path.isabs(ref_file_or_path) and os.path.exists(ref_file_or_path):
        return ref_file_or_path
    candidate = os.path.join(REF_DIR, os.path.basename(ref_file_or_path))
    if os.path.exists(candidate):
        return candidate
    return DEFAULT_REF_AUDIO


def fast_resample_1d(wav: np.ndarray, factor: float) -> np.ndarray:
    """
    Re-muestreo lineal 1D ultrarrápido y seguro en RAM (< 2 MB).
    Reemplaza torchaudio.functional.resample con frecuencias arbitrarias que saturaban la RAM (gcd=1).
    """
    if abs(factor - 1.0) < 1e-3 or len(wav) < 16:
        return wav
    new_len = max(16, int(len(wav) / factor))
    t_in = torch.from_numpy(wav).float().view(1, 1, -1)
    t_out = F.interpolate(t_in, size=new_len, mode="linear", align_corners=False)
    return t_out.view(-1).numpy()


def gentle_voice_adjust(
    src_audio: np.ndarray,
    sr: int,
    pitch_semitones: float = 0.0,
    speed: float = 1.0,
) -> np.ndarray:
    """
    Ajuste limpio y ligero en RAM de velocidad y tono suave.
    Evita artefactos metálicos de phase-vocoder extremo y mantiene el consumo de RAM < 5 MB.
    """
    eff_speed = max(0.5, min(2.0, float(speed)))
    semi = max(-8.0, min(8.0, float(pitch_semitones)))

    if abs(semi) < 0.05 and abs(eff_speed - 1.0) < 0.02:
        return src_audio

    pitch_factor = 2.0 ** (semi / 12.0)

    # Si solo cambia la velocidad sin cambiar el tono o cambio pequeño:
    # WSOLA ligero por solapamiento de ventanas Hann (sin FFT pesada ni distorsión de fase)
    stretch_ratio = eff_speed / pitch_factor
    if abs(stretch_ratio - 1.0) > 0.02:
        win_size = 1024
        hop_in = int(512 * stretch_ratio)
        hop_out = 512
        if hop_in > 16 and len(src_audio) > win_size * 2:
            window = np.hanning(win_size).astype(np.float32)
            n_frames = max(1, (len(src_audio) - win_size) // hop_in)
            out_len = n_frames * hop_out + win_size
            out_buf = np.zeros(out_len, dtype=np.float32)
            norm_buf = np.zeros(out_len, dtype=np.float32)
            for i in range(n_frames):
                in_start = i * hop_in
                out_start = i * hop_out
                frame = src_audio[in_start : in_start + win_size]
                if len(frame) < win_size:
                    break
                out_buf[out_start : out_start + win_size] += frame * window
                norm_buf[out_start : out_start + win_size] += window ** 2
            mask = norm_buf > 1e-4
            out_buf[mask] /= norm_buf[mask]
            stretched = out_buf
        else:
            stretched = src_audio
    else:
        stretched = src_audio

    if abs(pitch_factor - 1.0) > 0.01:
        pitched = fast_resample_1d(stretched, pitch_factor)
    else:
        pitched = stretched

    peak = np.max(np.abs(pitched))
    if peak > 1e-4:
        pitched = (pitched / peak) * 0.92
    return np.clip(pitched, -1.0, 1.0)


def decode_snac_tokens_to_wav(
    token_ids: list[int],
    out_path: str,
    request: TTSRequest,
) -> bool:
    """Decodifica los tokens SNAC a 24kHz de forma natural y escribe WAV PCM_16."""
    global snac_model
    AUDIO_TOKEN_OFFSET = 128266
    valid = [
        int(t) - AUDIO_TOKEN_OFFSET
        for t in token_ids
        if 128266 <= int(t) < 128266 + 7 * 4096
    ]
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

    del layers
    # Ajuste suave opcional sin distorsión metálica
    eff_pitch = float(request.pitch_semitones)
    if request.auto_clone_voice and abs(eff_pitch) < 0.1:
        eff_pitch = 3.5
    audio_hat = gentle_voice_adjust(
        audio_hat, 24000, pitch_semitones=eff_pitch, speed=request.speed
    )

    sf.write(out_path, audio_hat, 24000, subtype="PCM_16")
    return True


def unload_models_internal():
    """Descarga el LLM y el vocoder SNAC de la RAM/VRAM y devuelve la memoria al SO."""
    global llm, snac_model, loaded_model_id, backend_state
    with llm_lock:
        if llm is not None:
            try:
                del llm
            except Exception:
                pass
            llm = None
        if snac_model is not None:
            try:
                del snac_model
            except Exception:
                pass
            snac_model = None
        loaded_model_id = None
        release_os_memory()
        backend_state["status"] = "UNLOADED"
        backend_state["loaded_model_id"] = None
        backend_state["loaded_model_name"] = "Ninguno (Memoria Liberada)"
        backend_state["message"] = "Memoria RAM/VRAM liberada. Selecciona y carga un modelo."
        print("🧹 Modelos descargados de RAM/VRAM correctamente.", flush=True)


def load_model_worker(model_id: str):
    """Descarga (si falta) y carga en RAM/VRAM el modelo seleccionado con límites seguros de memoria."""
    global llm, snac_model, loaded_model_id, backend_state
    if model_id not in MODEL_CATALOG:
        model_id = "orpheus-es-conversacional-q4"

    cfg = MODEL_CATALOG[model_id]
    model_path = os.path.join(MODELS_DIR, cfg["filename"])

    with llm_lock:
        try:
            # Primero liberar cualquier modelo previo para no duplicar uso de RAM
            if llm is not None:
                del llm
                llm = None
            release_os_memory()

            os.makedirs(MODELS_DIR, exist_ok=True)
            if not os.path.exists(model_path):
                backend_state["status"] = "DOWNLOADING"
                backend_state["message"] = f"Descargando {cfg['name']}..."
                print(f"⏳ Descargando {cfg['repo_id']} ({cfg['filename']})...", flush=True)
                hf_hub_download(
                    repo_id=cfg["repo_id"],
                    filename=cfg["filename"],
                    local_dir=MODELS_DIR,
                )

            backend_state["status"] = "LOADING"
            backend_state["message"] = f"Cargando {cfg['name']} en memoria..."
            print(f"🧠 Cargando {cfg['filename']} con límites seguros de RAM/CPU...", flush=True)

            # n_ctx=1024 y n_batch=128 reducen drásticamente el consumo de KV Cache y picos de RAM
            llm = Llama(
                model_path=model_path,
                n_gpu_layers=-1,
                n_ctx=1024,
                n_batch=128,
                n_threads=min(4, max(2, (os.cpu_count() or 4) // 2)),
                use_mmap=False,
                verbose=False,
            )

            if snac_model is None:
                print("🎵 Cargando decodificador neuronal SNAC 24kHz...", flush=True)
                snac_model = SNAC.from_pretrained(SNAC_REPO).eval()

            loaded_model_id = model_id
            release_os_memory()
            backend_state["status"] = "READY"
            backend_state["loaded_model_id"] = model_id
            backend_state["loaded_model_name"] = cfg["name"]
            backend_state["message"] = f"Listo: {cfg['name']}"
            print(f"✅ Modelo {cfg['name']} cargado. Estado: READY", flush=True)
        except Exception as e:
            backend_state["status"] = "ERROR"
            backend_state["message"] = f"Error cargando modelo: {str(e)}"
            print(f"❌ Error al cargar modelo: {e}", flush=True)
            release_os_memory()


@asynccontextmanager
async def lifespan(app: FastAPI):
    print("🚀 Servidor Uvicorn iniciado. Cargando modelo predeterminado...", flush=True)
    threading.Thread(
        target=load_model_worker, args=("orpheus-es-conversacional-q4",), daemon=True
    ).start()
    yield
    print("🛑 Cerrando servidor TTS y liberando RAM...", flush=True)
    unload_models_internal()


app = FastAPI(title="LatAm TTS Backend (Model & Memory Manager)", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/")
async def root():
    return {"status": "ok", "state": backend_state, "memory": get_memory_stats()}


@app.get("/status")
async def get_status():
    data = dict(backend_state)
    data["memory"] = get_memory_stats()
    return data


@app.get("/models")
async def list_models():
    items = []
    for mid, m in MODEL_CATALOG.items():
        mpath = os.path.join(MODELS_DIR, m["filename"])
        items.append({
            **m,
            "downloaded": os.path.exists(mpath),
            "loaded": (loaded_model_id == mid and llm is not None),
        })
    return {
        "models": items,
        "loaded_model_id": loaded_model_id,
        "memory": get_memory_stats(),
    }


@app.post("/models/load")
async def api_load_model(req: ModelActionRequest):
    if req.model_id not in MODEL_CATALOG:
        raise HTTPException(status_code=404, detail="Modelo no encontrado en el catálogo")
    if backend_state["status"] in ["LOADING", "DOWNLOADING", "GENERATING"]:
        raise HTTPException(status_code=409, detail="El motor está ocupado en este momento")
    threading.Thread(target=load_model_worker, args=(req.model_id,), daemon=True).start()
    return {"status": "loading", "model_id": req.model_id}


@app.post("/models/unload")
def api_unload_model():
    if backend_state["status"] == "GENERATING":
        raise HTTPException(status_code=409, detail="Espera a que termine la generación actual")
    unload_models_internal()
    return {"status": "unloaded", "memory": get_memory_stats()}


@app.get("/reference_files")
async def list_reference_files():
    os.makedirs(REF_DIR, exist_ok=True)
    files = []
    for ext in ("*.mp3", "*.wav"):
        for p in sorted(glob.glob(os.path.join(REF_DIR, ext))):
            try:
                info = sf.info(p)
                files.append({
                    "name": os.path.basename(p),
                    "path": p,
                    "duration": round(info.duration, 2),
                    "samplerate": info.samplerate,
                })
            except Exception:
                pass
    return {
        "default": DEFAULT_REF_AUDIO,
        "active": backend_state.get("active_reference_path", DEFAULT_REF_AUDIO),
        "reference_f0_hz": backend_state.get("reference_f0_hz", 203.4),
        "files": files,
    }


@app.get("/reference_preview")
async def reference_preview(path: str = ""):
    target = resolve_ref_path(path or backend_state.get("active_reference_path", DEFAULT_REF_AUDIO))
    if not os.path.exists(target):
        raise HTTPException(status_code=404, detail="Audio de referencia no encontrado")
    preview_wav = os.path.join(BASE_DIR, "reference_preview.wav")
    data, sr = sf.read(target, dtype="float32")
    sf.write(preview_wav, data, sr, subtype="PCM_16")
    return FileResponse(preview_wav, media_type="audio/wav", filename="reference_preview.wav")


@app.post("/tts")
def generate_tts(request: TTSRequest):
    if backend_state["status"] == "UNLOADED" or llm is None:
        raise HTTPException(
            status_code=503,
            detail="No hay ningún modelo cargado en RAM. Pulsa 'Cargar Modelo' arriba.",
        )
    if backend_state["status"] not in ["READY", "SIMULATION", "GENERATING"]:
        raise HTTPException(
            status_code=503,
            detail="El modelo aún se está descargando o cargando en memoria.",
        )

    text = request.text.strip()
    if not text:
        raise HTTPException(status_code=400, detail="Texto vacío")

    ref_path = resolve_ref_path(request.reference_file)
    backend_state["active_reference_path"] = ref_path

    with llm_lock:
        prev_status = backend_state["status"]
        backend_state["status"] = "GENERATING"
        backend_state["message"] = "Generando voz natural con IA..."
        try:
            # Limpiar KV cache antes de cada generación para evitar fuga de RAM
            llm.reset()
            if int(request.seed) >= 0:
                llm.set_seed(int(request.seed))

            spk = request.speaker_hint.strip()
            formatted_text = (
                f"{spk}: {text}" if spk and spk.lower() != "ninguna" else text
            )
            print(
                f"🧠 Sintetizando con [{loaded_model_id}] ({len(text)} chars): {formatted_text[:65]}...",
                flush=True,
            )

            text_tokens = llm.tokenize(formatted_text.encode("utf-8"), add_bos=True)
            input_tokens = [128259] + text_tokens + [128009, 128260, 128261, 128257]

            est_frames = max(25, min(260, int(len(text) * 1.8)))
            user_cap = max(140, min(1800, int(request.max_audio_tokens)))
            max_tokens_limit = min(user_cap, est_frames * 7)
            max_tokens_limit = (max_tokens_limit // 7) * 7

            generated_tokens = []
            for tok in llm.generate(
                input_tokens,
                top_k=max(1, int(request.top_k)),
                top_p=max(0.1, min(1.0, float(request.top_p))),
                temp=max(0.1, float(request.temperature)),
                repeat_penalty=max(1.0, float(request.repeat_penalty)),
            ):
                if tok in (128258, 128009, 128262):
                    break
                if 128266 <= tok < 128266 + 7 * 4096:
                    generated_tokens.append(tok)
                if len(generated_tokens) >= max_tokens_limit:
                    break

            print(
                f"🎵 Decodificando {len(generated_tokens)} tokens SNAC a WAV natural 24kHz...",
                flush=True,
            )
            ok = decode_snac_tokens_to_wav(generated_tokens, OUT_AUDIO_PATH, request)
            if not ok:
                raise RuntimeError("No se generaron suficientes tokens de audio válidos.")

            release_os_memory()
            print("✅ Audio WAV PCM_16 generado exitosamente.", flush=True)
            return {
                "status": "success",
                "message": "Audio generado correctamente",
                "audio_url": "/download",
                "memory": get_memory_stats(),
            }
        except Exception as e:
            print(f"❌ Error en inferencia: {e}", flush=True)
            release_os_memory()
            raise HTTPException(status_code=500, detail=str(e))
        finally:
            backend_state["status"] = (
                "READY" if AI_AVAILABLE and llm is not None else prev_status
            )
            if loaded_model_id and loaded_model_id in MODEL_CATALOG:
                backend_state["message"] = f"Listo: {MODEL_CATALOG[loaded_model_id]['name']}"
            else:
                backend_state["message"] = "Motor TTS Listo"


@app.get("/download")
async def download_audio():
    if os.path.exists(OUT_AUDIO_PATH):
        return FileResponse(OUT_AUDIO_PATH, media_type="audio/wav", filename="resultado.wav")
    raise HTTPException(status_code=404, detail="Audio no encontrado")


@app.post("/upload_reference")
async def upload_reference(file: UploadFile = File(...)):
    os.makedirs(REF_DIR, exist_ok=True)
    safe_name = os.path.basename(file.filename or "custom_voice.mp3")
    dest_path = os.path.join(REF_DIR, safe_name)
    content = await file.read()
    with open(dest_path, "wb+") as f:
        f.write(content)
    if dest_path != DEFAULT_REF_AUDIO:
        with open(DEFAULT_REF_AUDIO, "wb+") as f:
            f.write(content)
    backend_state["active_reference_path"] = dest_path
    return {
        "info": "Voz de referencia cargada con éxito",
        "path": dest_path,
    }


if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=8000)
