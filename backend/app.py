import os
from fastapi import FastAPI, HTTPException, UploadFile, File
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from fastapi.responses import FileResponse
import uvicorn
# Importaciones para el modelo (comentadas hasta instalar dependencias)
# import torch
# from transformers import pipeline

app = FastAPI(title="LatAm TTS Backend (sirekist98/spanish_conversational_tts)")

# Permitir a la extensión de Brave comunicarse con el backend
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"], # En producción se limita a wtr-lab.com
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

class TTSRequest(BaseModel):
    text: str
    speed: float = 1.0
    temperature: float = 0.7 # Controla la expresividad/emoción

print("Iniciando motor TTS: sirekist98/spanish_conversational_tts...")
print("Límite VRAM configurado: < 5GB")

@app.post("/tts")
async def generate_tts(request: TTSRequest):
    if not request.text:
        raise HTTPException(status_code=400, detail="Texto vacío")
    
    print(f"Generando audio para texto ({len(request.text)} chars) | Vel: {request.speed} | Temp: {request.temperature}")
    
    # Aquí irá la lógica de inferencia zero-shot.
    # Se cargará el audio de reference_audio/base_voice.mp3
    # Y se aplicará el texto.
    
    # Placeholder de respuesta
    return {"status": "success", "message": "Audio generado en backend local"}

@app.post("/upload_reference")
async def upload_reference(file: UploadFile = File(...)):
    os.makedirs("reference_audio", exist_ok=True)
    file_location = "reference_audio/base_voice.mp3"
    with open(file_location, "wb+") as f:
        f.write(file.file.read())
    return {"info": f"Voz base guardada con éxito en {file_location}"}

if __name__ == "__main__":
    uvicorn.run(app, host="127.0.0.1", port=8000)
