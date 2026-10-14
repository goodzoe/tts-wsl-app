# Studio TTS LatAm — Clonación Zero-Shot (OmniVoice) & Modelos Locales GGUF

Aplicación de escritorio y servidor local de Síntesis de Voz (TTS) y Clonación de Voz Zero-Shot para **WSL2 + Windows (WSLg)** e integración directa con **Brave / Chrome**.

---

## 🏗️ Arquitectura Modular del Proyecto

```text
tts-wsl-app/
├── backend/
│   ├── app.py                 # Servidor FastAPI, endpoints HTTP (/status, /models, /tts, /download, /upload_reference)
│   ├── config.py              # Rutas, catálogo de modelos (OmniVoice + GGUF), persistencia de modelos locales y transcripciones
│   ├── schemas.py             # Esquemas Pydantic (TTSRequest, ModelActionRequest, AddLocalModelRequest)
│   ├── engine_manager.py      # Carga/descarga en RAM/VRAM, inferencia OmniVoice (3 modos) e inferencia Orpheus GGUF + SNAC
│   ├── audio_dsp.py           # Re-muestreo lineal 1D seguro en RAM, ajuste de tono/velocidad, auto-transcripción Whisper-tiny
│   ├── models/                # Pesos descargados (.gguf y omnivoice-0.6b) + custom_models.json
│   └── reference_audio/       # Audios base (.mp3/.wav) + transcripts.json (transcripciones alineadas)
├── frontend/
│   ├── main.py                # Ventana principal CustomTkinter con contenedor central scrollable y layout responsive
│   ├── ui_tabs.py             # Construcción modular de Pestaña 1 (Voz/Clonación/Estilo) y Pestaña 2 (Motor IA/Difusión/LLM/DSP)
│   ├── audio_player.py        # Reproductor pygame.mixer con soporte WSLg PulseAudio y pausa instantánea sin lag (buffer=256)
│   ├── constants.py           # Constantes, idiomas, modos y valores por defecto para Restablecer
│   └── presets/               # Configuraciones JSON guardadas por el usuario
├── extension/
│   ├── manifest.json          # Extensión Manifest V3 para Brave / Chrome (wtr-lab.com)
│   ├── content.js             # Widget flotante con selector de modo, polling de ETA en vivo y reproductor <audio> HTML5
│   └── style.css              # Estilos del reproductor flotante
├── docs/
│   └── ARCHITECTURE.md        # Documentación técnica detallada de motores, clonación y solución de problemas
├── run_backend.sh / .bat      # Scripts de inicio del servidor FastAPI en http://0.0.0.0:8000
└── run_ui.sh / .bat           # Scripts de inicio de la interfaz gráfica CustomTkinter
```

---

## 🚀 Cómo Ejecutar la Aplicación

### 1. Iniciar el Backend (Servidor FastAPI en puerto `8000`)
Desde WSL2:
```bash
./run_backend.sh
```
O desde Windows haciendo doble clic en `run_backend.bat`.

### 2. Iniciar la Interfaz Gráfica (CustomTkinter)
Desde WSL2:
```bash
./run_ui.sh
```
O desde Windows haciendo doble clic en `run_ui.bat`.

### 3. Instalar la Extensión en Brave / Chrome
1. Abre `brave://extensions/` (o `chrome://extensions/`).
2. Activa el **Modo de desarrollador** (esquina superior derecha).
3. Haz clic en **Cargar descomprimida** (*Load unpacked*) y selecciona la carpeta `extension/` de este repositorio.
4. Abre cualquier capítulo en `https://wtr-lab.com/`: verás el widget flotante **🎙️ Studio TTS LatAm** abajo a la derecha. Puedes seleccionar un párrafo con el mouse o pulsar directamente **🔊 Generar y Escuchar**.

---

## 🎙️ Modos de Síntesis y Motores Soportados

1. **`🎙️ Clonación de Voz (Audio Base)` — Motor: `OmniVoice Zero-Shot 0.6B` (`k2-fsa/OmniVoice`)**
   - Clona el timbre real, prosodia y cadencia del archivo de referencia seleccionado (`base_voice.mp3` o cualquier `.mp3`/`.wav` subido).
   - **Auto-Transcripción Inteligente:** Para que la clonación acústica sea exacta, el backend alinea los tokens de audio con la transcripción real del clip (`reference_audio/transcripts.json`). Cuando subes un nuevo audio, `Whisper-tiny` lo transcribe automáticamente en ~1 segundo.
2. **`🗣️ Texto a Voz (Voces Nativas)` — Motores: `Canopy Orpheus GGUF` / `OmniVoice`**
   - Sintetiza usando voces predefinidas entrenadas (`maria`, `lucia`, `sofia`, `tara`, `javi`) junto con instrucciones opcionales de estilo.
3. **`✨ Diseño de Voz (Prompt Natural)` — Motor: `OmniVoice Zero-Shot 0.6B`**
   - Diseña una voz nueva a partir de una descripción en lenguaje natural (ej. *"Voz femenina joven de 23 años, cálida, clara y natural con acento argentino"*).
