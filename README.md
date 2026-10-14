# 🎙️ Studio TTS LatAm — Zero-Shot Voice Cloning, Multi-Model TTS & Web Novel Reader

<p align="center">
  <a href="LICENSE"><img src="https://img.shields.io/badge/License-MIT_(Commercial_%26_Open_Source)-10b981?style=for-the-badge" alt="MIT License"></a>
  <img src="https://img.shields.io/badge/GPU_Acceleration-CUDA_12.1_%7C_CPU-2563eb?style=for-the-badge" alt="CUDA 12.1">
  <img src="https://img.shields.io/badge/Platform-Windows_%7C_WSL2_%7C_Linux_%7C_macOS-8b5cf6?style=for-the-badge" alt="Platforms">
  <img src="https://img.shields.io/badge/Browser_Extension-Manifest_V3_(Brave_%2F_Chrome)-f59e0b?style=for-the-badge" alt="Extension MV3">
</p>

**Studio TTS LatAm** es una plataforma local y de código abierto para **Clonación de Voz Zero-Shot en Español Latinoamericano / Argentino**, **Diseño de Voz por Prompt** y **Lectura Continua de Páginas Web y Novelas** (WTR-Lab, blogs, documentación y cualquier sitio web), acelerada por GPU local y 100% privada.

---

## ✨ Características Principales

- **🎛️ Control Total Multi-Modelo (Cero Bloqueos):**
  - Compatible con motores de difusión Zero-Shot (**OmniVoice 0.6B** en GPU/CPU) y modelos cuantizados **GGUF** (**Canopy / Orpheus 3B + Vocoder neuronal SNAC 24kHz**).
  - Agrega cualquier modelo `.gguf` o carpeta local con un clic (**➕ Agregar Local**).
  - **Sistema Inteligente de Compatibilidad:** Si seleccionas un modelo con diferente arquitectura, la app muestra una notificación transitoria (*toast*), ajusta por defecto el modo recomendado e informa qué parámetros aplican, pero **nunca bloquea tus controles**.
- **🌐 Extensión de Navegador Manifest V3 (Popup + Inspector DOM `Ctrl+Shift+X`):**
  - **Sin barras flotantes intrusivas ni popups de permisos en las pestañas:** Todo el control vive en el menú desplegable de la extensión y se comunica con el servidor local a través de un *Background Service Worker* aislado (`background.js`), evitando por completo el cartel de Chrome/Brave *"quiere acceder a otras aplicaciones y servicios de este dispositivo"*.
  - **Reproducción desactivada por defecto:** Nunca reproduce nada automáticamente al abrir una página.
  - **Inspector de Grupo de Etiquetas (`Ctrl+Shift+X`):** Igual que el inspector de Brave DevTools (`Ctrl+Shift+C`), pasa el mouse sobre cualquier contenedor de capítulo o grupo de párrafos, haz clic para seleccionarlo o escribe cualquier selector CSS (`.chapter-body p`, `article p`).
  - **Velocidad en Tiempo Real sobre el Audio Actual:** El deslizador de velocidad (`0.50x` a `2.50x`) ajusta instantáneamente la reproducción en curso (`playbackRate` con preservación de tono) sin tener que regenerar el audio.
  - **Pre-Generación Activa (*Lookahead Prefetch Queue*):** Mientras escuchas el párrafo `N`, una cola secuencial en segundo plano genera por adelantado los párrafos `N+1` y `N+2` en la GPU para lograr **0 ms de espera entre párrafos**.
- **⚡ Ultra-Rápido en GPU NVIDIA (`torch.float16` + Warmup CUDA):**
  - Tiempos reales en una RTX 4060 Laptop GPU: **~0.5s** en Diseño de Voz, **~1.1s** en Texto a Voz y **~1.5s** en Clonación Zero-Shot.

---

## 💻 Requisitos del Sistema

| Componente | Mínimo (Modo CPU / GGUF) | Recomendado (Modo GPU Zero-Shot) |
| :--- | :--- | :--- |
| **Sistema Operativo** | Windows 10/11, Linux (Ubuntu/Debian/Arch) o macOS | Windows 10/11 con **WSL2 (Ubuntu)** o Linux nativo |
| **GPU** | No requerida (usa AVX2 en CPU) | NVIDIA GTX 1660 / RTX 2060 / 3060 / 4060+ (**4 GB+ VRAM**) |
| **Memoria RAM** | 8 GB RAM | 12 GB – 16 GB RAM |
| **Navegador (Extensión)** | Brave, Google Chrome, Microsoft Edge o Chromium | Brave / Chrome (Manifest V3) |

---

## 🚀 Instalación Paso a Paso por Sistema Operativo

### 1. Clonar el Repositorio

```bash
git clone https://github.com/goodzoe/tts-wsl-app.git
cd tts-wsl-app
```

### 2. Instalación Automática (Recomendada)

- **En Linux / WSL2 (Ubuntu) / macOS:**
  ```bash
  chmod +x setup.sh
  ./setup.sh
  ```
- **En Windows 10 / 11 (Nativo o con WSL2):**
  Haz doble clic en **`setup.bat`** (o ejecuta `./setup.sh` dentro de tu terminal WSL).

<details>
<summary><b>🔧 Instalación Manual Avanzada (Paso a Paso)</b></summary>

1. Crear el entorno virtual en `backend/venv`:
   ```bash
   python3 -m venv backend/venv
   source backend/venv/bin/activate  # En Windows CMD: backend\venv\Scripts\activate
   ```
