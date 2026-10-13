import os
import torch
from transformers import pipeline
import soundfile as sf
from fastapi import FastAPI, HTTPException, UploadFile, File
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from fastapi.responses import FileResponse
import uvicorn
import uuid

app = FastAPI(title="LatAm TTS Backend (sirekist98/spanish_conversational_tts)")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"], 
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

class TTSRequest(BaseModel):
    text: str
    speed: float = 1.0
    temperature: float = 0.7 

print("Inicializando pipeline TTS...")
# Cargar modelo en memoria (Usando CPU/GPU según disponibilidad, buscando bajo consumo de VRAM)
device = "cuda" if torch.cuda.is_available() else "cpu"
print(f"Usando dispositivo: {device}")

# Usar el modelo conversacional latino de sirekist98
pipe = pipeline("text-to-speech", model="sirekist98/spanish_conversational_tts", device=device)
print("Pipeline TTS cargado con éxito. Listo para solicitudes.")

@app.post("/tts")
async def generate_tts(request: TTSRequest):
    if not request.text:
        raise HTTPException(status_code=400, detail="Texto vacío")
    
    print(f"Generando audio para texto ({len(request.text)} chars) | Vel: {request.speed} | Temp: {request.temperature}")
    
    os.makedirs("outputs", exist_ok=True)
    out_filename = f"outputs/output_{uuid.uuid4().hex[:8]}.wav"
    
    try:
        # Generar inferencia con el modelo (algunos modelos soportan forward params adicionales)
        # La referencia base (zero-shot) dependería de si el modelo lo expone como voice_preset o audio_ref
        
        # En la mayoría de pipelines TTS de HF:
        result = pipe(request.text)
        
        # Guardar a disco
        sf.write(out_filename, result["audio"][0], result["sampling_rate"])
        
        return FileResponse(out_filename, media_type="audio/wav")
    except Exception as e:
        print(f"Error en inferencia: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/upload_reference")
async def upload_reference(file: UploadFile = File(...)):
    os.makedirs("reference_audio", exist_ok=True)
    file_location = "reference_audio/base_voice.mp3"
    with open(file_location, "wb+") as f:
        f.write(file.file.read())
    return {"info": f"Voz base guardada con éxito en {file_location}"}

if __name__ == "__main__":
    uvicorn.run(app, host="127.0.0.1", port=8000)
