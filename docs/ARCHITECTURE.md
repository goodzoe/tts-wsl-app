# Documentación Técnica y Arquitectura — Studio TTS LatAm

## 1. Diagnóstico y Solución de Bugs Críticos

### 1.1. ¿Por qué no se clonaba la voz antes y cómo se solucionó?
1. **Modelos GGUF single/multi-speaker vs. Zero-Shot:** Los modelos `Orpheus 3B GGUF` (`Canopy` y `Jhonito45`) sólo generan a partir de texto con un prefijo de hablante entrenado (`maria: texto`), e ignoran por completo cualquier archivo de audio externo. Ahora, cuando el usuario selecciona el modo **`🎙️ Clonación de Voz (Audio Base)`**, el backend redirige y garantiza automáticamente el uso de **`OmniVoice Zero-Shot 0.6B`**.
2. **Alineación obligatoria `ref_text` ↔ `ref_audio` en OmniVoice:** En `OmniVoice`, `create_voice_clone_prompt` concatena internamente `ref_text + target_text` junto a `ref_audio_tokens`. Si se envía una frase inventada que no coincide con lo que dice `base_voice.mp3`, la matriz de atención cruzada se desalinea y el modelo pierde el timbre de referencia.
   - **Solución:** Se creó `backend/reference_audio/transcripts.json` con la transcripción real exacta de los audios incluidos (*"Hola, soy Barbie, qué lindo tenerte por acá..."*) y se integró auto-transcripción automática con `openai/whisper-tiny` en `audio_dsp.py` cada vez que el usuario sube un nuevo archivo `.mp3`/`.wav`.
3. **Conflicto entre `instruct` (Voice Design) y `voice_clone_prompt` (Voice Clone):** En `OmniVoice`, pasar simultáneamente una descripción genérica de voz en `instruct` y un `voice_clone_prompt` hace que el condicionamiento de texto compita contra los tokens acústicos del audio base. Ahora, en modo `clone`, `instruct` se deja vacío por defecto salvo que el usuario escriba explícitamente una emoción puntual.

### 1.2. Diseño Responsive y Prevención de Corte de Texto en la UI
- La ventana principal (`frontend/main.py`) ahora se divide en 3 áreas:
  1. **Encabezado fijo superior** con el monitor de RAM y un banner de estado multilínea con barra de progreso (`CTkProgressBar`).
  2. **Contenedor central `CTkScrollableFrame`** que aloja el gestor de modelos, modos y pestañas, evitando que los controles se aplasten o recorten en resoluciones bajas.
  3. **Barra inferior fija** con el botón `▶ Generar Audio Natural`, el cronómetro `ETA 2s / 22s` y el reproductor de audio.
- El evento `<Configure>` recalcula dinámicamente `wraplength` en todas las etiquetas informativas al redimensionar la ventana.

### 1.3. Pausa Instantánea en WSLg PulseAudio
- Se configuró `pygame.mixer` con `buffer=256` (~10 ms) en `frontend/audio_player.py` y se reemplazó `pause()` por captura de posición exacta + `stop()` para vaciar inmediatamente el buffer de salida de PulseAudio en WSLg sin retraso audible.

### 1.4. Extensión de Brave / Chrome (`extension/`)
- El script anterior (`extension/content.js`) hacía `POST /tts` pero **nunca llamaba a `GET /download` ni creaba un elemento `<audio>`**, por lo que jamás sonaba en el navegador.
- Ahora `extension/content.js` inyecta un widget completo con selector de modo (`Clonar Voz Base` / `Voz Nativa`), muestra el progreso y ETA en vivo consultando `GET /status`, descarga el `Blob` WAV desde `GET /download` y lo reproduce automáticamente en un reproductor `<audio controls>` HTML5.
