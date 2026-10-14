import os
import gc
import glob
import json
import time
import ctypes
import threading
import shutil
from typing import Optional
import numpy as np
import soundfile as sf
from tqdm.auto import tqdm
from contextlib import asynccontextmanager
from fastapi import FastAPI, HTTPException, UploadFile, File
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from fastapi.responses import FileResponse
import uvicorn
from huggingface_hub import hf_hub_download, snapshot_download

# Limitar hilos de CPU por defecto para evitar congelamientos en la netbook / WSL2
os.environ.setdefault("OMP_NUM_THREADS", "2")
os.environ.setdefault("MKL_NUM_THREADS", "2")
os.environ.setdefault("OPENBLAS_NUM_THREADS", "2")

try:
    import torch
    import torch.nn.functional as F
    import torchaudio
    torch.set_num_threads(2)
    TORCH_AVAILABLE = True
except ImportError as e:
    TORCH_AVAILABLE = False
    print(f"⚠️ [ADVERTENCIA] PyTorch no disponible: {e}", flush=True)

try:
    from llama_cpp import Llama
    from snac import SNAC
    GGUF_AVAILABLE = True
except ImportError:
    GGUF_AVAILABLE = False

try:
    from omnivoice import OmniVoice, OmniVoiceGenerationConfig
    OMNIVOICE_AVAILABLE = True
except ImportError:
    OMNIVOICE_AVAILABLE = False


def release_os_memory():
    """Fuerza al recolector de basura de Python, PyTorch y glibc (Linux) a devolver RAM al sistema."""
    gc.collect()
    if TORCH_AVAILABLE:
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
    """Lee el uso real de RAM del sistema y del proceso actual."""
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
CUSTOM_MODELS_JSON = os.path.join(MODELS_DIR, "custom_models.json")
REF_DIR = os.path.join(BASE_DIR, "reference_audio")
DEFAULT_REF_AUDIO = os.path.join(REF_DIR, "base_voice.mp3")
OUT_AUDIO_PATH = os.path.join(BASE_DIR, "output_audio.wav")
SNAC_REPO = "hubertsiuzdak/snac_24khz"

os.makedirs(MODELS_DIR, exist_ok=True)
os.makedirs(REF_DIR, exist_ok=True)

# Catálogo base de modelos (OmniVoice + Orpheus GGUF)
MODEL_CATALOG = {
    "omnivoice-zeroshot-0.6b": {
        "id": "omnivoice-zeroshot-0.6b",
        "name": "OmniVoice Zero-Shot 0.6B (Clonación Real + Diseño de Voz - 1.5 GB)",
        "engine": "omnivoice",
        "repo_id": "k2-fsa/OmniVoice",
        "filename": "omnivoice-0.6b",
        "local_path": os.path.join(MODELS_DIR, "omnivoice-0.6b"),
        "size_gb": 1.5,
        "default_speaker": "maria",
        "speakers": ["maria", "lucia", "sofia", "tara", "javi", "ninguna"],
        "description": "Clonación Zero-Shot real desde audio base y Diseño de Voz en +600 idiomas.",
    },
    "canopy-es-multivoz-q4": {
        "id": "canopy-es-multivoz-q4",
        "name": "Canopy Orpheus Español Multi-Voz Femenina Nativa Q4 (2.0 GB)",
        "engine": "gguf",
        "repo_id": "freddyaboulton/3b-es_it-ft-research_release-Q4_K_M-GGUF",
        "filename": "3b-es_it-ft-research_release-q4_k_m.gguf",
        "local_path": os.path.join(MODELS_DIR, "3b-es_it-ft-research_release-q4_k_m.gguf"),
        "size_gb": 2.0,
        "default_speaker": "maria",
        "speakers": ["maria", "javi", "tara", "leah", "ninguna"],
        "description": "Modelo GGUF con voz femenina nativa ('maria') en español.",
    },
    "canopy-es-ultralight-q2": {
        "id": "canopy-es-ultralight-q2",
        "name": "Canopy Orpheus Español Ultra-Ligero Q2_K (1.25 GB - Ahorro RAM)",
        "engine": "gguf",
        "repo_id": "GianDiego/3b-es_it-ft-research_release-Q2-K-GGUF",
        "filename": "3b-es_it-ft-research_release-q2_k.gguf",
        "local_path": os.path.join(MODELS_DIR, "3b-es_it-ft-research_release-q2_k.gguf"),
        "size_gb": 1.25,
        "default_speaker": "maria",
        "speakers": ["maria", "javi", "ninguna"],
        "description": "Versión GGUF ultra liviana (1.25 GB) con voz femenina 'maria'.",
    },
    "orpheus-es-conversacional-q4": {
        "id": "orpheus-es-conversacional-q4",
        "name": "Orpheus Español Conversacional Q4_K_M (2.0 GB - Local)",
        "engine": "gguf",
        "repo_id": "Jhonito45/orpheus-spanish-tts-finetuned-new-one-epoch-10-Q4_K_M-GGUF",
        "filename": "orpheus-spanish-tts-finetuned-new-one-epoch-10-q4_k_m.gguf",
        "local_path": os.path.join(
            MODELS_DIR, "orpheus-spanish-tts-finetuned-new-one-epoch-10-q4_k_m.gguf"
        ),
        "size_gb": 2.0,
        "default_speaker": "ninguna",
        "speakers": ["ninguna", "maria", "tara", "leah", "javi"],
        "description": "Ya descargado localmente en backend/models/.",
    },
}


