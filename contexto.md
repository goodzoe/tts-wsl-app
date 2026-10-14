# Contexto de Continuación del Proyecto — Studio TTS LatAm (`tts-wsl-app`)

**Fecha de actualización:** 14 de Octubre de 2026  
**Directorio raíz:** `/home/openclaw/.openclaw/workspace/tts-wsl-app`  
**Repositorio GitHub:** `https://github.com/goodzoe/tts-wsl-app` (rama `main`, sincronizada)

---

## 1. Objetivo y Estado Actual del Proyecto
Aplicación local de escritorio (CustomTkinter en WSLg/Windows) + Servidor Backend REST (FastAPI en WSL2, puerto `8000`) + Extensión de navegador Manifest V3 para Brave/Chrome (`wtr-lab.com`), diseñada para **Clonación de Voz Zero-Shot en Español Latinoamericano/Argentino**, **Voces Nativas** y **Diseño de Voz**.

### Estado de los Servicios en Ejecución
- **Backend FastAPI (`http://0.0.0.0:8000`):** Activo (`./run_backend.sh`) con el modelo `OmniVoice Zero-Shot 0.6B` cargado en memoria (`READY`).
- **Frontend UI (`frontend/main.py`):** Activo en WSLg (`./run_ui.sh`) con audio conectado a PulseAudio (`/mnt/wslg/PulseServer`).

---

## 2. Estructura Modular Refactorizada

```text
tts-wsl-app/
├── conexto.md                 # Archivo de contexto solicitado para retomar en nuevas sesiones
├── contexto.md                # Copia espejo
├── README.md                  # Guía de uso rápido y estructura
├── PLAN.md                    # Plan original del proyecto
├── docs/
│   └── ARCHITECTURE.md        # Detalles técnicos de motores, clonación y bugs resueltos
├── backend/
│   ├── app.py                 # Servidor FastAPI (/status, /models, /models/add_local, /models/load, /models/unload, /tts, /download, /reference_files, /reference_preview, /upload_reference)
│   ├── config.py              # Catálogo de modelos (OmniVoice + 3 GGUF), rutas y persistencia JSON
│   ├── schemas.py             # Modelos Pydantic (TTSRequest, ModelActionRequest, AddLocalModelRequest)
│   ├── engine_manager.py      # Carga/descarga en RAM/VRAM, inferencia OmniVoice (clone/tts/design), sanitizador de instruct y decodificación Orpheus GGUF + SNAC 24kHz
│   ├── audio_dsp.py           # fast_resample_1d (<2MB RAM), gentle_voice_adjust, malloc_trim y auto-transcripción con openai/whisper-tiny
│   ├── models/                # Pesos descargados:
│   │   ├── omnivoice-0.6b/                                              # Descargado (1.5 GB)
│   │   ├── 3b-es_it-ft-research_release-q4_k_m.gguf                     # Descargado (2.0 GB)
│   │   ├── orpheus-spanish-tts-finetuned-new-one-epoch-10-q4_k_m.gguf   # Descargado (2.0 GB)
│   │   └── custom_models.json                                           # Modelos locales agregados por el usuario desde la UI
│   └── reference_audio/       # Audios base para clonar:
│       ├── base_voice.mp3                                               # Voz femenina argentina ("Barbie", 9.36s)
│       ├── 11114---dd5fc9a8-bf90-49a0-b866-7f166d1c6486.mp3
│       ├── 11115---c06c3a34-6800-4dad-820e-216cab59f675.mp3
│       └── transcripts.json                                             # Transcripciones reales exactas de cada audio base
├── frontend/
│   ├── main.py                # Ventana principal CustomTkinter dividida en 3 zonas (Header fijo, Centro CTkScrollableFrame responsive, Footer reproductor fijo)
│   ├── ui_tabs.py             # Construcción de Pestaña 1 (Voz/Clonación/Estilo) y Pestaña 2 (Motor IA/Difusión/LLM/DSP)
│   ├── audio_player.py        # Controlador pygame.mixer con buffer=256 y corte stop() para pausa instantánea sin lag en WSLg
│   ├── constants.py           # Catálogo UI, modos, idiomas y DEFAULT_PRESET_VALUES para el botón Restablecer
│   └── presets/               # Presets JSON guardados por el usuario
└── extension/
    ├── manifest.json          # Extensión Manifest V3 para Brave/Chrome
    ├── content.js             # Widget flotante con selector de modo, polling de ETA a /status y reproductor <audio controls> HTML5
    └── style.css              # Estilos del widget flotante
```

