"""Punto de entrada FastAPI para LatAm Studio TTS Backend."""

import os
import glob
import time
import threading
import soundfile as sf
from contextlib import asynccontextmanager
from fastapi import FastAPI, HTTPException, UploadFile, File
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
import uvicorn

from config import (
    REF_DIR,
    DEFAULT_REF_AUDIO,
    OUT_AUDIO_PATH,
    PREVIEW_AUDIO_PATH,
    MODEL_CATALOG,
    DEFAULT_CPU_THREADS,
    is_model_downloaded,
    save_custom_models_to_disk,
    load_transcripts_map,
    resolve_ref_path,
)
from schemas import TTSRequest, ModelActionRequest, AddLocalModelRequest
from audio_dsp import get_memory_stats, release_os_memory, get_or_transcribe_reference_audio
import engine_manager as em


@asynccontextmanager
async def lifespan(app: FastAPI):
    print("🚀 Servidor Uvicorn iniciado. Cargando modelo local disponible...", flush=True)
    if is_model_downloaded(MODEL_CATALOG["omnivoice-zeroshot-0.6b"]):
        initial_model = "omnivoice-zeroshot-0.6b"
    elif is_model_downloaded(MODEL_CATALOG["canopy-es-multivoz-q4"]):
        initial_model = "canopy-es-multivoz-q4"
    else:
        initial_model = "orpheus-es-conversacional-q4"
    threading.Thread(
        target=em.load_model_worker,
        args=(initial_model, DEFAULT_CPU_THREADS, 1024),
        daemon=True,
    ).start()
    yield
    print("🛑 Cerrando servidor TTS y liberando RAM...", flush=True)
    em.unload_models_internal()


