"""Gestor de descarga, carga, cambio, liberación e inferencia de modelos TTS (OmniVoice & Orpheus GGUF)."""

import os
import glob
import time
import threading
import numpy as np
import soundfile as sf
from tqdm.auto import tqdm
from huggingface_hub import hf_hub_download, snapshot_download

from config import (
    MODELS_DIR,
    DEFAULT_REF_AUDIO,
    OUT_AUDIO_PATH,
    SNAC_REPO,
    MODEL_CATALOG,
    DEFAULT_CPU_THREADS,
    is_model_downloaded,
)
from schemas import TTSRequest
from audio_dsp import (
    TORCH_AVAILABLE,
    release_os_memory,
    fast_resample_1d,
    gentle_voice_adjust,
    get_or_transcribe_reference_audio,
)

if TORCH_AVAILABLE:
    import torch
    torch.set_num_threads(DEFAULT_CPU_THREADS)

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
    "active_reference_transcript": "",
}


class DownloadProgressTqdm(tqdm):
    """Hook de progreso para huggingface_hub que expone porcentaje, MB/s y ETA en backend_state."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._dl_start_t = time.time()

    def update(self, n=1):
        super().update(n)
        if self.total and self.total > 5 * 1024 * 1024:
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
                f"Descargando: {pct:.1f}% ({mb_done:.0f}/{mb_tot:.0f} MB) • {speed_mbps:.1f} MB/s • ETA {int(elapsed)}s / ~{int(elapsed)+eta_s}s"
            )


def unload_models_internal() -> None:
    """Libera todos los modelos de RAM/VRAM y devuelve las páginas al kernel Linux."""
    global llm, snac_model, omni_model, loaded_model_id
    with llm_lock:
        for obj_name in ("llm", "snac_model", "omni_model"):
            if globals().get(obj_name) is not None:
                try:
                    del globals()[obj_name]
                except Exception:
                    pass
                globals()[obj_name] = None
        cached_omni_clone_prompt.clear()
        loaded_model_id = None
        release_os_memory()
        backend_state.update({
            "status": "UNLOADED",
            "loaded_model_id": None,
            "loaded_model_name": "Ninguno (Memoria Liberada)",
            "loaded_engine": None,
            "download_progress": 0.0,
            "task_eta_sec": 0,
            "message": "Memoria RAM/VRAM liberada. Selecciona y carga un modelo.",
        })
        print("🧹 Modelos descargados de RAM/VRAM correctamente.", flush=True)


def load_model_worker(model_id: str, cpu_threads: int = DEFAULT_CPU_THREADS, n_ctx: int = 1024) -> None:
    """Descarga (si no existe localmente) y carga en RAM/VRAM el modelo solicitado."""
    global llm, snac_model, omni_model, loaded_model_id
    if model_id not in MODEL_CATALOG:
        model_id = "omnivoice-zeroshot-0.6b"

    cfg = MODEL_CATALOG[model_id]
    engine = cfg.get("engine", "gguf")
    local_path = cfg.get("local_path", os.path.join(MODELS_DIR, cfg.get("filename", "")))

    with llm_lock:
        try:
            if llm is not None:
                del llm
                llm = None
            if omni_model is not None:
                del omni_model
                omni_model = None
            cached_omni_clone_prompt.clear()
            release_os_memory()

            threads = max(2, min(8, int(cpu_threads)))
            if TORCH_AVAILABLE:
                torch.set_num_threads(threads)

            if engine == "omnivoice":
                if not OMNIVOICE_AVAILABLE:
                    raise RuntimeError("La librería 'omnivoice' no está instalada.")

                if not is_model_downloaded(cfg):
                    backend_state.update({
                        "status": "DOWNLOADING",
                        "task_start_time": time.time(),
                        "download_progress": 1.0,
                        "download_mb": 0.0,
                        "download_total_mb": cfg.get("size_gb", 1.5) * 1024,
                        "message": f"Descargando {cfg['name']}...",
                    })
                    snapshot_download(
                        repo_id=cfg["repo_id"],
                        local_dir=local_path,
                        tqdm_class=DownloadProgressTqdm,
                    )

                backend_state.update({
                    "status": "LOADING",
                    "task_start_time": time.time(),
                    "download_progress": 100.0,
                    "message": f"Cargando {cfg['name']} en memoria ({threads} hilos CPU)...",
                })
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
                backend_state.update({
                    "status": "READY",
                    "loaded_model_id": model_id,
                    "loaded_model_name": cfg["name"],
                    "loaded_engine": "omnivoice",
                    "download_progress": 0.0,
                    "message": f"Listo: {cfg['name']}",
                })
                print(f"✅ OmniVoice cargado en {dev} (threads={threads}). Estado: READY", flush=True)

            else:
                if not os.path.exists(local_path):
                    if not cfg.get("repo_id"):
                        raise FileNotFoundError(f"No existe el archivo local: {local_path}")
                    backend_state.update({
                        "status": "DOWNLOADING",
                        "task_start_time": time.time(),
                        "download_progress": 1.0,
                        "download_mb": 0.0,
                        "download_total_mb": cfg.get("size_gb", 2.0) * 1024,
                        "message": f"Descargando {cfg['name']}...",
                    })
                    hf_hub_download(
                        repo_id=cfg["repo_id"],
                        filename=cfg["filename"],
                        local_dir=MODELS_DIR,
                        tqdm_class=DownloadProgressTqdm,
                    )

                backend_state.update({
                    "status": "LOADING",
                    "task_start_time": time.time(),
                    "download_progress": 100.0,
                    "message": f"Cargando {cfg['name']} en memoria...",
                })
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
                    snac_model = SNAC.from_pretrained(SNAC_REPO).eval()

                loaded_model_id = model_id
                release_os_memory()
                backend_state.update({
                    "status": "READY",
                    "loaded_model_id": model_id,
                    "loaded_model_name": cfg["name"],
                    "loaded_engine": "gguf",
                    "download_progress": 0.0,
                    "message": f"Listo: {cfg['name']}",
                })
                print(f"✅ Modelo GGUF {cfg['name']} cargado. Estado: READY", flush=True)

        except Exception as e:
            backend_state["status"] = "ERROR"
            backend_state["message"] = f"Error cargando modelo: {str(e)}"
            print(f"❌ Error al cargar modelo: {e}", flush=True)
            release_os_memory()


def _decode_snac_tokens_to_wav(token_ids: list[int], out_path: str, request: TTSRequest) -> bool:
    """Decodifica frames de 7 tokens SNAC a WAV 24kHz PCM_16."""
    global snac_model
    OFFSET = 128266
    valid = [int(t) - OFFSET for t in token_ids if OFFSET <= int(t) < OFFSET + 7 * 4096]
    n_frames = len(valid) // 7
    if n_frames == 0 or snac_model is None:
        return False

    l1, l2, l3 = [], [], []
    for i in range(n_frames):
        b = 7 * i
        t0, t1, t2, t3, t4, t5, t6 = (
            valid[b],
            valid[b + 1] - 4096,
            valid[b + 2] - 2 * 4096,
            valid[b + 3] - 3 * 4096,
            valid[b + 4] - 4 * 4096,
            valid[b + 5] - 5 * 4096,
            valid[b + 6] - 6 * 4096,
        )
        if all(0 <= x < 4096 for x in (t0, t1, t2, t3, t4, t5, t6)):
            l1.append(t0)
            l2.extend([t1, t4])
            l3.extend([t2, t3, t5, t6])

    if not l1:
        return False

    dev_snac = next(snac_model.parameters()).device
    layers = [
        torch.tensor(l1, dtype=torch.long, device=dev_snac).unsqueeze(0),
        torch.tensor(l2, dtype=torch.long, device=dev_snac).unsqueeze(0),
        torch.tensor(l3, dtype=torch.long, device=dev_snac).unsqueeze(0),
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


def sanitize_omnivoice_instruct(raw_instruct: str) -> str:
    """
    Convierte cualquier descripción en español o inglés (libre) a las etiquetas exactas de vocabulario cerrado
    que acepta OmniVoice._resolve_instruct (máximo 1 por categoría: gender, age, pitch, style, accent),
    evitando por completo el error 500 'ValueError: Unsupported instruct items found'.
    """
    if not raw_instruct or not raw_instruct.strip():
        return ""
    s = raw_instruct.lower()

    gender = None
    if any(w in s for w in ["femenin", "female", "mujer", "chica", "girl", "woman", "barbie", "maria", "lucia", "sofia", "tara", "leah"]):
        gender = "female"
    elif any(w in s for w in ["masculin", "male", "hombre", "chico", "boy", "man", "javi"]):
        gender = "male"

    age = None
    if any(w in s for w in ["niñ", "child", "kid", "infantil"]):
        age = "child"
    elif any(w in s for w in ["adolescente", "teen", "teenager", "15", "16", "17"]):
        age = "teenager"
    elif any(w in s for w in ["ancian", "mayor", "viejo", "elderly", "old", "abuel"]):
        age = "elderly"
    elif any(w in s for w in ["adulto medio", "middle-aged", "40", "50", "madur"]):
        age = "middle-aged"
    elif any(w in s for w in ["joven", "young", "20", "21", "22", "23", "24", "25", "juvenil"]):
        age = "young adult"

    pitch = None
    if any(w in s for w in ["muy agud", "very high pitch"]):
        pitch = "very high pitch"
    elif any(w in s for w in ["agud", "high pitch", "brillante", "alegre"]):
        pitch = "high pitch"
    elif any(w in s for w in ["muy grave", "very low pitch", "profund"]):
        pitch = "very low pitch"
    elif any(w in s for w in ["grave", "low pitch", "bajo"]):
        pitch = "low pitch"
    elif any(w in s for w in ["moderad", "moderate pitch", "natural", "suave", "calid", "cálid", "calm", "conversacional"]):
        pitch = "moderate pitch"

    style = None
    if any(w in s for w in ["susurr", "whisper", "intim", "íntim", "secreto"]):
        style = "whisper"

    accent = None
    if "british" in s or "británic" in s or "britanic" in s:
        accent = "british accent"
    elif "australian" in s:
        accent = "australian accent"
    elif "canadian" in s:
        accent = "canadian accent"
    elif "indian" in s:
        accent = "indian accent"
    elif "portuguese" in s or "portugu" in s or "brasil" in s:
        accent = "portuguese accent"
    elif "russian" in s or "ruso" in s:
        accent = "russian accent"
    elif "japanese" in s or "japon" in s:
        accent = "japanese accent"
    elif "korean" in s or "corean" in s:
        accent = "korean accent"
    elif "chinese" in s or "chin" in s:
        accent = "chinese accent"

    tags = [t for t in (gender, age, pitch, style, accent) if t]
    return ", ".join(tags)


def run_omnivoice_synthesis(request: TTSRequest, ref_path: str) -> None:
    """
    Ejecuta síntesis en OmniVoice con sus 3 modos reales:
    - 'clone': Clona la voz del archivo ref_path usando su transcripción real alineada.
               En modo clone sólo pasa 'whisper' si el usuario pide susurro explícitamente,
               para que ningún atributo de diseño pise el timbre del audio de referencia.
    - 'design': Crea una voz desde cero traduciendo voice_description + style_instruct
                al vocabulario válido de OmniVoice.
    - 'tts': Usa las etiquetas válidas del speaker seleccionado + style_instruct.
    """
    global omni_model, cached_omni_clone_prompt
    text = request.text.strip()
    if TORCH_AVAILABLE:
        torch.set_num_threads(max(2, min(8, int(request.cpu_threads or DEFAULT_CPU_THREADS))))

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

    if request.mode == "clone":
        if not os.path.exists(ref_path):
            raise FileNotFoundError(f"No existe el audio de referencia: {ref_path}")

        # Obtener la transcripción real del audio base (desde input usuario, transcripts.json o Whisper-tiny)
        ref_text_aligned = get_or_transcribe_reference_audio(ref_path, request.reference_text)
        backend_state["active_reference_transcript"] = ref_text_aligned

        mtime = os.path.getmtime(ref_path)
        cache_key = (ref_path, mtime, ref_text_aligned, bool(request.preprocess_prompt))
        if cache_key not in cached_omni_clone_prompt:
            data, sr = sf.read(ref_path, dtype="float32")
            if data.ndim > 1:
                data = data.mean(axis=1)
            data = data[: int(sr * 10.0)]
            target_sr = int(getattr(omni_model, "sampling_rate", 24000) or 24000)
            if sr != target_sr:
                data = fast_resample_1d(data, float(sr) / float(target_sr))
                sr = target_sr
            wav_tensor = torch.from_numpy(data)
            cached_omni_clone_prompt[cache_key] = omni_model.create_voice_clone_prompt(
                ref_audio=(wav_tensor, sr),
                ref_text=ref_text_aligned,
                preprocess_prompt=bool(request.preprocess_prompt),
            )
        kw["voice_clone_prompt"] = cached_omni_clone_prompt[cache_key]
        # En modo CLONE no se pasa instruct de género/edad porque sobreescribe el timbre clonado.
        # Solo permitimos 'whisper' si el usuario explícitamente pide susurro.
        if "whisper" in request.style_instruct.lower() or "susurr" in request.style_instruct.lower():
            kw["instruct"] = "whisper"

    elif request.mode == "design":
        combined_raw = f"{request.voice_description} {request.style_instruct}".strip()
        valid_inst = sanitize_omnivoice_instruct(combined_raw) or "female, young adult, moderate pitch"
        kw["instruct"] = valid_inst

    else:
        # Modo TTS (Voces Nativas / Predefinidas)
        spk_map = {
            "maria": "female, young adult, moderate pitch",
            "lucia": "female, young adult, high pitch",
            "sofia": "female, teenager, high pitch",
            "tara": "female, middle-aged, moderate pitch",
            "leah": "female, young adult, low pitch",
            "javi": "male, young adult, moderate pitch",
        }
        base_spk = spk_map.get(request.speaker_hint.lower(), "female, young adult, moderate pitch")
        valid_inst = sanitize_omnivoice_instruct(f"{base_spk}, {request.style_instruct}") or base_spk
        kw["instruct"] = valid_inst

    if int(request.seed) >= 0 and TORCH_AVAILABLE:
        torch.manual_seed(int(request.seed))

    step_counter = [0]
    total_steps = max(1, int(gen_config.num_step))
    step_start_t = time.time()

    def _omni_step_hook(_mod, _inp, _out):
        step_counter[0] += 1
        cur_step = min(total_steps, step_counter[0])
        pct = min(96.0, 12.0 + (cur_step / total_steps) * 84.0)
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


def run_gguf_synthesis(request: TTSRequest, gen_start: float) -> None:
    """Ejecuta síntesis en modelos GGUF (Canopy / Orpheus 3B) y decodifica con SNAC 24kHz."""
    global llm, loaded_model_id
    llm.reset()
    if int(request.seed) >= 0:
        llm.set_seed(int(request.seed))

    spk = request.speaker_hint.strip()
    style_prefix = ""
    if request.mode == "design" and request.voice_description.strip():
        style_prefix = f"[{request.voice_description.strip()}] "
    elif request.style_instruct.strip():
        style_prefix = f"[{request.style_instruct.strip()}] "

    text = request.text.strip()
    formatted_text = (
        f"{spk}: {style_prefix}{text}"
        if spk and spk.lower() != "ninguna"
        else f"{style_prefix}{text}"
    )

    text_tokens = llm.tokenize(formatted_text.encode("utf-8"), add_bos=True)
    input_tokens = [128259] + text_tokens + [128009, 128260, 128261, 128257]

    est_frames = max(25, min(260, int(len(text) * 1.8)))
    user_cap = max(140, min(2030, int(request.max_audio_tokens)))
    max_tokens_limit = (min(user_cap, est_frames * 7) // 7) * 7

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
                    f"GGUF ({loaded_model_id}): {pct:.0f}% ({n_gen // 7} frames) • ETA {int(elapsed)}s / ~{tot_est_s}s"
                )
        if len(generated_tokens) >= max_tokens_limit:
            break

    backend_state["download_progress"] = 97.0
    backend_state["message"] = "Decodificando audio neuronal SNAC 24kHz..."
    ok = _decode_snac_tokens_to_wav(generated_tokens, OUT_AUDIO_PATH, request)
    if not ok:
        raise RuntimeError("No se generaron suficientes tokens de audio válidos.")
