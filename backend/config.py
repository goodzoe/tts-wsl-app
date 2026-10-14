"""Configuración global, rutas, capacidades y catálogo de modelos para LatAm Studio TTS Backend."""

import os
import json
import glob

# Configurar hilos de CPU a 6 por defecto (óptimo para i5-13420H de 8 hilos en WSL2)
DEFAULT_CPU_THREADS = min(6, max(2, os.cpu_count() or 4))
os.environ.setdefault("OMP_NUM_THREADS", str(DEFAULT_CPU_THREADS))
os.environ.setdefault("MKL_NUM_THREADS", str(DEFAULT_CPU_THREADS))
os.environ.setdefault("OPENBLAS_NUM_THREADS", str(DEFAULT_CPU_THREADS))

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
MODELS_DIR = os.path.join(BASE_DIR, "models")
CUSTOM_MODELS_JSON = os.path.join(MODELS_DIR, "custom_models.json")
REF_DIR = os.path.join(BASE_DIR, "reference_audio")
TRANSCRIPTS_JSON = os.path.join(REF_DIR, "transcripts.json")
DEFAULT_REF_AUDIO = os.path.join(REF_DIR, "base_voice.mp3")
OUT_AUDIO_PATH = os.path.join(BASE_DIR, "output_audio.wav")
PREVIEW_AUDIO_PATH = os.path.join(BASE_DIR, "reference_preview.wav")
SNAC_REPO = "hubertsiuzdak/snac_24khz"

os.makedirs(MODELS_DIR, exist_ok=True)
os.makedirs(REF_DIR, exist_ok=True)

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
        "supported_modes": ["clone", "design", "tts"],
        "capabilities": {
            "supports_clone": True,
            "supports_design": True,
            "supports_tts": True,
            "supports_diffusion_steps": True,
            "supports_llm_sampling": False,
            "recommended_mode": "clone",
            "compatibility_note": "Soporta todos los modos: Clonación Zero-Shot (Audio Base), Diseño de Voz por descripción y Texto a Voz.",
        },
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
        "supported_modes": ["tts"],
        "capabilities": {
            "supports_clone": False,
            "supports_design": False,
            "supports_tts": True,
            "supports_diffusion_steps": False,
            "supports_llm_sampling": True,
            "recommended_mode": "tts",
            "compatibility_note": "Modelo GGUF (Orpheus/SNAC): funciona con Voces Nativas ('maria', 'javi', 'tara', 'leah'), Muestreo LLM (Temp, Top-K, Top-P) y DSP (Tono/Velocidad). No incluye encoder Zero-Shot nativo para clonar audio base, aunque puedes reactivar cualquier ajuste bajo tu control.",
        },
        "description": "Modelo GGUF rápido con voz femenina nativa ('maria') en español.",
    },
    "canopy-es-ultralight-q2": {
        "id": "canopy-es-ultralight-q2",
        "name": "Canopy Orpheus Español Ultra-Ligero Q2_K (1.25 GB - Ahorro RAM)",
        "engine": "gguf",
        "repo_id": "GianDiego/3b-es_it-ft-research_release-Q2-K-GGUF",
        "filename": "3b-es_it-ft-research_release.q2_k.gguf",
        "local_path": os.path.join(MODELS_DIR, "3b-es_it-ft-research_release.q2_k.gguf"),
        "size_gb": 1.25,
        "default_speaker": "maria",
        "speakers": ["maria", "javi", "ninguna"],
        "supported_modes": ["tts"],
        "capabilities": {
            "supports_clone": False,
            "supports_design": False,
            "supports_tts": True,
            "supports_diffusion_steps": False,
            "supports_llm_sampling": True,
            "recommended_mode": "tts",
            "compatibility_note": "Modelo GGUF Q2_K: funciona con Voces Nativas ('maria', 'javi'), Muestreo LLM y DSP. No incluye clonación Zero-Shot nativa.",
        },
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
        "supported_modes": ["tts"],
        "capabilities": {
            "supports_clone": False,
            "supports_design": False,
            "supports_tts": True,
            "supports_diffusion_steps": False,
            "supports_llm_sampling": True,
            "recommended_mode": "tts",
            "compatibility_note": "Modelo GGUF Single-Speaker Conversacional: funciona mejor en modo Texto a Voz con voz 'ninguna' + Muestreo LLM y DSP.",
        },
        "description": "Modelo conversacional español pre-descargado en backend/models/.",
    },
}