app = FastAPI(
    title="LatAm Studio TTS Backend (OmniVoice Zero-Shot + Orpheus GGUF)",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/")
async def root():
    return {"status": "ok", "state": em.backend_state, "memory": get_memory_stats()}


@app.get("/status")
async def get_status():
    data = dict(em.backend_state)
    if (
        data.get("status") in ("DOWNLOADING", "LOADING", "GENERATING")
        and data.get("task_start_time", 0) > 0
    ):
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
            "loaded": (
                em.loaded_model_id == mid
                and (em.llm is not None or em.omni_model is not None)
            ),
        })
    return {
        "models": items,
        "loaded_model_id": em.loaded_model_id,
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
    return {"status": "added", "model": MODEL_CATALOG[model_id]}


@app.post("/models/load")
async def api_load_model(req: ModelActionRequest):
    if req.model_id not in MODEL_CATALOG:
        raise HTTPException(status_code=404, detail="Modelo no encontrado en el catálogo")
    if em.backend_state["status"] in ["LOADING", "DOWNLOADING", "GENERATING"]:
        raise HTTPException(status_code=409, detail="El motor está ocupado en este momento")
    threading.Thread(
        target=em.load_model_worker,
        args=(req.model_id, req.cpu_threads, req.n_ctx),
        daemon=True,
    ).start()
    return {"status": "loading", "model_id": req.model_id}


@app.post("/models/unload")
def api_unload_model():
    if em.backend_state["status"] == "GENERATING":
        raise HTTPException(status_code=409, detail="Espera a que termine la generación actual")
    em.unload_models_internal()
    return {"status": "unloaded", "memory": get_memory_stats()}


@app.get("/reference_files")
async def list_reference_files():
    os.makedirs(REF_DIR, exist_ok=True)
    tmap = load_transcripts_map()
    files = []
    for ext in ("*.mp3", "*.wav"):
        for p in sorted(glob.glob(os.path.join(REF_DIR, ext))):
            try:
                info = sf.info(p)
                fname = os.path.basename(p)
                files.append({
                    "name": fname,
                    "path": p,
                    "duration": round(info.duration, 2),
                    "samplerate": info.samplerate,
                    "transcript": tmap.get(fname, ""),
                })
            except Exception:
                pass
    return {
        "default": DEFAULT_REF_AUDIO,
        "active": em.backend_state.get("active_reference_path", DEFAULT_REF_AUDIO),
        "transcripts": tmap,
        "files": files,
    }


@app.get("/reference_preview")
async def reference_preview(path: str = ""):
    target = resolve_ref_path(
        path or em.backend_state.get("active_reference_path", DEFAULT_REF_AUDIO)
    )
    if not os.path.exists(target):
        raise HTTPException(status_code=404, detail="Audio de referencia no encontrado")
    data, sr = sf.read(target, dtype="float32")
    sf.write(PREVIEW_AUDIO_PATH, data, sr, subtype="PCM_16")
    return FileResponse(
        PREVIEW_AUDIO_PATH, media_type="audio/wav", filename="reference_preview.wav"
    )


@app.post("/tts")
def generate_tts(request: TTSRequest):
    if not request.text or not request.text.strip():
        raise HTTPException(status_code=400, detail="Texto vacío")

    # Si el usuario pide Clonación de Voz (mode == "clone") o solicitó un modelo específico que no está cargado,
    # cambiamos automáticamente al modelo adecuado dentro del lock síncrono.
    target_model = request.model_id
    if request.mode == "clone" and target_model in MODEL_CATALOG:
        if MODEL_CATALOG[target_model].get("engine") != "omnivoice":
            # Los modelos GGUF de Orpheus no aceptan audio de referencia zero-shot;
            # redirigir automáticamente a OmniVoice para garantizar clonación real.
            target_model = "omnivoice-zeroshot-0.6b"

    if (
        em.backend_state["status"] == "UNLOADED"
        or (em.llm is None and em.omni_model is None)
        or (target_model in MODEL_CATALOG and em.loaded_model_id != target_model)
    ):
        em.load_model_worker(target_model, request.cpu_threads, request.n_ctx)

    if em.llm is None and em.omni_model is None:
        raise HTTPException(
            status_code=503,
            detail="No se pudo cargar el modelo en memoria. Verifica el estado arriba.",
        )

    ref_path = resolve_ref_path(request.reference_file)
    em.backend_state["active_reference_path"] = ref_path

    with em.llm_lock:
        prev_status = em.backend_state["status"]
        gen_start = time.time()
        em.backend_state.update({
            "status": "GENERATING",
            "task_start_time": gen_start,
            "task_elapsed_sec": 0,
            "download_progress": 5.0,
            "message": f"Generando voz ({request.mode.upper()})...",
        })
        try:
            if em.backend_state.get("loaded_engine") == "omnivoice" and em.omni_model is not None:
                est_omni_sec = max(6, int(request.num_step * 1.4))
                em.backend_state["task_eta_sec"] = est_omni_sec
                em.backend_state["download_progress"] = 10.0
                em.backend_state["message"] = (
                    f"Sintetizando con OmniVoice ({request.mode.upper()}, {request.num_step} pasos) • ETA 0s / ~{est_omni_sec}s"
                )
                em.run_omnivoice_synthesis(request, ref_path)
                em.backend_state["download_progress"] = 100.0
            elif em.llm is not None and em.snac_model is not None:
                em.run_gguf_synthesis(request, gen_start)
                em.backend_state["download_progress"] = 100.0
            else:
                raise RuntimeError("Motor TTS no inicializado correctamente.")

            release_os_memory()
            print("✅ Audio WAV PCM_16 generado exitosamente.", flush=True)
            return {
                "status": "success",
                "message": "Audio generado correctamente",
                "audio_url": "/download",
                "used_model_id": em.loaded_model_id,
                "reference_transcript": em.backend_state.get("active_reference_transcript", ""),
                "memory": get_memory_stats(),
            }
        except Exception as e:
            print(f"❌ Error en inferencia: {e}", flush=True)
            release_os_memory()
            raise HTTPException(status_code=500, detail=str(e))
        finally:
            em.backend_state["download_progress"] = 0.0
            em.backend_state["task_eta_sec"] = 0
            em.backend_state["status"] = (
                "READY"
                if (em.llm is not None or em.omni_model is not None)
                else prev_status
            )
            if em.loaded_model_id and em.loaded_model_id in MODEL_CATALOG:
                em.backend_state["message"] = f"Listo: {MODEL_CATALOG[em.loaded_model_id]['name']}"
            else:
                em.backend_state["message"] = "Motor TTS Listo"


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
    em.cached_omni_clone_prompt.clear()
    em.backend_state["active_reference_path"] = dest_path
    transcript = get_or_transcribe_reference_audio(dest_path, "")
    return {
        "info": "Voz de referencia cargada y transcrita con éxito",
        "path": dest_path,
        "name": safe_name,
        "transcript": transcript,
    }


if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=8000)