---

## 3. Decisiones Técnicas y Problemas Críticos Ya Resueltos (¡No Revertir!)

1. **Clonación Zero-Shot Real en `OmniVoice` (`backend/engine_manager.py` + `backend/audio_dsp.py`):**
   - Los modelos GGUF (`Canopy` / `Orpheus`) **no clonan audio de referencia externo** (solo usan prefijos de hablante como `maria:`). Por eso, cuando `request.mode == "clone"`, el backend asegura automáticamente el uso de `omnivoice-zeroshot-0.6b`.
   - En `OmniVoice`, `create_voice_clone_prompt` requiere que `ref_text` coincida exactamente con lo que se dice en `ref_audio` (concatena `ref_text + target_text` junto a los tokens acústicos). Si se pasa un texto falso, la atención cruzada se rompe y no clona la voz.
   - `backend/reference_audio/transcripts.json` almacena la transcripción real de cada audio (ej. `base_voice.mp3` dice: *"Hola, soy Barbie, qué lindo tenerte por acá. Si buscas una voz cálida, cercana y natural, me encantaría darle vida a tu proyecto."*). Si el usuario sube un audio nuevo sin transcripción, `get_or_transcribe_reference_audio()` lo transcribe automáticamente con `openai/whisper-tiny` en ~1s y lo guarda en `transcripts.json`.

2. **Validación Estricta de `instruct` en `OmniVoice` (`sanitize_omnivoice_instruct`):**
   - `OmniVoice._resolve_instruct()` lanza `ValueError: Unsupported instruct items found` (Error 500) si recibe texto libre en español. Solo acepta una lista cerrada de etiquetas en inglés (`female`, `male`, `child`, `teenager`, `young adult`, `middle-aged`, `elderly`, `very low pitch`, `low pitch`, `moderate pitch`, `high pitch`, `very high pitch`, `whisper`, y acentos en inglés).
   - La función `sanitize_omnivoice_instruct()` en `backend/engine_manager.py` traduce cualquier prompt en español o inglés del usuario a esas etiquetas válidas.
   - Además, en modo `clone`, **no se inyectan etiquetas de género/edad en `instruct`** (solo `whisper` si el usuario pide susurro) para no pisar el timbre acústico del audio base.

3. **Prohibido usar `torchaudio.functional.resample` con frecuencias dinámicas:**
   - Causa picos de 7–9 GB de RAM cuando `gcd(orig_freq, new_freq) == 1`. Siempre usar `fast_resample_1d()` (interpolación lineal 1D de PyTorch en `backend/audio_dsp.py`).

4. **Nombre exacto del archivo `Q2_K` en HuggingFace:**
   - En el repositorio `GianDiego/3b-es_it-ft-research_release-Q2-K-GGUF`, el archivo se llama `3b-es_it-ft-research_release.q2_k.gguf` (con punto antes de `q2_k`, no guion). Ya está corregido en `backend/config.py`.

5. **UI Responsive sin Texto Cortado (`frontend/main.py`):**
   - La ventana usa un encabezado fijo con barra de progreso, un cuerpo central `CTkScrollableFrame` y una barra inferior fija para el reproductor, recalculando `wraplength` en el evento `<Configure>`.

---

## 4. Próximos Pasos Pendientes (Para la Siguiente Sesión)
- Matías mencionó que en un próximo turno pasará **más capturas/imágenes para integrar parámetros adicionales** en la interfaz y el backend, y validar cómo quedó la experiencia de uso tras esta refactorización.
