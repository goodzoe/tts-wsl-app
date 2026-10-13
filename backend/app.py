import os
import glob
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
    reference_file: str = "base_voice.mp3"
    reference_text: str = ""
    ref_duration: float = 2.5
    speaker_hint: str = "maria"
    auto_clone_voice: bool = True
    pitch_semitones: float = 0.0
    formant_shift: float = 1.18
    timbre_strength: float = 0.60
    speed: float = 1.0
    temperature: float = 0.65
    top_k: int = 50
    top_p: float = 0.90
    repeat_penalty: float = 1.12
    max_audio_tokens: int = 840
    seed: int = -1


BASE_DIR = os.path.dirname(os.path.abspath(__file__))
MODEL_REPO = "Jhonito45/orpheus-spanish-tts-finetuned-new-one-epoch-10-Q4_K_M-GGUF"
MODEL_FILE = "orpheus-spanish-tts-finetuned-new-one-epoch-10-q4_k_m.gguf"
MODEL_PATH = os.path.join(BASE_DIR, "models", MODEL_FILE)
SNAC_REPO = "hubertsiuzdak/snac_24khz"
REF_DIR = os.path.join(BASE_DIR, "reference_audio")
DEFAULT_REF_AUDIO = os.path.join(REF_DIR, "base_voice.mp3")
OUT_AUDIO_PATH = os.path.join(BASE_DIR, "output_audio.wav")

llm = None
snac_model = None
llm_lock = threading.Lock()
cached_ref_tokens = {}

backend_state = {
    "status": "INITIALIZING",
    "message": "Iniciando servidor backend...",
    "default_reference_path": DEFAULT_REF_AUDIO,
    "active_reference_path": DEFAULT_REF_AUDIO,
    "reference_f0_hz": 0.0,
}


def estimate_f0(sig: np.ndarray, sr: int = 24000) -> float:
    """Estima la frecuencia fundamental mediana (F0 en Hz) en cuadros sonorizados."""
    if sig is None or len(sig) < int(sr * 0.08):
        return 0.0
    frame_len = int(sr * 0.04)
    hop = int(sr * 0.015)
    f0s = []
    for i in range(0, len(sig) - frame_len, hop):
        frame = sig[i : i + frame_len]
        if np.sqrt(np.mean(frame ** 2)) < 0.02:
            continue
        frame = frame - np.mean(frame)
        corr = np.correlate(frame, frame, mode="full")[frame_len - 1 :]
        min_lag = int(sr / 360)
        max_lag = int(sr / 70)
        if max_lag < len(corr):
            lag = int(np.argmax(corr[min_lag:max_lag]) + min_lag)
            if corr[lag] > 0.30 * corr[0]:
                f0s.append(sr / lag)
    return float(np.median(f0s)) if f0s else 0.0


def resolve_ref_path(ref_file_or_path: str) -> str:
    if not ref_file_or_path:
        return DEFAULT_REF_AUDIO
    if os.path.isabs(ref_file_or_path) and os.path.exists(ref_file_or_path):
        return ref_file_or_path
    candidate = os.path.join(REF_DIR, os.path.basename(ref_file_or_path))
    if os.path.exists(candidate):
        return candidate
    return DEFAULT_REF_AUDIO


def encode_reference_audio_to_tokens(audio_path: str, max_seconds: float = 2.5) -> list[int]:
    """Codifica los primeros segundos del audio de referencia en tokens SNAC (Zero-Shot)."""
    global snac_model, cached_ref_tokens
    if snac_model is None or not os.path.exists(audio_path):
        return []
    try:
        max_seconds = max(0.5, min(6.0, float(max_seconds)))
        mtime = os.path.getmtime(audio_path)
        cache_key = (audio_path, round(max_seconds, 1), mtime)
        if cache_key in cached_ref_tokens:
            return cached_ref_tokens[cache_key]

        data, sr = sf.read(audio_path, dtype="float32")
        if data.ndim > 1:
            data = data.mean(axis=1)
        waveform = torch.from_numpy(data).unsqueeze(0)
        if sr != 24000:
            waveform = torchaudio.functional.resample(waveform, sr, 24000)
        max_samples = int(24000 * max_seconds)
        waveform = waveform[:, :max_samples]

        dev_snac = next(snac_model.parameters()).device
        with torch.no_grad():
            codes = snac_model.encode(waveform.unsqueeze(0).to(dev_snac))

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

        cached_ref_tokens[cache_key] = interleaved
        return interleaved
    except Exception as e:
        print(f"⚠️ Error codificando audio de referencia SNAC ({e})", flush=True)
        return []


