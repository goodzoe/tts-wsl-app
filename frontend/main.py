import os
import sys
import glob
import json
import ctypes
import time
import shutil
import platform
import threading
import tkinter
import tkinter.filedialog as fd
import requests
import customtkinter as ctk

# Configurar audio WSLg (PulseAudio) automáticamente antes de importar pygame
if platform.system() == "Linux" and os.path.exists("/mnt/wslg/PulseServer"):
    os.environ.setdefault("PULSE_SERVER", "unix:/mnt/wslg/PulseServer")
    os.environ.setdefault("SDL_AUDIODRIVER", "pulseaudio")
    site_pkgs = [p for p in sys.path if "site-packages" in p]
    for sp in site_pkgs:
        libs_dir = os.path.join(sp, "pygame.libs")
        if os.path.isdir(libs_dir):
            for pattern, link_name in [
                ("libpulsecommon-*.so*", None),
                ("libpulse-*.so*", "libpulse.so.0"),
                ("libpulse-simple-*.so*", "libpulse-simple.so.0"),
            ]:
                matches = glob.glob(os.path.join(libs_dir, pattern))
                if matches:
                    target = matches[0]
                    if link_name:
                        link_path = os.path.join(libs_dir, link_name)
                        if not os.path.exists(link_path):
                            try:
                                os.symlink(os.path.basename(target), link_path)
                            except OSError:
                                pass
                        target = link_path
                    try:
                        ctypes.CDLL(target, mode=ctypes.RTLD_GLOBAL)
                    except OSError:
                        pass

import pygame

ctk.set_appearance_mode("Dark")
ctk.set_default_color_theme("blue")

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
PRESETS_DIR = os.path.join(BASE_DIR, "presets")
DEFAULT_REF_DIR = os.path.abspath(os.path.join(BASE_DIR, "..", "backend", "reference_audio"))
DEFAULT_REF_FILE = os.path.join(DEFAULT_REF_DIR, "base_voice.mp3")
DEFAULT_MODELS_DIR = os.path.abspath(os.path.join(BASE_DIR, "..", "backend", "models"))

# Catálogo base (se sincroniza dinámicamente con GET /models del backend)
MODEL_LABELS_TO_ID = {
    "OmniVoice Zero-Shot 0.6B (Clonación Real + Diseño de Voz - 1.5 GB)": "omnivoice-zeroshot-0.6b",
    "Canopy Orpheus Español Multi-Voz Femenina Nativa Q4 (2.0 GB)": "canopy-es-multivoz-q4",
    "Canopy Orpheus Español Ultra-Ligero Q2_K (1.25 GB - Ahorro RAM)": "canopy-es-ultralight-q2",
    "Orpheus Español Conversacional Q4_K_M (2.0 GB - Local)": "orpheus-es-conversacional-q4",
}
MODEL_ID_TO_LABEL = {v: k for k, v in MODEL_LABELS_TO_ID.items()}

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


def format_time(seconds: float) -> str:
    seconds = max(0, int(seconds))
    mins = seconds // 60
    secs = seconds % 60
    return f"{mins:02d}:{secs:02d}"


