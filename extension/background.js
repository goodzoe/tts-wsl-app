/**
 * Background Service Worker — Studio TTS LatAm v3.2
 *
 * Actúa como puente (proxy privilegiado) entre el content.js (que corre dentro de páginas HTTPS
 * como wtr-lab.com donde Brave Shields o Private Network Access bloquean fetch directo a 127.0.0.1:8000)
 * y el servidor Backend FastAPI local en http://127.0.0.1:8000.
 */

const API_BASE = "http://127.0.0.1:8000";

function arrayBufferToBase64(buffer) {
  const bytes = new Uint8Array(buffer);
  const chunkSize = 0x8000;
  let binary = "";
  for (let i = 0; i < bytes.length; i += chunkSize) {
    binary += String.fromCharCode.apply(null, bytes.subarray(i, i + chunkSize));
  }
  return btoa(binary);
}

chrome.runtime.onMessage.addListener((msg, _sender, sendResponse) => {
  if (!msg || !msg.type) return false;

  if (msg.type === "STUDIO_TTS_API_JSON") {
    const url = `${API_BASE}${msg.path || "/status"}`;
    const options = {
      method: msg.method || "GET",
      headers: msg.body ? { "Content-Type": "application/json" } : undefined,
      body: msg.body ? JSON.stringify(msg.body) : undefined,
      cache: "no-store"
    };

    fetch(url, options)
      .then(async (resp) => {
        let data = null;
        try {
          data = await resp.json();
        } catch (_e) {}
        sendResponse({
          ok: resp.ok,
          status: resp.status,
          data
        });
      })
      .catch((err) => {
        sendResponse({
          ok: false,
          status: 0,
          error: err ? err.message : "Network error"
        });
      });

    return true; // Respuesta asíncrona
  }

  if (msg.type === "STUDIO_TTS_API_AUDIO") {
    const url = `${API_BASE}${msg.path || "/download"}`;
    fetch(url, { cache: "no-store" })
      .then(async (resp) => {
        if (!resp.ok) {
          sendResponse({
            ok: false,
            status: resp.status,
            error: `HTTP ${resp.status} descargando audio`
          });
          return;
        }
        const buf = await resp.arrayBuffer();
        const b64 = arrayBufferToBase64(buf);
        sendResponse({
          ok: true,
          status: 200,
          mimeType: resp.headers.get("content-type") || "audio/wav",
          base64: b64
        });
      })
      .catch((err) => {
        sendResponse({
          ok: false,
          status: 0,
          error: err ? err.message : "Audio fetch error"
        });
      });

    return true; // Respuesta asíncrona
  }

  return false;
});
