import os
import sys
import glob
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
    # Pre-cargar libpulse empaquetado con pygame si no está en el sistema
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


def format_time(seconds: float) -> str:
    seconds = max(0, int(seconds))
    mins = seconds // 60
    secs = seconds % 60
    return f"{mins:02d}:{secs:02d}"


class TTSApp(ctk.CTk):
    def __init__(self):
        super().__init__()
        self.title("Studio TTS LatAm - Zero-Shot Engine")
        self.geometry("740x700")
        self.minsize(680, 660)

        self.api_url = "http://127.0.0.1:8000"
        self.downloaded_audio = os.path.abspath("resultado.wav")

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

        self._init_audio_mixer()

        # --- ENCABEZADO ---
        self.frame_top = ctk.CTkFrame(self, fg_color="transparent")
        self.frame_top.pack(fill="x", pady=(15, 8), padx=24)

        self.lbl_title = ctk.CTkLabel(
            self.frame_top, text="Studio TTS", font=("Helvetica", 26, "bold")
        )
        self.lbl_title.pack(side="left")
        self.lbl_subtitle = ctk.CTkLabel(
            self.frame_top,
            text="Zero-Shot LatAm Engine",
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

        # --- SECCIÓN 1: VOZ DE REFERENCIA ---
        self.frame_voice = ctk.CTkFrame(self, corner_radius=12)
        self.frame_voice.pack(pady=8, padx=24, fill="x")

        self.lbl_voice_title = ctk.CTkLabel(
            self.frame_voice,
            text="Voz de Referencia (Clonación Zero-Shot)",
            font=("Helvetica", 15, "bold"),
        )
        self.lbl_voice_title.pack(anchor="w", padx=16, pady=(12, 4))

        self.lbl_voice = ctk.CTkLabel(
            self.frame_voice,
            text="Usando voz base por defecto (base_voice.mp3)",
            text_color="#9ca3af",
        )
        self.lbl_voice.pack(side="left", padx=16, pady=(0, 12))

        self.btn_voice = ctk.CTkButton(
            self.frame_voice,
            text="Subir MP3/WAV",
            command=self.upload_voice,
            width=130,
            corner_radius=8,
        )
        self.btn_voice.pack(side="right", padx=16, pady=(0, 12))

        # --- SECCIÓN 2: PARÁMETROS AVANZADOS ---
        self.frame_params = ctk.CTkFrame(self, corner_radius=12)
        self.frame_params.pack(pady=8, padx=24, fill="x")

        self.lbl_params_title = ctk.CTkLabel(
            self.frame_params,
            text="Parámetros de Generación",
            font=("Helvetica", 15, "bold"),
        )
        self.lbl_params_title.grid(
            row=0, column=0, columnspan=2, sticky="w", padx=16, pady=(12, 8)
        )

        self.lbl_speed = ctk.CTkLabel(self.frame_params, text="Velocidad: 1.0x", width=160, anchor="w")
        self.lbl_speed.grid(row=1, column=0, padx=16, pady=4, sticky="w")
        self.slider_speed = ctk.CTkSlider(
            self.frame_params, from_=0.5, to=2.0, command=self.update_speed_lbl
        )
        self.slider_speed.set(1.0)
        self.slider_speed.grid(row=1, column=1, padx=16, pady=4, sticky="ew")

        self.lbl_temp = ctk.CTkLabel(self.frame_params, text="Expresividad (Temp): 0.7", width=160, anchor="w")
        self.lbl_temp.grid(row=2, column=0, padx=16, pady=4, sticky="w")
        self.slider_temp = ctk.CTkSlider(
            self.frame_params, from_=0.1, to=1.5, command=self.update_temp_lbl
        )
        self.slider_temp.set(0.7)
        self.slider_temp.grid(row=2, column=1, padx=16, pady=4, sticky="ew")

        self.lbl_topk = ctk.CTkLabel(self.frame_params, text="Top K: 50", width=160, anchor="w")
        self.lbl_topk.grid(row=3, column=0, padx=16, pady=(4, 12), sticky="w")
        self.slider_topk = ctk.CTkSlider(
            self.frame_params,
            from_=10,
            to=100,
            number_of_steps=90,
            command=self.update_topk_lbl,
        )
        self.slider_topk.set(50)
        self.slider_topk.grid(row=3, column=1, padx=16, pady=(4, 12), sticky="ew")

        self.frame_params.grid_columnconfigure(1, weight=1)

        # --- SECCIÓN 3: TEXTO A GENERAR ---
        self.lbl_text = ctk.CTkLabel(
            self, text="Texto a convertir en voz:", font=("Helvetica", 15, "bold")
        )
        self.lbl_text.pack(anchor="w", padx=26, pady=(6, 2))
        self.textbox = ctk.CTkTextbox(self, height=120, corner_radius=12, font=("Helvetica", 13))
        self.textbox.pack(pady=4, padx=24, fill="both", expand=True)

        # --- BOTÓN GENERAR + ETA ---
        self.frame_actions = ctk.CTkFrame(self, fg_color="transparent")
        self.frame_actions.pack(fill="x", padx=24, pady=(8, 6))

        self.btn_generate = ctk.CTkButton(
            self.frame_actions,
            text="▶ Generar Audio",
            font=("Helvetica", 14, "bold"),
            height=42,
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
        self.frame_player.pack(fill="x", padx=24, pady=(6, 18))

        # Barra de progreso superior roja con punto deslizable (como en la imagen de referencia)
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

        # Fila inferior de controles (Play circular, Volumen circular, Píldora de tiempo MM:SS / MM:SS)
        self.frame_controls = ctk.CTkFrame(self.frame_player, fg_color="transparent")
        self.frame_controls.pack(fill="x", padx=14, pady=(0, 10))

        # Botón Play / Pause circular
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

        # Botón Mute / Volumen circular
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

        # Píldora de tiempo "00:00 / 00:00"
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

        # Control de volumen compacto
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

        # Botón Guardar Audio a la derecha
        self.btn_save = ctk.CTkButton(
            self.frame_controls,
            text="⬇ Guardar",
            width=95,
            height=34,
            corner_radius=17,
            fg_color="#262f3f",
            hover_color="#374151",
            font=("Helvetica", 12, "bold"),
            command=self.save_audio_copy,
        )
        self.btn_save.pack(side="right")

        self.is_generating = False

        # Si ya existe un resultado previo, cargarlo listo para reproducir
        if os.path.exists(self.downloaded_audio):
            self._load_audio_metadata(self.downloaded_audio)

        self.check_backend_status()
        self._update_player_loop()

    def _init_audio_mixer(self):
        try:
            pygame.mixer.init(frequency=44100, size=-16, channels=2, buffer=1024)
            pygame.mixer.music.set_volume(self.volume)
            self.mixer_ready = True
        except Exception as e:
            print(f"Advertencia: No se pudo iniciar pygame.mixer ({e})")
            self.mixer_ready = False

    def _load_audio_metadata(self, filepath: str):
        if not self.mixer_ready or not os.path.exists(filepath):
            return
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
        except Exception as e:
            print(f"Error cargando audio en el reproductor: {e}")

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
            self._load_audio_metadata(self.downloaded_audio)

        try:
            if self.is_playing and not self.is_paused:
                # Pausar
                pygame.mixer.music.pause()
                self.play_offset = self._get_current_pos()
                self.is_paused = True
                self.btn_play.configure(text="▶")
            elif self.is_playing and self.is_paused:
                # Reanudar
                pygame.mixer.music.unpause()
                self.play_start_wall = time.time()
                self.is_paused = False
                self.btn_play.configure(text="⏸")
            else:
                # Iniciar desde el offset actual (o desde 0 si llegó al final)
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
        if not self.is_playing:
            return self.play_offset
        if self.is_paused:
            return self.play_offset
        elapsed = time.time() - self.play_start_wall
        return min(self.audio_duration, self.play_offset + elapsed)

    def _update_player_loop(self):
        if self.mixer_ready and self.is_playing and not self.is_paused:
            if not pygame.mixer.music.get_busy():
                # Terminó la pista
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
            filetypes=[("Audio WAV/MP3", "*.wav *.mp3")],
            initialfile="tts_generado.wav",
        )
        if dest:
            shutil.copy(self.downloaded_audio, dest)
            self.status_lbl.configure(text="✅ Audio guardado", text_color="#10b981")

    def check_backend_status(self):
        try:
            resp = requests.get(f"{self.api_url}/status", timeout=2)
            if resp.status_code == 200:
                data = resp.json()
                state = data.get("status")
                msg = data.get("message")

                if state == "DOWNLOADING":
                    self.status_lbl.configure(text=f"⏳ {msg}", text_color="#3b82f6")
                    self.btn_generate.configure(state="disabled")
                elif state == "LOADING":
                    self.status_lbl.configure(text=f"🧠 {msg}", text_color="#f59e0b")
                    self.btn_generate.configure(state="disabled")
                elif state in ["READY", "SIMULATION"]:
                    if not self.is_generating:
                        self.status_lbl.configure(text=f"✅ {msg}", text_color="#10b981")
                        self.btn_generate.configure(state="normal")
                elif state == "ERROR":
                    self.status_lbl.configure(text=f"❌ {msg}", text_color="#ef4444")
                    self.btn_generate.configure(state="disabled")
            else:
                self.status_lbl.configure(text="Conectando al backend...", text_color="#f59e0b")
                self.btn_generate.configure(state="disabled")
        except Exception:
            self.status_lbl.configure(text="Backend offline. Esperando...", text_color="#ef4444")
            self.btn_generate.configure(state="disabled")

        self.after(2000, self.check_backend_status)

    def update_speed_lbl(self, val):
        self.lbl_speed.configure(text=f"Velocidad: {val:.1f}x")

    def update_temp_lbl(self, val):
        self.lbl_temp.configure(text=f"Expresividad (Temp): {val:.1f}")

    def update_topk_lbl(self, val):
        self.lbl_topk.configure(text=f"Top K: {int(val)}")

    def upload_voice(self):
        filepath = fd.askopenfilename(filetypes=[("Audio Files", "*.mp3 *.wav")])
        if filepath:
            self.lbl_voice.configure(text=f"{os.path.basename(filepath)}", text_color="white")
            threading.Thread(target=self._upload_voice_thread, args=(filepath,), daemon=True).start()

    def _upload_voice_thread(self, filepath):
        try:
            with open(filepath, "rb") as f:
                files = {"file": f}
                resp = requests.post(f"{self.api_url}/upload_reference", files=files)
            if resp.status_code == 200:
                self.status_lbl.configure(text="✅ Voz de referencia actualizada", text_color="#10b981")
        except Exception as e:
            print("Error subiendo voz:", e)

    def generate_audio(self):
        text = self.textbox.get("1.0", "end-1c")
        if not text.strip():
            return

        self.is_generating = True
        self.btn_generate.configure(state="disabled", text="⏳ Generando...")
        self.status_lbl.configure(text="Generando audio...", text_color="#f59e0b")
        eta_segs = max(3, int((len(text) / 100) * 2))
        self.lbl_eta.configure(text=f"ETA: ~{eta_segs}s")

        threading.Thread(target=self._generate_thread, args=(text,), daemon=True).start()

    def _generate_thread(self, text):
        try:
            payload = {
                "text": text,
                "speed": self.slider_speed.get(),
                "temperature": self.slider_temp.get(),
                "top_k": int(self.slider_topk.get()),
            }
            resp = requests.post(f"{self.api_url}/tts", json=payload)
            if resp.status_code == 200:
                audio_resp = requests.get(f"{self.api_url}/download")
                if audio_resp.status_code == 200:
                    if self.mixer_ready and self.is_playing:
                        pygame.mixer.music.stop()
                    with open(self.downloaded_audio, "wb") as f:
                        f.write(audio_resp.content)
                    self.after(0, lambda: self._on_audio_ready())
                self.status_lbl.configure(text="✅ Audio Generado", text_color="#10b981")
            else:
                try:
                    err_msg = resp.json().get("detail", "Error de generación")
                except Exception:
                    err_msg = "Error de generación"
                self.status_lbl.configure(text=f"❌ {err_msg}", text_color="#ef4444")
        except Exception:
            self.status_lbl.configure(text="❌ Error de red con el backend", text_color="#ef4444")
        finally:
            self.is_generating = False
            self.btn_generate.configure(state="normal", text="▶ Generar Audio")
            self.lbl_eta.configure(text="ETA: --")

    def _on_audio_ready(self):
        self._load_audio_metadata(self.downloaded_audio)
        self.toggle_play_pause()


if __name__ == "__main__":
    app = TTSApp()
    app.mainloop()
