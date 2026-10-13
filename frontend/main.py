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


def format_time(seconds: float) -> str:
    seconds = max(0, int(seconds))
    mins = seconds // 60
    secs = seconds % 60
    return f"{mins:02d}:{secs:02d}"


class TTSApp(ctk.CTk):
    def __init__(self):
        super().__init__()
        self.title("Studio TTS LatAm - Zero-Shot Voice Cloning")
        self.geometry("820x820")
        self.minsize(760, 760)

        os.makedirs(PRESETS_DIR, exist_ok=True)

        self.api_url = "http://127.0.0.1:8000"
        self.downloaded_audio = os.path.join(BASE_DIR, "resultado.wav")
        self.reference_audio_path = DEFAULT_REF_FILE

        # Estado del reproductor de audio
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
        self._status_poll_inflight = False

        self._init_audio_mixer()

        # --- ENCABEZADO ---
        self.frame_top = ctk.CTkFrame(self, fg_color="transparent")
        self.frame_top.pack(fill="x", pady=(12, 6), padx=24)

        self.lbl_title = ctk.CTkLabel(
            self.frame_top, text="Studio TTS", font=("Helvetica", 25, "bold")
        )
        self.lbl_title.pack(side="left")
        self.lbl_subtitle = ctk.CTkLabel(
            self.frame_top,
            text="Clonación Zero-Shot & Control Acústico",
            font=("Helvetica", 13),
            text_color="#9ca3af",
        )
        self.lbl_subtitle.pack(side="left", padx=12, pady=(8, 0))

        self.status_lbl = ctk.CTkLabel(
            self.frame_top,
            text="Conectando al backend...",
            text_color="#f59e0b",
            font=("Helvetica", 12, "bold"),
        )
        self.status_lbl.pack(side="right", pady=(6, 0))

        # --- SECCIÓN 1: VOZ DE REFERENCIA (PRE-CARGADA POR DEFECTO) ---
        self.frame_voice = ctk.CTkFrame(self, corner_radius=12)
        self.frame_voice.pack(pady=6, padx=24, fill="x")

        self.frame_voice_header = ctk.CTkFrame(self.frame_voice, fg_color="transparent")
        self.frame_voice_header.pack(fill="x", padx=16, pady=(10, 4))

        self.lbl_voice_title = ctk.CTkLabel(
            self.frame_voice_header,
            text="🎙️ Voz Base de Referencia (Femenina por defecto):",
            font=("Helvetica", 14, "bold"),
        )
        self.lbl_voice_title.pack(side="left")

        self.lbl_f0_badge = ctk.CTkLabel(
            self.frame_voice_header,
            text="F0 Ref: ~202.3 Hz (Femenina)",
            font=("Consolas", 12, "bold"),
            text_color="#34d399",
        )
        self.lbl_f0_badge.pack(side="right")

        # Selector de archivo + Ruta activa + Botones Cargar y Escuchar
        self.frame_voice_row = ctk.CTkFrame(self.frame_voice, fg_color="transparent")
        self.frame_voice_row.pack(fill="x", padx=16, pady=(2, 6))

        ref_choices = self._scan_local_ref_files()
        self.opt_ref_file = ctk.CTkOptionMenu(
            self.frame_voice_row,
            values=ref_choices,
            width=210,
            command=self.on_select_ref_dropdown,
        )
        self.opt_ref_file.set("base_voice.mp3")
        self.opt_ref_file.pack(side="left", padx=(0, 10))

        self.btn_preview_ref = ctk.CTkButton(
            self.frame_voice_row,
            text="🎧 Escuchar Base",
            width=130,
            corner_radius=8,
            fg_color="#374151",
            hover_color="#4b5563",
            command=self.preview_reference_voice,
        )
        self.btn_preview_ref.pack(side="right", padx=(8, 0))

        self.btn_voice = ctk.CTkButton(
            self.frame_voice_row,
            text="📂 Subir MP3/WAV",
            command=self.upload_voice,
            width=140,
            corner_radius=8,
        )
        self.btn_voice.pack(side="right")

        self.lbl_voice = ctk.CTkLabel(
            self.frame_voice,
            text=f"Ruta activa: {self.reference_audio_path}",
            text_color="#9ca3af",
            font=("Consolas", 11),
            anchor="w",
        )
        self.lbl_voice.pack(fill="x", padx=16, pady=(0, 8))

        # --- SECCIÓN 2: PESTAÑAS DE PARÁMETROS + GESTIÓN DE PRESETS ---
        self.frame_presets_bar = ctk.CTkFrame(self, fg_color="transparent")
        self.frame_presets_bar.pack(fill="x", padx=24, pady=(2, 0))

        ctk.CTkLabel(
            self.frame_presets_bar,
            text="Configuración y Parámetros:",
            font=("Helvetica", 14, "bold"),
        ).pack(side="left")

        self.btn_reset_params = ctk.CTkButton(
            self.frame_presets_bar,
            text="↺ Restaurar",
            width=95,
            height=28,
            corner_radius=8,
            fg_color="#374151",
            hover_color="#4b5563",
            command=self.reset_default_params,
        )
        self.btn_reset_params.pack(side="right", padx=(6, 0))

        self.btn_load_preset = ctk.CTkButton(
            self.frame_presets_bar,
            text="📂 Cargar Config",
            width=120,
            height=28,
            corner_radius=8,
            fg_color="#374151",
            hover_color="#4b5563",
            command=self.load_preset_dialog,
        )
        self.btn_load_preset.pack(side="right", padx=6)

        self.btn_save_preset = ctk.CTkButton(
            self.frame_presets_bar,
            text="💾 Guardar Config",
            width=125,
            height=28,
            corner_radius=8,
            fg_color="#374151",
            hover_color="#4b5563",
            command=self.save_preset_dialog,
        )
        self.btn_save_preset.pack(side="right")

        self.tabs = ctk.CTkTabview(self, height=235, corner_radius=12)
        self.tabs.pack(fill="x", padx=24, pady=(4, 6))
        self.tab_clone = self.tabs.add("🎙️ Clonación y Timbre Femenino")
        self.tab_engine = self.tabs.add("⚙️ Motor IA y Muestreo (LLM)")

        self._build_clone_tab()
        self._build_engine_tab()

        # --- SECCIÓN 3: TEXTO A GENERAR ---
        self.lbl_text = ctk.CTkLabel(
            self, text="Texto a convertir en voz:", font=("Helvetica", 14, "bold")
        )
        self.lbl_text.pack(anchor="w", padx=26, pady=(4, 2))
        self.textbox = ctk.CTkTextbox(self, height=110, corner_radius=12, font=("Helvetica", 13))
        self.textbox.pack(pady=4, padx=24, fill="both", expand=True)

        # --- BOTÓN GENERAR + ETA ---
        self.frame_actions = ctk.CTkFrame(self, fg_color="transparent")
        self.frame_actions.pack(fill="x", padx=24, pady=(6, 4))

        self.btn_generate = ctk.CTkButton(
            self.frame_actions,
            text="▶ Generar Audio Clonado",
            font=("Helvetica", 14, "bold"),
            height=40,
            corner_radius=10,
            command=self.generate_audio,
        )
        self.btn_generate.pack(side="left")

        self.lbl_eta = ctk.CTkLabel(
            self.frame_actions,
            text="ETA: --",
            text_color="#9ca3af",
            font=("Helvetica", 13),
        )
        self.lbl_eta.pack(side="left", padx=14)

        # --- SECCIÓN 4: REPRODUCTOR MODERNO (ESTILO MEDIA BAR) ---
        self.frame_player = ctk.CTkFrame(
            self, corner_radius=14, fg_color="#111827", border_width=1, border_color="#1f2937"
        )
        self.frame_player.pack(fill="x", padx=24, pady=(4, 14))

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
        self.seek_slider.pack(fill="x", padx=14, pady=(12, 6))
        self.seek_slider.bind("<ButtonPress-1>", self.on_seek_press)
        self.seek_slider.bind("<ButtonRelease-1>", self.on_seek_release)

        self.frame_controls = ctk.CTkFrame(self.frame_player, fg_color="transparent")
        self.frame_controls.pack(fill="x", padx=14, pady=(0, 10))

        self.btn_play = ctk.CTkButton(
            self.frame_controls,
            text="▶",
            width=40,
            height=40,
            corner_radius=20,
            fg_color="#262f3f",
            hover_color="#374151",
            text_color="#ffffff",
            font=("Helvetica", 16, "bold"),
            command=self.toggle_play_pause,
        )
        self.btn_play.pack(side="left", padx=(0, 8))

        self.btn_mute = ctk.CTkButton(
            self.frame_controls,
            text="🔊",
            width=40,
            height=40,
            corner_radius=20,
            fg_color="#262f3f",
            hover_color="#374151",
            text_color="#ffffff",
            font=("Helvetica", 15),
            command=self.toggle_mute,
        )
        self.btn_mute.pack(side="left", padx=(0, 8))

        self.frame_time_pill = ctk.CTkFrame(
            self.frame_controls,
            corner_radius=18,
            fg_color="#262f3f",
            height=36,
        )
        self.frame_time_pill.pack(side="left", padx=(0, 10))

        self.lbl_time = ctk.CTkLabel(
            self.frame_time_pill,
            text="00:00 / 00:00",
            font=("Consolas", 13, "bold"),
            text_color="#f3f4f6",
        )
        self.lbl_time.pack(padx=14, pady=6)

        self.slider_vol = ctk.CTkSlider(
            self.frame_controls,
            from_=0.0,
            to=1.0,
            width=90,
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
            width=110,
            height=34,
            corner_radius=17,
            fg_color="#262f3f",
            hover_color="#374151",
            font=("Helvetica", 12, "bold"),
            command=self.save_audio_copy,
        )
        self.btn_save.pack(side="right")

        if os.path.exists(self.downloaded_audio):
            self._load_audio_metadata(self.downloaded_audio)

        self.check_backend_status()
        self._update_player_loop()

    def _scan_local_ref_files(self) -> list[str]:
        items = ["base_voice.mp3"]
        if os.path.isdir(DEFAULT_REF_DIR):
            for f in sorted(os.listdir(DEFAULT_REF_DIR)):
                if f.lower().endswith((".mp3", ".wav")) and f not in items:
                    items.append(f)
        return items

    def _build_clone_tab(self):
        self.tab_clone.grid_columnconfigure(1, weight=1)
        self.tab_clone.grid_columnconfigure(3, weight=1)

        # Switch Auto-Clonar + Selector Voz Guía
        self.sw_autoclone = ctk.CTkSwitch(
            self.tab_clone,
            text="Auto-Clonar Tono/Timbre de Voz Base",
            font=("Helvetica", 12, "bold"),
        )
        self.sw_autoclone.select()
        self.sw_autoclone.grid(row=0, column=0, columnspan=2, padx=10, pady=(6, 6), sticky="w")

        ctk.CTkLabel(self.tab_clone, text="Voz Guía IA:", anchor="w").grid(
            row=0, column=2, padx=10, pady=(6, 6), sticky="w"
        )
        self.opt_speaker = ctk.CTkOptionMenu(
            self.tab_clone,
            values=["maria", "lucia", "sofia", "carmen", "tara", "javi", "ninguna"],
            width=140,
        )
        self.opt_speaker.set("maria")
        self.opt_speaker.grid(row=0, column=3, padx=10, pady=(6, 6), sticky="ew")

        # Pitch Offset Manual (Semitonos)
        self.lbl_pitch = ctk.CTkLabel(
            self.tab_clone, text="Ajuste Tono: +0.0 st", width=155, anchor="w"
        )
        self.lbl_pitch.grid(row=1, column=0, padx=10, pady=4, sticky="w")
        self.slider_pitch = ctk.CTkSlider(
            self.tab_clone,
            from_=-12.0,
            to=12.0,
            number_of_steps=48,
            command=lambda v: self.lbl_pitch.configure(text=f"Ajuste Tono: {float(v):+.1f} st"),
        )
        self.slider_pitch.set(0.0)
        self.slider_pitch.grid(row=1, column=1, padx=10, pady=4, sticky="ew")

        # Formantes (Tracto Vocal)
        self.lbl_formant = ctk.CTkLabel(
            self.tab_clone, text="Formantes (Femenino): 1.18", width=175, anchor="w"
        )
        self.lbl_formant.grid(row=1, column=2, padx=10, pady=4, sticky="w")
        self.slider_formant = ctk.CTkSlider(
            self.tab_clone,
            from_=0.75,
            to=1.45,
            number_of_steps=70,
            command=lambda v: self.lbl_formant.configure(
                text=f"Formantes (Femenino): {float(v):.2f}"
            ),
        )
        self.slider_formant.set(1.18)
        self.slider_formant.grid(row=1, column=3, padx=10, pady=4, sticky="ew")

        # Fuerza de Timbre Espectral + Segundos de Referencia Zero-Shot
        self.lbl_timbre = ctk.CTkLabel(
            self.tab_clone, text="Fuerza Timbre Ref: 0.60", width=155, anchor="w"
        )
        self.lbl_timbre.grid(row=2, column=0, padx=10, pady=4, sticky="w")
        self.slider_timbre = ctk.CTkSlider(
            self.tab_clone,
            from_=0.0,
            to=1.0,
            number_of_steps=50,
            command=lambda v: self.lbl_timbre.configure(
                text=f"Fuerza Timbre Ref: {float(v):.2f}"
            ),
        )
        self.slider_timbre.set(0.60)
        self.slider_timbre.grid(row=2, column=1, padx=10, pady=4, sticky="ew")

        self.lbl_refdur = ctk.CTkLabel(
            self.tab_clone, text="Ventana Ref Zero-Shot: 2.5s", width=175, anchor="w"
        )
        self.lbl_refdur.grid(row=2, column=2, padx=10, pady=4, sticky="w")
        self.slider_refdur = ctk.CTkSlider(
            self.tab_clone,
            from_=0.5,
            to=5.0,
            number_of_steps=45,
            command=lambda v: self.lbl_refdur.configure(
                text=f"Ventana Ref Zero-Shot: {float(v):.1f}s"
            ),
        )
        self.slider_refdur.set(2.5)
        self.slider_refdur.grid(row=2, column=3, padx=10, pady=4, sticky="ew")

        # Transcripción opcional del audio de referencia
        ctk.CTkLabel(
            self.tab_clone, text="Texto Ref (opcional):", anchor="w"
        ).grid(row=3, column=0, padx=10, pady=(6, 4), sticky="w")
        self.entry_reftext = ctk.CTkEntry(
            self.tab_clone,
            placeholder_text="Ej: Hola, bienvenidos a un nuevo capítulo de nuestra historia...",
        )
        self.entry_reftext.grid(
            row=3, column=1, columnspan=3, padx=10, pady=(6, 4), sticky="ew"
        )

    def _build_engine_tab(self):
        self.tab_engine.grid_columnconfigure(1, weight=1)
        self.tab_engine.grid_columnconfigure(3, weight=1)

        # Velocidad + Temperatura
        self.lbl_speed = ctk.CTkLabel(
            self.tab_engine, text="Velocidad: 1.00x", width=155, anchor="w"
        )
        self.lbl_speed.grid(row=0, column=0, padx=10, pady=6, sticky="w")
        self.slider_speed = ctk.CTkSlider(
            self.tab_engine,
            from_=0.5,
            to=2.0,
            number_of_steps=60,
            command=lambda v: self.lbl_speed.configure(text=f"Velocidad: {float(v):.2f}x"),
        )
        self.slider_speed.set(1.0)
        self.slider_speed.grid(row=0, column=1, padx=10, pady=6, sticky="ew")

        self.lbl_temp = ctk.CTkLabel(
            self.tab_engine, text="Expresividad (Temp): 0.65", width=175, anchor="w"
        )
        self.lbl_temp.grid(row=0, column=2, padx=10, pady=6, sticky="w")
        self.slider_temp = ctk.CTkSlider(
            self.tab_engine,
            from_=0.1,
            to=1.5,
            number_of_steps=70,
            command=lambda v: self.lbl_temp.configure(
                text=f"Expresividad (Temp): {float(v):.2f}"
            ),
        )
        self.slider_temp.set(0.65)
        self.slider_temp.grid(row=0, column=3, padx=10, pady=6, sticky="ew")

        # Top-K + Top-P
        self.lbl_topk = ctk.CTkLabel(
            self.tab_engine, text="Top-K: 50", width=155, anchor="w"
        )
        self.lbl_topk.grid(row=1, column=0, padx=10, pady=6, sticky="w")
        self.slider_topk = ctk.CTkSlider(
            self.tab_engine,
            from_=1,
            to=100,
            number_of_steps=99,
            command=lambda v: self.lbl_topk.configure(text=f"Top-K: {int(v)}"),
        )
        self.slider_topk.set(50)
        self.slider_topk.grid(row=1, column=1, padx=10, pady=6, sticky="ew")

        self.lbl_topp = ctk.CTkLabel(
            self.tab_engine, text="Top-P (Nucleus): 0.90", width=175, anchor="w"
        )
        self.lbl_topp.grid(row=1, column=2, padx=10, pady=6, sticky="w")
        self.slider_topp = ctk.CTkSlider(
            self.tab_engine,
            from_=0.10,
            to=1.00,
            number_of_steps=45,
            command=lambda v: self.lbl_topp.configure(
                text=f"Top-P (Nucleus): {float(v):.2f}"
            ),
        )
        self.slider_topp.set(0.90)
        self.slider_topp.grid(row=1, column=3, padx=10, pady=6, sticky="ew")

        # Repeat Penalty + Max Audio Tokens
        self.lbl_reppen = ctk.CTkLabel(
            self.tab_engine, text="Penaliz. Repetición: 1.12", width=155, anchor="w"
        )
        self.lbl_reppen.grid(row=2, column=0, padx=10, pady=6, sticky="w")
        self.slider_reppen = ctk.CTkSlider(
            self.tab_engine,
            from_=1.00,
            to=1.50,
            number_of_steps=50,
            command=lambda v: self.lbl_reppen.configure(
                text=f"Penaliz. Repetición: {float(v):.2f}"
            ),
        )
        self.slider_reppen.set(1.12)
        self.slider_reppen.grid(row=2, column=1, padx=10, pady=6, sticky="ew")

        self.lbl_maxtok = ctk.CTkLabel(
            self.tab_engine, text="Máx. Tokens Audio: 840", width=175, anchor="w"
        )
        self.lbl_maxtok.grid(row=2, column=2, padx=10, pady=6, sticky="w")
        self.slider_maxtok = ctk.CTkSlider(
            self.tab_engine,
            from_=140,
            to=2030,
            number_of_steps=270,
            command=lambda v: self.lbl_maxtok.configure(
                text=f"Máx. Tokens Audio: {int(v)}"
            ),
        )
        self.slider_maxtok.set(840)
        self.slider_maxtok.grid(row=2, column=3, padx=10, pady=6, sticky="ew")

        # Seed
        ctk.CTkLabel(
            self.tab_engine, text="Semilla (Seed, -1 = aleatoria):", anchor="w"
        ).grid(row=3, column=0, padx=10, pady=6, sticky="w")
        self.entry_seed = ctk.CTkEntry(self.tab_engine, width=120)
        self.entry_seed.insert(0, "-1")
        self.entry_seed.grid(row=3, column=1, padx=10, pady=6, sticky="w")

    def get_current_config(self) -> dict:
        try:
            seed_val = int(self.entry_seed.get().strip())
        except Exception:
            seed_val = -1
        return {
            "reference_file": self.reference_audio_path,
            "reference_text": self.entry_reftext.get().strip(),
            "ref_duration": round(float(self.slider_refdur.get()), 2),
            "speaker_hint": self.opt_speaker.get(),
            "auto_clone_voice": bool(self.sw_autoclone.get()),
            "pitch_semitones": round(float(self.slider_pitch.get()), 2),
            "formant_shift": round(float(self.slider_formant.get()), 2),
            "timbre_strength": round(float(self.slider_timbre.get()), 2),
            "speed": round(float(self.slider_speed.get()), 2),
            "temperature": round(float(self.slider_temp.get()), 2),
            "top_k": int(self.slider_topk.get()),
            "top_p": round(float(self.slider_topp.get()), 2),
            "repeat_penalty": round(float(self.slider_reppen.get()), 2),
            "max_audio_tokens": int(self.slider_maxtok.get()),
            "seed": seed_val,
        }

    def apply_config_dict(self, cfg: dict):
        ref_f = cfg.get("reference_file", DEFAULT_REF_FILE)
        if ref_f:
            self.reference_audio_path = ref_f
            self.lbl_voice.configure(text=f"Ruta activa: {ref_f}")
            base_n = os.path.basename(ref_f)
            if base_n in self.opt_ref_file.cget("values"):
                self.opt_ref_file.set(base_n)

        if "auto_clone_voice" in cfg:
            if cfg["auto_clone_voice"]:
                self.sw_autoclone.select()
            else:
                self.sw_autoclone.deselect()

        if "speaker_hint" in cfg:
            self.opt_speaker.set(str(cfg["speaker_hint"]))

        if "pitch_semitones" in cfg:
            v = float(cfg["pitch_semitones"])
            self.slider_pitch.set(v)
            self.lbl_pitch.configure(text=f"Ajuste Tono: {v:+.1f} st")

        if "formant_shift" in cfg:
            v = float(cfg["formant_shift"])
            self.slider_formant.set(v)
            self.lbl_formant.configure(text=f"Formantes (Femenino): {v:.2f}")

        if "timbre_strength" in cfg:
            v = float(cfg["timbre_strength"])
            self.slider_timbre.set(v)
            self.lbl_timbre.configure(text=f"Fuerza Timbre Ref: {v:.2f}")

        if "ref_duration" in cfg:
            v = float(cfg["ref_duration"])
            self.slider_refdur.set(v)
            self.lbl_refdur.configure(text=f"Ventana Ref Zero-Shot: {v:.1f}s")

        if "reference_text" in cfg:
            self.entry_reftext.delete(0, "end")
            self.entry_reftext.insert(0, str(cfg["reference_text"]))

        if "speed" in cfg:
            v = float(cfg["speed"])
            self.slider_speed.set(v)
            self.lbl_speed.configure(text=f"Velocidad: {v:.2f}x")

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

    def reset_default_params(self):
        self.apply_config_dict({
            "reference_file": DEFAULT_REF_FILE,
            "reference_text": "",
            "ref_duration": 2.5,
            "speaker_hint": "maria",
            "auto_clone_voice": True,
            "pitch_semitones": 0.0,
            "formant_shift": 1.18,
            "timbre_strength": 0.60,
            "speed": 1.0,
            "temperature": 0.65,
            "top_k": 50,
            "top_p": 0.90,
            "repeat_penalty": 1.12,
            "max_audio_tokens": 840,
            "seed": -1,
        })
        self.status_lbl.configure(text="✅ Parámetros restaurados", text_color="#10b981")

    def save_preset_dialog(self):
        dest = fd.asksaveasfilename(
            initialdir=PRESETS_DIR,
            defaultextension=".json",
            filetypes=[("Preset JSON", "*.json")],
            initialfile="voz_femenina_preset.json",
        )
        if dest:
            with open(dest, "w", encoding="utf-8") as f:
                json.dump(self.get_current_config(), f, indent=2, ensure_ascii=False)
            self.status_lbl.configure(text="💾 Configuración guardada", text_color="#10b981")

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
                self.status_lbl.configure(text="📂 Configuración cargada", text_color="#10b981")
            except Exception as e:
                self.status_lbl.configure(text=f"❌ Error preset: {e}", text_color="#ef4444")

    def on_select_ref_dropdown(self, filename: str):
        candidate = os.path.join(DEFAULT_REF_DIR, filename)
        if os.path.exists(candidate):
            self.reference_audio_path = candidate
            self.lbl_voice.configure(text=f"Ruta activa: {candidate}")
            self.status_lbl.configure(text=f"✅ Voz base: {filename}", text_color="#10b981")

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
                        text="🎧 Reproduciendo voz de referencia base", text_color="#3b82f6"
                    ),
                )
        except Exception as e:
            print("Error previsualizando voz base:", e)

    def _init_audio_mixer(self):
        try:
            pygame.mixer.init(frequency=24000, size=-16, channels=1, buffer=1024)
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
                pygame.mixer.music.pause()
                self.play_offset = self._get_current_pos()
                self.is_paused = True
                self.btn_play.configure(text="▶")
            elif self.is_playing and self.is_paused:
                pygame.mixer.music.unpause()
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
            self.play_offset = max(0.0, min(self.audio_duration - 0.1, pct * self.audio_duration))
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
        self.after(100, self._update_player_loop)

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
            self.status_lbl.configure(text="✅ Audio guardado", text_color="#10b981")

    def check_backend_status(self):
        if not self._status_poll_inflight:
            self._status_poll_inflight = True
            threading.Thread(target=self._poll_status_worker, daemon=True).start()
        self.after(2000, self.check_backend_status)

    def _poll_status_worker(self):
        try:
            resp = requests.get(f"{self.api_url}/status", timeout=8)
            if resp.status_code == 200:
                data = resp.json()
                self.after(0, lambda d=data: self._apply_backend_status(d))
            else:
                if not self.is_generating:
                    self.after(
                        0,
                        lambda: self.status_lbl.configure(
                            text="Conectando al backend...", text_color="#f59e0b"
                        ),
                    )
        except Exception:
            if not self.is_generating:
                self.after(
                    0,
                    lambda: self.status_lbl.configure(
                        text="Backend offline. Esperando...", text_color="#ef4444"
                    ),
                )
        finally:
            self._status_poll_inflight = False

    def _apply_backend_status(self, data: dict):
        state = data.get("status")
        msg = data.get("message", "")
        f0 = data.get("reference_f0_hz", 0.0)
        if f0 and float(f0) > 50:
            gender_tag = "Femenina" if float(f0) >= 165.0 else "Masculina"
            self.lbl_f0_badge.configure(text=f"F0 Ref: ~{float(f0):.1f} Hz ({gender_tag})")

        if self.is_generating or state == "GENERATING":
            self.status_lbl.configure(text="⏳ Clonando voz y generando...", text_color="#f59e0b")
            self.btn_generate.configure(state="disabled")
        elif state == "DOWNLOADING":
            self.status_lbl.configure(text=f"⏳ {msg}", text_color="#3b82f6")
            self.btn_generate.configure(state="disabled")
        elif state == "LOADING":
            self.status_lbl.configure(text=f"🧠 {msg}", text_color="#f59e0b")
            self.btn_generate.configure(state="disabled")
        elif state in ["READY", "SIMULATION"]:
            self.status_lbl.configure(text=f"✅ {msg}", text_color="#10b981")
            self.btn_generate.configure(state="normal")
        elif state == "ERROR":
            self.status_lbl.configure(text=f"❌ {msg}", text_color="#ef4444")
            self.btn_generate.configure(state="disabled")

    def upload_voice(self):
        init_dir = DEFAULT_REF_DIR if os.path.isdir(DEFAULT_REF_DIR) else BASE_DIR
        filepath = fd.askopenfilename(
            initialdir=init_dir,
            filetypes=[("Audio Files", "*.mp3 *.wav")],
        )
        if filepath:
            self.reference_audio_path = filepath
            self.lbl_voice.configure(text=f"Ruta activa: {filepath}", text_color="#e5e7eb")
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
                info = resp.json()
                f0 = info.get("reference_f0_hz", 0.0)
                choices = self._scan_local_ref_files()
                self.after(
                    0,
                    lambda: (
                        self.opt_ref_file.configure(values=choices),
                        self.opt_ref_file.set(os.path.basename(filepath)),
                        self.status_lbl.configure(
                            text=f"✅ Voz cargada ({f0} Hz)", text_color="#10b981"
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
        self.btn_generate.configure(state="disabled", text="⏳ Clonando y Generando...")
        self.status_lbl.configure(text="⏳ Clonando voz y generando...", text_color="#f59e0b")
        eta_segs = max(5, int((len(text) / 22) * 2))
        self.lbl_eta.configure(text=f"ETA: ~{eta_segs}s")

        threading.Thread(target=self._generate_thread, args=(text,), daemon=True).start()

    def _generate_thread(self, text):
        try:
            payload = self.get_current_config()
            payload["text"] = text
            resp = requests.post(f"{self.api_url}/tts", json=payload, timeout=300)
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
                    lambda: self.status_lbl.configure(
                        text="✅ Voz Femenina Clonada y Reproduciendo", text_color="#10b981"
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
                lambda: self.status_lbl.configure(
                    text="❌ Error comunicando con el backend", text_color="#ef4444"
                ),
            )
        finally:
            self.is_generating = False
            self.after(
                0,
                lambda: (
                    self.btn_generate.configure(
                        state="normal", text="▶ Generar Audio Clonado"
                    ),
                    self.lbl_eta.configure(text="ETA: --"),
                ),
            )

    def _on_audio_ready(self):
        if self._load_audio_metadata(self.downloaded_audio):
            self.toggle_play_pause()


if __name__ == "__main__":
    app = TTSApp()
    app.mainloop()
