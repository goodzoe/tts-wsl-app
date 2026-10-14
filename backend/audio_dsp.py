"""Utilidades de procesamiento digital de señal (DSP), gestión de RAM/VRAM y auto-transcripción Whisper."""

import os
import gc
import ctypes
import numpy as np
import soundfile as sf
from config import load_transcripts_map, save_transcript_for_file

try:
    import torch
    import torch.nn.functional as F
    TORCH_AVAILABLE = True
except ImportError:
    TORCH_AVAILABLE = False


def release_os_memory() -> None:
    """Fuerza al recolector de Python, PyTorch y glibc (Linux) a devolver páginas libres al kernel."""
    gc.collect()
    if TORCH_AVAILABLE:
        try:
            if torch.cuda.is_available():
                torch.cuda.empty_cache()
        except Exception:
            pass
    try:
        ctypes.CDLL("libc.so.6").malloc_trim(0)
    except Exception:
        pass


def get_memory_stats() -> dict:
    """Obtiene el uso actual de RAM del proceso y del sistema en Linux/WSL2."""
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


def fast_resample_1d(wav: np.ndarray, factor: float) -> np.ndarray:
    """Re-muestreo lineal 1D ultrarrápido y seguro en RAM (< 2 MB). Evita picos de torchaudio.resample."""
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
    """Ajuste limpio de velocidad (OLA) y tono fino (< 5 MB RAM)."""
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


def get_or_transcribe_reference_audio(ref_path: str, user_ref_text: str = "") -> str:
    """
    Devuelve la transcripción real del audio de referencia para clonación Zero-Shot precisa:
    1. Si el usuario ingresó transcripción manual, la usa y la guarda.
    2. Si ya existe en transcripts.json, la devuelve al instante.
    3. Si es un audio nuevo sin transcripción, ejecuta openai/whisper-tiny (<150MB, ~1s),
       libera la memoria y persiste el texto en transcripts.json.
    """
    fname = os.path.basename(ref_path)
    if user_ref_text and user_ref_text.strip():
        clean = user_ref_text.strip()
        save_transcript_for_file(fname, clean)
        return clean

    tmap = load_transcripts_map()
    if fname in tmap and tmap[fname].strip():
        return tmap[fname].strip()

    try:
        from transformers import WhisperProcessor, WhisperForConditionalGeneration
        print(f"🎙️ Auto-transcribiendo audio de referencia '{fname}' con Whisper-tiny...", flush=True)
        data, sr = sf.read(ref_path, dtype="float32")
        if data.ndim > 1:
            data = data.mean(axis=1)
        data = data[: int(sr * 10.0)]
        wav16 = fast_resample_1d(data, float(sr) / 16000.0) if sr != 16000 else data

        proc = WhisperProcessor.from_pretrained("openai/whisper-tiny")
        w_model = WhisperForConditionalGeneration.from_pretrained("openai/whisper-tiny")
        inp = proc(wav16, sampling_rate=16000, return_tensors="pt").input_features
        with torch.no_grad():
            ids = w_model.generate(inp, language="spanish", task="transcribe")
        txt = proc.batch_decode(ids, skip_special_tokens=True)[0].strip()
        del w_model, proc, inp, ids
        release_os_memory()
        if txt:
            save_transcript_for_file(fname, txt)
            print(f"✅ Transcripción detectada para '{fname}': {txt}", flush=True)
            return txt
    except Exception as e:
        print(f"⚠️ No se pudo auto-transcribir {fname}: {e}", flush=True)

    return "Hola, soy Barbie, qué lindo tenerte por acá."
