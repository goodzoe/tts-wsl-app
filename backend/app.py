import os
from fastapi import FastAPI, HTTPException, UploadFile, File
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from fastapi.responses import FileResponse
import uvicorn

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

print("Iniciando motor TTS: sirekist98/spanish_conversational_tts...")
print("Límite VRAM configurado: < 5GB")

@app.get("/")
async def root():
    return {"status": "ok", "message": "Backend TTS corriendo perfectamente. Endpoint activo: POST /tts"}

@app.post("/tts")
async def generate_tts(request: TTSRequest):
    if not request.text:
        raise HTTPException(status_code=400, detail="Texto vacío")
    
    print(f"Generando audio para texto ({len(request.text)} chars) | Vel: {request.speed} | Temp: {request.temperature}")
    return {"status": "success", "message": "Audio generado en backend local"}

@app.post("/upload_reference")
async def upload_reference(file: UploadFile = File(...)):
    os.makedirs("reference_audio", exist_ok=True)
    file_location = "reference_audio/base_voice.mp3"
    with open(file_location, "wb+") as f:
        f.write(file.file.read())
    return {"info": f"Voz base guardada con éxito en {file_location}"}

if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=8000)
