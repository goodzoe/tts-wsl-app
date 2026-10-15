"""Utilidades de procesamiento digital de señal (DSP), gestión de RAM/VRAM y auto-transcripción Whisper."""

import os
import sys
import gc
import types
import ctypes
import numpy as np
import soundfile as sf
from config import load_transcripts_map, save_transcript_for_file

try:
    import psutil
    PSUTIL_AVAILABLE = True
except ImportError:
    PSUTIL_AVAILABLE = False

try:
    import torch
    import torch.nn.functional as F

    if not hasattr(torch, "accelerator"):
        torch.accelerator = types.SimpleNamespace(
            current_accelerator=lambda: (
                torch.device("cuda")
                if torch.cuda.is_available()
                else (
                    torch.device("mps")
                    if hasattr(torch.backends, "mps") and torch.backends.mps.is_available()
                    else torch.device("cpu")
                )
            ),
            is_available=lambda: (
                torch.cuda.is_available()
                or (hasattr(torch.backends, "mps") and torch.backends.mps.is_available())
            ),
        )
    TORCH_AVAILABLE = True
except ImportError:
    TORCH_AVAILABLE = False


def get_compute_device() -> str:
    """Devuelve 'cuda:0' (NVIDIA), 'mps' (Apple Silicon) o 'cpu' como respaldo."""
    if TORCH_AVAILABLE:
        try:
            if torch.cuda.is_available():
                return "cuda:0"
            if hasattr(torch.backends, "mps") and torch.backends.mps.is_available():
                return "mps"
        except Exception:
            pass
    return "cpu"


def get_gpu_stats() -> dict:
    """Obtiene el nombre y uso de VRAM de la GPU si está activa."""
    if not TORCH_AVAILABLE:
        return {"gpu_available": False, "gpu_name": "CPU Only", "vram_allocated_mb": 0.0, "vram_total_mb": 0.0}
    try:
        if torch.cuda.is_available():
            props = torch.cuda.get_device_properties(0)
            alloc_mb = torch.cuda.memory_allocated(0) / (1024.0 * 1024.0)
            reserv_mb = torch.cuda.memory_reserved(0) / (1024.0 * 1024.0)
            total_mb = props.total_memory / (1024.0 * 1024.0)
            return {
                "gpu_available": True,
                "gpu_name": props.name,
                "vram_allocated_mb": round(max(alloc_mb, reserv_mb), 1),
                "vram_total_mb": round(total_mb, 1),
            }
        if hasattr(torch.backends, "mps") and torch.backends.mps.is_available():
            alloc_mb = (
                torch.mps.current_allocated_memory() / (1024.0 * 1024.0)
                if hasattr(torch, "mps") and hasattr(torch.mps, "current_allocated_memory")
                else 0.0
            )
            return {
                "gpu_available": True,
                "gpu_name": "Apple Metal (MPS)",
                "vram_allocated_mb": round(alloc_mb, 1),
                "vram_total_mb": 0.0,
            }
    except Exception:
        pass
    return {"gpu_available": False, "gpu_name": "CPU Only", "vram_allocated_mb": 0.0, "vram_total_mb": 0.0}


def release_os_memory() -> None:
    """Fuerza al recolector de Python, PyTorch (CUDA/MPS) y glibc (solo Linux) a devolver páginas libres."""
    gc.collect()
    if TORCH_AVAILABLE:
        try:
            if torch.cuda.is_available():
                torch.cuda.empty_cache()
                torch.cuda.ipc_collect()
            elif hasattr(torch, "mps") and hasattr(torch.mps, "empty_cache"):
                torch.mps.empty_cache()
        except Exception:
            pass
    if sys.platform.startswith("linux"):
        try:
            ctypes.CDLL("libc.so.6").malloc_trim(0)
        except (OSError, AttributeError):
            pass