def build_capabilities_for_engine(engine: str) -> dict:
    """Devuelve el diccionario de capacidades según la arquitectura detectada del modelo."""
    if engine == "omnivoice":
        return {
            "supports_clone": True,
            "supports_design": True,
            "supports_tts": True,
            "supports_diffusion_steps": True,
            "supports_llm_sampling": False,
            "recommended_mode": "clone",
            "compatibility_note": "Modelo con arquitectura de difusión Zero-Shot: soporta Clonación de Audio Base, Diseño de Voz y TTS.",
        }
    return {
        "supports_clone": False,
        "supports_design": False,
        "supports_tts": True,
        "supports_diffusion_steps": False,
        "supports_llm_sampling": True,
        "recommended_mode": "tts",
        "compatibility_note": "Modelo GGUF (LLM + Vocoder SNAC): funciona nativamente en Modo Texto a Voz (Voces Nativas), Muestreo LLM y DSP. La clonación/diseño se desactiva por defecto por incompatibilidad arquitectónica, pero puedes forzar cualquier opción.",
    }


def is_model_downloaded(cfg: dict) -> bool:
    """Verifica si los pesos de un modelo ya existen en disco."""
    lpath = cfg.get("local_path", "")
    if cfg.get("engine") == "omnivoice":
        return os.path.isdir(lpath) and (
            os.path.exists(os.path.join(lpath, "config.json"))
            or len(glob.glob(os.path.join(lpath, "*.safetensors"))) > 0
        )
    return os.path.exists(lpath)


def load_custom_models_from_disk() -> None:
    """Carga en MODEL_CATALOG los modelos personalizados agregados por el usuario."""
    if os.path.exists(CUSTOM_MODELS_JSON):
        try:
            with open(CUSTOM_MODELS_JSON, "r", encoding="utf-8") as f:
                custom_dict = json.load(f)
            for k, v in custom_dict.items():
                eng = v.get("engine", "gguf")
                if "capabilities" not in v:
                    v["capabilities"] = build_capabilities_for_engine(eng)
                if "supported_modes" not in v:
                    v["supported_modes"] = ["clone", "design", "tts"] if eng == "omnivoice" else ["tts"]
                MODEL_CATALOG[k] = v
        except Exception as e:
            print(f"⚠️ Error leyendo custom_models.json: {e}", flush=True)


def save_custom_models_to_disk() -> None:
    """Guarda en disco los modelos personalizados registrados."""
    custom_only = {
        k: v for k, v in MODEL_CATALOG.items() if v.get("is_custom", False)
    }
    try:
        with open(CUSTOM_MODELS_JSON, "w", encoding="utf-8") as f:
            json.dump(custom_only, f, indent=2, ensure_ascii=False)
    except Exception as e:
        print(f"⚠️ Error guardando custom_models.json: {e}", flush=True)


def load_transcripts_map() -> dict:
    """Lee el diccionario de transcripciones de audios de referencia."""
    if os.path.exists(TRANSCRIPTS_JSON):
        try:
            with open(TRANSCRIPTS_JSON, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            pass
    return {}


def save_transcript_for_file(filename: str, text: str) -> None:
    """Guarda la transcripción de un audio de referencia en transcripts.json."""
    if not filename or not text.strip():
        return
    data = load_transcripts_map()
    data[os.path.basename(filename)] = text.strip()
    try:
        with open(TRANSCRIPTS_JSON, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
    except Exception as e:
        print(f"⚠️ Error guardando transcripts.json: {e}", flush=True)


def resolve_ref_path(ref_file_or_path: str) -> str:
    """Resuelve un nombre de archivo o ruta absoluta al archivo de audio de referencia válido."""
    if not ref_file_or_path:
        return DEFAULT_REF_AUDIO
    if os.path.isabs(ref_file_or_path) and os.path.exists(ref_file_or_path):
        return ref_file_or_path
    candidate = os.path.join(REF_DIR, os.path.basename(ref_file_or_path))
    if os.path.exists(candidate):
        return candidate
    return DEFAULT_REF_AUDIO


load_custom_models_from_disk()
