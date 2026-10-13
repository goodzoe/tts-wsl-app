import tkinter
import customtkinter as ctk
import tkinter.filedialog as fd
import requests
import threading
import os

ctk.set_appearance_mode("Dark")
ctk.set_default_color_theme("blue")

class TTSApp(ctk.CTk):
    def __init__(self):
        super().__init__()
        self.title("TTS LatAm - Panel de Control")
        self.geometry("700x650")
        
        # Eliminar bordes clasicos de windows si se desea un look mas moderno
        # self.overrideredirect(True) # Opcional, pero quita la barra de titulo nativa
        
        self.api_url = "http://127.0.0.1:8000"
        
        # Titulo Principal Moderno
        self.frame_top = ctk.CTkFrame(self, fg_color="transparent")
        self.frame_top.pack(fill="x", pady=15, padx=20)
        
        self.lbl_title = ctk.CTkLabel(self.frame_top, text="Studio TTS", font=("Helvetica", 28, "bold"))
        self.lbl_title.pack(side="left")
        self.lbl_subtitle = ctk.CTkLabel(self.frame_top, text="Zero-Shot Engine", font=("Helvetica", 14), text_color="gray")
        self.lbl_subtitle.pack(side="left", padx=10, side="bottom")

        # --- SECCION 1: VOZ DE REFERENCIA ---
        self.frame_voice = ctk.CTkFrame(self, corner_radius=10)
        self.frame_voice.pack(pady=10, padx=20, fill="x")
        
        self.lbl_voice_title = ctk.CTkLabel(self.frame_voice, text="Voz de Referencia (Clonación)", font=("Helvetica", 16, "bold"))
        self.lbl_voice_title.pack(anchor="w", padx=15, pady=(15, 5))
        
        self.lbl_voice = ctk.CTkLabel(self.frame_voice, text="No seleccionada", text_color="gray")
        self.lbl_voice.pack(side="left", padx=15, pady=(0, 15))
        
        self.btn_voice = ctk.CTkButton(self.frame_voice, text="Subir MP3/WAV", command=self.upload_voice, width=120)
        self.btn_voice.pack(side="right", padx=15, pady=(0, 15))
        
        # --- SECCION 2: PARAMETROS AVANZADOS ---
        self.frame_params = ctk.CTkFrame(self, corner_radius=10)
        self.frame_params.pack(pady=10, padx=20, fill="x")
        
        self.lbl_params_title = ctk.CTkLabel(self.frame_params, text="Ajustes de Modelo", font=("Helvetica", 16, "bold"))
        self.lbl_params_title.grid(row=0, column=0, columnspan=2, sticky="w", padx=15, pady=(15, 10))
        
        self.lbl_speed = ctk.CTkLabel(self.frame_params, text="Velocidad: 1.0x")
        self.lbl_speed.grid(row=1, column=0, padx=15, pady=5, sticky="w")
        self.slider_speed = ctk.CTkSlider(self.frame_params, from_=0.5, to=2.0, command=self.update_speed_lbl)
        self.slider_speed.set(1.0)
        self.slider_speed.grid(row=1, column=1, padx=15, pady=5, sticky="ew")
        
        self.lbl_temp = ctk.CTkLabel(self.frame_params, text="Expresividad (Temp): 0.7")
        self.lbl_temp.grid(row=2, column=0, padx=15, pady=5, sticky="w")
        self.slider_temp = ctk.CTkSlider(self.frame_params, from_=0.1, to=1.5, command=self.update_temp_lbl)
        self.slider_temp.set(0.7)
        self.slider_temp.grid(row=2, column=1, padx=15, pady=5, sticky="ew")
        
        self.lbl_topk = ctk.CTkLabel(self.frame_params, text="Top K: 50")
        self.lbl_topk.grid(row=3, column=0, padx=15, pady=5, sticky="w")
        self.slider_topk = ctk.CTkSlider(self.frame_params, from_=10, to=100, number_of_steps=90, command=self.update_topk_lbl)
        self.slider_topk.set(50)
        self.slider_topk.grid(row=3, column=1, padx=15, pady=(5, 15), sticky="ew")
        
        self.frame_params.grid_columnconfigure(1, weight=1) # Make sliders expand

        # --- SECCION 3: TEXTO Y GENERACION ---
        self.lbl_text = ctk.CTkLabel(self, text="Texto a generar:", font=("Helvetica", 16, "bold"))
        self.lbl_text.pack(anchor="w", padx=25, pady=(10, 0))
        self.textbox = ctk.CTkTextbox(self, height=100, corner_radius=10)
        self.textbox.pack(pady=5, padx=20, fill="both", expand=True)
        
        # Contenedor inferior: Boton + Mini Reproductor + Estado
        self.frame_bottom = ctk.CTkFrame(self, fg_color="transparent")
        self.frame_bottom.pack(fill="x", padx=20, pady=15)
        
        self.btn_generate = ctk.CTkButton(self.frame_bottom, text="▶ Generar Audio", font=("Helvetica", 14, "bold"), height=45, command=self.generate_audio)
        self.btn_generate.pack(side="left", padx=(0, 10))
        
        self.lbl_eta = ctk.CTkLabel(self.frame_bottom, text="ETA: --", text_color="gray")
        self.lbl_eta.pack(side="left", padx=10)

        self.status_lbl = ctk.CTkLabel(self.frame_bottom, text="Estado: Listo", text_color="#10b981", font=("Helvetica", 12, "bold"))
        self.status_lbl.pack(side="right")
        
        # Mini Reproductor (Oculto por defecto hasta que haya audio)
        self.frame_player = ctk.CTkFrame(self, corner_radius=10, fg_color="#1f2937")
        self.frame_player.pack(fill="x", padx=20, pady=(0, 20))
        self.frame_player.pack_forget() # Ocultar inicialmente
        
        self.btn_play = ctk.CTkButton(self.frame_player, text="🔊 Reproducir Resultado", fg_color="#3b82f6", hover_color="#2563eb", command=self.play_audio)
        self.btn_play.pack(pady=10)

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
            self.status_lbl.configure(text="Subiendo voz...", text_color="#f59e0b")
            threading.Thread(target=self._upload_voice_thread, args=(filepath,)).start()

    def _upload_voice_thread(self, filepath):
        try:
            with open(filepath, 'rb') as f:
                files = {'file': f}
                resp = requests.post(f"{self.api_url}/upload_reference", files=files)
            if resp.status_code == 200:
                self.status_lbl.configure(text="Voz lista", text_color="#10b981")
            else:
                self.status_lbl.configure(text="Error al subir", text_color="#ef4444")
        except Exception as e:
            self.status_lbl.configure(text="Backend offline", text_color="#ef4444")

    def generate_audio(self):
        text = self.textbox.get("1.0", "end-1c")
        if not text.strip():
            return
        
        self.btn_generate.configure(state="disabled", text="⏳ Generando...")
        self.status_lbl.configure(text="Procesando modelo...", text_color="#f59e0b")
        # Calculo mockeado de ETA: ~2 segs por cada 100 caracteres + 5 seg overhead
        eta_segs = max(5, int((len(text) / 100) * 2) + 5)
        self.lbl_eta.configure(text=f"ETA: ~{eta_segs}s")
        self.frame_player.pack_forget()
        
        threading.Thread(target=self._generate_thread, args=(text,)).start()

    def _generate_thread(self, text):
        try:
            payload = {
                "text": text,
                "speed": self.slider_speed.get(),
                "temperature": self.slider_temp.get(),
                "top_k": int(self.slider_topk.get())
            }
            resp = requests.post(f"{self.api_url}/tts", json=payload)
            if resp.status_code == 200:
                self.status_lbl.configure(text="Generación Completada", text_color="#10b981")
                self.frame_player.pack(fill="x", padx=20, pady=(0, 20)) # Mostrar reproductor
            else:
                self.status_lbl.configure(text="Error de generación", text_color="#ef4444")
        except Exception as e:
            self.status_lbl.configure(text="Error de conexión al backend", text_color="#ef4444")
        finally:
            self.btn_generate.configure(state="normal", text="▶ Generar Audio")
            self.lbl_eta.configure(text="ETA: --")

    def play_audio(self):
        # Aqui conectariamos con pygame/pydub para reproducir el wav retornado
        # Por ahora simulamos que reproduce
        self.btn_play.configure(text="⏸ Reproduciendo...", fg_color="#10b981")
        self.after(3000, lambda: self.btn_play.configure(text="🔊 Reproducir Resultado", fg_color="#3b82f6"))

if __name__ == "__main__":
    app = TTSApp()
    app.mainloop()
