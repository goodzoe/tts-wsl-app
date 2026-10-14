/**
 * Popup Controller de Studio TTS LatAm v3.1
 * - Muestra en vivo el estado de conexión con el Backend (127.0.0.1:8000).
 * - Controla la activación de la extensión y reproducción (desactivadas por defecto).
 * - Activa el Inspector DOM tipo Brave DevTools (Ctrl+Shift+X) o aplica un selector CSS/grupo de etiquetas.
 * - Muestra notificaciones transitorias de compatibilidad de modelos desactivando por defecto opciones incompatibles pero permitiendo que el usuario las reactive libremente.
 */

(function () {
  "use strict";

  const API_BASE = "http://127.0.0.1:8000";

  const connPill = document.getElementById("conn-pill");
  const connText = document.getElementById("conn-text");
  const hwInfo = document.getElementById("hw-info");

  const compatToast = document.getElementById("compat-toast");
  const compatToastText = document.getElementById("compat-toast-text");
  const compatToastClose = document.getElementById("compat-toast-close");

  const swEnableExt = document.getElementById("sw-enable-ext");
  const extStateSub = document.getElementById("ext-state-sub");
  const btnInspectDom = document.getElementById("btn-inspect-dom");
  const inpCssSelector = document.getElementById("inp-css-selector");
  const btnApplySelector = document.getElementById("btn-apply-selector");
  const pickedInfo = document.getElementById("picked-info");

  const btnPrev = document.getElementById("btn-prev");
  const btnPlayPause = document.getElementById("btn-play-pause");
  const btnNext = document.getElementById("btn-next");
  const btnStop = document.getElementById("btn-stop");
  const playbackStatus = document.getElementById("playback-status");

  const rngVol = document.getElementById("rng-vol");
  const lblVol = document.getElementById("lbl-vol");
  const rngSpeed = document.getElementById("rng-speed");
  const lblSpeed = document.getElementById("lbl-speed");

  const selModel = document.getElementById("sel-model");
  const selMode = document.getElementById("sel-mode");
  const selRef = document.getElementById("sel-ref");
  const selSpeaker = document.getElementById("sel-speaker");
  const chkAutoAdv = document.getElementById("chk-autoadv");
  const chkShowWidget = document.getElementById("chk-show-widget");
  const btnRefreshBackend = document.getElementById("btn-refresh-backend");

  let modelsMeta = {};
  let toastTimer = null;

  function showToast(msg, duration = 7000) {
    if (toastTimer) clearTimeout(toastTimer);
    compatToastText.textContent = "🔔 " + msg;
    compatToast.style.display = "flex";
    toastTimer = setTimeout(() => {
      compatToast.style.display = "none";
    }, duration);
  }

  compatToastClose.addEventListener("click", () => {
    if (toastTimer) clearTimeout(toastTimer);
    compatToast.style.display = "none";
  });

  async function getActiveTab() {
    const tabs = await chrome.tabs.query({ active: true, currentWindow: true });
    return tabs[0] || null;
  }

  async function sendToActiveTab(message) {
    const tab = await getActiveTab();
    if (!tab || !tab.id) return null;
    try {
      return await chrome.tabs.sendMessage(tab.id, message);
    } catch (_e) {
      return null;
    }
  }

  function saveSettingsToStorage() {
    const cfg = {
      enabled: swEnableExt.checked,
      showWidget: chkShowWidget.checked,
      cssSelector: inpCssSelector.value.trim(),
      volume: Number(rngVol.value) / 100,
      speed: Number(rngSpeed.value),
      modelId: selModel.value,
      ttsMode: selMode.value,
      referenceFile: selRef.value,
      speakerHint: selSpeaker.value,
      autoAdvance: chkAutoAdv.checked
    };
    chrome.storage.local.set({ studioTtsConfig: cfg });
    sendToActiveTab({ type: "STUDIO_TTS_UPDATE_CONFIG", config: cfg });
  }

  async function loadSettingsFromStorage() {
    return new Promise((resolve) => {
      chrome.storage.local.get(["studioTtsConfig"], (res) => {
        const cfg = res.studioTtsConfig || {
          enabled: false, // Reproducción y extensión desactivadas por defecto
          showWidget: false,
          cssSelector: "",
          volume: 1.0,
          speed: 1.0,
          modelId: "omnivoice-zeroshot-0.6b",
          ttsMode: "clone",
          referenceFile: "base_voice.mp3",
          speakerHint: "maria",
          autoAdvance: true
        };
        swEnableExt.checked = Boolean(cfg.enabled);
        chkShowWidget.checked = Boolean(cfg.showWidget);
        inpCssSelector.value = cfg.cssSelector || "";
        const volPct = Math.round((cfg.volume ?? 1.0) * 100);
        rngVol.value = String(volPct);
        lblVol.textContent = `${volPct}%`;
        rngSpeed.value = String(cfg.speed ?? 1.0);
        lblSpeed.textContent = `${Number(cfg.speed ?? 1.0).toFixed(2)}x`;
        selModel.value = cfg.modelId || "omnivoice-zeroshot-0.6b";
        selMode.value = cfg.ttsMode || "clone";
        selSpeaker.value = cfg.speakerHint || "maria";
        chkAutoAdv.checked = cfg.autoAdvance !== false;
        updateToggleLabels();
        resolve(cfg);
      });
    });
  }

  function updateToggleLabels() {
    if (swEnableExt.checked) {
      extStateSub.textContent = "Activa • Lista para inspeccionar y reproducir";
      extStateSub.style.color = "#34d399";
    } else {
      extStateSub.textContent = "Desactivada por defecto (no reproduce automáticamente)";
      extStateSub.style.color = "#9ca3af";
    }
  }

  async function syncBackendStatus() {
    try {
      const [stRes, modRes, refRes] = await Promise.all([
        fetch(`${API_BASE}/status`),
        fetch(`${API_BASE}/models`),
        fetch(`${API_BASE}/reference_files`)
      ]);

      if (stRes.ok) {
        const st = await stRes.json();
        const isGpu = String(st.device || "").includes("cuda");
        if (st.status === "READY") {
          connPill.className = "conn-pill online";
          connText.textContent = isGpu ? "Online • GPU" : "Online • CPU";
        } else if (st.status === "GENERATING" || st.status === "LOADING" || st.status === "DOWNLOADING") {
          connPill.className = "conn-pill busy";
          connText.textContent = st.status;
        } else {
          connPill.className = "conn-pill online";
          connText.textContent = st.status || "Conectado";
        }
        const vram = st.memory && st.memory.vram_allocated_mb ? `VRAM: ${Math.round(st.memory.vram_allocated_mb)}MB` : "";
        hwInfo.textContent = `Modelo: ${st.loaded_model_id || "ninguno"} ${vram ? "• " + vram : ""}`;
      } else {
        throw new Error("HTTP status error");
      }

      if (modRes.ok) {
        const mdata = await modRes.json();
        const list = mdata.models || [];
        if (list.length > 0) {
          const prevVal = selModel.value;
          selModel.innerHTML = "";
          modelsMeta = {};
          for (const m of list) {
            modelsMeta[m.id] = m;
            const opt = document.createElement("option");
            opt.value = m.id;
            opt.textContent = m.name;
            selModel.appendChild(opt);
          }
          if (prevVal && modelsMeta[prevVal]) {
            selModel.value = prevVal;
          } else if (mdata.loaded_model_id && modelsMeta[mdata.loaded_model_id]) {
            selModel.value = mdata.loaded_model_id;
          }
        }
      }

      if (refRes.ok) {
        const rdata = await refRes.json();
        const files = rdata.files || [];
        if (files.length > 0) {
          const prevRef = selRef.value;
          selRef.innerHTML = "";
          for (const f of files) {
            const opt = document.createElement("option");
            opt.value = f.name;
            opt.textContent = `${f.name} (${f.duration}s)`;
            selRef.appendChild(opt);
          }
          if (prevRef) selRef.value = prevRef;
        }
      }
    } catch (_e) {
      connPill.className = "conn-pill offline";
      connText.textContent = "Offline (:8000)";
      hwInfo.textContent = "Backend desconectado • Ejecuta ./run_backend.sh";
    }
  }

  async function refreshTabPlaybackState() {
    const resp = await sendToActiveTab({ type: "STUDIO_TTS_GET_STATE" });
    if (!resp) return;
    if (resp.selectorDescription) {
      pickedInfo.textContent = `Objetivo: ${resp.selectorDescription} (${resp.chunksCount || 0} bloques)`;
    }
    if (resp.cssSelector && !inpCssSelector.value) {
      inpCssSelector.value = resp.cssSelector;
    }
    if (resp.statusText) {
      playbackStatus.textContent = resp.statusText;
    }
    if (resp.isPlaying && !resp.isPaused) {
      btnPlayPause.textContent = "⏸ Pausar";
    } else if (resp.isPlaying && resp.isPaused) {
      btnPlayPause.textContent = "▶ Continuar";
    } else {
      btnPlayPause.textContent = "▶ Reproducir";
    }
  }

  // Eventos de UI
  swEnableExt.addEventListener("change", () => {
    updateToggleLabels();
    if (swEnableExt.checked) {
      chkShowWidget.checked = true;
    }
    saveSettingsToStorage();
  });

  chkShowWidget.addEventListener("change", saveSettingsToStorage);
  chkAutoAdv.addEventListener("change", saveSettingsToStorage);
  selRef.addEventListener("change", saveSettingsToStorage);
  selSpeaker.addEventListener("change", saveSettingsToStorage);

  selModel.addEventListener("change", () => {
    const mid = selModel.value;
    const meta = modelsMeta[mid] || {};
    const caps = meta.capabilities || {};
    const speakers = meta.speakers || ["maria", "lucia", "sofia", "tara", "leah", "javi", "ninguna"];
    const defSpk = meta.default_speaker || "maria";

    selSpeaker.innerHTML = "";
    for (const s of speakers) {
      const opt = document.createElement("option");
      opt.value = s;
      opt.textContent = s;
      selSpeaker.appendChild(opt);
    }
    selSpeaker.value = defSpk;

    const supportsClone = caps.supports_clone !== undefined ? caps.supports_clone : mid.includes("omnivoice");
    if (!supportsClone && (selMode.value === "clone" || selMode.value === "design")) {
      selMode.value = "tts";
      showToast(
        `Incompatibilidad en '${meta.name || mid}': se desactivó Clonación/Diseño por defecto y se pasó a Voces Nativas (${defSpk}). Puedes volver a activar cualquier opción manualmente.`
      );
    } else if (caps.compatibility_note) {
      showToast(caps.compatibility_note, 5000);
    }
    saveSettingsToStorage();
  });

  selMode.addEventListener("change", () => {
    const mid = selModel.value;
    const meta = modelsMeta[mid] || {};
    const caps = meta.capabilities || {};
    const supportsClone = caps.supports_clone !== undefined ? caps.supports_clone : mid.includes("omnivoice");
    if (!supportsClone && (selMode.value === "clone" || selMode.value === "design")) {
      showToast(
        "Has reactivado Clonación/Diseño sobre un modelo GGUF. Se respetará tu configuración sin cambiar de modelo.",
        5500
      );
    }
    saveSettingsToStorage();
  });

  rngVol.addEventListener("input", () => {
    lblVol.textContent = `${rngVol.value}%`;
    saveSettingsToStorage();
  });

  rngSpeed.addEventListener("input", () => {
    lblSpeed.textContent = `${Number(rngSpeed.value).toFixed(2)}x`;
    saveSettingsToStorage();
  });

  btnInspectDom.addEventListener("click", async () => {
    if (!swEnableExt.checked) {
      swEnableExt.checked = true;
      chkShowWidget.checked = true;
      updateToggleLabels();
      saveSettingsToStorage();
    }
    await sendToActiveTab({ type: "STUDIO_TTS_START_INSPECTOR" });
    window.close();
  });

  btnApplySelector.addEventListener("click", async () => {
    const sel = inpCssSelector.value.trim();
    if (!swEnableExt.checked) {
      swEnableExt.checked = true;
      chkShowWidget.checked = true;
      updateToggleLabels();
    }
    saveSettingsToStorage();
    const res = await sendToActiveTab({ type: "STUDIO_TTS_APPLY_SELECTOR", selector: sel });
    if (res && res.ok) {
      pickedInfo.textContent = `Selector aplicado: ${sel || "Auto"} (${res.chunksCount} bloques)`;
      showToast(`Selector '${sel || "Auto"}' aplicado: ${res.chunksCount} bloques detectados.`, 4000);
    } else {
      showToast("No se encontraron elementos con ese selector en la pestaña actual.", 4500);
    }
  });

  btnPlayPause.addEventListener("click", async () => {
    if (!swEnableExt.checked) {
      swEnableExt.checked = true;
      chkShowWidget.checked = true;
      updateToggleLabels();
      saveSettingsToStorage();
    }
    await sendToActiveTab({ type: "STUDIO_TTS_COMMAND", action: "play_pause" });
    setTimeout(refreshTabPlaybackState, 250);
  });

  btnPrev.addEventListener("click", async () => {
    await sendToActiveTab({ type: "STUDIO_TTS_COMMAND", action: "prev" });
    setTimeout(refreshTabPlaybackState, 250);
  });

  btnNext.addEventListener("click", async () => {
    await sendToActiveTab({ type: "STUDIO_TTS_COMMAND", action: "next" });
    setTimeout(refreshTabPlaybackState, 250);
  });

  btnStop.addEventListener("click", async () => {
    await sendToActiveTab({ type: "STUDIO_TTS_COMMAND", action: "stop" });
    setTimeout(refreshTabPlaybackState, 250);
  });

  btnRefreshBackend.addEventListener("click", () => {
    syncBackendStatus();
    refreshTabPlaybackState();
  });

  // Inicialización
  (async () => {
    await loadSettingsFromStorage();
    await syncBackendStatus();
    await refreshTabPlaybackState();
    setInterval(syncBackendStatus, 2500);
    setInterval(refreshTabPlaybackState, 1200);
  })();
})();