def load_custom_models_from_disk():
    if os.path.exists(CUSTOM_MODELS_JSON):
        try:
            with open(CUSTOM_MODELS_JSON, "r", encoding="utf-8") as f:
                custom_dict = json.load(f)
            for k, v in custom_dict.items():
                MODEL_CATALOG[k] = v
        except Exception as e:
            print(f"⚠️ Error leyendo custom_models.json: {e}", flush=True)


def save_custom_models_to_disk():
    custom_only = {
        k: v for k, v in MODEL_CATALOG.items() if v.get("is_custom", False)
    }
    try:
        with open(CUSTOM_MODELS_JSON, "w", encoding="utf-8") as f:
            json.dump(custom_only, f, indent=2, ensure_ascii=False)
    except Exception as e:
        print(f"⚠️ Error guardando custom_models.json: {e}", flush=True)


load_custom_models_from_disk()


class TTSRequest(BaseModel):
    text: str
    mode: str = "clone"  # "clone" | "tts" | "design"
    model_id: str = "omnivoice-zeroshot-0.6b"
    language: str = "Spanish"
    reference_file: str = "base_voice.mp3"
    reference_text: str = ""
    use_xvector_only: bool = False
    speaker_hint: str = "maria"
    style_instruct: str = ""
    voice_description: str = ""
    # Parámetros OmniVoice (Difusión)
    num_step: int = 24
    guidance_scale: float = 2.0
    t_shift: float = 0.1
    position_temperature: float = 5.0
    class_temperature: float = 0.0
    layer_penalty_factor: float = 5.0
    denoise: bool = True
    preprocess_prompt: bool = True
    postprocess_output: bool = True
    # Parámetros Audio / DSP / GGUF LLM
    auto_clone_voice: bool = False
    pitch_semitones: float = 0.0
    speed: float = 1.0
    duration: float = 0.0
    temperature: float = 0.60
    top_k: int = 50
    top_p: float = 0.90
    repeat_penalty: float = 1.12
    max_audio_tokens: int = 700
    seed: int = -1
    cpu_threads: int = 4
    n_ctx: int = 1024


class ModelActionRequest(BaseModel):
    model_id: str
    cpu_threads: int = 4
    n_ctx: int = 1024


class AddLocalModelRequest(BaseModel):
    path: str
    name: Optional[str] = None
    engine: Optional[str] = None  # "gguf" | "omnivoice"


