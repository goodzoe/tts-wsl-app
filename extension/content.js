/**
 * Studio TTS LatAm - Extensión de Navegador (Brave / Chrome Manifest V3)
 * Extrae el texto seleccionado o el contenido del capítulo, consulta el estado en vivo
 * (ETA y %) desde http://localhost:8000/status, genera el audio vía POST /tts y
 * descarga/reproduce automáticamente el WAV en un reproductor flotante integrado.
 */

const API_BASE = "http://localhost:8000";
let statusPollTimer = null;

function extractTargetText() {
    // 1. Si el usuario seleccionó un párrafo con el mouse, leer exactamente esa selección
    const sel = window.getSelection ? window.getSelection().toString().trim() : "";
    if (sel.length > 3) {
        return sel.slice(0, 650);
    }

    // 2. si no hay selección, buscar el contenedor del capítulo en wtr-lab
    const container =
        document.querySelector(".chapter-body") ||
        document.querySelector(".chapter-content") ||
        document.querySelector(".read-container") ||
        document.querySelector("article") ||
        document.querySelector("main");

    const raw = (container ? container.innerText : document.body.innerText) || "";
    const clean = raw.replace(/\s+/g, " ").trim();
    // Limitar a un fragmento razonable por generación para respuesta rápida
    return clean.slice(0, 500);
}

function createFloatingWidget() {
    if (document.getElementById("studio-tts-widget")) return;

    const widget = document.createElement("div");
    widget.id = "studio-tts-widget";
    widget.className = "studio-tts-widget";

    widget.innerHTML = `
        <div class="studio-tts-header">
            <span class="studio-tts-title">🎙️ Studio TTS LatAm</span>
            <select id="studio-tts-mode" class="studio-tts-select" title="Modo de Síntesis">
                <option value="clone" selected>Clonar Voz Base</option>
                <option value="tts">Voz Nativa (María)</option>
            </select>
        </div>
        <div id="studio-tts-status" class="studio-tts-status">Listo (Selecciona texto o pulsa Escuchar)</div>
        <div class="studio-tts-actions">
            <button id="local-tts-play-btn" class="tts-floating-btn">🔊 Generar y Escuchar</button>
        </div>
        <audio id="studio-tts-audio" class="studio-tts-audio" controls preload="none"></audio>
    `;

    document.body.appendChild(widget);

    const btn = document.getElementById("local-tts-play-btn");
    const statusEl = document.getElementById("studio-tts-status");
    const modeEl = document.getElementById("studio-tts-mode");
    const audioEl = document.getElementById("studio-tts-audio");

    btn.addEventListener("click", async () => {
        const text = extractTargetText();
        if (!text) {
            statusEl.textContent = "⚠️ No se encontró texto para leer.";
            return;
        }

        const mode = modeEl.value;
        btn.disabled = true;
        btn.textContent = "⏳ Generando...";
        statusEl.textContent = `Sintetizando (${text.length} caracteres)...`;

        // Polling de progreso y ETA cada 1s mientras genera
        statusPollTimer = setInterval(async () => {
            try {
                const stRes = await fetch(`${API_BASE}/status`);
                if (stRes.ok) {
                    const st = await stRes.json();
                    if (st.message) {
                        statusEl.textContent = st.message;
                    }
                }
            } catch (_e) {
                // ignorar errores transitorios de polling
            }
        }, 1000);

        try {
            const payload = {
                text: text,
                mode: mode,
                model_id: mode === "clone" ? "omnivoice-zeroshot-0.6b" : "canopy-es-multivoz-q4",
                language: "Spanish",
                reference_file: "base_voice.mp3",
                speaker_hint: "maria",
                num_step: 16,
                guidance_scale: 2.0,
                speed: 1.0,
                temperature: 0.6,
                top_k: 50
            };

            const response = await fetch(`${API_BASE}/tts`, {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify(payload)
            });

            if (!response.ok) {
                let errDetail = "Error en el servidor TTS";
                try {
                    const errJson = await response.json();
                    errDetail = errJson.detail || errDetail;
                } catch (_e) {}
                throw new Error(errDetail);
            }

            // Descargar el archivo WAV generado y reproducirlo en el elemento <audio>
            const wavResp = await fetch(`${API_BASE}/download?t=${Date.now()}`);
            if (!wavResp.ok) {
                throw new Error("No se pudo descargar el audio WAV generado.");
            }
            const blob = await wavResp.blob();
            const blobUrl = URL.createObjectURL(blob);
            audioEl.src = blobUrl;
            audioEl.style.display = "block";
            await audioEl.play();

            statusEl.textContent = "✅ Reproduciendo audio generado";
        } catch (error) {
            console.error("[Studio TTS Extension]", error);
            statusEl.textContent = `❌ ${error.message || "Backend offline en localhost:8000"}`;
        } finally {
            if (statusPollTimer) {
                clearInterval(statusPollTimer);
                statusPollTimer = null;
            }
            btn.disabled = false;
            btn.textContent = "🔊 Generar y Escuchar";
        }
    });
}

if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", createFloatingWidget);
} else {
    createFloatingWidget();
}
