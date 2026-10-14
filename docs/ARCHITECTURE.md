# Arquitectura Técnica y Registro de Correcciones — Studio TTS LatAm (`tts-wsl-app`)

**Última actualización:** 14 de Octubre de 2026  
**Hardware activo verificado en WSL2:** `NVIDIA GeForce RTX 4060 Laptop GPU` (CUDA 12.1, `torch.float16`)  
**Repositorio GitHub:** `https://github.com/goodzoe/tts-wsl-app` (rama `main`, sincronizada)

---

## 1. Control Total del Usuario sobre Modelos y Capacidades (Cero Redirecciones Forzadas)

1. **Adaptabilidad por Modelo (`backend/config.py`, `backend/app.py`, `frontend/main.py`):**
   - Se eliminó el enrutamiento forzoso que cambiaba silenciosamente a `omnivoice-zeroshot-0.6b` cuando el usuario elegía **Clonación** o **Diseño de Voz**. Ahora tanto la UI como `POST /tts` **respetan al 100% el modelo seleccionado por el usuario** (incluidos modelos futuros descargados o agregados con `➕ Agregar Local`).
   - Cada modelo expone su diccionario `capabilities` (`supports_clone`, `supports_design`, `supports_tts`, `supports_diffusion_steps`, `supports_llm_sampling`, `recommended_mode`, `compatibility_note`).
2. **Notificación Push Transitoria y Desactivación por Defecto sin Bloqueos:**
   - Cuando seleccionas o cargas un modelo que no soporta Clonación/Diseño Zero-Shot nativo (ej. modelos GGUF), la app muestra un **Toast Push Transitorio** (que desaparece solo tras unos segundos o con `✖`), **desactiva por defecto** la opción incompatible pasando a **Modo Texto a Voz (Voces Nativas)** e informa qué ajustes funcionan con ese modelo (Voces Nativas + Muestreo LLM Temp/Top-K/Top-P + DSP Tono/Velocidad).
   - **Libertad total:** Ningún control se bloquea; si el usuario vuelve a activar manualmente Clonación o Diseño sobre cualquier modelo, se respeta su decisión y el backend devuelve un aviso no intrusivo en `warnings`.

---

## 2. Extensión Universal de Navegador v3.1 (`extension/`)

- **Popup de Control Dedicado (`popup.html`, `popup.css`, `popup.js`):**
  - Interfaz oscura moderna con indicador de conexión en vivo con el Backend (`Online • GPU` / `Offline (:8000)`) y telemetría de modelo/VRAM.
  - **Reproducción y extensión desactivadas por defecto (`enabled: false`):** Nunca inyecta barras ni reproduce nada automáticamente al abrir pestañas hasta que el usuario la active.
  - Controles de transporte (**⏮**, **▶ Reproducir / ⏸ Pausar**, **⏭**, **⏹**), sliders de **Volumen (0–100%)** y **Velocidad**, y selectores de Modelo, Modo, Audio Base y Voz Nativa con notificaciones transitorias de compatibilidad.
- **Inspector DOM de Grupos de Etiquetas estilo Brave DevTools (`Ctrl+Shift+X`):**
  - Botón punteado **🎯 Inspeccionar Grupo de Etiquetas (Ctrl+Shift+X)** en el popup y en el widget, además de campo manual de **Selector CSS** (ej. `.chapter-body p`, `article p`).
  - Al pasar el mouse por la página, resalta contenedores y grupos de etiquetas con borde punteado azul y un tooltip que muestra el selector CSS exacto y cuántos bloques de texto contiene; al hacer clic, fija ese grupo de etiquetas para reproducir su contenido con pre-carga (*pre-fetch*).

---

## 3. Aceleración por GPU NVIDIA RTX 4060 y Estabilidad

- **PyTorch CUDA 12.1 (`torch==2.5.1+cu121`) + Warmup CUDA:** Síntesis en `cuda:0` (`torch.float16`) en **~0.5s – 1.8s** para `OmniVoice` y decodificación `SNAC 24kHz` en GPU para modelos GGUF.
- **Banner de Errores Persistente en Desktop UI:** Los errores nunca desaparecen solos por el polling de `/status`; cuentan con botón de copiado y cierre manual.