def apply_voice_cloning_transfer(
    src_audio: np.ndarray,
    sr: int,
    ref_path: str,
    auto_clone_voice: bool = True,
    pitch_semitones: float = 0.0,
    formant_shift: float = 1.18,
    timbre_strength: float = 0.60,
    speed: float = 1.0,
) -> np.ndarray:
    """Transfiere F0 (tono), formantes del tracto vocal y envolvente espectral de la voz de referencia."""
    try:
        ref_data, ref_sr = sf.read(ref_path, dtype="float32")
        if ref_data.ndim > 1:
            ref_data = ref_data.mean(axis=1)
        if ref_sr != sr:
            ref_t = (
                torchaudio.functional.resample(
                    torch.from_numpy(ref_data).float().unsqueeze(0), ref_sr, sr
                )
                .squeeze(0)
                .numpy()
            )
        else:
            ref_t = ref_data.astype(np.float32)

        f0_ref = estimate_f0(ref_t, sr)
        f0_src = estimate_f0(src_audio, sr)
        backend_state["reference_f0_hz"] = round(f0_ref, 1)

        if auto_clone_voice and f0_ref > 80.0 and f0_src > 65.0:
            auto_semi = 12.0 * np.log2(f0_ref / f0_src)
            auto_semi = float(np.clip(auto_semi, -14.0, 14.0))
        elif auto_clone_voice:
            auto_semi = 8.5
        else:
            auto_semi = 0.0

        total_semi = auto_semi + float(pitch_semitones)
        pitch_factor = 2.0 ** (total_semi / 12.0)
        eff_speed = max(0.5, min(2.0, float(speed)))

        print(
            f"🎙️ Clonación Acústica: F0_src={f0_src:.1f}Hz -> F0_ref={f0_ref:.1f}Hz "
            f"(shift={total_semi:+.1f}st, formant={formant_shift:.2f}, timbre={timbre_strength:.2f})",
            flush=True,
        )

        n_fft = 1024
        hop = 256
        win = torch.hann_window(n_fft)
        src_t = torch.from_numpy(src_audio).float()

        stretch_rate = eff_speed / pitch_factor
        spec = torch.stft(
            src_t, n_fft=n_fft, hop_length=hop, win_length=n_fft, window=win, return_complex=True
        )
        n_bins = spec.shape[0]
        phase_advance = torch.linspace(0, np.pi * hop, n_bins)[..., None]
        stretched_spec = torchaudio.functional.phase_vocoder(
            spec.unsqueeze(0), rate=stretch_rate, phase_advance=phase_advance
        ).squeeze(0)

        stretched_wav = torch.istft(
            stretched_spec, n_fft=n_fft, hop_length=hop, win_length=n_fft, window=win
        )
        pitched_wav = torchaudio.functional.resample(
            stretched_wav.unsqueeze(0), int(sr * pitch_factor), sr
        ).squeeze(0)

        # Transferencia de formantes y envolvente espectral cepstral
        ref_slice = ref_t[: min(len(ref_t), sr * 8)]
        ref_spec = torch.stft(
            torch.from_numpy(ref_slice).float(),
            n_fft=n_fft,
            hop_length=hop,
            win_length=n_fft,
            window=win,
            return_complex=True,
        )
        ref_mag = torch.abs(ref_spec)
        ref_energy = ref_mag.mean(dim=0)
        voiced_ref = ref_mag[:, ref_energy > torch.quantile(ref_energy, 0.35)]
        if voiced_ref.shape[1] == 0:
            voiced_ref = ref_mag
        ref_env = torch.mean(torch.log(voiced_ref + 1e-6), dim=1).numpy()

        cep_ref = np.fft.irfft(ref_env)
        lifter = np.zeros_like(cep_ref)
        lifter[:30] = 1.0
        lifter[-29:] = 1.0
        smooth_ref_env = np.fft.rfft(cep_ref * lifter).real

        p_spec = torch.stft(
            pitched_wav,
            n_fft=n_fft,
            hop_length=hop,
            win_length=n_fft,
            window=win,
            return_complex=True,
        )
        p_mag = torch.abs(p_spec).numpy()
        p_phase = torch.angle(p_spec).numpy()

        src_energy = p_mag.mean(axis=0)
        voiced_src = p_mag[:, src_energy > np.quantile(src_energy, 0.35)]
        if voiced_src.shape[1] == 0:
            voiced_src = p_mag
        src_env = np.mean(np.log(voiced_src + 1e-6), axis=1)
        cep_src = np.fft.irfft(src_env)
        smooth_src_env = np.fft.rfft(cep_src * lifter).real

        bins = np.arange(len(smooth_src_env))
        eff_formant = pitch_factor / max(0.70, min(1.60, float(formant_shift)))
        warped_src_env = np.interp(
            bins * eff_formant,
            bins,
            smooth_src_env,
            left=smooth_src_env[0],
            right=smooth_src_env[-1],
        )

        t_str = max(0.0, min(1.0, float(timbre_strength)))
        target_env = (1.0 - t_str) * warped_src_env + t_str * smooth_ref_env
        max_db_rad = 11.0 / 20.0 * np.log(10.0)
        gain_log = np.clip(target_env - smooth_src_env, -max_db_rad, max_db_rad)
        gain = np.exp(gain_log)[:, None]

        new_mag = p_mag * gain
        new_spec = torch.from_numpy(new_mag * np.exp(1j * p_phase)).to(torch.complex64)
        out_wav = torch.istft(
            new_spec, n_fft=n_fft, hop_length=hop, win_length=n_fft, window=win
        ).numpy()

        peak = np.max(np.abs(out_wav))
        if peak > 1e-4:
            out_wav = (out_wav / peak) * 0.92
        return np.clip(out_wav, -1.0, 1.0)
    except Exception as e:
        print(f"⚠️ Advertencia en transferencia acústica ({e}), usando audio base.", flush=True)
        return np.clip(src_audio, -1.0, 1.0)