llm = None
snac_model = None
omni_model = None
loaded_model_id = None
llm_lock = threading.Lock()
cached_omni_clone_prompt = {}

backend_state = {
    "status": "INITIALIZING",
    "message": "Iniciando servidor backend...",
    "loaded_model_id": None,
    "loaded_model_name": "Ninguno (Memoria libre)",
    "loaded_engine": None,
    "download_progress": 0.0,
    "download_mb": 0.0,
    "download_total_mb": 0.0,
    "task_start_time": 0.0,
    "task_elapsed_sec": 0,
    "task_eta_sec": 0,
    "default_reference_path": DEFAULT_REF_AUDIO,
    "active_reference_path": DEFAULT_REF_AUDIO,
}


class DownloadProgressTqdm(tqdm):
    """Hook de progreso para huggingface_hub que actualiza el porcentaje, velocidad y ETA en backend_state."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._dl_start_t = time.time()

    def update(self, n=1):
        super().update(n)
        if self.total and self.total > 0:
            # Ignorar archivos pequeños de configuración (< 5 MB) para no distorsionar la barra principal
            if self.total > 5 * 1024 * 1024:
                pct = min(99.9, (self.n / self.total) * 100.0)
                mb_done = self.n / (1024 * 1024)
                mb_tot = self.total / (1024 * 1024)
                elapsed = max(0.2, time.time() - self._dl_start_t)
                speed_mbps = mb_done / elapsed
                rem_mb = max(0.0, mb_tot - mb_done)
                eta_s = int(rem_mb / speed_mbps) if speed_mbps > 0.05 else 0

                backend_state["download_progress"] = round(pct, 1)
                backend_state["download_mb"] = round(mb_done, 1)
                backend_state["download_total_mb"] = round(mb_tot, 1)
                backend_state["task_elapsed_sec"] = int(elapsed)
                backend_state["task_eta_sec"] = eta_s
                backend_state["message"] = (
                    f"Descargando: {pct:.1f}% ({mb_done:.0f}/{mb_tot:.0f} MB) • {speed_mbps:.1f} MB/s • ETA: ~{eta_s}s"
                )


def is_model_downloaded(cfg: dict) -> bool:
    lpath = cfg.get("local_path", "")
    if cfg.get("engine") == "omnivoice":
        return os.path.isdir(lpath) and (
            os.path.exists(os.path.join(lpath, "config.json"))
            or len(glob.glob(os.path.join(lpath, "*.safetensors"))) > 0
        )
    return os.path.exists(lpath)


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
    """Re-muestreo lineal 1D ultrarrápido y seguro en RAM (< 2 MB)."""
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
    """Ajuste limpio y ligero en RAM de velocidad y tono suave (< 5 MB RAM)."""
    eff_speed = max(0.5, min(2.0, float(speed)))
    semi = max(-8.0, min(8.0, float(pitch_semitones)))

    if abs(semi) < 0.05 and abs(eff_speed - 1.0) < 0.02:
        return src_audio

    pitch_factor = 2.0 ** (semi / 12.0)
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
    eff_pitch = float(request.pitch_semitones)
    if request.auto_clone_voice and abs(eff_pitch) < 0.1:
        eff_pitch = 3.5
    audio_hat = gentle_voice_adjust(
        audio_hat, 24000, pitch_semitones=eff_pitch, speed=request.speed
    )

    sf.write(out_path, audio_hat, 24000, subtype="PCM_16")
    return True


def unload_models_internal():
    """Descarga todos los modelos (LLM, SNAC, OmniVoice) de RAM/VRAM y devuelve la memoria al SO."""
    global llm, snac_model, omni_model, loaded_model_id, cached_omni_clone_prompt, backend_state
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
        if omni_model is not None:
            try:
                del omni_model
            except Exception:
                pass
            omni_model = None
        cached_omni_clone_prompt.clear()
        loaded_model_id = None
        release_os_memory()
        backend_state["status"] = "UNLOADED"
        backend_state["loaded_model_id"] = None
        backend_state["loaded_model_name"] = "Ninguno (Memoria Liberada)"
        backend_state["loaded_engine"] = None
        backend_state["download_progress"] = 0.0
        backend_state["message"] = "Memoria RAM/VRAM liberada. Selecciona y carga un modelo."
        print("🧹 Modelos descargados de RAM/VRAM correctamente.", flush=True)


def load_model_worker(model_id: str, cpu_threads: int = 4, n_ctx: int = 1024):
    """Descarga (con barra de porcentaje real) y carga en RAM/VRAM el modelo seleccionado."""
    global llm, snac_model, omni_model, loaded_model_id, backend_state
    if model_id not in MODEL_CATALOG:
        model_id = "orpheus-es-conversacional-q4"

    cfg = MODEL_CATALOG[model_id]
    engine = cfg.get("engine", "gguf")
    local_path = cfg.get("local_path", os.path.join(MODELS_DIR, cfg.get("filename", "")))

    with llm_lock:
        try:
            # Liberar modelos previos antes de cargar el nuevo
            if llm is not None:
                del llm
                llm = None
            if omni_model is not None:
                del omni_model
                omni_model = None
            cached_omni_clone_prompt.clear()
            release_os_memory()

            threads = max(1, min(8, int(cpu_threads)))
            if TORCH_AVAILABLE:
                torch.set_num_threads(max(1, threads // 2))

            if engine == "omnivoice":
                if not OMNIVOICE_AVAILABLE:
                    raise RuntimeError("La librería 'omnivoice' no está instalada en el entorno.")

                if not is_model_downloaded(cfg):
                    backend_state["status"] = "DOWNLOADING"
                    backend_state["task_start_time"] = time.time()
                    backend_state["download_progress"] = 1.0
                    backend_state["download_mb"] = 0.0
                    backend_state["download_total_mb"] = cfg.get("size_gb", 1.5) * 1024
                    backend_state["message"] = f"Descargando {cfg['name']}..."
                    print(f"⏳ Descargando OmniVoice ({cfg['repo_id']})...", flush=True)
                    snapshot_download(
                        repo_id=cfg["repo_id"],
                        local_dir=local_path,
                        tqdm_class=DownloadProgressTqdm,
                    )

                backend_state["status"] = "LOADING"
                backend_state["task_start_time"] = time.time()
                backend_state["download_progress"] = 100.0
                backend_state["message"] = f"Cargando {cfg['name']} en memoria..."
                print(f"🧠 Cargando OmniVoice desde {local_path}...", flush=True)

                dev = "cuda:0" if (TORCH_AVAILABLE and torch.cuda.is_available()) else "cpu"
                dt = torch.float16 if dev.startswith("cuda") else torch.float32
                omni_model = OmniVoice.from_pretrained(
                    local_path,
                    device_map=dev,
                    dtype=dt,
                    load_asr=False,
                )
                loaded_model_id = model_id
                release_os_memory()
                backend_state["status"] = "READY"
                backend_state["loaded_model_id"] = model_id
                backend_state["loaded_model_name"] = cfg["name"]
                backend_state["loaded_engine"] = "omnivoice"
                backend_state["download_progress"] = 0.0
                backend_state["message"] = f"Listo: {cfg['name']}"
                print(f"✅ OmniVoice cargado en {dev}. Estado: READY", flush=True)

            else:
                # Engine GGUF (Orpheus / Canopy / Custom GGUF)
                if not os.path.exists(local_path):
                    if not cfg.get("repo_id"):
                        raise FileNotFoundError(f"No se encontró el archivo local: {local_path}")
                    backend_state["status"] = "DOWNLOADING"
                    backend_state["task_start_time"] = time.time()
                    backend_state["download_progress"] = 1.0
                    backend_state["download_mb"] = 0.0
                    backend_state["download_total_mb"] = cfg.get("size_gb", 2.0) * 1024
                    backend_state["message"] = f"Descargando {cfg['name']}..."
                    print(f"⏳ Descargando {cfg['repo_id']} ({cfg['filename']})...", flush=True)
                    hf_hub_download(
                        repo_id=cfg["repo_id"],
                        filename=cfg["filename"],
                        local_dir=MODELS_DIR,
                        tqdm_class=DownloadProgressTqdm,
                    )

                backend_state["status"] = "LOADING"
                backend_state["task_start_time"] = time.time()
                backend_state["download_progress"] = 100.0
                backend_state["message"] = f"Cargando {cfg['name']} en memoria..."
                print(f"🧠 Cargando GGUF {local_path} (threads={threads}, n_ctx={n_ctx})...", flush=True)

                llm = Llama(
                    model_path=local_path,
                    n_gpu_layers=-1,
                    n_ctx=max(512, min(4096, int(n_ctx))),
                    n_batch=128,
                    n_threads=threads,
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
                backend_state["loaded_engine"] = "gguf"
                backend_state["download_progress"] = 0.0
                backend_state["message"] = f"Listo: {cfg['name']}"
                print(f"✅ Modelo GGUF {cfg['name']} cargado. Estado: READY", flush=True)

        except Exception as e:
            backend_state["status"] = "ERROR"
            backend_state["message"] = f"Error cargando modelo: {str(e)}"
            print(f"❌ Error al cargar modelo: {e}", flush=True)
            release_os_memory()


@asynccontextmanager
async def lifespan(app: FastAPI):
    print("🚀 Servidor Uvicorn iniciado. Cargando modelo local disponible...", flush=True)
    # Si ya está descargado OmniVoice lo prioriza, si no carga el local ya descargado sin bloquear el inicio
    if is_model_downloaded(MODEL_CATALOG["omnivoice-zeroshot-0.6b"]):
        initial_model = "omnivoice-zeroshot-0.6b"
    elif is_model_downloaded(MODEL_CATALOG["canopy-es-multivoz-q4"]):
        initial_model = "canopy-es-multivoz-q4"
    else:
        initial_model = "orpheus-es-conversacional-q4"
    threading.Thread(
        target=load_model_worker, args=(initial_model, 4, 1024), daemon=True
    ).start()
    yield
    print("🛑 Cerrando servidor TTS y liberando RAM...", flush=True)
    unload_models_internal()


app = FastAPI(title="LatAm Studio TTS Backend (OmniVoice + Orpheus GGUF)", lifespan=lifespan)

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
    if data.get("status") in ("DOWNLOADING", "LOADING", "GENERATING") and data.get("task_start_time", 0) > 0:
        data["task_elapsed_sec"] = max(0, int(time.time() - data["task_start_time"]))
    data["memory"] = get_memory_stats()
    return data


@app.get("/models")
async def list_models():
    items = []
    for mid, m in MODEL_CATALOG.items():
        items.append({
            **m,
            "downloaded": is_model_downloaded(m),
            "loaded": (loaded_model_id == mid and (llm is not None or omni_model is not None)),
        })
    return {
        "models": items,
        "loaded_model_id": loaded_model_id,
        "memory": get_memory_stats(),
    }


@app.post("/models/add_local")
async def api_add_local_model(req: AddLocalModelRequest):
    path = os.path.abspath(req.path.strip())
    if not os.path.exists(path):
        raise HTTPException(status_code=404, detail=f"La ruta no existe: {path}")

    base_name = os.path.basename(path.rstrip("/\\"))
    if os.path.isfile(path) and path.lower().endswith(".gguf"):
        engine = "gguf"
        size_gb = round(os.path.getsize(path) / (1024 ** 3), 2)
        display_name = req.name or f"Local GGUF: {base_name} ({size_gb} GB)"
    elif os.path.isdir(path):
        # Verificar si contiene un archivo .gguf único o es un directorio HuggingFace/OmniVoice
        ggufs = glob.glob(os.path.join(path, "*.gguf"))
        if ggufs and req.engine != "omnivoice":
            path = ggufs[0]
            base_name = os.path.basename(path)
            engine = "gguf"
            size_gb = round(os.path.getsize(path) / (1024 ** 3), 2)
            display_name = req.name or f"Local GGUF: {base_name} ({size_gb} GB)"
        else:
            engine = req.engine or "omnivoice"
            size_gb = 1.5
            display_name = req.name or f"Local Dir: {base_name}"
    else:
        raise HTTPException(
            status_code=400,
            detail="Selecciona un archivo .gguf o una carpeta de modelo válida.",
        )

    model_id = f"custom-{base_name.lower().replace(' ', '-')}"
    MODEL_CATALOG[model_id] = {
        "id": model_id,
        "name": display_name,
        "engine": engine,
        "repo_id": "",
        "filename": base_name,
        "local_path": path,
        "size_gb": size_gb,
        "default_speaker": "maria",
        "speakers": ["maria", "tara", "leah", "javi", "ninguna"],
        "description": f"Modelo local agregado por el usuario ({path})",
        "is_custom": True,
    }
    save_custom_models_to_disk()
    return {
        "status": "added",
        "model": MODEL_CATALOG[model_id],
    }


@app.post("/models/load")
async def api_load_model(req: ModelActionRequest):
    if req.model_id not in MODEL_CATALOG:
        raise HTTPException(status_code=404, detail="Modelo no encontrado en el catálogo")
    if backend_state["status"] in ["LOADING", "DOWNLOADING", "GENERATING"]:
        raise HTTPException(status_code=409, detail="El motor está ocupado en este momento")
    threading.Thread(
        target=load_model_worker,
        args=(req.model_id, req.cpu_threads, req.n_ctx),
        daemon=True,
    ).start()
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


def _generate_with_omnivoice(request: TTSRequest, ref_path: str) -> None:
    global omni_model, cached_omni_clone_prompt
    text = request.text.strip()

    gen_config = OmniVoiceGenerationConfig(
        num_step=max(4, min(64, int(request.num_step))),
        guidance_scale=max(0.0, min(6.0, float(request.guidance_scale))),
        t_shift=max(0.01, min(1.0, float(request.t_shift))),
        position_temperature=max(0.0, min(15.0, float(request.position_temperature))),
        class_temperature=max(0.0, min(10.0, float(request.class_temperature))),
        layer_penalty_factor=max(0.0, min(15.0, float(request.layer_penalty_factor))),
        denoise=bool(request.denoise),
        preprocess_prompt=bool(request.preprocess_prompt),
        postprocess_output=bool(request.postprocess_output),
    )

    lang = request.language.strip() if request.language else None
    if lang and lang.lower() in ["auto", "automático", "automatico"]:
        lang = None
    elif lang and "español" in lang.lower():
        lang = "Spanish"

    kw = {
        "text": text,
        "language": lang,
        "generation_config": gen_config,
    }
    if abs(float(request.speed) - 1.0) > 0.02:
        kw["speed"] = max(0.5, min(2.0, float(request.speed)))
    if float(request.duration) > 0.2:
        kw["duration"] = float(request.duration)

    # Modo 1: Clonación de Voz Zero-Shot desde el archivo de audio base
    if request.mode == "clone":
        if not os.path.exists(ref_path):
            raise FileNotFoundError(f"No existe el audio de referencia: {ref_path}")

        ref_text_clean = request.reference_text.strip()
        if request.use_xvector_only or not ref_text_clean:
            # Evita tener que cargar un modelo pesado Whisper ASR extra en RAM si el usuario no puso transcripción
            ref_text_clean = (
                ref_text_clean
                or "Hola, bienvenidos a un nuevo capítulo de nuestra historia."
            )

        mtime = os.path.getmtime(ref_path)
        cache_key = (ref_path, mtime, ref_text_clean, bool(request.preprocess_prompt))
        if cache_key not in cached_omni_clone_prompt:
            data, sr = sf.read(ref_path, dtype="float32")
            if data.ndim > 1:
                data = data.mean(axis=1)
            # Limitar a primeros 10 segundos para máxima calidad y bajo uso de RAM
            max_samples = int(sr * 10.0)
            data = data[:max_samples]
            target_sr = int(getattr(omni_model, "sampling_rate", 24000) or 24000)
            if sr != target_sr:
                data = fast_resample_1d(data, float(sr) / float(target_sr))
                sr = target_sr
            wav_tensor = torch.from_numpy(data)
            cached_omni_clone_prompt[cache_key] = omni_model.create_voice_clone_prompt(
                ref_audio=(wav_tensor, sr),
                ref_text=ref_text_clean,
                preprocess_prompt=bool(request.preprocess_prompt),
            )
        kw["voice_clone_prompt"] = cached_omni_clone_prompt[cache_key]

    # Instrucciones de estilo o diseño de voz
    instruct_parts = []
    if request.mode == "design" and request.voice_description.strip():
        instruct_parts.append(request.voice_description.strip())
    elif request.mode == "tts" and request.speaker_hint.strip():
        spk_map = {
            "maria": "female voice, young adult, warm Latin American Spanish accent",
            "lucia": "female voice, soft and clear Latin American Spanish",
            "sofia": "female voice, expressive and bright Spanish",
            "tara": "female voice, calm conversational tone",
            "javi": "male voice, natural conversational Spanish",
        }
        spk_desc = spk_map.get(request.speaker_hint.lower(), request.speaker_hint)
        if spk_desc and spk_desc != "ninguna":
            instruct_parts.append(spk_desc)

    if request.style_instruct.strip():
        instruct_parts.append(request.style_instruct.strip())

    if instruct_parts:
        kw["instruct"] = ", ".join(instruct_parts)

    if int(request.seed) >= 0 and TORCH_AVAILABLE:
        torch.manual_seed(int(request.seed))

    print(
        f"🧠 OmniVoice generando [modo={request.mode}, pasos={gen_config.num_step}, ref={os.path.basename(ref_path)}]...",
        flush=True,
    )
    step_counter = [0]
    total_steps = max(1, int(gen_config.num_step))
    step_start_t = time.time()

    def _omni_step_hook(_mod, _inp, _out):
        step_counter[0] += 1
        cur_step = min(total_steps, step_counter[0])
        pct = min(96.0, 15.0 + (cur_step / total_steps) * 80.0)
        elapsed = max(0.1, time.time() - step_start_t)
        avg_per_step = elapsed / cur_step
        rem_s = max(0, int((total_steps - cur_step) * avg_per_step))
        tot_est_s = max(int(elapsed), int(elapsed) + rem_s)
        backend_state["download_progress"] = round(pct, 1)
        backend_state["task_elapsed_sec"] = int(elapsed)
        backend_state["task_eta_sec"] = rem_s
        backend_state["message"] = (
            f"OmniVoice ({request.mode.upper()}): paso {cur_step}/{total_steps} ({pct:.0f}%) • ETA {int(elapsed)}s / ~{tot_est_s}s"
        )

    hook_handle = None
    try:
        hook_handle = omni_model.register_forward_hook(_omni_step_hook)
    except Exception:
        hook_handle = None

    try:
        audio_list = omni_model.generate(**kw)
    finally:
        if hook_handle is not None:
            try:
                hook_handle.remove()
            except Exception:
                pass
    wav_out = np.asarray(audio_list[0], dtype=np.float32)

    if abs(float(request.pitch_semitones)) > 0.05:
        wav_out = gentle_voice_adjust(
            wav_out,
            omni_model.sampling_rate,
            pitch_semitones=request.pitch_semitones,
            speed=1.0,
        )

    sf.write(OUT_AUDIO_PATH, wav_out, omni_model.sampling_rate, subtype="PCM_16")


@app.post("/tts")
def generate_tts(request: TTSRequest):
    if backend_state["status"] == "UNLOADED" or (llm is None and omni_model is None):
        raise HTTPException(
            status_code=503,
            detail="No hay ningún modelo cargado en RAM. Pulsa '⚡ Cargar Modelo' arriba.",
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
        gen_start = time.time()
        backend_state["status"] = "GENERATING"
        backend_state["task_start_time"] = gen_start
        backend_state["task_elapsed_sec"] = 0
        backend_state["download_progress"] = 5.0
        backend_state["message"] = f"Generando voz ({request.mode.upper()})..."
        try:
            if backend_state.get("loaded_engine") == "omnivoice" and omni_model is not None:
                est_omni_sec = max(4, int(request.num_step * 0.45))
                backend_state["task_eta_sec"] = est_omni_sec
                backend_state["download_progress"] = 25.0
                backend_state["message"] = (
                    f"Sintetizando con OmniVoice ({request.mode.upper()}, {request.num_step} pasos) • ETA: ~{est_omni_sec}s"
                )
                _generate_with_omnivoice(request, ref_path)
                backend_state["download_progress"] = 100.0
            elif llm is not None and snac_model is not None:
                llm.reset()
                if int(request.seed) >= 0:
                    llm.set_seed(int(request.seed))

                spk = request.speaker_hint.strip()
                style_prefix = ""
                if request.mode == "design" and request.voice_description.strip():
                    style_prefix = f"[{request.voice_description.strip()}] "
                elif request.style_instruct.strip():
                    style_prefix = f"[{request.style_instruct.strip()}] "

                formatted_text = (
                    f"{spk}: {style_prefix}{text}"
                    if spk and spk.lower() != "ninguna"
                    else f"{style_prefix}{text}"
                )
                print(
                    f"🧠 GGUF Sintetizando [{loaded_model_id}] ({len(text)} chars): {formatted_text[:65]}...",
                    flush=True,
                )

                text_tokens = llm.tokenize(formatted_text.encode("utf-8"), add_bos=True)
                input_tokens = [128259] + text_tokens + [128009, 128260, 128261, 128257]

                est_frames = max(25, min(260, int(len(text) * 1.8)))
                user_cap = max(140, min(2030, int(request.max_audio_tokens)))
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
                        n_gen = len(generated_tokens)
                        if n_gen % 14 == 0:
                            pct = min(95.0, (n_gen / max(7, max_tokens_limit)) * 100.0)
                            elapsed = max(0.2, time.time() - gen_start)
                            rate = n_gen / elapsed
                            rem_s = max(1, int(max(0, max_tokens_limit - n_gen) / max(1.0, rate)))
                            tot_est_s = int(elapsed) + rem_s
                            backend_state["download_progress"] = round(pct, 1)
                            backend_state["task_elapsed_sec"] = int(elapsed)
                            backend_state["task_eta_sec"] = rem_s
                            backend_state["message"] = (
                                f"Generando voz: {pct:.0f}% ({n_gen // 7} frames) • ETA {int(elapsed)}s / ~{tot_est_s}s"
                            )
                    if len(generated_tokens) >= max_tokens_limit:
                        break

                backend_state["download_progress"] = 97.0
                backend_state["message"] = "Decodificando audio SNAC 24kHz..."
                ok = decode_snac_tokens_to_wav(generated_tokens, OUT_AUDIO_PATH, request)
                if not ok:
                    raise RuntimeError("No se generaron suficientes tokens de audio válidos.")
                backend_state["download_progress"] = 100.0
            else:
                data, sr = sf.read(ref_path, dtype="float32")
                sf.write(OUT_AUDIO_PATH, data, sr, subtype="PCM_16")

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
            backend_state["download_progress"] = 0.0
            backend_state["task_eta_sec"] = 0
            backend_state["status"] = (
                "READY"
                if (llm is not None or omni_model is not None)
                else prev_status
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
    cached_omni_clone_prompt.clear()
    backend_state["active_reference_path"] = dest_path
    return {
        "info": "Voz de referencia cargada con éxito",
        "path": dest_path,
    }


if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=8000)
