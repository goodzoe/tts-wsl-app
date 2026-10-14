"""Ventana principal de Studio TTS LatAm (CustomTkinter) con diseño responsive, historial persistente de alertas y soporte GPU."""

import os
import json
import time
import shutil
import threading
import tkinter.filedialog as fd
import requests
import customtkinter as ctk

import constants as const
from constants import (
    BASE_DIR,
    PRESETS_DIR,
    DEFAULT_REF_DIR,
    DEFAULT_REF_FILE,
    DEFAULT_MODELS_DIR,
    LANGUAGE_CHOICES,
    MODE_UI_TO_API,
    MODE_API_TO_UI,
    DEFAULT_PRESET_VALUES,
    load_local_transcripts,
    scan_local_ref_files,
    format_time,
)
from audio_player import AudioPlayerController
from ui_tabs import build_voice_tab, build_engine_tab

ctk.set_appearance_mode("Dark")
ctk.set_default_color_theme("blue")


class TTSApp(ctk.CTk):
    def __init__(self):
        super().__init__()
        self.title("Studio TTS LatAm - Clonación Zero-Shot GPU (OmniVoice) & Modelos Locales")
        self.geometry("980x900")
        self.minsize(760, 680)

        self.api_url = "http://127.0.0.1:8000"
        self.downloaded_audio = os.path.join(BASE_DIR, "resultado.wav")
        self.reference_audio_path = DEFAULT_REF_FILE
        self.transcripts_cache = load_local_transcripts()

        self.player = AudioPlayerController()
        self.user_dragging_seek = False
        self.is_generating = False
        self.gen_local_start_t = 0.0
        self.gen_target_eta_s = 0
        self._status_poll_inflight = False
        self._models_synced_once = False
        self._last_wrap_w = 0

        # Protección para que los errores en rojo NUNCA desaparezcan solos antes de ser leídos:
        self._sticky_error_msg = ""
        self._sticky_error_until = 0.0

        # Layout principal en 3 zonas:
        # 1. Zona superior fija (Encabezado + Estado + Caja persistente de Errores/Alertas)
        # 2. Zona central scrollable (Modelos + Modos + Pestañas + Texto)
        # 3. Zona inferior fija (Botón Generar + ETA + Reproductor de Audio)
        self._build_top_header()
        self._build_bottom_bar()
        self._build_scrollable_center()

        self.bind("<Configure>", self._on_window_resize)

        if os.path.exists(self.downloaded_audio):
            self._refresh_player_metadata(self.downloaded_audio)

        self.sync_models_from_backend()
        self.check_backend_status()
        self._update_ui_loop()

    def _build_top_header(self):
        self.frame_top = ctk.CTkFrame(self, fg_color="transparent")
        self.frame_top.pack(side="top", fill="x", pady=(8, 2), padx=18)

        row_title = ctk.CTkFrame(self.frame_top, fg_color="transparent")
        row_title.pack(fill="x")

        self.lbl_title = ctk.CTkLabel(
            row_title, text="Studio TTS LatAm ⚡", font=("Helvetica", 22, "bold")
        )
        self.lbl_title.pack(side="left")

        self.lbl_ram = ctk.CTkLabel(
            row_title,
            text="GPU: -- | RAM App: -- MB | Sistema: -- GB",
            font=("Consolas", 11, "bold"),
            text_color="#60a5fa",
        )
        self.lbl_ram.pack(side="right", pady=(4, 0))

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
            wraplength=880,
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

        # Banner Push Transitorio (auto-desaparece en ~8s) para avisos de compatibilidad de modelos
        self.frame_toast_box = ctk.CTkFrame(
            self.frame_top, corner_radius=8, fg_color="#1e293b", border_width=1, border_color="#f59e0b"
        )
        self.lbl_toast = ctk.CTkLabel(
            self.frame_toast_box,
            text="",
            text_color="#fde68a",
            font=("Helvetica", 11, "bold"),
            anchor="w",
            justify="left",
            wraplength=820,
        )
        self.lbl_toast.pack(side="left", fill="x", expand=True, padx=(10, 4), pady=5)
        self.btn_close_toast = ctk.CTkButton(
            self.frame_toast_box,
            text="✖",
            width=28,
            height=22,
            corner_radius=6,
            fg_color="#334155",
            hover_color="#475569",
            font=("Helvetica", 11, "bold"),
            command=self.hide_transient_toast,
        )
        self.btn_close_toast.pack(side="right", padx=(2, 8), pady=4)
        self._toast_after_id = None

        # Banner de Error Persistente (copiable y con botón Cerrar, para que jamás desaparezca sin leerlo)
        self.frame_error_box = ctk.CTkFrame(
            self.frame_top, corner_radius=8, fg_color="#450a0a", border_width=1, border_color="#dc2626"
        )
        self.entry_error_log = ctk.CTkEntry(
            self.frame_error_box,
            fg_color="#450a0a",
            border_width=0,
            text_color="#fecaca",
            font=("Consolas", 11, "bold"),
            height=26,
        )
        self.entry_error_log.pack(side="left", fill="x", expand=True, padx=(10, 4), pady=4)

        self.btn_copy_error = ctk.CTkButton(
            self.frame_error_box,
            text="📋 Copiar",
            width=72,
            height=24,
            corner_radius=6,
            fg_color="#7f1d1d",
            hover_color="#991b1b",
            font=("Helvetica", 11, "bold"),
            command=self._copy_error_to_clipboard,
        )
        self.btn_copy_error.pack(side="right", padx=3, pady=4)

        self.btn_clear_error = ctk.CTkButton(
            self.frame_error_box,
            text="✖ Ocultar",
            width=72,
            height=24,
            corner_radius=6,
            fg_color="#991b1b",
            hover_color="#b91c1c",
            font=("Helvetica", 11, "bold"),
            command=self.clear_sticky_error,
        )
        self.btn_clear_error.pack(side="right", padx=(3, 8), pady=4)

    def show_sticky_error(self, message: str):
        """Muestra un error en rojo que NO es borrado por el polling de /status hasta que el usuario lo cierre o genere de nuevo."""
        clean_msg = str(message).strip()
        self._sticky_error_msg = clean_msg
        self._sticky_error_until = time.time() + 180.0
        self.status_lbl.configure(text=f"❌ {clean_msg}", text_color="#ef4444")
        self.entry_error_log.configure(state="normal")
        self.entry_error_log.delete(0, "end")
        self.entry_error_log.insert(0, f"Último error registrado: {clean_msg}")
        self.entry_error_log.configure(state="readonly")
        self.frame_error_box.pack(fill="x", pady=(2, 2))

    def clear_sticky_error(self):
        self._sticky_error_msg = ""
        self._sticky_error_until = 0.0
        self.frame_error_box.pack_forget()

    def _copy_error_to_clipboard(self):
        if self._sticky_error_msg:
            self.clipboard_clear()
            self.clipboard_append(self._sticky_error_msg)
            self.btn_copy_error.configure(text="✅ Copiado")
            self.after(1500, lambda: self.btn_copy_error.configure(text="📋 Copiar"))

    def _build_scrollable_center(self):
        self.main_scroll = ctk.CTkScrollableFrame(self, fg_color="transparent")
        self.main_scroll.pack(side="top", fill="both", expand=True, padx=10, pady=2)

        # --- SECCIÓN 0: GESTOR DE MODELOS IA Y MEMORIA (GRID RESPONSIVE) ---
        self.frame_models = ctk.CTkFrame(self.main_scroll, corner_radius=12)
        self.frame_models.pack(pady=4, padx=8, fill="x")
        self.frame_models.grid_columnconfigure(0, weight=1)

        frame_models_top = ctk.CTkFrame(self.frame_models, fg_color="transparent")
        frame_models_top.grid(row=0, column=0, padx=12, pady=(6, 2), sticky="ew")
        frame_models_top.grid_columnconfigure(0, weight=1)

        self.lbl_models_header = ctk.CTkLabel(
            frame_models_top,
            text="🧠 Modelo IA Activo y Gestión de Memoria (OmniVoice GPU clona voz / diseña voz / TTS):",
            font=("Helvetica", 12, "bold"),
            anchor="w",
            justify="left",
        )
        self.lbl_models_header.grid(row=0, column=0, sticky="ew")

        self.lbl_loaded_model = ctk.CTkLabel(
            frame_models_top,
            text="Activo: Verificando...",
            font=("Consolas", 11, "bold"),
            text_color="#34d399",
            anchor="e",
            justify="right",
        )
        self.lbl_loaded_model.grid(row=0, column=1, padx=(8, 0), sticky="e")

        frame_models_row = ctk.CTkFrame(self.frame_models, fg_color="transparent")
        frame_models_row.grid(row=1, column=0, padx=12, pady=(2, 8), sticky="ew")
        frame_models_row.grid_columnconfigure(0, weight=1)

        self.opt_model = ctk.CTkOptionMenu(
            frame_models_row,
            values=list(const.MODEL_LABELS_TO_ID.keys()),
            dynamic_resizing=False,
            command=self.on_model_select_change,
        )
        self.opt_model.set("OmniVoice Zero-Shot 0.6B (Clonación Real + Diseño de Voz - 1.5 GB)")
        self.opt_model.grid(row=0, column=0, padx=(0, 6), pady=2, sticky="ew")

        self.btn_load_model = ctk.CTkButton(
            frame_models_row,
            text="⚡ Cargar Modelo",
            width=126,
            height=30,
            corner_radius=8,
            fg_color="#2563eb",
            hover_color="#1d4ed8",
            font=("Helvetica", 12, "bold"),
            command=self.load_selected_model,
        )
        self.btn_load_model.grid(row=0, column=1, padx=3, pady=2)

        self.btn_add_local_dir = ctk.CTkButton(
            frame_models_row,
            text="📁 Carpeta Modelo",
            width=126,
            height=30,
            corner_radius=8,
            fg_color="#374151",
            hover_color="#4b5563",
            font=("Helvetica", 11, "bold"),
            command=self.browse_and_add_local_folder,
        )
        self.btn_add_local_dir.grid(row=0, column=2, padx=3, pady=2)

        self.btn_add_local_file = ctk.CTkButton(
            frame_models_row,
            text="➕ Archivo .GGUF",
            width=122,
            height=30,
            corner_radius=8,
            fg_color="#374151",
            hover_color="#4b5563",
            font=("Helvetica", 11, "bold"),
            command=self.browse_and_add_local_gguf,
        )
        self.btn_add_local_file.grid(row=0, column=3, padx=3, pady=2)

        self.btn_unload_model = ctk.CTkButton(
            frame_models_row,
            text="🧹 Liberar RAM",
            width=116,
            height=30,
            corner_radius=8,
            fg_color="#b91c1c",
            hover_color="#991b1b",
            font=("Helvetica", 12, "bold"),
            command=self.unload_model_from_ram,
        )
        self.btn_unload_model.grid(row=0, column=4, padx=(3, 0), pady=2)

        # --- SECCIÓN 1: MODO DE OPERACIÓN + PRESETS + RESTABLECER (GRID RESPONSIVE) ---
        frame_mode_bar = ctk.CTkFrame(self.main_scroll, fg_color="transparent")
        frame_mode_bar.pack(fill="x", padx=8, pady=(4, 2))
        frame_mode_bar.grid_columnconfigure(1, weight=1)

        ctk.CTkLabel(
            frame_mode_bar,
            text="Modo:",
            font=("Helvetica", 13, "bold"),
        ).grid(row=0, column=0, padx=(0, 6), pady=2, sticky="w")

        self.seg_mode = ctk.CTkSegmentedButton(
            frame_mode_bar,
            values=list(MODE_UI_TO_API.keys()),
            font=("Helvetica", 12, "bold"),
            selected_color="#2563eb",
            selected_hover_color="#1d4ed8",
            command=self.on_mode_change,
        )
        self.seg_mode.set("🎙️ Clonación de Voz (Audio Base)")
        self.seg_mode.grid(row=0, column=1, padx=(0, 8), pady=2, sticky="w")

        self.btn_save_preset = ctk.CTkButton(
            frame_mode_bar,
            text="💾 Guardar Config",
            width=115,
            height=28,
            corner_radius=8,
            fg_color="#374151",
            hover_color="#4b5563",
            font=("Helvetica", 11, "bold"),
            command=self.save_preset_dialog,
        )
        self.btn_save_preset.grid(row=0, column=2, padx=3, pady=2)

        self.btn_load_preset = ctk.CTkButton(
            frame_mode_bar,
            text="📂 Cargar Config",
            width=112,
            height=28,
            corner_radius=8,
            fg_color="#374151",
            hover_color="#4b5563",
            font=("Helvetica", 11, "bold"),
            command=self.load_preset_dialog,
        )
        self.btn_load_preset.grid(row=0, column=3, padx=3, pady=2)

        self.btn_reset_params = ctk.CTkButton(
            frame_mode_bar,
            text="↺ Restablecer",
            width=110,
            height=28,
            corner_radius=8,
            fg_color="#d97706",
            hover_color="#b45309",
            text_color="#ffffff",
            font=("Helvetica", 12, "bold"),
            command=self.reset_default_params,
        )
        self.btn_reset_params.grid(row=0, column=4, padx=(3, 0), pady=2)

        self.lbl_ux_hint = ctk.CTkLabel(
            self.main_scroll,
            text="💡 Ambas pestañas suman sus ajustes al generar: Pestaña 1 define Voz/Clonación/Estilo y Pestaña 2 controla el Motor IA (GPU/CPU) y Tono/Velocidad.",
            text_color="#9ca3af",
            font=("Helvetica", 11),
            anchor="w",
            justify="left",
            wraplength=880,
        )
        self.lbl_ux_hint.pack(fill="x", padx=10, pady=(0, 2))

        # --- SECCIÓN 2: PESTAÑAS DE PARÁMETROS ---
        self.tabs = ctk.CTkTabview(self.main_scroll, height=305, corner_radius=12)
        self.tabs.pack(fill="x", padx=8, pady=(0, 4))
        self.tab_voice = self.tabs.add("🎙️ 1. Voz, Clonación y Estilo (Activo)")
        self.tab_engine = self.tabs.add("⚙️ 2. Motor IA, Difusión, LLM y DSP (Activo)")

        build_voice_tab(self, self.tab_voice)
        build_engine_tab(self, self.tab_engine)

        # --- SECCIÓN 3: TEXTO A CONVERTIR EN VOZ ---
        self.lbl_text = ctk.CTkLabel(
            self.main_scroll, text="Texto a convertir en voz:", font=("Helvetica", 13, "bold")
        )
        self.lbl_text.pack(anchor="w", padx=10, pady=(2, 2))
        self.textbox = ctk.CTkTextbox(
            self.main_scroll, height=110, corner_radius=12, font=("Helvetica", 13), wrap="word"
        )
        self.textbox.pack(pady=2, padx=8, fill="both", expand=True)
        self.textbox.insert(
            "1.0",
            "Hola, esta es una prueba de clonación de voz natural y expresiva en español acelerada por GPU.",
        )

    def _build_bottom_bar(self):
        self.frame_bottom = ctk.CTkFrame(self, fg_color="transparent")
        self.frame_bottom.pack(side="bottom", fill="x", padx=18, pady=(2, 10))

        self.frame_actions = ctk.CTkFrame(self.frame_bottom, fg_color="transparent")
        self.frame_actions.pack(fill="x", pady=(2, 4))

        self.btn_generate = ctk.CTkButton(
            self.frame_actions,
            text="▶ Generar Audio Natural",
            font=("Helvetica", 14, "bold"),
            width=210,
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
            width=145,
            height=34,
            corner_radius=8,
            fg_color="#374151",
            hover_color="#d97706",
            font=("Helvetica", 12, "bold"),
            command=self.reset_default_params,
        )
        self.btn_reset_bottom.pack(side="right")

        # Reproductor de Audio
        self.frame_player = ctk.CTkFrame(
            self.frame_bottom, corner_radius=14, fg_color="#111827", border_width=1, border_color="#1f2937"
        )
        self.frame_player.pack(fill="x", pady=(2, 0))

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
            self.frame_controls, corner_radius=18, fg_color="#262f3f", height=32
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
        self.slider_vol.set(self.player.volume)
        self.slider_vol.pack(side="left", padx=6)

        self.btn_save = ctk.CTkButton(
            self.frame_controls,
            text="⬇ Guardar WAV",
            width=120,
            height=32,
            corner_radius=16,
            fg_color="#262f3f",
            hover_color="#374151",
            font=("Helvetica", 12, "bold"),
            command=self.save_audio_copy,
        )
        self.btn_save.pack(side="right")

    def _on_window_resize(self, event):
        if event.widget == self:
            new_w = max(460, event.width - 75)
            if abs(new_w - self._last_wrap_w) < 12:
                return
            self._last_wrap_w = new_w
            try:
                self.status_lbl.configure(wraplength=new_w)
                self.lbl_ux_hint.configure(wraplength=new_w - 15)
                self.lbl_voice.configure(wraplength=new_w - 40)
                self.lbl_mode_desc.configure(wraplength=new_w - 40)
                self.lbl_models_header.configure(wraplength=max(320, int(new_w * 0.58)))
                self.lbl_loaded_model.configure(wraplength=max(200, int(new_w * 0.38)))
            except Exception:
                pass

    def show_transient_toast(self, message: str, duration_ms: int = 8500):
        """Muestra una notificación push transitoria que desaparece sola tras unos segundos sin bloquear al usuario."""
        if self._toast_after_id:
            try:
                self.after_cancel(self._toast_after_id)
            except Exception:
                pass
        self.lbl_toast.configure(text=f"🔔 {message}")
        self.frame_toast_box.pack(fill="x", pady=(2, 2))
        self._toast_after_id = self.after(duration_ms, self.hide_transient_toast)

    def hide_transient_toast(self):
        if self._toast_after_id:
            try:
                self.after_cancel(self._toast_after_id)
            except Exception:
                pass
            self._toast_after_id = None
        self.frame_toast_box.pack_forget()

    def on_model_select_change(self, label: str):
        """Adapta las opciones por defecto según las capacidades del modelo elegido, avisando con notificación transitoria pero permitiendo que el usuario reactive cualquier opción."""
        model_id = const.MODEL_LABELS_TO_ID.get(label, "")
        meta = const.MODEL_METADATA.get(model_id, {})
        caps = meta.get("capabilities", {})
        speakers = meta.get("speakers", ["maria", "lucia", "sofia", "tara", "leah", "javi", "ninguna"])
        default_spk = meta.get("default_speaker", "maria")

        if speakers:
            self.opt_speaker.configure(values=speakers)
            if self.opt_speaker.get() not in speakers:
                self.opt_speaker.set(default_spk)

        cur_mode = MODE_UI_TO_API.get(self.seg_mode.get(), "clone")
        supports_clone = caps.get("supports_clone", model_id == "omnivoice-zeroshot-0.6b")
        supports_design = caps.get("supports_design", model_id == "omnivoice-zeroshot-0.6b")
        note = caps.get("compatibility_note", "")

        if not supports_clone and cur_mode in ("clone", "design"):
            # Desactivar por defecto la configuración incompatible pasando a Modo Texto a Voz (pero sin bloquear que el usuario la vuelva a pulsar)
            ui_tts = MODE_API_TO_UI["tts"]
            self.seg_mode.set(ui_tts)
            self.opt_speaker.set(default_spk)
            self.sw_denoise.deselect()
            self.lbl_mode_desc.configure(
                text=f"ℹ️ {label}: Modo cambiado por defecto a Texto a Voz ({default_spk}). Funciona con: Voces Nativas ({', '.join(speakers)}), Temp/Top-K/Top-P y Tono/Velocidad. (Puedes reactivar Clonación/Diseño si deseas forzarlo).",
                text_color="#fbbf24",
            )
            self.show_transient_toast(
                f"Incompatibilidad detectada en '{label}': se desactivó Clonación/Diseño por defecto y se activó Voces Nativas ({default_spk}). Funciona con Muestreo LLM + DSP. Puedes volver a activar cualquier opción manualmente."
            )
        else:
            if supports_clone:
                self.sw_denoise.select()
            if note:
                self.show_transient_toast(f"Modelo seleccionado: {note}", duration_ms=5500)

    def on_mode_change(self, ui_mode_label: str):
        mode = MODE_UI_TO_API.get(ui_mode_label, "clone")
        cur_mid = const.MODEL_LABELS_TO_ID.get(self.opt_model.get(), "")
        meta = const.MODEL_METADATA.get(cur_mid, {})
        caps = meta.get("capabilities", {})
        supports_clone = caps.get("supports_clone", "omnivoice" in cur_mid)
        supports_design = caps.get("supports_design", "omnivoice" in cur_mid)

        if mode == "clone":
            if not supports_clone:
                self.lbl_mode_desc.configure(
                    text="⚠️ MODO CLONACIÓN FORZADO POR USUARIO: El modelo actual es GGUF (sin encoder Zero-Shot nativo). Se respetará tu elección usando el modelo cargado.",
                    text_color="#f59e0b",
                )
                self.show_transient_toast(
                    "Has reactivado Clonación manualmente sobre un modelo GGUF. Se respetará tu configuración sin cambiar de modelo.",
                    duration_ms=6500,
                )
            else:
                self.lbl_mode_desc.configure(
                    text="🎙️ MODO CLONACIÓN ACTIVO: Usa la transcripción real del Audio Base para clonar su timbre exacto.",
                    text_color="#34d399",
                )
        elif mode == "tts":
            self.lbl_mode_desc.configure(
                text="🗣️ MODO TEXTO A VOZ (VOCES NATIVAS): Usa la voz predefinida seleccionada + Instrucción de Estilo y controles DSP/LLM.",
                text_color="#60a5fa",
            )
        else:
            if not supports_design:
                self.lbl_mode_desc.configure(
                    text="⚠️ MODO DISEÑO FORZADO POR USUARIO: El modelo actual es GGUF. Se adaptará tu descripción a sus voces entrenadas.",
                    text_color="#f59e0b",
                )
                self.show_transient_toast(
                    "Has reactivado Diseño de Voz manualmente sobre un modelo GGUF. Se respetará tu configuración sin cambiar de modelo.",
                    duration_ms=6500,
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
                self.after(
                    0, lambda m=models_list, lid=loaded_id: self._apply_models_catalog(m, lid)
                )
            ref_resp = requests.get(f"{self.api_url}/reference_files", timeout=6)
            if ref_resp.status_code == 200:
                tmap = ref_resp.json().get("transcripts", {})
                if tmap:
                    self.transcripts_cache.update(tmap)
        except Exception:
            pass

    def _apply_models_catalog(self, models_list: list[dict], loaded_id: str | None):
        new_l2i = {}
        new_i2l = {}
        for m in models_list:
            mid = m["id"]
            name = m["name"]
            new_l2i[name] = mid
            new_i2l[mid] = name
            const.MODEL_METADATA[mid] = {
                "engine": m.get("engine", "gguf"),
                "speakers": m.get("speakers", ["maria", "javi", "tara", "leah", "ninguna"]),
                "default_speaker": m.get("default_speaker", "maria"),
                "capabilities": m.get("capabilities", {}),
            }
        if new_l2i:
            const.MODEL_LABELS_TO_ID = new_l2i
            const.MODEL_ID_TO_LABEL = new_i2l
            cur_val = self.opt_model.get()
            self.opt_model.configure(values=list(const.MODEL_LABELS_TO_ID.keys()))
            if not self._models_synced_once and loaded_id and loaded_id in const.MODEL_ID_TO_LABEL:
                self.opt_model.set(const.MODEL_ID_TO_LABEL[loaded_id])
                self._models_synced_once = True
            elif cur_val in const.MODEL_LABELS_TO_ID:
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
        self.clear_sticky_error()
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
                    const.MODEL_LABELS_TO_ID[mname] = mid
                    const.MODEL_ID_TO_LABEL[mid] = mname
                    const.MODEL_METADATA[mid] = {
                        "engine": model_info.get("engine", "gguf"),
                        "speakers": model_info.get("speakers", ["maria", "tara", "leah", "javi", "ninguna"]),
                        "default_speaker": model_info.get("default_speaker", "maria"),
                        "capabilities": model_info.get("capabilities", {}),
                    }
                    self.after(
                        0,
                        lambda: (
                            self.opt_model.configure(values=list(const.MODEL_LABELS_TO_ID.keys())),
                            self.opt_model.set(mname),
                            self.on_model_select_change(mname),
                            self.load_selected_model(),
                        ),
                    )
            else:
                detail = resp.json().get("detail", "No se pudo agregar el modelo local")
                self.after(0, lambda d=detail: self.show_sticky_error(d))
        except Exception as e:
            self.after(0, lambda err=str(e): self.show_sticky_error(f"Error agregando modelo local: {err}"))

    def load_selected_model(self):
        self.clear_sticky_error()
        label = self.opt_model.get()
        model_id = const.MODEL_LABELS_TO_ID.get(label, "omnivoice-zeroshot-0.6b")
        try:
            threads = int(self.opt_threads.get())
        except Exception:
            threads = 6
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
            resp = requests.post(
                f"{self.api_url}/models/load",
                json={"model_id": model_id, "cpu_threads": threads, "n_ctx": 1024},
                timeout=10,
            )
            if resp.status_code >= 400:
                detail = resp.json().get("detail", "No se pudo cargar el modelo")
                self.after(0, lambda d=detail: self.show_sticky_error(d))
        except Exception as e:
            self.after(0, lambda err=str(e): self.show_sticky_error(f"Error solicitando carga: {err}"))

    def unload_model_from_ram(self):
        self.clear_sticky_error()
        self.status_lbl.configure(text="🧹 Liberando memoria RAM/VRAM...", text_color="#f59e0b")
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
            self.after(0, lambda err=str(e): self.show_sticky_error(f"Error liberando memoria: {err}"))

    def get_current_config(self) -> dict:
        try:
            seed_val = int(self.entry_seed.get().strip())
        except Exception:
            seed_val = -1
        try:
            threads_val = int(self.opt_threads.get())
        except Exception:
            threads_val = 6

        model_id = const.MODEL_LABELS_TO_ID.get(self.opt_model.get(), "omnivoice-zeroshot-0.6b")
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
        if "model_id" in cfg and cfg["model_id"] in const.MODEL_ID_TO_LABEL:
            self.opt_model.set(const.MODEL_ID_TO_LABEL[cfg["model_id"]])

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
            base_n = os.path.basename(ref_f)
            self.lbl_voice.configure(text=f"Archivo activo: {base_n} ({ref_f})")
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
            self.lbl_steps.configure(text=f"Pasos Difusión (12=GPU Rápido): {v}")

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
        self.clear_sticky_error()
        self.apply_config_dict(DEFAULT_PRESET_VALUES)
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
                self.status_lbl.configure(
                    text="📂 Configuración cargada correctamente", text_color="#10b981"
                )
            except Exception as e:
                self.show_sticky_error(f"Error cargando preset: {e}")

    def on_select_ref_dropdown(self, filename: str):
        candidate = os.path.join(DEFAULT_REF_DIR, filename)
        if os.path.exists(candidate):
            self.reference_audio_path = candidate
            self.lbl_voice.configure(text=f"Archivo activo: {filename} ({candidate})")
            self.transcripts_cache.update(load_local_transcripts())
            tr = self.transcripts_cache.get(filename, "")
            self.entry_ref_text.delete(0, "end")
            if tr:
                self.entry_ref_text.insert(0, tr)
            self.status_lbl.configure(
                text=f"✅ Voz base seleccionada: {filename} (transcripción actualizada)",
                text_color="#10b981",
            )

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
                self.player.stop()
                with open(preview_file, "wb") as f:
                    f.write(resp.content)
                self.after(0, self._on_audio_ready)
                self.after(
                    0,
                    lambda: self.status_lbl.configure(
                        text=f"🎧 Reproduciendo audio de referencia: {os.path.basename(self.reference_audio_path)}",
                        text_color="#3b82f6",
                    ),
                )
        except Exception as e:
            self.after(0, lambda err=str(e): self.show_sticky_error(f"Error previsualizando voz base: {err}"))

    def _refresh_player_metadata(self, filepath: str) -> bool:
        if self.player.load_file(filepath):
            self.btn_play.configure(text="▶")
            self.seek_slider.set(0.0)
            self.lbl_time.configure(text=f"00:00 / {format_time(self.player.audio_duration)}")
            return True
        return False

    def toggle_play_pause(self):
        res = self.player.toggle_play_pause(self.downloaded_audio)
        if res == "no_device":
            self.show_sticky_error("Sin dispositivo de audio disponible en WSLg / PulseAudio.")
        elif res == "no_file":
            self.status_lbl.configure(text="⚠️ Genera un audio primero", text_color="#f59e0b")
        elif res == "paused":
            self.btn_play.configure(text="▶")
            pos = self.player.play_offset
            dur = self.player.audio_duration
            if dur > 0:
                self.seek_slider.set(min(100.0, (pos / dur) * 100.0))
                self.lbl_time.configure(text=f"{format_time(pos)} / {format_time(dur)}")
        elif res == "playing":
            self.btn_play.configure(text="⏸")
        else:
            self.show_sticky_error("Error reproduciendo el archivo WAV generado.")

    def toggle_mute(self):
        muted = self.player.toggle_mute()
        self.btn_mute.configure(text="🔇" if muted else "🔊")

    def on_volume_change(self, val):
        muted = self.player.set_volume(float(val))
        self.btn_mute.configure(text="🔇" if muted else "🔊")

    def on_seek_press(self, _event):
        self.user_dragging_seek = True

    def on_seek_drag(self, val):
        dur = self.player.audio_duration
        if dur > 0:
            target_sec = (float(val) / 100.0) * dur
            self.lbl_time.configure(text=f"{format_time(target_sec)} / {format_time(dur)}")

    def on_seek_release(self, _event):
        pos = self.player.seek_to_percent(float(self.seek_slider.get()))
        if self.player.audio_duration > 0:
            self.lbl_time.configure(
                text=f"{format_time(pos)} / {format_time(self.player.audio_duration)}"
            )
        self.user_dragging_seek = False

    def _update_ui_loop(self):
        if self.player.is_playing and not self.player.is_paused:
            if not self.player.is_busy():
                self.player.stop()
                self.btn_play.configure(text="▶")
                if not self.user_dragging_seek:
                    self.seek_slider.set(100.0)
                    dur = self.player.audio_duration
                    self.lbl_time.configure(text=f"{format_time(dur)} / {format_time(dur)}")
            else:
                cur = self.player.get_current_pos()
                dur = self.player.audio_duration
                if not self.user_dragging_seek and dur > 0:
                    self.seek_slider.set(min(100.0, (cur / dur) * 100.0))
                    self.lbl_time.configure(text=f"{format_time(cur)} / {format_time(dur)}")

        if self.is_generating and self.gen_local_start_t > 0:
            elapsed_s = max(0, int(time.time() - self.gen_local_start_t))
            target_s = max(elapsed_s + 1, self.gen_target_eta_s)
            self.lbl_eta.configure(text=f"ETA {elapsed_s}s / {target_s}s")

        self.after(50, self._update_ui_loop)

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
                if not self.is_generating and not self._sticky_error_msg:
                    self.after(
                        0,
                        lambda: self.status_lbl.configure(
                            text="⏳ Conectando al backend...", text_color="#f59e0b"
                        ),
                    )
        except Exception:
            if not self.is_generating and not self._sticky_error_msg:
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
            gpu_avail = mem.get("gpu_available", False)
            vram_mb = mem.get("vram_allocated_mb", 0.0)
            gpu_tag = f"⚡ GPU VRAM: {vram_mb:.0f} MB | " if gpu_avail else "CPU | "
            ram_color = "#ef4444" if sys_p > 85 else ("#f59e0b" if sys_p > 70 else "#60a5fa")
            self.lbl_ram.configure(
                text=f"{gpu_tag}RAM App: {proc_mb:.0f} MB | Sistema: {sys_u:.1f}/{sys_t:.1f} GB ({sys_p:.0f}%)",
                text_color=ram_color,
            )

        if state == "ERROR":
            self.progress_bar.set(0.0)
            self.btn_generate.configure(state="normal")
            if msg:
                self.show_sticky_error(msg)
            return

        # Si hay un error persistente activo y no estamos generando/descargando, NO pisar el texto rojo
        if self._sticky_error_msg and time.time() < self._sticky_error_until and state == "READY" and not self.is_generating:
            self.btn_generate.configure(state="normal")
            return

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

    def upload_voice(self):
        init_dir = DEFAULT_REF_DIR if os.path.isdir(DEFAULT_REF_DIR) else BASE_DIR
        filepath = fd.askopenfilename(
            initialdir=init_dir,
            filetypes=[("Audio Files", "*.mp3 *.wav")],
        )
        if filepath:
            self.reference_audio_path = filepath
            base_n = os.path.basename(filepath)
            self.lbl_voice.configure(text=f"Archivo activo: {base_n} ({filepath})", text_color="#e5e7eb")
            threading.Thread(
                target=self._upload_voice_thread, args=(filepath,), daemon=True
            ).start()

    def _upload_voice_thread(self, filepath):
        try:
            with open(filepath, "rb") as f:
                files = {"file": (os.path.basename(filepath), f)}
                resp = requests.post(
                    f"{self.api_url}/upload_reference", files=files, timeout=45
                )
            if resp.status_code == 200:
                rdata = resp.json()
                tr = rdata.get("transcript", "")
                fname = os.path.basename(filepath)
                if tr:
                    self.transcripts_cache[fname] = tr
                choices = scan_local_ref_files()
                self.after(
                    0,
                    lambda: (
                        self.opt_ref_file.configure(values=choices),
                        self.opt_ref_file.set(fname),
                        self.entry_ref_text.delete(0, "end"),
                        self.entry_ref_text.insert(0, tr),
                        self.status_lbl.configure(
                            text=f"✅ Voz subida y auto-transcrita: '{tr[:60]}...'",
                            text_color="#10b981",
                        ),
                    ),
                )
            else:
                self.after(0, lambda: self.show_sticky_error("No se pudo subir el audio de referencia."))
        except Exception as e:
            self.after(0, lambda err=str(e): self.show_sticky_error(f"Error subiendo voz: {err}"))

    def generate_audio(self):
        text = self.textbox.get("1.0", "end-1c")
        if not text.strip():
            self.show_sticky_error("Ingresa un texto para convertir en voz.")
            return

        self.clear_sticky_error()
        self.is_generating = True
        self.gen_local_start_t = time.time()
        cfg = self.get_current_config()

        # Respetamos 100% el modelo y modo elegidos por el usuario (sin sobrescribir model_id).
        if "omnivoice" in cfg.get("model_id", ""):
            self.gen_target_eta_s = max(1, int(cfg.get("num_step", 12) * 0.12))
        else:
            self.gen_target_eta_s = max(4, int((len(text) / 18) * 2))

        self.btn_generate.configure(state="disabled", text="⏳ Generando...")
        self.progress_bar.set(0.08)
        self.status_lbl.configure(
            text=f"⏳ Generando voz ({cfg.get('mode', 'clone').upper()})...", text_color="#f59e0b"
        )
        self.lbl_eta.configure(text=f"ETA 0s / ~{self.gen_target_eta_s}s")

        threading.Thread(target=self._generate_thread, args=(text, cfg), daemon=True).start()

    def _generate_thread(self, text: str, payload: dict):
        try:
            payload["text"] = text
            resp = requests.post(f"{self.api_url}/tts", json=payload, timeout=360)
            total_gen_s = round(max(0.1, time.time() - self.gen_local_start_t), 2)
            if resp.status_code == 200:
                rdata = resp.json()
                used_tr = rdata.get("reference_transcript", "")
                warns = rdata.get("warnings", [])
                if warns:
                    self.after(0, lambda w=warns[0]: self.show_transient_toast(w, duration_ms=8000))
                audio_resp = requests.get(
                    f"{self.api_url}/download",
                    params={"t": int(time.time() * 1000)},
                    timeout=30,
                )
                if audio_resp.status_code == 200 and len(audio_resp.content) > 200:
                    self.player.stop()
                    with open(self.downloaded_audio, "wb") as f:
                        f.write(audio_resp.content)
                    self.after(0, self._on_audio_ready)
                    self.after(
                        0,
                        lambda t=total_gen_s, tr=used_tr: (
                            self.progress_bar.set(1.0),
                            self.lbl_eta.configure(text=f"Listo en {t:.1f}s"),
                            (
                                self.entry_ref_text.insert(0, tr)
                                if (tr and not self.entry_ref_text.get().strip())
                                else None
                            ),
                            self.status_lbl.configure(
                                text=f"✅ Audio generado con éxito en {t:.2f}s y reproduciendo",
                                text_color="#10b981",
                            ),
                        ),
                    )
                else:
                    self.after(
                        0,
                        lambda: self.show_sticky_error("El servidor no devolvió un archivo WAV válido."),
                    )
            else:
                try:
                    err_msg = resp.json().get("detail", f"Error HTTP {resp.status_code}")
                except Exception:
                    err_msg = f"Error HTTP {resp.status_code} en generación"
                self.after(0, lambda m=err_msg: self.show_sticky_error(m))
        except Exception as e:
            self.after(0, lambda err=str(e): self.show_sticky_error(f"Error de conexión/inferencia: {err}"))
        finally:
            self.is_generating = False
            self.after(
                0,
                lambda: self.btn_generate.configure(
                    state="normal", text="▶ Generar Audio Natural"
                ),
            )

    def _on_audio_ready(self):
        if self._refresh_player_metadata(self.downloaded_audio):
            self.toggle_play_pause()


if __name__ == "__main__":
    app = TTSApp()
    app.mainloop()