def get_memory_stats() -> dict:
    """Obtiene el uso actual de RAM del proceso, RAM del sistema y VRAM de forma multiplataforma."""
    mem_total_mb = 0.0
    mem_avail_mb = 0.0
    proc_rss_mb = 0.0

    if PSUTIL_AVAILABLE:
        try:
            vm = psutil.virtual_memory()
            mem_total_mb = vm.total / (1024.0 * 1024.0)
            mem_avail_mb = vm.available / (1024.0 * 1024.0)
            proc_rss_mb = psutil.Process(os.getpid()).memory_info().rss / (1024.0 * 1024.0)
        except Exception:
            pass
    elif sys.platform.startswith("linux"):
        try:
            if os.path.exists("/proc/meminfo"):
                with open("/proc/meminfo", "r", encoding="utf-8") as f:
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
                with open("/proc/self/status", "r", encoding="utf-8") as f:
                    for line in f:
                        if line.startswith("VmRSS:"):
                            proc_rss_mb = int(line.split()[1]) / 1024.0
                            break
        except Exception:
            pass

    mem_used_mb = max(0.0, mem_total_mb - mem_avail_mb)
    pct = (mem_used_mb / mem_total_mb * 100.0) if mem_total_mb > 0 else 0.0
    gpu_info = get_gpu_stats()
    return {
        "process_ram_mb": round(proc_rss_mb, 1),
        "system_used_gb": round(mem_used_mb / 1024.0, 2),
        "system_total_gb": round(mem_total_mb / 1024.0, 2),
        "system_percent": round(pct, 1),
        **gpu_info,
    }


def fast_resample_1d(wav: np.ndarray, factor: float) -> np.ndarray:
    """Re-muestreo lineal 1D ultrarrápido y seguro en RAM (< 2 MB)."""
    if abs(factor - 1.0) < 1e-3 or len(wav) < 16:
        return wav.astype(np.float32, copy=False)
    new_len = max(16, int(len(wav) / factor))
    if TORCH_AVAILABLE:
        t_in = torch.from_numpy(np.asarray(wav, dtype=np.float32)).view(1, 1, -1)
        t_out = F.interpolate(t_in, size=new_len, mode="linear", align_corners=False)
        return t_out.view(-1).numpy()
    x_old = np.linspace(0.0, 1.0, len(wav), dtype=np.float32)
    x_new = np.linspace(0.0, 1.0, new_len, dtype=np.float32)
    return np.interp(x_new, x_old, wav).astype(np.float32)


def gentle_voice_adjust(
    src_audio: np.ndarray,
    sr: int,
    pitch_semitones: float = 0.0,
    speed: float = 1.0,
) -> np.ndarray:
    """Ajuste limpio de velocidad (OLA) y tono fino (< 5 MB RAM)."""
    src_audio = np.asarray(src_audio, dtype=np.float32)
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

    peak = np.max(np.abs(pitched)) if len(pitched) > 0 else 0.0
    if peak > 1e-4:
        pitched = (pitched / peak) * 0.92
    return np.clip(pitched, -1.0, 1.0)


def get_or_transcribe_reference_audio(
    ref_path: str,
    user_ref_text: str = "",
    allow_auto_transcribe: bool = True,
) -> str:
    """Obtiene o transcribe el audio de referencia sin contaminar el prompt con texto falso si falla."""
    fname = os.path.basename(ref_path)
    if user_ref_text and user_ref_text.strip():
        clean = user_ref_text.strip()
        save_transcript_for_file(fname, clean)
        return clean

    tmap = load_transcripts_map()
    if fname in tmap and tmap[fname].strip():
        return tmap[fname].strip()

    if not allow_auto_transcribe:
        return ""

    try:
        from transformers import WhisperProcessor, WhisperForConditionalGeneration

        dev = get_compute_device()
        print(f"Auto-transcribiendo '{fname}' con Whisper-tiny en {dev}...", flush=True)
        data, sr = sf.read(ref_path, dtype="float32")
        if data.ndim > 1:
            data = data.mean(axis=1)
        data = data[: int(sr * 10.0)]
        wav16 = fast_resample_1d(data, float(sr) / 16000.0) if sr != 16000 else data

        proc = WhisperProcessor.from_pretrained("openai/whisper-tiny")
        w_model = WhisperForConditionalGeneration.from_pretrained("openai/whisper-tiny").to(dev)
        inp = proc(wav16, sampling_rate=16000, return_tensors="pt").input_features.to(dev)
        with torch.no_grad():
            ids = w_model.generate(inp, language="spanish", task="transcribe")
        txt = proc.batch_decode(ids, skip_special_tokens=True)[0].strip()
        del w_model, proc, inp, ids
        release_os_memory()
        if txt:
            save_transcript_for_file(fname, txt)
            print(f"Transcripcion detectada para '{fname}': {txt}", flush=True)
            return txt
    except Exception as e:
        print(f"Advertencia: No se pudo auto-transcribir {fname}: {e}", flush=True)

    return ""
