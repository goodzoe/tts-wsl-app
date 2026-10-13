console.log("Lector TTS LatAm activado en wtr-lab.com");

function createPlayButton() {
    if (document.getElementById("local-tts-play-btn")) return;

    const btn = document.createElement("button");
    btn.id = "local-tts-play-btn";
    btn.innerText = "🔊 Escuchar con TTS Local";
    btn.className = "tts-floating-btn";
    
    btn.addEventListener("click", async () => {
        const textElement = document.querySelector(".chapter-content") || document.querySelector(".read-container") || document.querySelector("body");
        if (!textElement) {
            alert("No se encontró el texto del capítulo.");
            return;
        }
        
        const text = textElement.innerText.replace(/\n{3,}/g, '\n\n');
        
        btn.innerText = "⏳ Generando Voz...";
        btn.disabled = true;

        try {
            const response = await fetch("http://localhost:8000/tts", {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify({ text: text, speed: 1.0, temperature: 0.7, top_k: 50 })
            });

            if (response.status === 503) {
                alert("El modelo de Inteligencia Artificial se está descargando en el servidor local. Por favor, abre el Panel de Control para ver el progreso del ETA.");
                throw new Error("Modelo descargándose");
            } else if (response.status === 400) {
                alert("Por favor sube primero un audio de referencia en el Panel de Control para poder usar la clonación Zero-Shot.");
                throw new Error("Falta audio de referencia");
            } else if (!response.ok) {
                throw new Error("Error del backend");
            }

            btn.innerText = "▶ Audio Generado";
            setTimeout(() => {
                btn.innerText = "🔊 Escuchar de nuevo";
                btn.disabled = false;
            }, 3000);

        } catch (error) {
            console.error(error);
            if (error.message !== "Modelo descargándose" && error.message !== "Falta audio de referencia") {
                alert("Error conectando con el Backend en localhost:8000. ¿Está encendido?");
            }
            btn.innerText = "🔊 Escuchar con TTS Local";
            btn.disabled = false;
        }
    });

    document.body.appendChild(btn);
}

if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", createPlayButton);
} else {
    createPlayButton();
}
