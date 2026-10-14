/**
 * Studio TTS LatAm — Motor Content Script Limpio v3.3
 *
 * 1. CERO CONEXIONES DIRECTAS A LOCALHOST DESDE LA PÁGINA WEB:
 *    Elimina por completo el cartel de Chrome/Brave "<sitio> quiere acceder a otras aplicaciones
 *    y servicios de este dispositivo" (Private Network Access). Todas las llamadas a 127.0.0.1:8000
 *    ocurren exclusivamente dentro del Service Worker (background.js).
 * 2. CERO BARRAS FLOTANTES EN LA PÁGINA:
 *    Todo el control vive en el menú desplegable de la extensión (popup.html). No se inyecta
 *    ningún widget que tape contenido.
 * 3. VELOCIDAD EN TIEMPO REAL SOBRE EL AUDIO ACTUAL:
 *    El slider de velocidad ajusta instantáneamente `audioEl.playbackRate` (y `preservesPitch = true`)
 *    sobre el audio que está sonando sin re-generarlo ni distorsionar el tono.
 * 4. PRE-GENERACIÓN ACTIVA (PREFETCH QUEUE):
 *    En cuanto el fragmento `idx` queda listo y empieza a sonar, lanza una cola secuencial en
 *    segundo plano que pre-genera activamente `idx + 1` e `idx + 2` en el backend GPU para que la
 *    transición entre párrafos sea inmediata (0 ms de espera).
 */