class TTSApp(ctk.CTk):
    def __init__(self):
        super().__init__()
        self.title("Studio TTS LatAm - Clonación Zero-Shot (OmniVoice) & Modelos Locales")
        self.geometry("940x930")
        self.minsize(760, 820)

        os.makedirs(PRESETS_DIR, exist_ok=True)

        self.api_url = "http://127.0.0.1:8000"
        self.downloaded_audio = os.path.join(BASE_DIR, "resultado.wav")
        self.reference_audio_path = DEFAULT_REF_FILE

        # Estado del reproductor de audio (buffer 256 para pausa instantánea sin lag)
        self.mixer_ready = False
        self.is_playing = False
        self.is_paused = False
        self.is_muted = False
        self.volume = 0.85
        self.audio_duration = 0.0
        self.play_start_wall = 0.0
        self.play_offset = 0.0
        self.user_dragging_seek = False
        self.is_generating = False
        self.gen_local_start_t = 0.0
        self.gen_target_eta_s = 0
        self._status_poll_inflight = False
        self._models_synced_once = False

        self._init_audio_mixer()

        # --- ENCABEZADO + MONITOR DE RAM + BANNER DE ESTADO MULTILÍNEA (SIN TRUNCADO) ---
        self.frame_top = ctk.CTkFrame(self, fg_color="transparent")
        self.frame_top.pack(fill="x", pady=(8, 2), padx=20)

        self.frame_top_row1 = ctk.CTkFrame(self.frame_top, fg_color="transparent")
        self.frame_top_row1.pack(fill="x")

        self.lbl_title = ctk.CTkLabel(
            self.frame_top_row1, text="Studio TTS LatAm", font=("Helvetica", 22, "bold")
        )
        self.lbl_title.pack(side="left")

        self.lbl_ram = ctk.CTkLabel(
            self.frame_top_row1,
            text="RAM App: -- MB | Sistema: -- GB",
            font=("Consolas", 12, "bold"),
            text_color="#60a5fa",
        )
        self.lbl_ram.pack(side="right", pady=(4, 0))

        # Fila dedicada al estado y barra de progreso para que NUNCA se tape ni corte
        self.frame_status_banner = ctk.CTkFrame(
            self.frame_top, corner_radius=8, fg_color="#111827", border_width=1, border_color="#1f2937"
        )
        self.frame_status_banner.pack(fill="x", pady=(4, 2))

        self.status_lbl = ctk.CTkLabel(
            self.frame_status_banner,
            text="⏳ Conectando con el servidor backend local...",
            text_color="#f59e0b",
            font=("Helvetica", 12, "bold"),
            anchor="w",
            justify="left",
            wraplength=860,
        )
        self.status_lbl.pack(fill="x", padx=12, pady=(5, 3))

        self.progress_bar = ctk.CTkProgressBar(
            self.frame_status_banner,
            height=8,
            corner_radius=4,
            progress_color="#3b82f6",
        )
        self.progress_bar.set(0.0)
        self.progress_bar.pack(fill="x", padx=12, pady=(0, 6))

        # --- SECCIÓN 0: GESTOR DE MODELOS IA Y MEMORIA (OMNIVOICE + GGUF + EXPLORAR LOCAL) ---
        self.frame_models = ctk.CTkFrame(self, corner_radius=12)
        self.frame_models.pack(pady=4, padx=20, fill="x")

        self.frame_models_top = ctk.CTkFrame(self.frame_models, fg_color="transparent")
        self.frame_models_top.pack(fill="x", padx=12, pady=(6, 2))

        ctk.CTkLabel(
            self.frame_models_top,
            text="🧠 Modelo IA Activo y Gestión de Memoria (OmniVoice clona voz real / GGUF usa voces nativas):",
            font=("Helvetica", 12, "bold"),
            anchor="w",
            justify="left",
        ).pack(side="left", fill="x", expand=True)

        self.lbl_loaded_model = ctk.CTkLabel(
            self.frame_models_top,
            text="Activo: Verificando...",
            font=("Consolas", 11, "bold"),
            text_color="#34d399",
        )
        self.lbl_loaded_model.pack(side="right")

        self.frame_models_row = ctk.CTkFrame(self.frame_models, fg_color="transparent")
        self.frame_models_row.pack(fill="x", padx=12, pady=(2, 8))

        self.opt_model = ctk.CTkOptionMenu(
            self.frame_models_row,
            values=list(MODEL_LABELS_TO_ID.keys()),
            width=390,
        )
        self.opt_model.set("OmniVoice Zero-Shot 0.6B (Clonación Real + Diseño de Voz - 1.5 GB)")
        self.opt_model.pack(side="left", padx=(0, 6), fill="x", expand=True)

        self.btn_unload_model = ctk.CTkButton(
            self.frame_models_row,
            text="🧹 Liberar RAM",
            width=120,
            corner_radius=8,
            fg_color="#b91c1c",
            hover_color="#991b1b",
            font=("Helvetica", 12, "bold"),
            command=self.unload_model_from_ram,
        )
        self.btn_unload_model.pack(side="right", padx=(5, 0))

        self.btn_add_local_file = ctk.CTkButton(
            self.frame_models_row,
            text="➕ Archivo .GGUF",
            width=125,
            corner_radius=8,
            fg_color="#374151",
            hover_color="#4b5563",
            font=("Helvetica", 11, "bold"),
            command=self.browse_and_add_local_gguf,
        )
        self.btn_add_local_file.pack(side="right", padx=4)

        self.btn_add_local_dir = ctk.CTkButton(
            self.frame_models_row,
            text="📁 Carpeta Modelo",
            width=130,
            corner_radius=8,
            fg_color="#374151",
            hover_color="#4b5563",
            font=("Helvetica", 11, "bold"),
            command=self.browse_and_add_local_folder,
        )
        self.btn_add_local_dir.pack(side="right", padx=4)

        self.btn_load_model = ctk.CTkButton(
            self.frame_models_row,
            text="⚡ Cargar Modelo",
            width=135,
            corner_radius=8,
            fg_color="#2563eb",
            hover_color="#1d4ed8",
            font=("Helvetica", 12, "bold"),
            command=self.load_selected_model,
        )
        self.btn_load_model.pack(side="right", padx=(0, 4))

        # --- SECCIÓN 1: SELECTOR DE MODO DE SÍNTESIS + GESTIÓN DE CONFIGURACIÓN / RESTABLECER ---
        self.frame_mode_bar = ctk.CTkFrame(self, fg_color="transparent")
        self.frame_mode_bar.pack(fill="x", padx=20, pady=(4, 2))

        ctk.CTkLabel(
            self.frame_mode_bar,
            text="Modo de Operación:",
            font=("Helvetica", 13, "bold"),
        ).pack(side="left", padx=(0, 8))

        self.seg_mode = ctk.CTkSegmentedButton(
            self.frame_mode_bar,
            values=list(MODE_UI_TO_API.keys()),
            font=("Helvetica", 12, "bold"),
            selected_color="#2563eb",
            selected_hover_color="#1d4ed8",
            command=self.on_mode_change,
        )
        self.seg_mode.set("🎙️ Clonación de Voz (Audio Base)")
        self.seg_mode.pack(side="left")

        # Botón Restablecer muy visible y destacado siguiendo principios de UX
        self.btn_reset_params = ctk.CTkButton(
            self.frame_mode_bar,
            text="↺ Restablecer",
            width=115,
            height=28,
            corner_radius=8,
            fg_color="#d97706",
            hover_color="#b45309",
            text_color="#ffffff",
            font=("Helvetica", 12, "bold"),
            command=self.reset_default_params,
        )
        self.btn_reset_params.pack(side="right", padx=(6, 0))

        self.btn_load_preset = ctk.CTkButton(
            self.frame_mode_bar,
            text="📂 Cargar Config",
            width=110,
            height=28,
            corner_radius=8,
            fg_color="#374151",
            hover_color="#4b5563",
            font=("Helvetica", 11, "bold"),
            command=self.load_preset_dialog,
        )
        self.btn_load_preset.pack(side="right", padx=4)

        self.btn_save_preset = ctk.CTkButton(
            self.frame_mode_bar,
            text="💾 Guardar Config",
            width=115,
            height=28,
            corner_radius=8,
            fg_color="#374151",
            hover_color="#4b5563",
            font=("Helvetica", 11, "bold"),
            command=self.save_preset_dialog,
        )
        self.btn_save_preset.pack(side="right", padx=4)

        # Nota aclaratoria de UX sobre cómo interactúan las pestañas
        self.lbl_ux_hint = ctk.CTkLabel(
            self,
            text="💡 Todas las pestañas suman sus ajustes al generar: Pestaña 1 define Voz/Modo/Estilo y Pestaña 2 controla el Motor IA (OmniVoice o GGUF) y el Tono/Velocidad.",
            text_color="#9ca3af",
            font=("Helvetica", 11),
            anchor="w",
            justify="left",
            wraplength=880,
        )
        self.lbl_ux_hint.pack(fill="x", padx=22, pady=(0, 2))

        # --- SECCIÓN 2: PESTAÑAS DE CONFIGURACIÓN COMPLETA ---
        self.tabs = ctk.CTkTabview(self, height=290, corner_radius=12)
        self.tabs.pack(fill="x", padx=20, pady=(0, 4))
        self.tab_voice = self.tabs.add("🎙️ 1. Configuración de Voz, Clonación y Estilo (Activo)")
        self.tab_engine = self.tabs.add("⚙️ 2. Motor IA, Difusión OmniVoice, Muestreo LLM y DSP (Activo)")

        self._build_voice_tab()
        self._build_engine_tab()

        # --- SECCIÓN 3: TEXTO A GENERAR ---
        self.lbl_text = ctk.CTkLabel(
            self, text="Texto a convertir en voz:", font=("Helvetica", 13, "bold")
        )
        self.lbl_text.pack(anchor="w", padx=22, pady=(2, 2))
        self.textbox = ctk.CTkTextbox(
            self, height=85, corner_radius=12, font=("Helvetica", 13), wrap="word"
        )
        self.textbox.pack(pady=2, padx=20, fill="both", expand=True)
        self.textbox.insert("1.0", "Hola, esta es una prueba de clonación de voz natural y expresiva en español.")

        # --- BOTÓN GENERAR + ETA EN TIEMPO REAL (EJ: ETA 2s / 8s) ---
        self.frame_actions = ctk.CTkFrame(self, fg_color="transparent")
        self.frame_actions.pack(fill="x", padx=20, pady=(4, 4))

        self.btn_generate = ctk.CTkButton(
            self.frame_actions,
            text="▶ Generar Audio Natural",
            font=("Helvetica", 14, "bold"),
            height=38,
            corner_radius=10,
            command=self.generate_audio,
        )
        self.btn_generate.pack(side="left")

        self.lbl_eta = ctk.CTkLabel(
            self.frame_actions,
            text="ETA: -- / --",
            text_color="#60a5fa",
            font=("Consolas", 13, "bold"),
        )
        self.lbl_eta.pack(side="left", padx=14)

        self.btn_reset_bottom = ctk.CTkButton(
            self.frame_actions,
            text="↺ Restablecer Todo",
            width=135,
            height=34,
            corner_radius=8,
            fg_color="#374151",
            hover_color="#d97706",
            font=("Helvetica", 12, "bold"),
            command=self.reset_default_params,
        )
        self.btn_reset_bottom.pack(side="right")

        # --- SECCIÓN 4: REPRODUCTOR MODERNO CON PAUSA INSTANTÁNEA ---
        self.frame_player = ctk.CTkFrame(
            self, corner_radius=14, fg_color="#111827", border_width=1, border_color="#1f2937"
        )
        self.frame_player.pack(fill="x", padx=20, pady=(2, 10))

        self.seek_slider = ctk.CTkSlider(
            self.frame_player,
            from_=0.0,
            to=100.0,
            height=16,
            corner_radius=8,
            button_corner_radius=8,
            button_length=10,
            fg_color="#374151",
            progress_color="#ef4444",
            button_color="#ef4444",
            button_hover_color="#dc2626",
            command=self.on_seek_drag,
        )
        self.seek_slider.set(0.0)
        self.seek_slider.pack(fill="x", padx=14, pady=(8, 4))
        self.seek_slider.bind("<ButtonPress-1>", self.on_seek_press)
        self.seek_slider.bind("<ButtonRelease-1>", self.on_seek_release)

        self.frame_controls = ctk.CTkFrame(self.frame_player, fg_color="transparent")
        self.frame_controls.pack(fill="x", padx=14, pady=(0, 8))

        self.btn_play = ctk.CTkButton(
            self.frame_controls,
            text="▶",
            width=38,
            height=36,
            corner_radius=18,
            fg_color="#262f3f",
            hover_color="#374151",
            text_color="#ffffff",
            font=("Helvetica", 15, "bold"),
            command=self.toggle_play_pause,
        )
        self.btn_play.pack(side="left", padx=(0, 8))

        self.btn_mute = ctk.CTkButton(
            self.frame_controls,
            text="🔊",
            width=38,
            height=36,
            corner_radius=18,
            fg_color="#262f3f",
            hover_color="#374151",
            text_color="#ffffff",
            font=("Helvetica", 14),
            command=self.toggle_mute,
        )
        self.btn_mute.pack(side="left", padx=(0, 8))

        self.frame_time_pill = ctk.CTkFrame(
            self.frame_controls,
            corner_radius=18,
            fg_color="#262f3f",
            height=32,
        )
        self.frame_time_pill.pack(side="left", padx=(0, 10))

        self.lbl_time = ctk.CTkLabel(
            self.frame_time_pill,
            text="00:00 / 00:00",
            font=("Consolas", 13, "bold"),
            text_color="#f3f4f6",
        )
        self.lbl_time.pack(padx=14, pady=4)

        self.slider_vol = ctk.CTkSlider(
            self.frame_controls,
            from_=0.0,
            to=1.0,
            width=95,
            height=14,
            fg_color="#374151",
            progress_color="#9ca3af",
            button_color="#e5e7eb",
            button_hover_color="#ffffff",
            command=self.on_volume_change,
        )
        self.slider_vol.set(self.volume)
        self.slider_vol.pack(side="left", padx=6)

        self.btn_save = ctk.CTkButton(
            self.frame_controls,
            text="⬇ Guardar WAV",
            width=115,
            height=32,
            corner_radius=16,
            fg_color="#262f3f",
            hover_color="#374151",
            font=("Helvetica", 12, "bold"),
            command=self.save_audio_copy,
        )
        self.btn_save.pack(side="right")

        # Evento para recalcular wraplength automáticamente cuando la ventana cambia de ancho
        self.bind("<Configure>", self._on_window_resize)

        if os.path.exists(self.downloaded_audio):
            self._load_audio_metadata(self.downloaded_audio)

        self.sync_models_from_backend()
        self.check_backend_status()
        self._update_player_loop()

    def _on_window_resize(self, event):
        if event.widget == self:
            new_w = max(480, event.width - 65)
            try:
                self.status_lbl.configure(wraplength=new_w)
                self.lbl_ux_hint.configure(wraplength=new_w)
                self.lbl_voice.configure(wraplength=new_w - 20)
                self.lbl_mode_desc.configure(wraplength=new_w - 30)
            except Exception:
                pass

    def _scan_local_ref_files(self) -> list[str]:
        items = ["base_voice.mp3"]
        if os.path.isdir(DEFAULT_REF_DIR):
            for f in sorted(os.listdir(DEFAULT_REF_DIR)):
                if f.lower().endswith((".mp3", ".wav")) and f not in items:
                    items.append(f)
        return items

    def _build_voice_tab(self):
        # Fila 0: Explicación dinámica del modo seleccionado + Idioma + Voz Nativa
        self.lbl_mode_desc = ctk.CTkLabel(
            self.tab_voice,
            text="🎙️ MODO CLONACIÓN ACTIVO: Usa OmniVoice Zero-Shot para clonar el timbre real del Audio Base seleccionado abajo.",
            text_color="#34d399",
            font=("Helvetica", 12, "bold"),
            anchor="w",
            justify="left",
            wraplength=840,
        )
        self.lbl_mode_desc.pack(fill="x", padx=10, pady=(4, 4))

        # Bloque de Audio de Referencia (para Clonación)
        self.frame_ref_box = ctk.CTkFrame(self.tab_voice, corner_radius=8, fg_color="#1f2937")
        self.frame_ref_box.pack(fill="x", padx=10, pady=3)

        row_ref1 = ctk.CTkFrame(self.frame_ref_box, fg_color="transparent")
        row_ref1.pack(fill="x", padx=10, pady=(6, 2))

        ctk.CTkLabel(
            row_ref1,
            text="🎙️ Audio Base a Clonar:",
            font=("Helvetica", 12, "bold"),
        ).pack(side="left", padx=(0, 6))

        ref_choices = self._scan_local_ref_files()
        self.opt_ref_file = ctk.CTkOptionMenu(
            row_ref1,
            values=ref_choices,
            width=210,
            command=self.on_select_ref_dropdown,
        )
        self.opt_ref_file.set("base_voice.mp3")
        self.opt_ref_file.pack(side="left", padx=(0, 8))

        self.btn_voice = ctk.CTkButton(
            row_ref1,
            text="📂 Subir MP3/WAV",
            command=self.upload_voice,
            width=130,
            height=26,
            corner_radius=6,
        )
        self.btn_voice.pack(side="left", padx=4)

        self.btn_preview_ref = ctk.CTkButton(
            row_ref1,
            text="🎧 Escuchar Base",
            width=125,
            height=26,
            corner_radius=6,
            fg_color="#374151",
            hover_color="#4b5563",
            command=self.preview_reference_voice,
        )
        self.btn_preview_ref.pack(side="left", padx=4)

        self.chk_xvector = ctk.CTkCheckBox(
            row_ref1,
            text="Clonación Rápida (Sin transcripción exacta)",
            font=("Helvetica", 11),
            checkbox_width=18,
            checkbox_height=18,
        )
        self.chk_xvector.select()
        self.chk_xvector.pack(side="right", padx=6)

        self.lbl_voice = ctk.CTkLabel(
            self.frame_ref_box,
            text=f"Archivo activo: {self.reference_audio_path}",
            text_color="#9ca3af",
            font=("Consolas", 10),
            anchor="w",
            justify="left",
            wraplength=820,
        )
        self.lbl_voice.pack(fill="x", padx=10, pady=(0, 2))

        row_ref2 = ctk.CTkFrame(self.frame_ref_box, fg_color="transparent")
        row_ref2.pack(fill="x", padx=10, pady=(2, 6))

        ctk.CTkLabel(
            row_ref2,
            text="Transcripción del Audio Base (Opcional):",
            font=("Helvetica", 11),
        ).pack(side="left", padx=(0, 6))

        self.entry_ref_text = ctk.CTkEntry(
            row_ref2,
            placeholder_text="Escribe lo que dice el audio de referencia para mejorar aún más la clonación (o déjalo vacío)...",
            height=26,
        )
        self.entry_ref_text.pack(side="left", fill="x", expand=True)

        # Fila de Idioma + Voz Nativa (TTS)
        row_lang_spk = ctk.CTkFrame(self.tab_voice, fg_color="transparent")
        row_lang_spk.pack(fill="x", padx=10, pady=4)

        ctk.CTkLabel(
            row_lang_spk,
            text="🌎 Idioma:",
            font=("Helvetica", 12, "bold"),
        ).pack(side="left", padx=(0, 6))

        self.opt_language = ctk.CTkOptionMenu(
            row_lang_spk,
            values=LANGUAGE_CHOICES,
            width=245,
        )
        self.opt_language.set("Español (Latinoamérica / Argentina)")
        self.opt_language.pack(side="left", padx=(0, 16))

        ctk.CTkLabel(
            row_lang_spk,
            text="🗣️ Voz Predefinida (Modo Voces Nativas / GGUF):",
            font=("Helvetica", 12, "bold"),
        ).pack(side="left", padx=(0, 6))

        self.opt_speaker = ctk.CTkOptionMenu(
            row_lang_spk,
            values=["maria", "lucia", "sofia", "tara", "leah", "javi", "ninguna"],
            width=130,
        )
        self.opt_speaker.set("maria")
        self.opt_speaker.pack(side="left")

        # Fila de Prompt de Estilo (Style Instruction) y Descripción de Voz (Voice Design)
        row_prompts = ctk.CTkFrame(self.tab_voice, fg_color="transparent")
        row_prompts.pack(fill="x", padx=10, pady=(2, 4))
        row_prompts.grid_columnconfigure(1, weight=1)
        row_prompts.grid_columnconfigure(3, weight=1)

        ctk.CTkLabel(
            row_prompts,
            text="🎭 Prompt de Estilo / Emoción:",
            font=("Helvetica", 11, "bold"),
            anchor="w",
        ).grid(row=0, column=0, padx=(0, 6), pady=2, sticky="w")

        self.entry_style_instruct = ctk.CTkEntry(
            row_prompts,
            placeholder_text="Ej: tono conversacional, voz femenina cálida, alegre, acento argentino",
            height=28,
        )
        self.entry_style_instruct.insert(
            0, "tono conversacional, voz femenina cálida y suave, acento español argentino"
        )
        self.entry_style_instruct.grid(row=0, column=1, padx=(0, 12), pady=2, sticky="ew")

        ctk.CTkLabel(
            row_prompts,
            text="✨ Descripción Diseño de Voz:",
            font=("Helvetica", 11, "bold"),
            anchor="w",
        ).grid(row=0, column=2, padx=(0, 6), pady=2, sticky="w")

        self.entry_voice_design = ctk.CTkEntry(
            row_prompts,
            placeholder_text="Ej: Voz femenina joven de 23 años, clara, expresiva y amigable",
            height=28,
        )
        self.entry_voice_design.insert(
            0, "Voz femenina joven de 23 años, cálida, clara y natural con acento argentino"
        )
        self.entry_voice_design.grid(row=0, column=3, pady=2, sticky="ew")

    def _build_engine_tab(self):
        self.tab_engine.grid_columnconfigure(1, weight=1)
        self.tab_engine.grid_columnconfigure(3, weight=1)

        # --- Sub-encabezado: Parámetros de Difusión OmniVoice + Audio DSP ---
        ctk.CTkLabel(
            self.tab_engine,
            text="⚡ Parámetros OmniVoice (Difusión Zero-Shot) & Post-Procesado de Audio:",
            font=("Helvetica", 11, "bold"),
            text_color="#60a5fa",
            anchor="w",
        ).grid(row=0, column=0, columnspan=4, padx=8, pady=(2, 2), sticky="w")

        # Fila 1: Pasos de Difusión (num_step) + Guidance Scale (CFG)
        self.lbl_steps = ctk.CTkLabel(
            self.tab_engine, text="Pasos Difusión (Calidad): 24", width=185, anchor="w", font=("Helvetica", 11)
        )
        self.lbl_steps.grid(row=1, column=0, padx=8, pady=2, sticky="w")
        self.slider_steps = ctk.CTkSlider(
            self.tab_engine,
            from_=8,
            to=48,
            number_of_steps=40,
            command=lambda v: self.lbl_steps.configure(text=f"Pasos Difusión (Calidad): {int(v)}"),
        )
        self.slider_steps.set(24)
        self.slider_steps.grid(row=1, column=1, padx=8, pady=2, sticky="ew")

        self.lbl_cfg = ctk.CTkLabel(
            self.tab_engine, text="Fidelidad / CFG Scale: 2.0", width=185, anchor="w", font=("Helvetica", 11)
        )
        self.lbl_cfg.grid(row=1, column=2, padx=8, pady=2, sticky="w")
        self.slider_cfg = ctk.CTkSlider(
            self.tab_engine,
            from_=0.5,
            to=5.0,
            number_of_steps=45,
            command=lambda v: self.lbl_cfg.configure(text=f"Fidelidad / CFG Scale: {float(v):.1f}"),
        )
        self.slider_cfg.set(2.0)
        self.slider_cfg.grid(row=1, column=3, padx=8, pady=2, sticky="ew")

        # Fila 2: Pitch Fino (st) + Velocidad de Habla (speed)
        self.lbl_pitch = ctk.CTkLabel(
            self.tab_engine, text="Ajuste Tono Fino: +0.0 st", width=185, anchor="w", font=("Helvetica", 11)
        )
        self.lbl_pitch.grid(row=2, column=0, padx=8, pady=2, sticky="w")
        self.slider_pitch = ctk.CTkSlider(
            self.tab_engine,
            from_=-6.0,
            to=6.0,
            number_of_steps=24,
            command=lambda v: self.lbl_pitch.configure(text=f"Ajuste Tono Fino: {float(v):+.1f} st"),
        )
        self.slider_pitch.set(0.0)
        self.slider_pitch.grid(row=2, column=1, padx=8, pady=2, sticky="ew")

        self.lbl_speed = ctk.CTkLabel(
            self.tab_engine, text="Velocidad de Habla: 1.00x", width=185, anchor="w", font=("Helvetica", 11)
        )
        self.lbl_speed.grid(row=2, column=2, padx=8, pady=2, sticky="w")
        self.slider_speed = ctk.CTkSlider(
            self.tab_engine,
            from_=0.5,
            to=2.0,
            number_of_steps=60,
            command=lambda v: self.lbl_speed.configure(text=f"Velocidad de Habla: {float(v):.2f}x"),
        )
        self.slider_speed.set(1.0)
        self.slider_speed.grid(row=2, column=3, padx=8, pady=2, sticky="ew")

        # --- Sub-encabezado: Parámetros de Muestreo LLM (Orpheus GGUF) y Hardware ---
        ctk.CTkLabel(
            self.tab_engine,
            text="🧠 Parámetros Muestreo LLM (Orpheus GGUF), Semilla y Rendimiento CPU/Contexto:",
            font=("Helvetica", 11, "bold"),
            text_color="#a78bfa",
            anchor="w",
        ).grid(row=3, column=0, columnspan=4, padx=8, pady=(4, 2), sticky="w")

        # Fila 4: Temperatura + Top-K
        self.lbl_temp = ctk.CTkLabel(
            self.tab_engine, text="Expresividad (Temp): 0.60", width=185, anchor="w", font=("Helvetica", 11)
        )
        self.lbl_temp.grid(row=4, column=0, padx=8, pady=2, sticky="w")
        self.slider_temp = ctk.CTkSlider(
            self.tab_engine,
            from_=0.1,
            to=1.5,
            number_of_steps=70,
            command=lambda v: self.lbl_temp.configure(text=f"Expresividad (Temp): {float(v):.2f}"),
        )
        self.slider_temp.set(0.60)
        self.slider_temp.grid(row=4, column=1, padx=8, pady=2, sticky="ew")

        self.lbl_topk = ctk.CTkLabel(
            self.tab_engine, text="Top-K: 50", width=185, anchor="w", font=("Helvetica", 11)
        )
        self.lbl_topk.grid(row=4, column=2, padx=8, pady=2, sticky="w")
        self.slider_topk = ctk.CTkSlider(
            self.tab_engine,
            from_=1,
            to=100,
            number_of_steps=99,
            command=lambda v: self.lbl_topk.configure(text=f"Top-K: {int(v)}"),
        )
        self.slider_topk.set(50)
        self.slider_topk.grid(row=4, column=3, padx=8, pady=2, sticky="ew")

        # Fila 5: Top-P + Repeat Penalty
        self.lbl_topp = ctk.CTkLabel(
            self.tab_engine, text="Top-P (Nucleus): 0.90", width=185, anchor="w", font=("Helvetica", 11)
        )
        self.lbl_topp.grid(row=5, column=0, padx=8, pady=2, sticky="w")
        self.slider_topp = ctk.CTkSlider(
            self.tab_engine,
            from_=0.10,
            to=1.00,
            number_of_steps=45,
            command=lambda v: self.lbl_topp.configure(text=f"Top-P (Nucleus): {float(v):.2f}"),
        )
        self.slider_topp.set(0.90)
        self.slider_topp.grid(row=5, column=1, padx=8, pady=2, sticky="ew")

        self.lbl_reppen = ctk.CTkLabel(
            self.tab_engine, text="Penaliz. Repetición: 1.12", width=185, anchor="w", font=("Helvetica", 11)
        )
        self.lbl_reppen.grid(row=5, column=2, padx=8, pady=2, sticky="w")
        self.slider_reppen = ctk.CTkSlider(
            self.tab_engine,
            from_=1.00,
            to=1.50,
            number_of_steps=50,
            command=lambda v: self.lbl_reppen.configure(text=f"Penaliz. Repetición: {float(v):.2f}"),
        )
        self.slider_reppen.set(1.12)
        self.slider_reppen.grid(row=5, column=3, padx=8, pady=2, sticky="ew")

        # Fila 6: Max Audio Tokens + Switches y Semilla/Hilos
        self.lbl_maxtok = ctk.CTkLabel(
            self.tab_engine, text="Máx. Tokens Audio: 700", width=185, anchor="w", font=("Helvetica", 11)
        )
        self.lbl_maxtok.grid(row=6, column=0, padx=8, pady=2, sticky="w")
        self.slider_maxtok = ctk.CTkSlider(
            self.tab_engine,
            from_=140,
            to=1680,
            number_of_steps=220,
            command=lambda v: self.lbl_maxtok.configure(text=f"Máx. Tokens Audio: {int(v)}"),
        )
        self.slider_maxtok.set(700)
        self.slider_maxtok.grid(row=6, column=1, padx=8, pady=2, sticky="ew")

        frame_hw = ctk.CTkFrame(self.tab_engine, fg_color="transparent")
        frame_hw.grid(row=6, column=2, columnspan=2, padx=8, pady=2, sticky="ew")

        ctk.CTkLabel(frame_hw, text="Seed:", font=("Helvetica", 11)).pack(side="left", padx=(0, 3))
        self.entry_seed = ctk.CTkEntry(frame_hw, width=58, height=24)
        self.entry_seed.insert(0, "-1")
        self.entry_seed.pack(side="left", padx=(0, 8))

        ctk.CTkLabel(frame_hw, text="Hilos CPU:", font=("Helvetica", 11)).pack(side="left", padx=(0, 3))
        self.opt_threads = ctk.CTkOptionMenu(frame_hw, values=["2", "4", "6", "8"], width=58, height=24)
        self.opt_threads.set("4")
        self.opt_threads.pack(side="left", padx=(0, 8))

        self.sw_denoise = ctk.CTkSwitch(
            frame_hw, text="Denoise", font=("Helvetica", 11), switch_width=32, switch_height=16
        )
        self.sw_denoise.select()
        self.sw_denoise.pack(side="left", padx=(0, 6))

        self.sw_autoclone = ctk.CTkSwitch(
            frame_hw, text="Shift +3.5st", font=("Helvetica", 11), switch_width=32, switch_height=16
        )
        self.sw_autoclone.deselect()
        self.sw_autoclone.pack(side="left")

    def on_mode_change(self, ui_mode_label: str):
        mode = MODE_UI_TO_API.get(ui_mode_label, "clone")
        if mode == "clone":
            self.lbl_mode_desc.configure(
                text="🎙️ MODO CLONACIÓN ACTIVO: Usa OmniVoice Zero-Shot para clonar el timbre real del Audio Base seleccionado abajo.",
                text_color="#34d399",
            )
            # Si el usuario elige Clonación y tiene seleccionado un GGUF que no clona, sugerir OmniVoice
            cur_mid = MODEL_LABELS_TO_ID.get(self.opt_model.get(), "")
            if cur_mid != "omnivoice-zeroshot-0.6b" and "omnivoice" not in cur_mid:
                for lbl, mid in MODEL_LABELS_TO_ID.items():
                    if mid == "omnivoice-zeroshot-0.6b":
                        self.opt_model.set(lbl)
                        break
        elif mode == "tts":
            self.lbl_mode_desc.configure(
                text="🗣️ MODO TEXTO A VOZ (VOCES NATIVAS): Usa la voz predefinida seleccionada ('maria', 'lucia', 'javi') + Prompt de Estilo.",
                text_color="#60a5fa",
            )
        else:
            self.lbl_mode_desc.configure(
                text="✨ MODO DISEÑO DE VOZ: Crea una voz a medida a partir de la 'Descripción Diseño de Voz' en lenguaje natural.",
                text_color="#c084fc",
            )

    def sync_models_from_backend(self):
        threading.Thread(target=self._sync_models_worker, daemon=True).start()

    def _sync_models_worker(self):
        try:
            resp = requests.get(f"{self.api_url}/models", timeout=6)
            if resp.status_code == 200:
                data = resp.json()
                models_list = data.get("models", [])
                loaded_id = data.get("loaded_model_id")
                self.after(0, lambda m=models_list, lid=loaded_id: self._apply_models_catalog(m, lid))
        except Exception:
            pass

    def _apply_models_catalog(self, models_list: list[dict], loaded_id: str | None):
        global MODEL_LABELS_TO_ID, MODEL_ID_TO_LABEL
        new_l2i = {}
        new_i2l = {}
        for m in models_list:
            mid = m["id"]
            name = m["name"]
            new_l2i[name] = mid
            new_i2l[mid] = name
        if new_l2i:
            MODEL_LABELS_TO_ID = new_l2i
            MODEL_ID_TO_LABEL = new_i2l
            cur_val = self.opt_model.get()
            self.opt_model.configure(values=list(MODEL_LABELS_TO_ID.keys()))
            if not self._models_synced_once and loaded_id and loaded_id in MODEL_ID_TO_LABEL:
                self.opt_model.set(MODEL_ID_TO_LABEL[loaded_id])
                self._models_synced_once = True
            elif cur_val in MODEL_LABELS_TO_ID:
                self.opt_model.set(cur_val)

    def browse_and_add_local_gguf(self):
        init_dir = DEFAULT_MODELS_DIR if os.path.isdir(DEFAULT_MODELS_DIR) else BASE_DIR
        filepath = fd.askopenfilename(
            title="Seleccionar archivo de modelo .GGUF descargado",
            initialdir=init_dir,
            filetypes=[("Modelos GGUF", "*.gguf"), ("Todos los archivos", "*.*")],
        )
        if filepath:
            self._register_and_load_local_model(filepath, engine="gguf")

    def browse_and_add_local_folder(self):
        init_dir = DEFAULT_MODELS_DIR if os.path.isdir(DEFAULT_MODELS_DIR) else BASE_DIR
        folderpath = fd.askdirectory(
            title="Seleccionar carpeta de modelo descargado (OmniVoice / HuggingFace / GGUF)",
            initialdir=init_dir,
        )
        if folderpath:
            self._register_and_load_local_model(folderpath, engine=None)

    def _register_and_load_local_model(self, path: str, engine: str | None = None):
        self.status_lbl.configure(
            text=f"➕ Registrando y cargando modelo local: {os.path.basename(path)}...",
            text_color="#3b82f6",
        )
        threading.Thread(
            target=self._add_local_model_worker, args=(path, engine), daemon=True
        ).start()

    def _add_local_model_worker(self, path: str, engine: str | None):
        try:
            payload = {"path": path}
            if engine:
                payload["engine"] = engine
            resp = requests.post(f"{self.api_url}/models/add_local", json=payload, timeout=12)
            if resp.status_code == 200:
                model_info = resp.json().get("model", {})
                mid = model_info.get("id")
                mname = model_info.get("name")
                if mid and mname:
                    MODEL_LABELS_TO_ID[mname] = mid
                    MODEL_ID_TO_LABEL[mid] = mname
                    self.after(
                        0,
                        lambda: (
                            self.opt_model.configure(values=list(MODEL_LABELS_TO_ID.keys())),
                            self.opt_model.set(mname),
                            self.load_selected_model(),
                        ),
                    )
            else:
                detail = resp.json().get("detail", "No se pudo agregar el modelo local")
                self.after(
                    0,
                    lambda d=detail: self.status_lbl.configure(
                        text=f"❌ {d}", text_color="#ef4444"
                    ),
                )
        except Exception as e:
            self.after(
                0,
                lambda err=str(e): self.status_lbl.configure(
                    text=f"❌ Error agregando modelo local: {err}", text_color="#ef4444"
                ),
            )

    def load_selected_model(self):
        label = self.opt_model.get()
        model_id = MODEL_LABELS_TO_ID.get(label, "omnivoice-zeroshot-0.6b")
        try:
            threads = int(self.opt_threads.get())
        except Exception:
            threads = 4
        self.progress_bar.set(0.05)
        self.status_lbl.configure(
            text=f"⏳ Iniciando descarga / carga en memoria de: {label}...",
            text_color="#3b82f6",
        )
        threading.Thread(
            target=self._load_model_worker, args=(model_id, threads), daemon=True
        ).start()

    def _load_model_worker(self, model_id: str, threads: int):
        try:
            requests.post(
                f"{self.api_url}/models/load",
                json={"model_id": model_id, "cpu_threads": threads, "n_ctx": 1024},
                timeout=10,
            )
        except Exception as e:
            print("Error solicitando carga de modelo:", e)

    def unload_model_from_ram(self):
        self.status_lbl.configure(
            text="🧹 Liberando memoria RAM/VRAM...", text_color="#f59e0b"
        )
        threading.Thread(target=self._unload_model_worker, daemon=True).start()

    def _unload_model_worker(self):
        try:
            resp = requests.post(f"{self.api_url}/models/unload", timeout=15)
            if resp.status_code == 200:
                self.after(
                    0,
                    lambda: (
                        self.progress_bar.set(0.0),
                        self.status_lbl.configure(
                            text="🧹 Memoria RAM/VRAM liberada por completo.",
                            text_color="#10b981",
                        ),
                    ),
                )
        except Exception as e:
            print("Error liberando modelo:", e)

    def get_current_config(self) -> dict:
        try:
            seed_val = int(self.entry_seed.get().strip())
        except Exception:
            seed_val = -1
        try:
            threads_val = int(self.opt_threads.get())
        except Exception:
            threads_val = 4

        model_id = MODEL_LABELS_TO_ID.get(
            self.opt_model.get(), "omnivoice-zeroshot-0.6b"
        )
        mode_api = MODE_UI_TO_API.get(self.seg_mode.get(), "clone")

        lang_ui = self.opt_language.get()
        if "Español" in lang_ui:
            lang_api = "Spanish"
        elif "Automático" in lang_ui:
            lang_api = "Auto"
        else:
            lang_api = lang_ui

        return {
            "model_id": model_id,
            "mode": mode_api,
            "language": lang_api,
            "reference_file": self.reference_audio_path,
            "reference_text": self.entry_ref_text.get().strip(),
            "use_xvector_only": bool(self.chk_xvector.get()),
            "speaker_hint": self.opt_speaker.get(),
            "style_instruct": self.entry_style_instruct.get().strip(),
            "voice_description": self.entry_voice_design.get().strip(),
            "num_step": int(self.slider_steps.get()),
            "guidance_scale": round(float(self.slider_cfg.get()), 2),
            "denoise": bool(self.sw_denoise.get()),
            "auto_clone_voice": bool(self.sw_autoclone.get()),
            "pitch_semitones": round(float(self.slider_pitch.get()), 2),
            "speed": round(float(self.slider_speed.get()), 2),
            "temperature": round(float(self.slider_temp.get()), 2),
            "top_k": int(self.slider_topk.get()),
            "top_p": round(float(self.slider_topp.get()), 2),
            "repeat_penalty": round(float(self.slider_reppen.get()), 2),
            "max_audio_tokens": int(self.slider_maxtok.get()),
            "seed": seed_val,
            "cpu_threads": threads_val,
        }

    def apply_config_dict(self, cfg: dict):
        if "model_id" in cfg and cfg["model_id"] in MODEL_ID_TO_LABEL:
            self.opt_model.set(MODEL_ID_TO_LABEL[cfg["model_id"]])

        if "mode" in cfg and cfg["mode"] in MODE_API_TO_UI:
            ui_m = MODE_API_TO_UI[cfg["mode"]]
            self.seg_mode.set(ui_m)
            self.on_mode_change(ui_m)

        if "language" in cfg:
            lval = cfg["language"]
            if lval == "Spanish":
                self.opt_language.set("Español (Latinoamérica / Argentina)")
            elif lval == "Auto":
                self.opt_language.set("Automático (Detectar Idioma)")
            elif lval in LANGUAGE_CHOICES:
                self.opt_language.set(lval)

        ref_f = cfg.get("reference_file", DEFAULT_REF_FILE)
        if ref_f:
            self.reference_audio_path = ref_f
            self.lbl_voice.configure(text=f"Archivo activo: {ref_f}")
            base_n = os.path.basename(ref_f)
            if base_n in self.opt_ref_file.cget("values"):
                self.opt_ref_file.set(base_n)

        if "reference_text" in cfg:
            self.entry_ref_text.delete(0, "end")
            self.entry_ref_text.insert(0, str(cfg["reference_text"]))

        if "use_xvector_only" in cfg:
            if cfg["use_xvector_only"]:
                self.chk_xvector.select()
            else:
                self.chk_xvector.deselect()

        if "speaker_hint" in cfg:
            self.opt_speaker.set(str(cfg["speaker_hint"]))

        if "style_instruct" in cfg:
            self.entry_style_instruct.delete(0, "end")
            self.entry_style_instruct.insert(0, str(cfg["style_instruct"]))

        if "voice_description" in cfg:
            self.entry_voice_design.delete(0, "end")
            self.entry_voice_design.insert(0, str(cfg["voice_description"]))

        if "num_step" in cfg:
            v = int(cfg["num_step"])
            self.slider_steps.set(v)
            self.lbl_steps.configure(text=f"Pasos Difusión (Calidad): {v}")

        if "guidance_scale" in cfg:
            v = float(cfg["guidance_scale"])
            self.slider_cfg.set(v)
            self.lbl_cfg.configure(text=f"Fidelidad / CFG Scale: {v:.1f}")

        if "denoise" in cfg:
            if cfg["denoise"]:
                self.sw_denoise.select()
            else:
                self.sw_denoise.deselect()

        if "auto_clone_voice" in cfg:
            if cfg["auto_clone_voice"]:
                self.sw_autoclone.select()
            else:
                self.sw_autoclone.deselect()

        if "pitch_semitones" in cfg:
            v = float(cfg["pitch_semitones"])
            self.slider_pitch.set(v)
            self.lbl_pitch.configure(text=f"Ajuste Tono Fino: {v:+.1f} st")

        if "speed" in cfg:
            v = float(cfg["speed"])
            self.slider_speed.set(v)
            self.lbl_speed.configure(text=f"Velocidad de Habla: {v:.2f}x")

        if "temperature" in cfg:
            v = float(cfg["temperature"])
            self.slider_temp.set(v)
            self.lbl_temp.configure(text=f"Expresividad (Temp): {v:.2f}")

        if "top_k" in cfg:
            v = int(cfg["top_k"])
            self.slider_topk.set(v)
            self.lbl_topk.configure(text=f"Top-K: {v}")

        if "top_p" in cfg:
            v = float(cfg["top_p"])
            self.slider_topp.set(v)
            self.lbl_topp.configure(text=f"Top-P (Nucleus): {v:.2f}")

        if "repeat_penalty" in cfg:
            v = float(cfg["repeat_penalty"])
            self.slider_reppen.set(v)
            self.lbl_reppen.configure(text=f"Penaliz. Repetición: {v:.2f}")

        if "max_audio_tokens" in cfg:
            v = int(cfg["max_audio_tokens"])
            self.slider_maxtok.set(v)
            self.lbl_maxtok.configure(text=f"Máx. Tokens Audio: {v}")

        if "seed" in cfg:
            self.entry_seed.delete(0, "end")
            self.entry_seed.insert(0, str(cfg["seed"]))

        if "cpu_threads" in cfg:
            self.opt_threads.set(str(cfg["cpu_threads"]))

    def reset_default_params(self):
        self.apply_config_dict({
            "model_id": "omnivoice-zeroshot-0.6b",
            "mode": "clone",
            "language": "Spanish",
            "reference_file": DEFAULT_REF_FILE,
            "reference_text": "",
            "use_xvector_only": True,
            "speaker_hint": "maria",
            "style_instruct": "tono conversacional, voz femenina cálida y suave, acento español argentino",
            "voice_description": "Voz femenina joven de 23 años, cálida, clara y natural con acento argentino",
            "num_step": 24,
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
            "cpu_threads": 4,
        })
        self.status_lbl.configure(
            text="↺ Todos los parámetros y configuraciones fueron restablecidos a sus valores originales.",
            text_color="#10b981",
        )

    def save_preset_dialog(self):
        dest = fd.asksaveasfilename(
            initialdir=PRESETS_DIR,
            defaultextension=".json",
            filetypes=[("Preset JSON", "*.json")],
            initialfile="voz_clonada_preset.json",
        )
        if dest:
            with open(dest, "w", encoding="utf-8") as f:
                json.dump(self.get_current_config(), f, indent=2, ensure_ascii=False)
            self.status_lbl.configure(text="💾 Configuración guardada con éxito", text_color="#10b981")

    def load_preset_dialog(self):
        src = fd.askopenfilename(
            initialdir=PRESETS_DIR,
            filetypes=[("Preset JSON", "*.json")],
        )
        if src and os.path.exists(src):
            try:
                with open(src, "r", encoding="utf-8") as f:
                    cfg = json.load(f)
                self.apply_config_dict(cfg)
                self.status_lbl.configure(text="📂 Configuración cargada correctamente", text_color="#10b981")
            except Exception as e:
                self.status_lbl.configure(text=f"❌ Error cargando preset: {e}", text_color="#ef4444")

    def on_select_ref_dropdown(self, filename: str):
        candidate = os.path.join(DEFAULT_REF_DIR, filename)
        if os.path.exists(candidate):
            self.reference_audio_path = candidate
            self.lbl_voice.configure(text=f"Archivo activo: {candidate}")
            self.status_lbl.configure(text=f"✅ Voz base seleccionada: {filename}", text_color="#10b981")

    def preview_reference_voice(self):
        threading.Thread(target=self._preview_ref_worker, daemon=True).start()

    def _preview_ref_worker(self):
        try:
            resp = requests.get(
                f"{self.api_url}/reference_preview",
                params={"path": self.reference_audio_path},
                timeout=10,
            )
            if resp.status_code == 200:
                preview_file = os.path.join(BASE_DIR, "resultado.wav")
                if self.mixer_ready and self.is_playing:
                    pygame.mixer.music.stop()
                with open(preview_file, "wb") as f:
                    f.write(resp.content)
                self.after(0, self._on_audio_ready)
                self.after(
                    0,
                    lambda: self.status_lbl.configure(
                        text="🎧 Reproduciendo audio de referencia base", text_color="#3b82f6"
                    ),
                )
        except Exception as e:
            print("Error previsualizando voz base:", e)

    def _init_audio_mixer(self):
        try:
            # Buffer pequeño (256 samples ≈ 10ms) para que pausar/reanudar sea instantáneo sin lag en WSLg
            pygame.mixer.pre_init(frequency=24000, size=-16, channels=1, buffer=256)
            pygame.mixer.init(frequency=24000, size=-16, channels=1, buffer=256)
            pygame.mixer.music.set_volume(self.volume)
            self.mixer_ready = True
        except Exception as e:
            print(f"Advertencia: No se pudo iniciar pygame.mixer ({e})")
            self.mixer_ready = False

    def _load_audio_metadata(self, filepath: str) -> bool:
        if not self.mixer_ready or not os.path.exists(filepath):
            return False
        try:
            snd = pygame.mixer.Sound(filepath)
            self.audio_duration = max(0.1, float(snd.get_length()))
            pygame.mixer.music.load(filepath)
            self.play_offset = 0.0
            self.is_playing = False
            self.is_paused = False
            self.btn_play.configure(text="▶")
            self.seek_slider.set(0.0)
            self.lbl_time.configure(
                text=f"00:00 / {format_time(self.audio_duration)}"
            )
            return True
        except Exception as e:
            print(f"Error cargando audio en el reproductor: {e}")
            return False

    def toggle_play_pause(self):
        if not self.mixer_ready:
            self._init_audio_mixer()
            if not self.mixer_ready:
                self.status_lbl.configure(text="❌ Sin dispositivo de audio", text_color="#ef4444")
                return

        if not os.path.exists(self.downloaded_audio):
            self.status_lbl.configure(text="⚠️ Genera un audio primero", text_color="#f59e0b")
            return

        if self.audio_duration <= 0.1:
            if not self._load_audio_metadata(self.downloaded_audio):
                return

        try:
            if self.is_playing and not self.is_paused:
                # Capturar el instante exacto ANTES de pausar y usar stop() en vez de pause()
                # para vaciar inmediatamente el buffer de PulseAudio/WSLg sin retraso audible
                exact_pos = self._get_current_pos()
                pygame.mixer.music.stop()
                self.play_offset = exact_pos
                self.is_paused = True
                self.btn_play.configure(text="▶")
                if self.audio_duration > 0:
                    pct = min(100.0, (exact_pos / self.audio_duration) * 100.0)
                    self.seek_slider.set(pct)
                    self.lbl_time.configure(
                        text=f"{format_time(exact_pos)} / {format_time(self.audio_duration)}"
                    )
            elif self.is_playing and self.is_paused:
                if self.play_offset >= self.audio_duration - 0.1:
                    self.play_offset = 0.0
                pygame.mixer.music.load(self.downloaded_audio)
                pygame.mixer.music.play(start=self.play_offset)
                pygame.mixer.music.set_volume(0.0 if self.is_muted else self.volume)
                self.play_start_wall = time.time()
                self.is_paused = False
                self.btn_play.configure(text="⏸")
            else:
                if self.play_offset >= self.audio_duration - 0.15:
                    self.play_offset = 0.0
                pygame.mixer.music.load(self.downloaded_audio)
                pygame.mixer.music.play(start=self.play_offset)
                pygame.mixer.music.set_volume(0.0 if self.is_muted else self.volume)
                self.play_start_wall = time.time()
                self.is_playing = True
                self.is_paused = False
                self.btn_play.configure(text="⏸")
        except Exception as e:
            print(f"Error al reproducir: {e}")
            self.status_lbl.configure(text="❌ Error reproduciendo audio", text_color="#ef4444")

    def toggle_mute(self):
        self.is_muted = not self.is_muted
        if self.is_muted:
            self.btn_mute.configure(text="🔇")
            if self.mixer_ready:
                pygame.mixer.music.set_volume(0.0)
        else:
            self.btn_mute.configure(text="🔊")
            if self.mixer_ready:
                pygame.mixer.music.set_volume(self.volume)

    def on_volume_change(self, val):
        self.volume = float(val)
        if self.volume == 0.0:
            self.is_muted = True
            self.btn_mute.configure(text="🔇")
        else:
            self.is_muted = False
            self.btn_mute.configure(text="🔊")
        if self.mixer_ready:
            pygame.mixer.music.set_volume(0.0 if self.is_muted else self.volume)

    def on_seek_press(self, _event):
        self.user_dragging_seek = True

    def on_seek_drag(self, val):
        if self.audio_duration > 0:
            target_sec = (float(val) / 100.0) * self.audio_duration
            self.lbl_time.configure(
                text=f"{format_time(target_sec)} / {format_time(self.audio_duration)}"
            )

    def on_seek_release(self, _event):
        if self.audio_duration > 0 and self.mixer_ready:
            pct = float(self.seek_slider.get()) / 100.0
            self.play_offset = max(0.0, min(self.audio_duration - 0.05, pct * self.audio_duration))
            self.lbl_time.configure(
                text=f"{format_time(self.play_offset)} / {format_time(self.audio_duration)}"
            )
            if self.is_playing and not self.is_paused:
                try:
                    pygame.mixer.music.play(start=self.play_offset)
                    self.play_start_wall = time.time()
                except Exception:
                    pass
        self.user_dragging_seek = False

    def _get_current_pos(self) -> float:
        if not self.is_playing or self.is_paused:
            return self.play_offset
        elapsed = time.time() - self.play_start_wall
        return min(self.audio_duration, self.play_offset + elapsed)

    def _update_player_loop(self):
        # 1. Actualizar reproductor de audio con alta frecuencia (50ms) para máxima precisión visual
        if self.mixer_ready and self.is_playing and not self.is_paused:
            if not pygame.mixer.music.get_busy():
                self.is_playing = False
                self.is_paused = False
                self.play_offset = 0.0
                self.btn_play.configure(text="▶")
                if not self.user_dragging_seek:
                    self.seek_slider.set(100.0)
                    self.lbl_time.configure(
                        text=f"{format_time(self.audio_duration)} / {format_time(self.audio_duration)}"
                    )
            else:
                cur = self._get_current_pos()
                if not self.user_dragging_seek and self.audio_duration > 0:
                    pct = min(100.0, (cur / self.audio_duration) * 100.0)
                    self.seek_slider.set(pct)
                    self.lbl_time.configure(
                        text=f"{format_time(cur)} / {format_time(self.audio_duration)}"
                    )

        # 2. Actualizar cronómetro de generación en vivo (Ej: ETA 2s / 8s) cada 50ms
        if self.is_generating and self.gen_local_start_t > 0:
            elapsed_s = max(0, int(time.time() - self.gen_local_start_t))
            target_s = max(elapsed_s + 1, self.gen_target_eta_s)
            self.lbl_eta.configure(text=f"ETA {elapsed_s}s / {target_s}s")

        self.after(50, self._update_player_loop)

    def save_audio_copy(self):
        if not os.path.exists(self.downloaded_audio):
            return
        dest = fd.asksaveasfilename(
            defaultextension=".wav",
            filetypes=[("Audio WAV", "*.wav")],
            initialfile="tts_generado.wav",
        )
        if dest:
            shutil.copy(self.downloaded_audio, dest)
            self.status_lbl.configure(text="✅ Copia de audio WAV guardada", text_color="#10b981")

    def check_backend_status(self):
        if not self._status_poll_inflight:
            self._status_poll_inflight = True
            threading.Thread(target=self._poll_status_worker, daemon=True).start()
        self.after(1000, self.check_backend_status)

    def _poll_status_worker(self):
        try:
            resp = requests.get(f"{self.api_url}/status", timeout=6)
            if resp.status_code == 200:
                data = resp.json()
                self.after(0, lambda d=data: self._apply_backend_status(d))
            else:
                if not self.is_generating:
                    self.after(
                        0,
                        lambda: self.status_lbl.configure(
                            text="⏳ Conectando al backend...", text_color="#f59e0b"
                        ),
                    )
        except Exception:
            if not self.is_generating:
                self.after(
                    0,
                    lambda: self.status_lbl.configure(
                        text="❌ Backend offline. Ejecuta ./run_backend.sh", text_color="#ef4444"
                    ),
                )
        finally:
            self._status_poll_inflight = False

    def _apply_backend_status(self, data: dict):
        state = data.get("status")
        msg = data.get("message", "")
        loaded_name = data.get("loaded_model_name", "Ninguno")
        loaded_id = data.get("loaded_model_id")
        dl_pct = float(data.get("download_progress", 0.0) or 0.0)
        elapsed_b = int(data.get("task_elapsed_sec", 0) or 0)
        eta_b = int(data.get("task_eta_sec", 0) or 0)

        self.lbl_loaded_model.configure(
            text=f"Activo: {loaded_name}",
            text_color="#34d399" if state == "READY" else "#f59e0b",
        )

        if not self._models_synced_once and loaded_id:
            self.sync_models_from_backend()

        mem = data.get("memory", {})
        if mem:
            proc_mb = mem.get("process_ram_mb", 0.0)
            sys_u = mem.get("system_used_gb", 0.0)
            sys_t = mem.get("system_total_gb", 0.0)
            sys_p = mem.get("system_percent", 0.0)
            ram_color = "#ef4444" if sys_p > 85 else ("#f59e0b" if sys_p > 70 else "#60a5fa")
            self.lbl_ram.configure(
                text=f"RAM App: {proc_mb:.0f} MB | Sistema: {sys_u:.1f}/{sys_t:.1f} GB ({sys_p:.0f}%)",
                text_color=ram_color,
            )

        if state == "DOWNLOADING":
            self.progress_bar.set(max(0.02, min(1.0, dl_pct / 100.0)))
            tot_s = elapsed_b + eta_b
            self.lbl_eta.configure(text=f"Descarga {dl_pct:.1f}% • ETA {elapsed_b}s / {tot_s}s")
            self.status_lbl.configure(text=f"⬇️ {msg}", text_color="#3b82f6")
            self.btn_generate.configure(state="disabled")
        elif state == "LOADING":
            self.progress_bar.set(0.95)
            self.lbl_eta.configure(text=f"Cargando ({elapsed_b}s)")
            self.status_lbl.configure(text=f"🧠 {msg}", text_color="#f59e0b")
            self.btn_generate.configure(state="disabled")
        elif self.is_generating or state == "GENERATING":
            self.progress_bar.set(max(0.08, min(1.0, dl_pct / 100.0)))
            if eta_b > 0:
                self.gen_target_eta_s = elapsed_b + eta_b
            self.status_lbl.configure(text=f"⏳ {msg}", text_color="#f59e0b")
            self.btn_generate.configure(state="disabled")
        elif state == "UNLOADED":
            self.progress_bar.set(0.0)
            self.status_lbl.configure(
                text="🧹 Memoria Libre (Selecciona un modelo arriba y pulsa '⚡ Cargar Modelo')",
                text_color="#60a5fa",
            )
            self.btn_generate.configure(state="disabled")
        elif state in ["READY", "SIMULATION"]:
            self.progress_bar.set(1.0)
            self.status_lbl.configure(text=f"✅ {msg}", text_color="#10b981")
            self.btn_generate.configure(state="normal")
        elif state == "ERROR":
            self.progress_bar.set(0.0)
            self.status_lbl.configure(text=f"❌ {msg}", text_color="#ef4444")
            self.btn_generate.configure(state="normal")

    def upload_voice(self):
        init_dir = DEFAULT_REF_DIR if os.path.isdir(DEFAULT_REF_DIR) else BASE_DIR
        filepath = fd.askopenfilename(
            initialdir=init_dir,
            filetypes=[("Audio Files", "*.mp3 *.wav")],
        )
        if filepath:
            self.reference_audio_path = filepath
            self.lbl_voice.configure(text=f"Archivo activo: {filepath}", text_color="#e5e7eb")
            threading.Thread(
                target=self._upload_voice_thread, args=(filepath,), daemon=True
            ).start()

    def _upload_voice_thread(self, filepath):
        try:
            with open(filepath, "rb") as f:
                files = {"file": (os.path.basename(filepath), f)}
                resp = requests.post(
                    f"{self.api_url}/upload_reference", files=files, timeout=15
                )
            if resp.status_code == 200:
                choices = self._scan_local_ref_files()
                self.after(
                    0,
                    lambda: (
                        self.opt_ref_file.configure(values=choices),
                        self.opt_ref_file.set(os.path.basename(filepath)),
                        self.status_lbl.configure(
                            text=f"✅ Voz de referencia subida y activa: {os.path.basename(filepath)}",
                            text_color="#10b981",
                        ),
                    ),
                )
        except Exception as e:
            print("Error subiendo voz:", e)

    def generate_audio(self):
        text = self.textbox.get("1.0", "end-1c")
        if not text.strip():
            return

        self.is_generating = True
        self.gen_local_start_t = time.time()
        cfg = self.get_current_config()
        if "omnivoice" in cfg.get("model_id", ""):
            self.gen_target_eta_s = max(5, int(cfg.get("num_step", 24) * 0.45))
        else:
            self.gen_target_eta_s = max(4, int((len(text) / 18) * 2))

        self.btn_generate.configure(state="disabled", text="⏳ Generando...")
        self.progress_bar.set(0.08)
        self.status_lbl.configure(
            text=f"⏳ Generando voz ({cfg.get('mode', 'clone').upper()})...", text_color="#f59e0b"
        )
        self.lbl_eta.configure(text=f"ETA 0s / {self.gen_target_eta_s}s")

        threading.Thread(target=self._generate_thread, args=(text, cfg), daemon=True).start()

    def _generate_thread(self, text: str, payload: dict):
        try:
            payload["text"] = text
            # Si el usuario eligió un modelo en el dropdown que aún no es el que está cargado en el backend,
            # verificamos primero y si hace falta lo cargamos automáticamente para que su elección siempre aplique.
            try:
                st_resp = requests.get(f"{self.api_url}/status", timeout=5)
                if st_resp.status_code == 200:
                    st_data = st_resp.json()
                    cur_loaded = st_data.get("loaded_model_id")
                    req_model = payload.get("model_id")
                    if req_model and cur_loaded != req_model:
                        self.after(
                            0,
                            lambda rm=req_model: self.status_lbl.configure(
                                text=f"⏳ Cambiando automáticamente al modelo seleccionado ({rm})...",
                                text_color="#3b82f6",
                            ),
                        )
                        requests.post(
                            f"{self.api_url}/models/load",
                            json={
                                "model_id": req_model,
                                "cpu_threads": payload.get("cpu_threads", 4),
                                "n_ctx": 1024,
                            },
                            timeout=10,
                        )
                        # Esperar hasta que termine de descargar/cargar
                        while True:
                            time.sleep(0.8)
                            w_resp = requests.get(f"{self.api_url}/status", timeout=6)
                            if w_resp.status_code == 200:
                                w_st = w_resp.json().get("status")
                                if w_st == "READY":
                                    break
                                if w_st == "ERROR":
                                    raise RuntimeError(w_resp.json().get("message", "Error cargando modelo"))
                        self.gen_local_start_t = time.time()
            except RuntimeError as re_err:
                raise re_err
            except Exception:
                pass

            resp = requests.post(f"{self.api_url}/tts", json=payload, timeout=360)
            total_gen_s = max(1, int(time.time() - self.gen_local_start_t))
            if resp.status_code == 200:
                audio_resp = requests.get(f"{self.api_url}/download", timeout=30)
                if audio_resp.status_code == 200:
                    if self.mixer_ready and self.is_playing:
                        pygame.mixer.music.stop()
                    with open(self.downloaded_audio, "wb") as f:
                        f.write(audio_resp.content)
                    self.after(0, self._on_audio_ready)
                self.after(
                    0,
                    lambda t=total_gen_s: (
                        self.progress_bar.set(1.0),
                        self.lbl_eta.configure(text=f"Completado en {t}s"),
                        self.status_lbl.configure(
                            text=f"✅ Audio generado con éxito en {t}s y reproduciendo",
                            text_color="#10b981",
                        ),
                    ),
                )
            else:
                try:
                    err_msg = resp.json().get("detail", "Error de generación")
                except Exception:
                    err_msg = "Error de generación"
                self.after(
                    0,
                    lambda m=err_msg: self.status_lbl.configure(
                        text=f"❌ {m}", text_color="#ef4444"
                    ),
                )
        except Exception as e:
            print("Error en generación:", e)
            self.after(
                0,
                lambda err=str(e): self.status_lbl.configure(
                    text=f"❌ Error: {err}", text_color="#ef4444"
                ),
            )
        finally:
            self.is_generating = False
            self.after(
                0,
                lambda: self.btn_generate.configure(
                    state="normal", text="▶ Generar Audio Natural"
                ),
            )

    def _on_audio_ready(self):
        if self._load_audio_metadata(self.downloaded_audio):
            self.toggle_play_pause()


if __name__ == "__main__":
    app = TTSApp()
    app.mainloop()