2. Instalar PyTorch con aceleración CUDA 12.1 (si tienes GPU NVIDIA):
   ```bash
   pip install torch torchvision torchaudio --index-url https://download.pytorch.org/whl/cu121
   ```
3. Instalar dependencias del servidor, motores IA e interfaz gráfica:
   ```bash
   pip install fastapi uvicorn soundfile numpy scipy tqdm requests pydantic python-multipart customtkinter pygame huggingface_hub transformers accelerate snac omnivoice llama-cpp-python
   ```
</details>

---

## ▶️ Uso e Integración

### A. Iniciar el Servidor Backend (`http://127.0.0.1:8000`)
- **Linux / WSL2 / macOS:**
  ```bash
  ./run_backend.sh
  ```
- **Windows:** Doble clic en **`run_backend.bat`**.

### B. Iniciar la Aplicación de Escritorio (Studio UI)
- **Linux / WSL2 (WSLg):**
  ```bash
  ./run_ui.sh
  ```
- **Windows:** Doble clic en **`run_ui.bat`** (o `run_ui_windows_native.bat`).

### C. Instalar la Extensión en Brave / Chrome / Edge
1. Abre tu navegador y entra en `brave://extensions/` (o `chrome://extensions/`).
2. Activa el interruptor **Modo de desarrollador** (*Developer mode*) arriba a la derecha.
3. Haz clic en **Cargar descomprimida** (*Load unpacked*) y selecciona la carpeta **`extension/`** dentro de este proyecto.
4. *(Tip)* Fija el ícono 🎙️ **Studio TTS LatAm** en la barra superior de tu navegador:
   - Al abrir el menú desplegable verás el estado en vivo (**Online • GPU**), el botón **🎯 Inspeccionar Grupo de Etiquetas (Ctrl+Shift+X)**, el selector CSS, los controles de reproducción y los deslizadores de **Volumen** y **Velocidad de Audio en tiempo real**.

---

## ⚙️ Configuración Personalizada (`.env`)

Puedes copiar el archivo `.env.example` a `.env` en la raíz del proyecto para ajustar puertos, cantidad de hilos de CPU o el modelo que se carga por defecto al arrancar:

```ini
TTS_BACKEND_HOST=0.0.0.0
TTS_BACKEND_PORT=8000
OMP_NUM_THREADS=6
TTS_DEFAULT_MODEL=omnivoice-zeroshot-0.6b
```

---

## 🔌 API REST para Integración con Otros Proyectos

Puedes integrar fácilmente **Studio TTS LatAm** en tus propios agentes, bots de Discord, lectores o videojuegos haciendo peticiones HTTP a `http://127.0.0.1:8000`:

| Endpoint | Método | Descripción |
| :--- | :---: | :--- |
| `/status` | `GET` | Estado del motor (`READY`, `GENERATING`), modelo activo, GPU/CPU y uso de RAM/VRAM. |
| `/models` | `GET` | Lista el catálogo de modelos, sus capacidades (`capabilities`) y si están descargados. |
| `/models/load` | `POST` | Carga un modelo en memoria (`{"model_id": "omnivoice-zeroshot-0.6b", "cpu_threads": 6}`). |
| `/models/add_local` | `POST` | Registra un modelo `.gguf` o directorio local personalizado en el catálogo. |
| `/tts` | `POST` | Sintetiza texto en los modos `clone`, `tts` o `design` y genera el archivo WAV PCM_16. |
| `/download` | `GET` | Descarga el último audio generado (`audio/wav`, 24kHz PCM_16). |
| `/upload_reference` | `POST` | Sube un nuevo audio base (`.mp3`/`.wav`) y lo auto-transcribe con `Whisper-tiny`. |

Ejemplo rápido con `curl`:
```bash
curl -X POST http://127.0.0.1:8000/tts \
  -H "Content-Type: application/json" \
  -d '{
    "text": "Hola, esta es una prueba de clonación de voz en tiempo real.",
    "mode": "clone",
    "model_id": "omnivoice-zeroshot-0.6b",
    "reference_file": "base_voice.mp3"
  }' && curl -s http://127.0.0.1:8000/download --output salida.wav
```

---

## 🤝 Contribuciones y Comunidad

¡Las contribuciones de la comunidad son bienvenidas! Si quieres sumar nuevos modelos TTS en español, mejorar los filtros de extracción DOM para más sitios de lectura o aportar optimizaciones de inferencia:

1. Haz un **Fork** del repositorio.
2. Crea una rama para tu mejora (`git checkout -b feat/nueva-mejora`).
3. Abre un **Pull Request** detallando los cambios.
4. Si encuentras un bug o tienes una idea, abre un [Issue en GitHub](https://github.com/goodzoe/tts-wsl-app/issues).

---

## 📜 Credits and License (Commercial & Open Source Use)

**Studio TTS LatAm** is open source under the **[MIT License](LICENSE)** — free for both personal and commercial use. Models and neural vocoders (`k2-fsa/OmniVoice`, `Canopy Orpheus`, `SNAC`) retain their respective upstream open-source licenses.

## Support Studio TTS LatAm

Studio TTS LatAm is free and open source. If it is useful to you, you can support its development:

<p align="center"><a href="https://buymeacoffee.com/"><img src="https://cdn.buymeacoffee.com/buttons/v2/default-yellow.png" alt="Buy Me A Coffee" height="50"></a></p>
