"""Constantes, rutas y diccionarios de configuración del frontend de Studio TTS LatAm."""

import os
import json

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
PRESETS_DIR = os.path.join(BASE_DIR, "presets")
DEFAULT_REF_DIR = os.path.abspath(os.path.join(BASE_DIR, "..", "backend", "reference_audio"))
DEFAULT_REF_FILE = os.path.join(DEFAULT_REF_DIR, "base_voice.mp3")
TRANSCRIPTS_JSON = os.path.join(DEFAULT_REF_DIR, "transcripts.json")
DEFAULT_MODELS_DIR = os.path.abspath(os.path.join(BASE_DIR, "..", "backend", "models"))

os.makedirs(PRESETS_DIR, exist_ok=True)

MODEL_LABELS_TO_ID = {
    "OmniVoice Zero-Shot 0.6B (Clonación Real + Diseño de Voz - 1.5 GB)": "omnivoice-zeroshot-0.6b",
    "Canopy Orpheus Español Multi-Voz Femenina Nativa Q4 (2.0 GB)": "canopy-es-multivoz-q4",
    "Canopy Orpheus Español Ultra-Ligero Q2_K (1.25 GB - Ahorro RAM)": "canopy-es-ultralight-q2",
    "Orpheus Español Conversacional Q4_K_M (2.0 GB - Local)": "orpheus-es-conversacional-q4",
}
MODEL_ID_TO_LABEL = {v: k for k, v in MODEL_LABELS_TO_ID.items()}

MODEL_METADATA = {
    "omnivoice-zeroshot-0.6b": {
        "engine": "omnivoice",
        "speakers": ["maria", "lucia", "sofia", "tara", "javi", "ninguna"],
        "default_speaker": "maria",
        "capabilities": {
            "supports_clone": True,
            "supports_design": True,
            "supports_tts": True,
            "supports_diffusion_steps": True,
            "supports_llm_sampling": False,
            "recommended_mode": "clone",
            "compatibility_note": "OmniVoice Zero-Shot (GPU): Soporta Clonación de Audio Base, Diseño de Voz por descripción y Texto a Voz.",
        },
    },
    "canopy-es-multivoz-q4": {
        "engine": "gguf",
        "speakers": ["maria", "javi", "tara", "leah", "ninguna"],
        "default_speaker": "maria",
        "capabilities": {
            "supports_clone": False,
            "supports_design": False,
            "supports_tts": True,
            "supports_diffusion_steps": False,
            "supports_llm_sampling": True,
            "recommended_mode": "tts",
            "compatibility_note": "Modelo GGUF (Canopy Multi-Voz): Funciona nativamente con Voces Nativas ('maria', 'javi', 'tara', 'leah'), Muestreo LLM (Temp, Top-K, Top-P) y DSP. Clonación/Diseño se desactivan por defecto por incompatibilidad, pero puedes volver a activarlos manualmente.",
        },
    },
    "canopy-es-ultralight-q2": {
        "engine": "gguf",
        "speakers": ["maria", "javi", "ninguna"],
        "default_speaker": "maria",
        "capabilities": {
            "supports_clone": False,
            "supports_design": False,
            "supports_tts": True,
            "supports_diffusion_steps": False,
            "supports_llm_sampling": True,
            "recommended_mode": "tts",
            "compatibility_note": "Modelo GGUF Ultra-Ligero Q2_K: Funciona con Voces Nativas ('maria', 'javi'), Muestreo LLM y DSP. Clonación/Diseño desactivados por defecto (puedes reactivarlos si lo deseas).",
        },
    },
    "orpheus-es-conversacional-q4": {
        "engine": "gguf",
        "speakers": ["ninguna", "maria", "tara", "leah", "javi"],
        "default_speaker": "ninguna",
        "capabilities": {
            "supports_clone": False,
            "supports_design": False,
            "supports_tts": True,
            "supports_diffusion_steps": False,
            "supports_llm_sampling": True,
            "recommended_mode": "tts",
            "compatibility_note": "Modelo GGUF Single-Speaker Conversacional: Funciona con Modo Texto a Voz (voz 'ninguna'), Muestreo LLM y DSP. Clonación/Diseño desactivados por defecto (reactivación libre).",
        },
    },
}

LANGUAGE_CHOICES = [
    "Español (Latinoamérica / Argentina)",
    "Automático (Detectar Idioma)",
    "English",
    "Portuguese",
    "Italian",
    "French",
]

MODE_UI_TO_API = {
    "🎙️ Clonación de Voz (Audio Base)": "clone",
    "🗣️ Texto a Voz (Voces Nativas)": "tts",
    "✨ Diseño de Voz (Prompt Natural)": "design",
}
MODE_API_TO_UI = {v: k for k, v in MODE_UI_TO_API.items()}

DEFAULT_PRESET_VALUES = {
    "model_id": "omnivoice-zeroshot-0.6b",
    "mode": "clone",
    "language": "Spanish",
    "reference_file": DEFAULT_REF_FILE,
    "reference_text": "Hola, soy Barbie, qué lindo tenerte por acá. Si buscas una voz cálida, cercana y natural, me encantaría darle vida a tu proyecto.",
    "use_xvector_only": True,
    "speaker_hint": "maria",
    "style_instruct": "",
    "voice_description": "Voz femenina joven de 23 años, cálida, clara y natural con acento argentino",
    "num_step": 12,
    "guidance_scale": 2.0,
    "denoise": True,
    "auto_clone_voice": False,
    "pitch_semitones": 0.0,
    "speed": 1.0,
    "temperature": 0.60,
    "top_k": 50,
    "top_p": 0.90,
    "repeat_penalty": 1.12,
    "max_audio_tokens": 700,
    "seed": -1,
    "cpu_threads": 6,
}


def load_local_transcripts() -> dict:
    """Lee el archivo transcripts.json del backend si está disponible localmente."""
    if os.path.exists(TRANSCRIPTS_JSON):
        try:
            with open(TRANSCRIPTS_JSON, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            pass
    return {}


def scan_local_ref_files() -> list[str]:
    """Escanea los archivos .mp3/.wav dentro de backend/reference_audio/."""
    items = ["base_voice.mp3"]
    if os.path.isdir(DEFAULT_REF_DIR):
    
        for f in sorted(os.listdir(DEFAULT_REF_DIR)):
            if f.lower().endswith((".mp3", ".wav")) and f not in items:
                items.append(f)
    return items


def format_time(seconds: float) -> str:
    """Formatea segundos como MM:SS."""
    seconds = max(0, int(seconds))
    return f"{seconds // 60:02d}:{seconds % 60:02d}"
