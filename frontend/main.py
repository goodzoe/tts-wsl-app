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
        self.geometry("600x550")
        
        self.api_url = "http://127.0.0.1:8000"
        
        # Título
        self.lbl_title = ctk.CTkLabel(self, text="Motor TTS (sirekist98) - Zero Shot", font=("Arial", 20, "bold"))
        self.lbl_title.pack(pady=15)
        
        # Selección de Voz Base
        self.frame_voice = ctk.CTkFrame(self)
        self.frame_voice.pack(pady=10, padx=20, fill="x")
        self.lbl_voice = ctk.CTkLabel(self.frame_voice, text="Voz de Referencia (Clonación): No seleccionada")
        self.lbl_voice.pack(side="left", padx=10, pady=10)
        self.btn_voice = ctk.CTkButton(self.frame_voice, text="Subir MP3/WAV", command=self.upload_voice)
        self.btn_voice.pack(side="right", padx=10, pady=10)
        
        # Parámetros
        self.frame_params = ctk.CTkFrame(self)
        self.frame_params.pack(pady=10, padx=20, fill="x")
        
        self.lbl_speed = ctk.CTkLabel(self.frame_params, text="Velocidad: 1.0x")
        self.lbl_speed.grid(row=0, column=0, padx=10, pady=5, sticky="w")
        self.slider_speed = ctk.CTkSlider(self.frame_params, from_=0.5, to=2.0, command=self.update_speed_lbl)
        self.slider_speed.set(1.0)
        self.slider_speed.grid(row=0, column=1, padx=10, pady=5)
        
        self.lbl_temp = ctk.CTkLabel(self.frame_params, text="Expresividad (Temp): 0.7")
        self.lbl_temp.grid(row=1, column=0, padx=10, pady=5, sticky="w")
        self.slider_temp = ctk.CTkSlider(self.frame_params, from_=0.1, to=1.5, command=self.update_temp_lbl)
        self.slider_temp.set(0.7)
        self.slider_temp.grid(row=1, column=1, padx=10, pady=5)
        
        # Área de Texto
        self.lbl_text = ctk.CTkLabel(self, text="Texto a generar:")
        self.lbl_text.pack(anchor="w", padx=20)
        self.textbox = ctk.CTkTextbox(self, height=150)
        self.textbox.pack(pady=5, padx=20, fill="both", expand=True)
        
        # Botón Generar
        self.btn_generate = ctk.CTkButton(self, text="▶ Generar Audio", font=("Arial", 14, "bold"), height=40, command=self.generate_audio)
        self.btn_generate.pack(pady=20)
        
        self.status_lbl = ctk.CTkLabel(self, text="Estado: Listo", text_color="green")
        self.status_lbl.pack(pady=5)

    def update_speed_lbl(self, val):
        self.lbl_speed.configure(text=f"Velocidad: {val:.1f}x")

    def update_temp_lbl(self, val):
        self.lbl_temp.configure(text=f"Expresividad (Temp): {val:.1f}")

    def upload_voice(self):
        filepath = fd.askopenfilename(filetypes=[("Audio Files", "*.mp3 *.wav")])
        if filepath:
            self.lbl_voice.configure(text=f"Voz: {os.path.basename(filepath)}")
            self.status_lbl.configure(text="Subiendo voz al backend...", text_color="orange")
            threading.Thread(target=self._upload_voice_thread, args=(filepath,)).start()

    def _upload_voice_thread(self, filepath):
        try:
            with open(filepath, 'rb') as f:
                files = {'file': f}
                resp = requests.post(f"{self.api_url}/upload_reference", files=files)
            if resp.status_code == 200:
                self.status_lbl.configure(text="Voz subida correctamente", text_color="green")
            else:
                self.status_lbl.configure(text="Error al subir voz", text_color="red")
        except Exception as e:
            self.status_lbl.configure(text="Backend offline", text_color="red")

    def generate_audio(self):
        text = self.textbox.get("1.0", "end-1c")
        if not text.strip():
            return
        self.status_lbl.configure(text="Generando...", text_color="orange")
        threading.Thread(target=self._generate_thread, args=(text,)).start()

    def _generate_thread(self, text):
        try:
            payload = {
                "text": text,
                "speed": self.slider_speed.get(),
                "temperature": self.slider_temp.get()
            }
            resp = requests.post(f"{self.api_url}/tts", json=payload)
            if resp.status_code == 200:
                self.status_lbl.configure(text="Audio generado", text_color="green")
            else:
                self.status_lbl.configure(text="Error de generación", text_color="red")
        except Exception as e:
            self.status_lbl.configure(text="Error de conexión al backend", text_color="red")

if __name__ == "__main__":
    app = TTSApp()
    app.mainloop()
