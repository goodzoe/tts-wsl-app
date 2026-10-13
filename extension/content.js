console.log("Lector TTS LatAm activado en wtr-lab.com");

function createPlayButton() {
    if (document.getElementById("local-tts-play-btn")) return;

    const btn = document.createElement("button");
    btn.id = "local-tts-play-btn";
    btn.innerText = "🔊 Escuchar con TTS Local";
    btn.className = "tts-floating-btn";
    
    btn.addEventListener("click", async () => {
        // En wtr-lab, el texto suele estar bajo ciertas clases. Ajustar si el DOM cambia.
        const textElement = document.querySelector(".chapter-content") || document.querySelector(".read-container") || document.querySelector("body");
        if (!textElement) {
            alert("No se encontró el texto del capítulo.");
            return;
        }
        
        // Limpiamos un poco el texto de saltos de línea excesivos
        const text = textElement.innerText.replace(/\n{3,}/g, '\n\n');
        
        btn.innerText = "⏳ Generando Voz...";
        btn.disabled = true;

        try {
            const response = await fetch("http://localhost:8000/tts", {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify({ text: text, speed: 1.0, temperature: 0.7 })
            });

            if (!response.ok) throw new Error("El backend no responde");

            // Simulación de lectura terminada (hasta conectar el audio blob real)
            btn.innerText = "▶ Audio Generado";
            setTimeout(() => {
                btn.innerText = "🔊 Escuchar de nuevo";
                btn.disabled = false;
            }, 3000);

        } catch (error) {
            console.error(error);
            alert("Error conectando con el Backend FastAPI en localhost:8000. ¿Está encendido?");
            btn.innerText = "🔊 Escuchar con TTS Local";
            btn.disabled = false;
        }
    });

    document.body.appendChild(btn);
}

// Ejecutar cuando el DOM esté listo
if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", createPlayButton);
} else {
    createPlayButton();
}