(function () {
    "use strict";

    if (window.__studioTtsLatAmInjected) return;
    window.__studioTtsLatAmInjected = true;

    // Eliminar cualquier widget viejo si quedó de una versión previa sin recargar pestaña
    const legacyWidget = document.getElementById("studio-tts-widget");
    if (legacyWidget) legacyWidget.remove();

    const NOVEL_CONTAINER_SELECTORS = [
        ".chapter-body",
        ".chapter-content",
        "#chapter-content",
        "#chr-content",
        ".read-container",
        ".reading-content",
        ".text-left",
        ".novel-content",
        ".entry-content",
        "article.chapter",
        "article",
        "[role='main'] article",
        "main"
    ];

    const NOISE_SELECTORS = [
        "nav", "header", "footer", "aside", "script", "style", "noscript", "svg", "iframe",
        "button", "select", "input", "textarea", "form",
        ".ads", ".ad", ".advertisement", "[class*='advert']",
        ".comments", "#comments", ".comment-section", ".disqus",
        ".chapter-nav", ".chapter-actions", ".pagination", ".pager", ".breadcrumb",
        ".toc", ".table-of-contents", ".sidebar", ".social-share", ".share-buttons",
        ".author-note", ".translator-note", "[role='navigation']", "[aria-hidden='true']"
    ];

    const state = {
        enabled: false,         // Reproducción desactivada por defecto
        pickingElement: false,
        customContainer: null,
        cssSelector: "",
        selectorDescription: "Auto-detección de capítulo",
        chunks: [],
        currentIndex: 0,
        isPlaying: false,
        isPaused: false,
        stopRequested: false,
        autoAdvance: true,
        volume: 1.0,
        playbackRate: 1.0,      // Velocidad de reproducción en tiempo real sobre el audio actual
        ttsMode: "clone",       // "clone" | "tts" | "design"
        modelId: "omnivoice-zeroshot-0.6b",
        referenceFile: "base_voice.mp3",
        speakerHint: "maria",
        voiceDescription: "Voz femenina joven de 23 años, cálida, clara y natural con acento argentino",
        styleInstruct: "",
        numStep: 12,
        chunkSize: 320,
        prefetchLookahead: 2,   // Pre-generar activamente los siguientes 2 fragmentos
        prefetchCache: new Map(), // index -> Promise<Blob>
        prefetchStatuses: new Map(), // index -> "queued" | "generating" | "ready" | "error"
        synthesisChain: Promise.resolve(), // Cola secuencial para no colisionar en el backend
        activeBlobUrl: null,
        highlightedEl: null,
        inspectorHoverEl: null,
        inspectorTooltipEl: null,
        statusText: "⏹ Reproducción en espera (desactivada por defecto)"
    };

    // Elemento de audio en memoria (oculto, jamás visible en el DOM)
    const audioEl = new Audio();
    audioEl.preload = "auto";
    if ("preservesPitch" in audioEl) audioEl.preservesPitch = true;
    if ("mozPreservesPitch" in audioEl) audioEl.mozPreservesPitch = true;
    if ("webkitPreservesPitch" in audioEl) audioEl.webkitPreservesPitch = true;

    function base64ToBlob(base64, mimeType = "audio/wav") {
        const binStr = atob(base64);
        const len = binStr.length;
        const bytes = new Uint8Array(len);
        for (let i = 0; i < len; i++) {
            bytes[i] = binStr.charCodeAt(i);
        }
        return new Blob([bytes], { type: mimeType });
    }

    /**
     * Comunicación 100% vía Background Service Worker (NUNCA hace fetch desde la página web).
     * Esto evita que aparezca el popup de permiso de red local de Chrome/Brave en las pestañas.
     */
    function bgApiJsonRequest(path, method = "GET", body = null) {
        return new Promise((resolve, reject) => {
            if (typeof chrome === "undefined" || !chrome.runtime || !chrome.runtime.sendMessage) {
                reject(new Error("Extensión recargada. Actualiza la pestaña (F5)."));
                return;
            }
            chrome.runtime.sendMessage(
                { type: "STUDIO_TTS_API_JSON", path, method, body },
                (resp) => {
                    if (chrome.runtime.lastError) {
                        reject(new Error("Backend o extensión no disponible."));
                        return;
                    }
                    if (!resp || !resp.ok) {
                        const detail = (resp && resp.data && resp.data.detail) || (resp && resp.error) || "Backend offline (:8000)";
                        reject(new Error(detail));
                        return;
                    }
                    resolve(resp.data);
                }
            );
        });
    }

    function bgApiAudioBlobRequest(path) {
        return new Promise((resolve, reject) => {
            if (typeof chrome === "undefined" || !chrome.runtime || !chrome.runtime.sendMessage) {
                reject(new Error("Extensión recargada. Actualiza la pestaña (F5)."));
                return;
            }
            chrome.runtime.sendMessage(
                { type: "STUDIO_TTS_API_AUDIO", path },
                (resp) => {
                    if (chrome.runtime.lastError || !resp || !resp.ok || !resp.base64) {
                        reject(new Error((resp && resp.error) || "No se pudo descargar el audio WAV generado."));
                        return;
                    }
                    resolve(base64ToBlob(resp.base64, resp.mimeType || "audio/wav"));
                }
            );
        });
    }

    function isCleanNarrativeParagraph(text) {
        if (!text) return false;
        const clean = text.replace(/\s+/g, " ").trim();
        if (clean.length < 2) return false;

        const uiNoisePatterns = [
            /^(prev(ious)?|next)\s*(chapter|cap[íi]tulo)?$/i,
            /^(cap[íi]tulo\s*(anterior|siguiente))$/i,
            /^(table of contents|[íi]ndice|volver al [íi]ndice)$/i,
            /^(report(ar)?\s*error|comentar|compartir|share|bookmark)$/i,
            /^(font\s*size|tama[ñn]o de letra|dark mode|modo oscuro)$/i,
            /^(loading|cargando|advertisement|publicidad)\.{0,3}$/i
        ];
        for (const pat of uiNoisePatterns) {
            if (pat.test(clean)) return false;
        }
        return true;
    }

    function buildCssSelectorForElement(el) {
        if (!el || el === document.body || el === document.documentElement) return "body";
        const tag = el.tagName.toLowerCase();
        if (el.id) {
            return `${tag}#${CSS.escape(el.id)}`;
        }
        const classes = Array.from(el.classList || [])
            .filter((c) => !c.startsWith("studio-tts-"))
            .slice(0, 2);
        if (classes.length > 0) {
            return `${tag}.${classes.map((c) => CSS.escape(c)).join(".")}`;
        }
        return tag;
    }

    function findBestNarrativeContainer() {
        if (state.customContainer && document.body.contains(state.customContainer)) {
            return state.customContainer;
        }

        for (const sel of NOVEL_CONTAINER_SELECTORS) {
            const candidates = Array.from(document.querySelectorAll(sel));
            for (const el of candidates) {
                const textLen = (el.innerText || "").trim().length;
                if (textLen > 250) {
                    return el;
                }
            }
        }

        let bestEl = document.body;
        let bestScore = 0;
        const containers = document.querySelectorAll("article, main, section, div");

        for (const el of containers) {
            const pList = el.querySelectorAll(":scope > p, :scope > div > p");
            if (pList.length < 2) continue;

            let textScore = 0;
            for (const p of pList) {
                const t = (p.innerText || "").trim();
                if (t.length > 40) textScore += t.length;
            }

            const linkTextLen = Array.from(el.querySelectorAll("a"))
                .reduce((acc, a) => acc + ((a.innerText || "").length), 0);
            const effectiveScore = textScore - linkTextLen * 1.5;

            if (effectiveScore > bestScore) {
                bestScore = effectiveScore;
                bestEl = el;
            }
        }

        return bestEl;
    }

    function splitTextIntoNaturalChunks(text, maxChars = 320) {
        const clean = text.replace(/\s+/g, " ").trim();
        if (!clean) return [];
        if (clean.length <= maxChars) return [clean];

        const sentences = clean.match(/[^.!?…]+[.!?…]+["'»”)]*|.+/g) || [clean];
        const chunks = [];
        let current = "";

        for (const rawSent of sentences) {
            const sent = rawSent.trim();
            if (!sent) continue;

            if ((current + " " + sent).trim().length <= maxChars) {
                current = (current + " " + sent).trim();
            } else {
                if (current) chunks.push(current);
                if (sent.length <= maxChars) {
                    current = sent;
                } else {
                    const parts = sent.split(/([,;:])/);
                    let sub = "";
                    for (const part of parts) {
                        if ((sub + part).length <= maxChars) {
                            sub += part;
                        } else {
                            if (sub.trim()) chunks.push(sub.trim());
                            sub = part;
                        }
                    }
                    current = sub.trim();
                }
            }
        }
        if (current) chunks.push(current);
        return chunks;
    }

    function extractChapterChunks(maxChars = 320) {
        const selText = window.getSelection ? window.getSelection().toString().trim() : "";
        if (selText.length > 15) {
            return splitTextIntoNaturalChunks(selText, maxChars).map((text) => ({
                text,
                element: null
            }));
        }

        const noiseSelectorJoined = NOISE_SELECTORS.join(", ");
        const paragraphs = [];

        if (state.cssSelector && state.cssSelector.trim()) {
            try {
                const matchedNodes = Array.from(document.querySelectorAll(state.cssSelector.trim()))
                    .filter((n) => !n.closest(noiseSelectorJoined));
                if (matchedNodes.length === 1) {
                    const singleContainer = matchedNodes[0];
                    const innerBlocks = singleContainer.querySelectorAll("h1, h2, h3, p, blockquote, li");
                    if (innerBlocks.length > 0) {
                        for (const blk of innerBlocks) {
                            if (blk.closest(noiseSelectorJoined)) continue;
                            const raw = (blk.innerText || "").replace(/\s+/g, " ").trim();
                            if (isCleanNarrativeParagraph(raw)) {
                                paragraphs.push({ text: raw, element: blk });
                            }
                        }
                    } else {
                        const raw = (singleContainer.innerText || "").replace(/\s+/g, " ").trim();
                        if (isCleanNarrativeParagraph(raw)) {
                            paragraphs.push({ text: raw, element: singleContainer });
                        }
                    }
                } else if (matchedNodes.length > 1) {
                    for (const node of matchedNodes) {
                        const raw = (node.innerText || "").replace(/\s+/g, " ").trim();
                        if (isCleanNarrativeParagraph(raw)) {
                            paragraphs.push({ text: raw, element: node });
                        }
                    }
                }
            } catch (_e) {}
        }

        if (paragraphs.length === 0) {
            const container = findBestNarrativeContainer();
            if (!container) return [];

            const blocks = container.querySelectorAll("h1, h2, h3, p, blockquote, li");
            if (blocks.length > 0) {
                for (const blk of blocks) {
                    if (blk.closest(noiseSelectorJoined)) continue;
                    if (blk.offsetParent === null && blk.tagName !== "H1") continue;
                    const raw = (blk.innerText || "").replace(/\s+/g, " ").trim();
                    if (isCleanNarrativeParagraph(raw)) {
                        paragraphs.push({ text: raw, element: blk });
                    }
                }
            }

            if (paragraphs.length === 0) {
                const clone = container.cloneNode(true);
                clone.querySelectorAll(noiseSelectorJoined).forEach((n) => n.remove());
                const lines = (clone.innerText || "")
                    .split(/\n+/)
                    .map((l) => l.replace(/\s+/g, " ").trim())
                    .filter(isCleanNarrativeParagraph);
                for (const line of lines) {
                    paragraphs.push({ text: line, element: container });
                }
            }
        }

        const finalChunks = [];
        for (const item of paragraphs) {
            const subChunks = splitTextIntoNaturalChunks(item.text, maxChars);
            for (const sc of subChunks) {
                finalChunks.push({
                    text: sc,
                    element: item.element
                });
            }
        }

        return finalChunks;
    }

    function highlightActiveElement(el) {
        if (state.highlightedEl && state.highlightedEl !== el) {
            state.highlightedEl.classList.remove("studio-tts-active-paragraph");
        }
        if (el && el !== document.body) {
            el.classList.add("studio-tts-active-paragraph");
            state.highlightedEl = el;
            try {
                el.scrollIntoView({ behavior: "smooth", block: "center" });
            } catch (_e) {}
        }
    }

    function clearHighlight() {
        if (state.highlightedEl) {
            state.highlightedEl.classList.remove("studio-tts-active-paragraph");
            state.highlightedEl = null;
        }
    }

    function revokeActiveBlob() {
        if (state.activeBlobUrl) {
            try {
                URL.revokeObjectURL(state.activeBlobUrl);
            } catch (_e) {}
            state.activeBlobUrl = null;
        }
    }

    function invalidatePrefetchCache() {
        state.prefetchCache.clear();
        state.prefetchStatuses.clear();
    }

    /**
     * Encola la síntesis y descarga del fragmento `index` de manera estrictamente secuencial
     * para que la pre-generación (prefetch) de `idx + 1` e `idx + 2` nunca colisione ni pise
     * el archivo WAV en el servidor.
     * NOTA: `speed` al backend se envía siempre en 1.0; la velocidad del popup controla `audioEl.playbackRate` en vivo.
     */
    function enqueueChunkSynthesis(index) {
        if (index < 0 || index >= state.chunks.length) {
            return Promise.reject(new Error("Índice fuera de rango"));
        }
        if (state.prefetchCache.has(index)) {
            return state.prefetchCache.get(index);
        }

        const chunkObj = state.chunks[index];
        state.prefetchStatuses.set(index, "queued");

        const payload = {
            text: chunkObj.text,
            mode: state.ttsMode,
            model_id: state.modelId,
            language: "Spanish",
            reference_file: state.referenceFile,
            speaker_hint: state.speakerHint,
            style_instruct: state.styleInstruct,
            voice_description: state.voiceDescription,
            num_step: Number(state.numStep) || 12,
            guidance_scale: 2.0,
            speed: 1.0, // La velocidad del usuario se aplica en tiempo real sobre audioEl.playbackRate
            temperature: 0.6,
            top_k: 50
        };

        const taskPromise = state.synthesisChain.then(async () => {
            if (state.stopRequested) {
                throw new Error("Reproducción detenida");
            }
            state.prefetchStatuses.set(index, "generating");
            await bgApiJsonRequest("/tts", "POST", payload);
            const blob = await bgApiAudioBlobRequest(`/download?t=${Date.now()}_${index}`);
            state.prefetchStatuses.set(index, "ready");
            return blob;
        });

        // Mantener viva la cadena aunque un eslabón falle
        state.synthesisChain = taskPromise.catch(() => {});

        state.prefetchCache.set(index, taskPromise);
        taskPromise.catch(() => {
            state.prefetchCache.delete(index);
            state.prefetchStatuses.set(index, "error");
        });

        return taskPromise;
    }

    /**
     * Dispara activamente la pre-generación en segundo plano de los siguientes N fragmentos
     * mientras el usuario escucha el fragmento actual.
     */
    function triggerActivePrefetch(fromIndex) {
        if (!state.autoAdvance || state.stopRequested) return;
        const maxLookahead = state.prefetchLookahead || 2;
        for (let offset = 1; offset <= maxLookahead; offset++) {
            const targetIdx = fromIndex + offset;
            if (targetIdx < state.chunks.length && !state.prefetchCache.has(targetIdx)) {
                enqueueChunkSynthesis(targetIdx).catch(() => {});
            }
        }
    }

    async function playChunkAtIndex(idx) {
        if (state.stopRequested || idx < 0 || idx >= state.chunks.length) {
            finishPlayback();
            return;
        }

        state.currentIndex = idx;
        const currentChunk = state.chunks[idx];
        highlightActiveElement(currentChunk.element);

        const wasAlreadyPrefetched = state.prefetchStatuses.get(idx) === "ready";
        state.statusText = wasAlreadyPrefetched
            ? `⚡ Cargando desde caché párrafo ${idx + 1}/${state.chunks.length}...`
            : `⏳ Sintetizando párrafo ${idx + 1} de ${state.chunks.length}...`;

        try {
            const wavBlob = await enqueueChunkSynthesis(idx);
            if (state.stopRequested || state.currentIndex !== idx) return;

            // Pre-generar activamente los siguientes fragmentos (idx+1, idx+2) mientras suena este
            triggerActivePrefetch(idx);

            revokeActiveBlob();
            const blobUrl = URL.createObjectURL(wavBlob);
            state.activeBlobUrl = blobUrl;

            audioEl.src = blobUrl;
            audioEl.volume = Math.max(0, Math.min(1, Number(state.volume ?? 1.0)));
            audioEl.playbackRate = Math.max(0.4, Math.min(3.0, Number(state.playbackRate ?? 1.0)));

            audioEl.onended = () => {
                revokeActiveBlob();
                if (!state.stopRequested && state.autoAdvance && state.currentIndex + 1 < state.chunks.length) {
                    playChunkAtIndex(state.currentIndex + 1);
                } else {
                    finishPlayback();
                }
            };

            state.isPlaying = true;
            state.isPaused = false;
            const nextStatus = state.prefetchStatuses.get(idx + 1);
            const prefetchTag = (idx + 1 < state.chunks.length)
                ? (nextStatus === "ready" ? " • ⚡ Siguiente listo" : " • 🔄 Pre-generando sig.")
                : "";
            state.statusText = `🔊 Narrando [${idx + 1}/${state.chunks.length}] (${state.playbackRate.toFixed(2)}x)${prefetchTag}`;

            await audioEl.play();
        } catch (err) {
            if (state.stopRequested) return;
            state.statusText = `❌ ${err.message || "Backend offline en 127.0.0.1:8000"}`;
            state.isPlaying = false;
        }
    }

    function finishPlayback() {
        state.isPlaying = false;
        state.isPaused = false;
        clearHighlight();
        state.statusText = "✅ Lectura finalizada";
    }

    function startOrResumePlayback(forceRestart = false) {
        if (!forceRestart && state.isPlaying && !state.isPaused && !audioEl.paused) {
            audioEl.pause();
            state.isPaused = true;
            state.statusText = `⏸ Pausado en [${state.currentIndex + 1}/${state.chunks.length}]`;
            return;
        }

        if (!forceRestart && state.isPlaying && state.isPaused) {
            state.isPaused = false;
            audioEl.playbackRate = Math.max(0.4, Math.min(3.0, Number(state.playbackRate ?? 1.0)));
            state.statusText = `🔊 Narrando [${state.currentIndex + 1}/${state.chunks.length}] (${state.playbackRate.toFixed(2)}x)`;
            audioEl.play();
            return;
        }

        state.stopRequested = false;
        if (state.chunks.length === 0 || forceRestart) {
            state.chunks = extractChapterChunks(state.chunkSize);
            if (!forceRestart) state.currentIndex = 0;
        }

        if (state.chunks.length === 0) {
            state.statusText = "⚠️ No se detectó texto narrativo en esta página.";
            return;
        }

        playChunkAtIndex(state.currentIndex);
    }

    function stopPlayback() {
        state.stopRequested = true;
        state.isPlaying = false;
        state.isPaused = false;
        try {
            audioEl.pause();
            audioEl.currentTime = 0;
        } catch (_e) {}
        revokeActiveBlob();
        clearHighlight();
        state.statusText = "⏹ Lectura detenida";
    }

    // =========================================================================
    // INSPECTOR DOM ESTILO BRAVE DEVTOOLS (Ctrl+Shift+X o desde el Popup)
    // =========================================================================
    function ensureInspectorTooltip() {
        if (!state.inspectorTooltipEl) {
            const tip = document.createElement("div");
            tip.className = "studio-tts-inspector-tooltip";
            tip.style.display = "none";
            document.body.appendChild(tip);
            state.inspectorTooltipEl = tip;
        }
        return state.inspectorTooltipEl;
    }

    function startDomInspector() {
        state.pickingElement = true;
        state.statusText = "🎯 Inspector DOM activo (ESC para cancelar): haz clic en el grupo de etiquetas...";
    }

    function stopDomInspector() {
        state.pickingElement = false;
        if (state.inspectorHoverEl) {
            state.inspectorHoverEl.classList.remove("studio-tts-inspector-highlight");
            state.inspectorHoverEl = null;
        }
        if (state.inspectorTooltipEl) {
            state.inspectorTooltipEl.style.display = "none";
        }
    }

    document.addEventListener("mousemove", (ev) => {
        if (!state.pickingElement) return;
        const target = ev.target;
        if (!target || target.classList.contains("studio-tts-inspector-tooltip")) {
            return;
        }
        const candidate = target.closest("article, section, main, .chapter-body, .chapter-content, div, p, ul, ol, blockquote") || target;
        if (state.inspectorHoverEl && state.inspectorHoverEl !== candidate) {
            state.inspectorHoverEl.classList.remove("studio-tts-inspector-highlight");
        }
        candidate.classList.add("studio-tts-inspector-highlight");
        state.inspectorHoverEl = candidate;

        const sel = buildCssSelectorForElement(candidate);
        const pCount = candidate.querySelectorAll("p, li, blockquote").length || 1;
        const tip = ensureInspectorTooltip();
        tip.textContent = `🎯 ${sel} • ${pCount} bloque(s) de texto (Clic para seleccionar)`;
        tip.style.display = "block";
        tip.style.left = `${Math.min(window.innerWidth - 320, ev.clientX + 14)}px`;
        tip.style.top = `${Math.max(10, ev.clientY - 32)}px`;
    }, true);

    document.addEventListener("keydown", (ev) => {
        if (ev.ctrlKey && ev.shiftKey && (ev.key === "X" || ev.key === "x")) {
            ev.preventDefault();
            if (state.pickingElement) {
                stopDomInspector();
                state.statusText = "Modo Inspector DOM cancelado.";
            } else {
                state.enabled = true;
                startDomInspector();
            }
        } else if (ev.key === "Escape" && state.pickingElement) {
            stopDomInspector();
            state.statusText = "Modo Inspector DOM cancelado.";
        }
    }, true);

    document.addEventListener("click", (ev) => {
        if (!state.pickingElement) return;
        ev.preventDefault();
        ev.stopPropagation();

        const clickedEl = state.inspectorHoverEl || ev.target;
        stopDomInspector();

        const isParagraph = ["P", "LI", "BLOCKQUOTE", "H1", "H2", "H3"].includes(clickedEl.tagName);
        const container = isParagraph
            ? (clickedEl.closest(".chapter-body, .chapter-content, #chapter-content, article, section, main, div") || clickedEl.parentElement)
            : clickedEl;

        state.customContainer = container;
        const containerSel = buildCssSelectorForElement(container);
        state.cssSelector = isParagraph ? `${containerSel} ${clickedEl.tagName.toLowerCase()}` : containerSel;
        state.selectorDescription = state.cssSelector;

        state.chunks = extractChapterChunks(state.chunkSize);
        invalidatePrefetchCache();

        let foundIdx = 0;
        if (isParagraph) {
            const clickedText = (clickedEl.innerText || "").replace(/\s+/g, " ").trim().slice(0, 60);
            if (clickedText) {
                const matchIdx = state.chunks.findIndex((c) => c.text.includes(clickedText));
                if (matchIdx >= 0) foundIdx = matchIdx;
            }
        }
        state.currentIndex = foundIdx;
        if (state.chunks[foundIdx] && state.chunks[foundIdx].element) {
            highlightActiveElement(state.chunks[foundIdx].element);
        }
        state.statusText = `🎯 Grupo seleccionado (${state.cssSelector}): ${state.chunks.length} bloques listos desde #${foundIdx + 1}`;

        if (typeof chrome !== "undefined" && chrome.storage && chrome.storage.local) {
            chrome.storage.local.get(["studioTtsConfig"], (res) => {
                const cfg = res.studioTtsConfig || {};
                cfg.cssSelector = state.cssSelector;
                chrome.storage.local.set({ studioTtsConfig: cfg });
            });
        }
    }, true);

    // =========================================================================
    // SINCRONIZACIÓN CON EL POPUP DE LA EXTENSIÓN (popup.js)
    // =========================================================================
    function applyConfigFromPopup(cfg) {
        if (!cfg) return;
        const wasEnabled = state.enabled;
        state.enabled = Boolean(cfg.enabled);

        if (typeof cfg.volume === "number") {
            state.volume = Math.max(0, Math.min(1, cfg.volume));
            audioEl.volume = state.volume;
        }

        // Velocidad modifica en tiempo real el audio actual que se está reproduciendo (sin invalidar caché ni regenerar)
        if (typeof cfg.speed === "number") {
            state.playbackRate = Math.max(0.4, Math.min(3.0, cfg.speed));
            audioEl.playbackRate = state.playbackRate;
            if (state.isPlaying && !state.isPaused) {
                const nextStatus = state.prefetchStatuses.get(state.currentIndex + 1);
                const prefetchTag = (state.currentIndex + 1 < state.chunks.length)
                    ? (nextStatus === "ready" ? " • ⚡ Siguiente listo" : " • 🔄 Pre-generando sig.")
                    : "";
                state.statusText = `🔊 Narrando [${state.currentIndex + 1}/${state.chunks.length}] (${state.playbackRate.toFixed(2)}x)${prefetchTag}`;
            }
        }

        // Solo invalidamos caché de pre-generación si cambió el modelo, modo o voz
        const synthChanged =
            (cfg.modelId && cfg.modelId !== state.modelId) ||
            (cfg.ttsMode && cfg.ttsMode !== state.ttsMode) ||
            (cfg.referenceFile && cfg.referenceFile !== state.referenceFile) ||
            (cfg.speakerHint && cfg.speakerHint !== state.speakerHint);

        if (cfg.modelId) state.modelId = cfg.modelId;
        if (cfg.ttsMode) state.ttsMode = cfg.ttsMode;
        if (cfg.referenceFile) state.referenceFile = cfg.referenceFile;
        if (cfg.speakerHint) state.speakerHint = cfg.speakerHint;
        if (typeof cfg.autoAdvance === "boolean") state.autoAdvance = cfg.autoAdvance;

        if (typeof cfg.cssSelector === "string" && cfg.cssSelector !== state.cssSelector) {
            state.cssSelector = cfg.cssSelector;
            state.selectorDescription = cfg.cssSelector || "Auto-detección de capítulo";
            state.chunks = extractChapterChunks(state.chunkSize);
            invalidatePrefetchCache();
        } else if (synthChanged) {
            invalidatePrefetchCache();
            if (state.isPlaying) {
                triggerActivePrefetch(state.currentIndex);
            }
        }

        if (wasEnabled && !state.enabled) {
            stopPlayback();
        }
    }

    if (typeof chrome !== "undefined" && chrome.runtime && chrome.runtime.onMessage) {
        chrome.runtime.onMessage.addListener((msg, _sender, sendResponse) => {
            if (!msg || !msg.type) return false;

            if (msg.type === "STUDIO_TTS_GET_STATE") {
                if (state.chunks.length === 0) {
                    state.chunks = extractChapterChunks(state.chunkSize);
                }
                const nextIdx = state.currentIndex + 1;
                const nextPrefetchState = (nextIdx < state.chunks.length)
                    ? (state.prefetchStatuses.get(nextIdx) || "idle")
                    : "none";
                sendResponse({
                    enabled: state.enabled,
                    isPlaying: state.isPlaying,
                    isPaused: state.isPaused,
                    chunksCount: state.chunks.length,
                    currentIndex: state.currentIndex,
                    cssSelector: state.cssSelector,
                    selectorDescription: state.selectorDescription,
                    statusText: state.statusText,
                    nextPrefetchState
                });
                return true;
            }

            if (msg.type === "STUDIO_TTS_UPDATE_CONFIG") {
                applyConfigFromPopup(msg.config);
                sendResponse({ ok: true });
                return true;
            }

            if (msg.type === "STUDIO_TTS_START_INSPECTOR") {
                state.enabled = true;
                startDomInspector();
                sendResponse({ ok: true });
                return true;
            }

            if (msg.type === "STUDIO_TTS_APPLY_SELECTOR") {
                state.cssSelector = (msg.selector || "").trim();
                state.selectorDescription = state.cssSelector || "Auto-detección de capítulo";
                state.customContainer = null;
                state.chunks = extractChapterChunks(state.chunkSize);
                state.currentIndex = 0;
                invalidatePrefetchCache();
                state.statusText = `🎯 Selector '${state.selectorDescription}': ${state.chunks.length} bloques listos`;
                sendResponse({ ok: state.chunks.length > 0, chunksCount: state.chunks.length });
                return true;
            }

            if (msg.type === "STUDIO_TTS_COMMAND") {
                state.enabled = true;
                if (msg.action === "play_pause") {
                    startOrResumePlayback(false);
                } else if (msg.action === "prev") {
                    if (state.chunks.length === 0) state.chunks = extractChapterChunks(state.chunkSize);
                    state.stopRequested = false;
                    playChunkAtIndex(Math.max(0, state.currentIndex - 1));
                } else if (msg.action === "next") {
                    if (state.chunks.length === 0) state.chunks = extractChapterChunks(state.chunkSize);
                    state.stopRequested = false;
                    playChunkAtIndex(Math.min(state.chunks.length - 1, state.currentIndex + 1));
                } else if (msg.action === "stop") {
                    stopPlayback();
                }
                sendResponse({ ok: true });
                return true;
            }

            return false;
        });
    }

    if (typeof chrome !== "undefined" && chrome.storage && chrome.storage.local) {
        chrome.storage.local.get(["studioTtsConfig"], (res) => {
            if (res && res.studioTtsConfig) {
                applyConfigFromPopup(res.studioTtsConfig);
            }
        });
    }
})();