def decode_snac_tokens_to_wav(
    token_ids: list[int],
    out_path: str,
    ref_path: str,
    request: TTSRequest,
) -> bool:
    """Decodifica los tokens SNAC a 24kHz, aplica clonación acústica a la voz de referencia y guarda WAV PCM_16."""
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

    if (
        request.auto_clone_voice
        or abs(request.pitch_semitones) > 0.05
        or abs(request.speed - 1.0) > 0.03
        or request.timbre_strength > 0.05
    ):
        audio_hat = apply_voice_cloning_transfer(
            src_audio=audio_hat,
            sr=24000,
            ref_path=ref_path,
            auto_clone_voice=request.auto_clone_voice,
            pitch_semitones=request.pitch_semitones,
            formant_shift=request.formant_shift,
            timbre_strength=request.timbre_strength,
            speed=request.speed,
        )

    sf.write(out_path, audio_hat, 24000, subtype="PCM_16")
    return True


def load_models_background():
    global llm, snac_model, backend_state
    try:
        if os.path.exists(DEFAULT_REF_AUDIO):
            ref_d, ref_sr = sf.read(DEFAULT_REF_AUDIO, dtype="float32")
            if ref_d.ndim > 1:
                ref_d = ref_d.mean(axis=1)
            backend_state["reference_f0_hz"] = round(estimate_f0(ref_d, ref_sr), 1)
    except Exception:
        pass

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
            hf_hub_download(
                repo_id=MODEL_REPO,
                filename=MODEL_FILE,
                local_dir=os.path.join(BASE_DIR, "models"),
            )

        backend_state["status"] = "LOADING"
        backend_state["message"] = "Cargando Orpheus GGUF + Vocoder SNAC 24kHz..."
        print("🧠 Cargando modelo GGUF con llama.cpp (use_mmap=False)...", flush=True)
        llm = Llama(
            model_path=MODEL_PATH,
            n_gpu_layers=-1,
            n_ctx=2048,
            n_threads=max(4, (os.cpu_count() or 8) - 2),
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


app = FastAPI(title="LatAm TTS Backend (GGUF Q4 + SNAC + Voice Cloning)", lifespan=lifespan)

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


@app.get("/reference_files")
async def list_reference_files():
    os.makedirs(REF_DIR, exist_ok=True)
    files = []
    for ext in ("*.mp3", "*.wav"):
        for p in sorted(glob.glob(os.path.join(REF_DIR, ext))):
            try:
                # Validar que el archivo sea legible por soundfile
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
        "reference_f0_hz": backend_state.get("reference_f0_hz", 0.0),
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
        backend_state["message"] = "Clonando voz y generando audio..."
        try:
            if not AI_AVAILABLE or llm is None or snac_model is None:
                data, sr = sf.read(ref_path, dtype="float32")
                sf.write(OUT_AUDIO_PATH, data, sr, subtype="PCM_16")
                return {
                    "status": "success",
                    "message": "Audio generado (Simulado)",
                    "audio_url": "/download",
                }

            if int(request.seed) >= 0:
                llm.set_seed(int(request.seed))

            spk = request.speaker_hint.strip()
            formatted_text = f"{spk}: {text}" if spk and spk.lower() != "ninguna" else text
            print(
                f"🧠 Sintetizando [{os.path.basename(ref_path)}] ({len(text)} chars): {formatted_text[:65]}...",
                flush=True,
            )

            # Codificar tokens SNAC del audio de referencia (Zero-Shot Turn)
            ref_snac_tokens = encode_reference_audio_to_tokens(
                ref_path, max_seconds=request.ref_duration
            )

            target_tokens = llm.tokenize(formatted_text.encode("utf-8"), add_bos=False)
            if ref_snac_tokens:
                ref_caption = (
                    request.reference_text.strip()
                    or "Hola, bienvenidos a un nuevo capítulo de nuestra historia."
                )
                ref_prompt = f"{spk}: {ref_caption}" if spk and spk.lower() != "ninguna" else ref_caption
                ref_text_tokens = llm.tokenize(ref_prompt.encode("utf-8"), add_bos=True)
                # Turno 1 (Voz de referencia audio+texto) + Turno 2 (Texto objetivo a sintetizar)
                input_tokens = (
                    [128259]
                    + ref_text_tokens
                    + [128009, 128260, 128261, 128257]
                    + ref_snac_tokens
                    + [128258, 128262, 128259]
                    + target_tokens
                    + [128009, 128260, 128261, 128257]
                )
            else:
                text_tokens = llm.tokenize(formatted_text.encode("utf-8"), add_bos=True)
                input_tokens = [128259] + text_tokens + [128009, 128260, 128261, 128257]

            est_frames = max(25, min(300, int(len(text) * 1.9)))
            user_cap = max(140, min(2048, int(request.max_audio_tokens)))
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
                f"🎵 Decodificando {len(generated_tokens)} tokens SNAC + transferencia de voz femenina ({os.path.basename(ref_path)})...",
                flush=True,
            )
            ok = decode_snac_tokens_to_wav(
                generated_tokens, OUT_AUDIO_PATH, ref_path, request
            )
            if not ok:
                raise RuntimeError("No se generaron suficientes tokens de audio válidos.")

            print("✅ Audio WAV PCM_16 clonado y generado exitosamente.", flush=True)
            return {
                "status": "success",
                "message": "Audio clonado y generado correctamente",
                "audio_url": "/download",
                "reference_f0_hz": backend_state.get("reference_f0_hz", 0.0),
            }
        except Exception as e:
            print(f"❌ Error en inferencia: {e}", flush=True)
            raise HTTPException(status_code=500, detail=str(e))
        finally:
            backend_state["status"] = (
                "READY" if AI_AVAILABLE and llm is not None else prev_status
            )
            backend_state["message"] = "Motor TTS Zero-Shot Listo"


