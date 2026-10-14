"""Esquemas Pydantic de entrada/salida para la API REST de Studio TTS LatAm."""

from typing import Optional
from pydantic import BaseModel


class TTSRequest(BaseModel):
    text: str
    mode: str = "clone"  # "clone" | "tts" | "design"
    model_id: str = "omnivoice-zeroshot-0.6b"
    language: str = "Spanish"
    reference_file: str = "base_voice.mp3"
    reference_text: str = ""
    use_xvector_only: bool = True
    speaker_hint: str = "maria"
    style_instruct: str = ""
    voice_description: str = ""
    # Parámetros OmniVoice (Difusión Iterativa)
    num_step: int = 12
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
    cpu_threads: int = 6
    n_ctx: int = 1024


class ModelActionRequest(BaseModel):
    model_id: str
    cpu_threads: int = 6
    n_ctx: int = 1024


class AddLocalModelRequest(BaseModel):
    path: str
    name: Optional[str] = None
    engine: Optional[str] = None  # "gguf" | "omnivoice"