@app.get("/download")
async def download_audio():
    if os.path.exists(OUT_AUDIO_PATH):
        return FileResponse(OUT_AUDIO_PATH, media_type="audio/wav", filename="resultado.wav")
    raise HTTPException(status_code=404, detail="Audio no encontrado")


@app.post("/upload_reference")
async def upload_reference(file: UploadFile = File(...)):
    global cached_ref_tokens
    os.makedirs(REF_DIR, exist_ok=True)
    safe_name = os.path.basename(file.filename or "custom_voice.mp3")
    dest_path = os.path.join(REF_DIR, safe_name)
    content = await file.read()
    with open(dest_path, "wb+") as f:
        f.write(content)
    # Actualizar también base_voice.mp3 como predeterminado activo
    if dest_path != DEFAULT_REF_AUDIO:
        with open(DEFAULT_REF_AUDIO, "wb+") as f:
            f.write(content)
    cached_ref_tokens.clear()
    backend_state["active_reference_path"] = dest_path
    try:
        ref_d, ref_sr = sf.read(dest_path, dtype="float32")
        if ref_d.ndim > 1:
            ref_d = ref_d.mean(axis=1)
        backend_state["reference_f0_hz"] = round(estimate_f0(ref_d, ref_sr), 1)
    except Exception:
        pass
    return {
        "info": "Voz de referencia cargada con éxito",
        "path": dest_path,
        "reference_f0_hz": backend_state.get("reference_f0_hz", 0.0),
    }


if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=8000)
