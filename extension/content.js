/**
 * Studio TTS LatAm — Extensión Universal y Narrador de Novelas (WTR-Lab & Web) v3.1
 *
 * - Reproducción y barra flotante DESACTIVADAS por defecto para nunca ser intrusivas.
 * - Inspector DOM tipo Brave DevTools (Ctrl+Shift+X o desde el Popup/Widget):
 *   resalta contenedores/grupos de etiquetas al pasar el mouse, muestra el selector CSS
 *   y la cantidad de bloques detectados, y al hacer clic extrae únicamente ese grupo.
 * - Sincronizado en tiempo real con popup.html/popup.js y con el Backend local (127.0.0.1:8000).
 * - Respeta el control total del usuario sobre modelos y modos, avisando con toast transitorio
 *   si se elige un modelo GGUF sin soporte Zero-Shot nativo.
 */

(function () {
    "use strict";

    if (window.__studioTtsLatAmInjected) return;
    window.__studioTtsLatAmInjected = true;

    const DEFAULT_API_BASE = "http://127.0.0.1:8000";

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
        ".studio-tts-widget", ".ads", ".ad", ".advertisement", "[class*='advert']",
        ".comments", "#comments", ".comment-section", ".disqus",
        ".chapter-nav", ".chapter-actions", ".pagination", ".pager", ".breadcrumb",
        ".toc", ".table-of-contents", ".sidebar", ".social-share", ".share-buttons",
        ".author-note", ".translator-note", "[role='navigation']", "[aria-hidden='true']"
    ];

    const state = {
        apiBase: DEFAULT_API_BASE,
        enabled: false,         // Desactivada por defecto
        showWidget: false,      // No mostrar widget flotante hasta que el usuario active la extensión
        minimized: false,
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
        sourceMode: "chapter", // "chapter" | "selection" | "picked" | "selector"
        ttsMode: "clone",      // "clone" | "tts" | "design"
        modelId: "omnivoice-zeroshot-0.6b",
        referenceFile: "base_voice.mp3",
        speakerHint: "maria",
        voiceDescription: "Voz femenina joven de 23 años, cálida, clara y natural con acento argentino",
        styleInstruct: "",
        speed: 1.0,
        numStep: 12,
        chunkSize: 320,
        prefetchCache: new Map(),
        activeBlobUrl: null,
        highlightedEl: null,
        inspectorHoverEl: null,
        inspectorTooltipEl: null,
        statusPollTimer: null,
        statusText: "⏹ Reproducción en espera (desactivada por defecto)",
        modelsMeta: {}
    };

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
                if (el.closest("#studio-tts-widget")) continue;
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
            if (el.closest("#studio-tts-widget")) continue;
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

    function extractChapterChunks(maxChars = 320) {
        const selText = window.getSelection ? window.getSelection().toString().trim() : "";
        if (state.sourceMode === "selection" || selText.length > 15) {
            if (!selText) return [];
            return splitTextIntoNaturalChunks(selText, maxChars).map((text) => ({
                text,
                element: null
            }));
        }

        const noiseSelectorJoined = NOISE_SELECTORS.join(", ");
        const paragraphs = [];

        // Si el usuario definió un selector CSS de grupo de etiquetas (ej: ".chapter-body p" o "article p")
        if (state.cssSelector && state.cssSelector.trim()) {
            try {
                const matchedNodes = Array.from(document.querySelectorAll(state.cssSelector.trim()))
                    .filter((n) => !n.closest("#studio-tts-widget") && !n.closest(noiseSelectorJoined));
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

    function setStatusText(txt) {
        state.statusText = txt;
        const statusEl = document.getElementById("studio-tts-status");
        if (statusEl) statusEl.textContent = txt;
    }

    function requestChunkAudioBlob(index) {
        if (index < 0 || index >= state.chunks.length) {
            return Promise.reject(new Error("Índice fuera de rango"));
        }
        if (state.prefetchCache.has(index)) {
            return state.prefetchCache.get(index);
        }

        const chunkObj = state.chunks[index];
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
            speed: Number(state.speed) || 1.0,
            temperature: 0.6,
            top_k: 50
        };

        const promise = (async () => {
            const response = await fetch(`${state.apiBase}/tts`, {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify(payload)
            });

            if (!response.ok) {
                let errDetail = `Error HTTP ${response.status}`;
                try {
                    const errJson = await response.json();
                    errDetail = errJson.detail || errDetail;
                } catch (_e) {}
                throw new Error(errDetail);
            }

            const wavResp = await fetch(`${state.apiBase}/download?t=${Date.now()}_${index}`);
            if (!wavResp.ok) {
                throw new Error("No se pudo descargar el audio WAV generado.");
            }
            return await wavResp.blob();
        })();

        state.prefetchCache.set(index, promise);
        promise.catch(() => {
            state.prefetchCache.delete(index);
        });
        return promise;
    }

    // =========================================================================
    // INSPECTOR DOM ESTILO BRAVE DEVTOOLS (Ctrl+Shift+X / Botón Inspector)
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
        ensureWidgetExists();
        state.pickingElement = true;
        const pickBtn = document.getElementById("studio-tts-pick-btn");
        if (pickBtn) pickBtn.classList.add("active");
        setStatusText("🎯 Inspector DOM activo (ESC para cancelar): pasa el mouse y haz clic en el grupo de etiquetas...");
    }

    function stopDomInspector() {
        state.pickingElement = false;
        const pickBtn = document.getElementById("studio-tts-pick-btn");
        if (pickBtn) pickBtn.classList.remove("active");
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
        if (!target || target.closest("#studio-tts-widget") || target.classList.contains("studio-tts-inspector-tooltip")) {
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
                setStatusText("Modo Inspector DOM cancelado.");
            } else {
                state.enabled = true;
                state.showWidget = true;
                updateWidgetVisibility();
                startDomInspector();
            }
        } else if (ev.key === "Escape" && state.pickingElement) {
            stopDomInspector();
            setStatusText("Modo Inspector DOM cancelado.");
        }
    }, true);

    document.addEventListener("click", (ev) => {
        if (!state.pickingElement) return;
        if (ev.target.closest("#studio-tts-widget")) return;
        ev.preventDefault();
        ev.stopPropagation();

        const clickedEl = state.inspectorHoverEl || ev.target;
        stopDomInspector();

        // Determinar si el usuario clickeó un párrafo individual dentro de un grupo o un contenedor
        const isParagraph = ["P", "LI", "BLOCKQUOTE", "H1", "H2", "H3"].includes(clickedEl.tagName);
        const container = isParagraph
            ? (clickedEl.closest(".chapter-body, .chapter-content, #chapter-content, article, section, main, div") || clickedEl.parentElement)
            : clickedEl;

        state.customContainer = container;
        const containerSel = buildCssSelectorForElement(container);
        state.cssSelector = isParagraph ? `${containerSel} ${clickedEl.tagName.toLowerCase()}` : containerSel;
        state.selectorDescription = state.cssSelector;
        state.sourceMode = "picked";

        const sourceSel = document.getElementById("studio-tts-source");
        if (sourceSel) sourceSel.value = "picked";

        state.chunks = extractChapterChunks(state.chunkSize);
        state.prefetchCache.clear();

        let foundIdx = 0;
        if (isParagraph) {
            const clickedText = (clickedEl.innerText || "").replace(/\s+/g, " ").trim().slice(0, 60);
            if (clickedText) {
                const matchIdx = state.chunks.findIndex((c) => c.text.includes(clickedText));
                if (matchIdx >= 0) foundIdx = matchIdx;
            }
        }
        state.currentIndex = foundIdx;
        setStatusText(`🎯 Grupo seleccionado (${state.cssSelector}): ${state.chunks.length} bloques listos (En espera, pulsa ▶ para reproducir)`);

        const previewEl = document.getElementById("studio-tts-preview");
        if (previewEl && state.chunks[foundIdx]) {
            previewEl.textContent = `[${foundIdx + 1}/${state.chunks.length}] ${state.chunks[foundIdx].text.slice(0, 110)}...`;
        }

        if (typeof chrome !== "undefined" && chrome.storage && chrome.storage.local) {
            chrome.storage.local.get(["studioTtsConfig"], (res) => {
                const cfg = res.studioTtsConfig || {};
                cfg.cssSelector = state.cssSelector;
                chrome.storage.local.set({ studioTtsConfig: cfg });
            });
        }
    }, true);

    // =========================================================================
    // WIDGET FLOTANTE Y CONTROLES DE REPRODUCCIÓN
    // =========================================================================
    function ensureWidgetExists() {
        if (!document.getElementById("studio-tts-widget")) {
            createFloatingWidget();
        }
    }

    function updateWidgetVisibility() {
        ensureWidgetExists();
        const w = document.getElementById("studio-tts-widget");
        if (!w) return;
        w.style.display = (state.enabled && state.showWidget) ? "block" : "none";
    }

    function createFloatingWidget() {
        if (document.getElementById("studio-tts-widget")) return;

        const widget = document.createElement("div");
        widget.id = "studio-tts-widget";
        widget.className = "studio-tts-widget";
        widget.style.display = (state.enabled && state.showWidget) ? "block" : "none";

        widget.innerHTML = `
            <div class="studio-tts-header" id="studio-tts-drag-handle">
                <div class="studio-tts-brand">
                    <span class="studio-tts-title">🎙️ Studio TTS LatAm</span>
                    <span id="studio-tts-badge" class="studio-tts-badge">v3.1</span>
                </div>
                <div class="studio-tts-header-btns">
                    <button id="studio-tts-pick-btn" class="studio-tts-icon-btn" title="Inspeccionar grupo de etiquetas (Ctrl+Shift+X)">🎯</button>
                    <button id="studio-tts-cfg-btn" class="studio-tts-icon-btn" title="Mostrar/Ocultar Ajustes Avanzados">⚙️</button>
                    <button id="studio-tts-min-btn" class="studio-tts-icon-btn" title="Minimizar/Expandir">➖</button>
                </div>
            </div>

            <div id="studio-tts-body" class="studio-tts-body">
                <div class="studio-tts-row">
                    <select id="studio-tts-source" class="studio-tts-select" title="Qué contenido leer de la página">
                        <option value="chapter" selected>📖 Narrar Capítulo / Artículo Limpio</option>
                        <option value="selection">✂️ Solo Texto Seleccionado</option>
                        <option value="picked">🎯 Grupo Inspeccionado (Ctrl+Shift+X)</option>
                    </select>
                    <select id="studio-tts-mode" class="studio-tts-select" title="Modo de Síntesis">
                        <option value="clone" selected>🎙️ Clonar Voz</option>
                        <option value="tts">🗣️ Voz Nativa</option>
                        <option value="design">✨ Diseño Voz</option>
                    </select>
                </div>

                <div id="studio-tts-adv-panel" class="studio-tts-adv-panel" style="display:none;">
                    <div class="studio-tts-field">
                        <label>Selector CSS de Etiquetas:</label>
                        <input id="studio-tts-css-input" type="text" class="studio-tts-input" placeholder="Ej: .chapter-body p, article p" />
                    </div>
                    <div class="studio-tts-field">
                        <label>Modelo IA:</label>
                        <select id="studio-tts-model" class="studio-tts-select-full">
                            <option value="omnivoice-zeroshot-0.6b">OmniVoice Zero-Shot 0.6B (GPU Rápido)</option>
                            <option value="canopy-es-multivoz-q4">Canopy Orpheus Español Multi-Voz Q4</option>
                            <option value="canopy-es-ultralight-q2">Canopy Orpheus Ultra-Ligero Q2_K</option>
                            <option value="orpheus-es-conversacional-q4">Orpheus Español Conversacional Q4</option>
                        </select>
                    </div>
                    <div class="studio-tts-row">
                        <div class="studio-tts-field" style="flex:1;">
                            <label>Audio Base (Clon):</label>
                            <select id="studio-tts-ref" class="studio-tts-select-full">
                                <option value="base_voice.mp3">base_voice.mp3</option>
                            </select>
                        </div>
                        <div class="studio-tts-field" style="width:95px;">
                            <label>Voz Nativa:</label>
                            <select id="studio-tts-speaker" class="studio-tts-select-full">
                                <option value="maria">maria</option>
                                <option value="lucia">lucia</option>
                                <option value="sofia">sofia</option>
                                <option value="tara">tara</option>
                                <option value="leah">leah</option>
                                <option value="javi">javi</option>
                                <option value="ninguna">ninguna</option>
                            </select>
                        </div>
                    </div>
                    <div class="studio-tts-row">
                        <div class="studio-tts-field" style="flex:1;">
                            <label>Velocidad: <span id="studio-tts-speed-val">1.0x</span></label>
                            <input id="studio-tts-speed" type="range" min="0.7" max="1.6" step="0.05" value="1.0" />
                        </div>
                        <div class="studio-tts-field" style="flex:1;">
                            <label>Pasos (Rapidez): <span id="studio-tts-steps-val">12</span></label>
                            <input id="studio-tts-steps" type="range" min="6" max="24" step="2" value="12" />
                        </div>
                    </div>
                    <div class="studio-tts-field">
                        <label>Prompt Diseño / Estilo:</label>
                        <input id="studio-tts-prompt" type="text" class="studio-tts-input" placeholder="Ej: voz femenina cálida, narración expresiva" value="Voz femenina joven de 23 años, cálida, clara y natural con acento argentino" />
                    </div>
                    <div class="studio-tts-row" style="justify-content:space-between; align-items:center;">
                        <label class="studio-tts-check-label">
                            <input id="studio-tts-autoadv" type="checkbox" checked />
                            Continuar siguiente párrafo + Pre-cargar
                        </label>
                        <button id="studio-tts-scan-btn" class="studio-tts-mini-btn" title="Re-escanear párrafos de la página">🔄 Escanear</button>
                    </div>
                </div>

                <div id="studio-tts-status" class="studio-tts-status">⏹ Reproducción desactivada por defecto • Pulsa ▶ para iniciar</div>
                <div id="studio-tts-preview" class="studio-tts-preview"></div>

                <div class="studio-tts-transport">
                    <button id="studio-tts-prev-btn" class="studio-tts-ctrl-btn" title="Párrafo Anterior">⏮</button>
                    <button id="local-tts-play-btn" class="tts-floating-btn">▶ Narrar Capítulo</button>
                    <button id="studio-tts-next-btn" class="studio-tts-ctrl-btn" title="Párrafo Siguiente">⏭</button>
                    <button id="studio-tts-stop-btn" class="studio-tts-ctrl-btn studio-tts-stop" title="Detener">⏹</button>
                </div>

                <audio id="studio-tts-audio" class="studio-tts-audio" controls preload="none"></audio>
            </div>
        `;

        document.body.appendChild(widget);
        bindWidgetEvents();
        syncWithBackend();
    }

    async function syncWithBackend() {
        const badge = document.getElementById("studio-tts-badge");
        const modelSel = document.getElementById("studio-tts-model");
        const refSel = document.getElementById("studio-tts-ref");
        try {
            const [stRes, modRes, refRes] = await Promise.all([
                fetch(`${state.apiBase}/status`),
                fetch(`${state.apiBase}/models`),
                fetch(`${state.apiBase}/reference_files`)
            ]);
            if (stRes.ok) {
                const st = await stRes.json();
                const dev = st.device || "online";
                if (badge) {
                    badge.textContent = dev.includes("cuda") ? "⚡ GPU" : "CPU";
                    badge.style.background = dev.includes("cuda") ? "#065f46" : "#1f2937";
                }
            }
            if (modRes.ok && modelSel) {
                const mdata = await modRes.json();
                const list = mdata.models || [];
                if (list.length > 0) {
                    modelSel.innerHTML = "";
                    state.modelsMeta = {};
                    for (const m of list) {
                        state.modelsMeta[m.id] = m;
                        const opt = document.createElement("option");
                        opt.value = m.id;
                        opt.textContent = m.name;
                        modelSel.appendChild(opt);
                    }
                    if (mdata.loaded_model_id && state.modelsMeta[mdata.loaded_model_id]) {
                        state.modelId = mdata.loaded_model_id;
                        modelSel.value = mdata.loaded_model_id;
                    }
                }
            }
            if (refRes.ok && refSel) {
                const rdata = await refRes.json();
                const files = rdata.files || [];
                if (files.length > 0) {
                    refSel.innerHTML = "";
                    for (const f of files) {
                        const opt = document.createElement("option");
                        opt.value = f.name;
                        opt.textContent = `${f.name} (${f.duration}s)`;
                        refSel.appendChild(opt);
                    }
                }
            }
        } catch (_e) {
            if (badge) {
                badge.textContent = "Offline";
                badge.style.background = "#7f1d1d";
            }
        }
    }

    let playChunkAtIndexFn = null;
    let startOrResumePlaybackFn = null;
    let stopPlaybackFn = null;

    function bindWidgetEvents() {
        const bodyEl = document.getElementById("studio-tts-body");
        const minBtn = document.getElementById("studio-tts-min-btn");
        const cfgBtn = document.getElementById("studio-tts-cfg-btn");
        const pickBtn = document.getElementById("studio-tts-pick-btn");
        const advPanel = document.getElementById("studio-tts-adv-panel");
        const cssInput = document.getElementById("studio-tts-css-input");
        const sourceSel = document.getElementById("studio-tts-source");
        const modeSel = document.getElementById("studio-tts-mode");
        const modelSel = document.getElementById("studio-tts-model");
        const refSel = document.getElementById("studio-tts-ref");
        const spkSel = document.getElementById("studio-tts-speaker");
        const speedInput = document.getElementById("studio-tts-speed");
        const speedVal = document.getElementById("studio-tts-speed-val");
        const stepsInput = document.getElementById("studio-tts-steps");
        const stepsVal = document.getElementById("studio-tts-steps-val");
        const promptInput = document.getElementById("studio-tts-prompt");
        const autoAdvChk = document.getElementById("studio-tts-autoadv");
        const scanBtn = document.getElementById("studio-tts-scan-btn");

        const playBtn = document.getElementById("local-tts-play-btn");
        const prevBtn = document.getElementById("studio-tts-prev-btn");
        const nextBtn = document.getElementById("studio-tts-next-btn");
        const stopBtn = document.getElementById("studio-tts-stop-btn");
        const previewEl = document.getElementById("studio-tts-preview");
        const audioEl = document.getElementById("studio-tts-audio");

        minBtn.addEventListener("click", () => {
            state.minimized = !state.minimized;
            bodyEl.style.display = state.minimized ? "none" : "block";
            minBtn.textContent = state.minimized ? "➕" : "➖";
        });

        cfgBtn.addEventListener("click", () => {
            const open = advPanel.style.display !== "none";
            advPanel.style.display = open ? "none" : "block";
        });

        cssInput.addEventListener("change", () => {
            state.cssSelector = cssInput.value.trim();
            state.selectorDescription = state.cssSelector || "Auto-detección de capítulo";
            state.chunks = extractChapterChunks(state.chunkSize);
            state.prefetchCache.clear();
            setStatusText(`✅ Selector '${state.selectorDescription}': ${state.chunks.length} bloques listos`);
        });

        sourceSel.addEventListener("change", () => {
            state.sourceMode = sourceSel.value;
            state.chunks = [];
            state.prefetchCache.clear();
        });

        // Control total del usuario: al cambiar modelo, adaptar por defecto pero permitir reactivar
        modelSel.addEventListener("change", () => {
            state.modelId = modelSel.value;
            const meta = state.modelsMeta[state.modelId] || {};
            const caps = meta.capabilities || {};
            const supportsClone = caps.supports_clone !== undefined ? caps.supports_clone : state.modelId.includes("omnivoice");
            if (!supportsClone && (state.ttsMode === "clone" || state.ttsMode === "design")) {
                state.ttsMode = "tts";
                modeSel.value = "tts";
                setStatusText(`🔔 Incompatibilidad en '${meta.name || state.modelId}': se pasó a Voz Nativa por defecto (puedes reactivar Clonación manualmente).`);
            }
            state.prefetchCache.clear();
        });

        modeSel.addEventListener("change", () => {
            state.ttsMode = modeSel.value;
            const meta = state.modelsMeta[state.modelId] || {};
            const caps = meta.capabilities || {};
            const supportsClone = caps.supports_clone !== undefined ? caps.supports_clone : state.modelId.includes("omnivoice");
            if (!supportsClone && (state.ttsMode === "clone" || state.ttsMode === "design")) {
                setStatusText(`⚠️ Modo ${state.ttsMode.toUpperCase()} forzado por usuario sobre modelo GGUF. Se respetará tu configuración.`);
            }
            state.prefetchCache.clear();
        });

        refSel.addEventListener("change", () => {
            state.referenceFile = refSel.value;
            state.prefetchCache.clear();
        });

        spkSel.addEventListener("change", () => {
            state.speakerHint = spkSel.value;
            state.prefetchCache.clear();
        });

        speedInput.addEventListener("input", () => {
            state.speed = parseFloat(speedInput.value) || 1.0;
            speedVal.textContent = `${state.speed.toFixed(2)}x`;
            state.prefetchCache.clear();
        });

        stepsInput.addEventListener("input", () => {
            state.numStep = parseInt(stepsInput.value, 10) || 12;
            stepsVal.textContent = String(state.numStep);
            state.prefetchCache.clear();
        });

        promptInput.addEventListener("change", () => {
            state.voiceDescription = promptInput.value.trim();
            state.styleInstruct = promptInput.value.trim();
            state.prefetchCache.clear();
        });

        autoAdvChk.addEventListener("change", () => {
            state.autoAdvance = autoAdvChk.checked;
        });

        scanBtn.addEventListener("click", () => {
            state.chunks = extractChapterChunks(state.chunkSize);
            state.currentIndex = 0;
            state.prefetchCache.clear();
            setStatusText(`✅ Escaneados ${state.chunks.length} fragmentos narrativos limpios.`);
            if (state.chunks.length > 0) {
                previewEl.textContent = `[1/${state.chunks.length}] ${state.chunks[0].text.slice(0, 110)}...`;
            }
        });

        pickBtn.addEventListener("click", () => {
            if (state.pickingElement) {
                stopDomInspector();
                setStatusText("Modo Inspector DOM cancelado.");
            } else {
                startDomInspector();
            }
        });

        async function playChunkAtIndex(idx) {
            if (state.stopRequested || idx < 0 || idx >= state.chunks.length) {
                finishPlayback();
                return;
            }

            state.currentIndex = idx;
            const currentChunk = state.chunks[idx];
            highlightActiveElement(currentChunk.element);
            previewEl.textContent = `[${idx + 1}/${state.chunks.length}] ${currentChunk.text}`;

            playBtn.textContent = `⏳ Generando (${idx + 1}/${state.chunks.length})...`;
            setStatusText(`Sintetizando fragmento ${idx + 1} de ${state.chunks.length}...`);

            if (state.statusPollTimer) clearInterval(state.statusPollTimer);
            state.statusPollTimer = setInterval(async () => {
                try {
                    const stRes = await fetch(`${state.apiBase}/status`);
                    if (stRes.ok) {
                        const st = await stRes.json();
                        if (st.status === "GENERATING" && st.message) {
                            setStatusText(st.message);
                        }
                    }
                } catch (_e) {}
            }, 900);

            try {
                const wavBlob = await requestChunkAudioBlob(idx);
                if (state.stopRequested) return;

                if (state.autoAdvance && idx + 1 < state.chunks.length) {
                    requestChunkAudioBlob(idx + 1).catch(() => {});
                }

                revokeActiveBlob();
                const blobUrl = URL.createObjectURL(wavBlob);
                state.activeBlobUrl = blobUrl;

                audioEl.volume = Math.max(0, Math.min(1, Number(state.volume ?? 1.0)));
                audioEl.src = blobUrl;
                audioEl.style.display = "block";
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
                playBtn.textContent = "⏸ Pausar";
                setStatusText(`🔊 Narrando párrafo ${idx + 1} de ${state.chunks.length}`);
                await audioEl.play();
            } catch (err) {
                console.error("[Studio TTS LatAm Extension]", err);
                setStatusText(`❌ ${err.message || "Backend offline en 127.0.0.1:8000"}`);
                state.isPlaying = false;
                playBtn.textContent = "▶ Reintentar";
            } finally {
                if (state.statusPollTimer) {
                    clearInterval(state.statusPollTimer);
                    state.statusPollTimer = null;
                }
            }
        }

        function finishPlayback() {
            state.isPlaying = false;
            state.isPaused = false;
            clearHighlight();
            playBtn.textContent = "▶ Narrar Capítulo";
            setStatusText("✅ Lectura finalizada");
        }

        function startOrResumePlayback(forceRestart = false) {
            if (!forceRestart && state.isPlaying && !state.isPaused && !audioEl.paused) {
                audioEl.pause();
                state.isPaused = true;
                playBtn.textContent = "⏸ Pausado • ▶ Continuar";
                setStatusText(`⏸ Pausado en [${state.currentIndex + 1}/${state.chunks.length}]`);
                return;
            }

            if (!forceRestart && state.isPlaying && state.isPaused) {
                state.isPaused = false;
                playBtn.textContent = "⏸ Pausar";
                setStatusText(`🔊 Narrando [${state.currentIndex + 1}/${state.chunks.length}]`);
                audioEl.play();
                return;
            }

            state.stopRequested = false;
            if (state.chunks.length === 0 || forceRestart) {
                state.chunks = extractChapterChunks(state.chunkSize);
                if (!forceRestart) state.currentIndex = 0;
            }

            if (state.chunks.length === 0) {
                setStatusText("⚠️ No se detectó texto narrativo en esta página.");
                return;
            }

            playChunkAtIndex(state.currentIndex);
        }

        function stopPlayback() {
            state.stopRequested = true;
            state.isPlaying = false;
            state.isPaused = false;
            if (state.statusPollTimer) {
                clearInterval(state.statusPollTimer);
                state.statusPollTimer = null;
            }
            try {
                audioEl.pause();
                audioEl.currentTime = 0;
            } catch (_e) {}
            revokeActiveBlob();
            clearHighlight();
            playBtn.textContent = "▶ Narrar Capítulo";
            setStatusText("⏹ Lectura detenida");
        }

        playChunkAtIndexFn = playChunkAtIndex;
        startOrResumePlaybackFn = startOrResumePlayback;
        stopPlaybackFn = stopPlayback;

        playBtn.addEventListener("click", () => startOrResumePlayback(false));

        prevBtn.addEventListener("click", () => {
            if (state.chunks.length === 0) {
                state.chunks = extractChapterChunks(state.chunkSize);
            }
            if (state.chunks.length === 0) return;
            state.stopRequested = false;
            const prevIdx = Math.max(0, state.currentIndex - 1);
            playChunkAtIndex(prevIdx);
        });

        nextBtn.addEventListener("click", () => {
            if (state.chunks.length === 0) {
                state.chunks = extractChapterChunks(state.chunkSize);
            }
            if (state.chunks.length === 0) return;
            state.stopRequested = false;
            const nextIdx = Math.min(state.chunks.length - 1, state.currentIndex + 1);
            playChunkAtIndex(nextIdx);
        });

        stopBtn.addEventListener("click", stopPlayback);
    }

    // =========================================================================
    // MENSAJERÍA CON EL POPUP DE CONTROL DE LA EXTENSIÓN (popup.js)
    // =========================================================================
    function applyConfigFromPopup(cfg) {
        if (!cfg) return;
        const wasEnabled = state.enabled;
        state.enabled = Boolean(cfg.enabled);
        state.showWidget = Boolean(cfg.showWidget);
        if (typeof cfg.cssSelector === "string") {
            state.cssSelector = cfg.cssSelector;
            state.selectorDescription = cfg.cssSelector || "Auto-detección de capítulo";
            const cssInput = document.getElementById("studio-tts-css-input");
            if (cssInput) cssInput.value = cfg.cssSelector;
        }
        if (typeof cfg.volume === "number") {
            state.volume = cfg.volume;
            const audioEl = document.getElementById("studio-tts-audio");
            if (audioEl) audioEl.volume = Math.max(0, Math.min(1, cfg.volume));
        }
        if (typeof cfg.speed === "number") {
            state.speed = cfg.speed;
        }
        if (cfg.modelId) state.modelId = cfg.modelId;
        if (cfg.ttsMode) state.ttsMode = cfg.ttsMode;
        if (cfg.referenceFile) state.referenceFile = cfg.referenceFile;
        if (cfg.speakerHint) state.speakerHint = cfg.speakerHint;
        if (typeof cfg.autoAdvance === "boolean") state.autoAdvance = cfg.autoAdvance;

        state.prefetchCache.clear();
        updateWidgetVisibility();

        if (wasEnabled && !state.enabled && stopPlaybackFn) {
            stopPlaybackFn();
        }
    }

    if (typeof chrome !== "undefined" && chrome.runtime && chrome.runtime.onMessage) {
        chrome.runtime.onMessage.addListener((msg, _sender, sendResponse) => {
            if (!msg || !msg.type) return false;

            ensureWidgetExists();

            if (msg.type === "STUDIO_TTS_GET_STATE") {
                if (state.chunks.length === 0) {
                    state.chunks = extractChapterChunks(state.chunkSize);
                }
                sendResponse({
                    enabled: state.enabled,
                    isPlaying: state.isPlaying,
                    isPaused: state.isPaused,
                    chunksCount: state.chunks.length,
                    currentIndex: state.currentIndex,
                    cssSelector: state.cssSelector,
                    selectorDescription: state.selectorDescription,
                    statusText: state.statusText
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
                state.showWidget = true;
                updateWidgetVisibility();
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
                state.prefetchCache.clear();
                setStatusText(`🎯 Selector '${state.selectorDescription}': ${state.chunks.length} bloques listos`);
                sendResponse({ ok: state.chunks.length > 0, chunksCount: state.chunks.length });
                return true;
            }

            if (msg.type === "STUDIO_TTS_COMMAND") {
                state.enabled = true;
                updateWidgetVisibility();
                if (msg.action === "play_pause" && startOrResumePlaybackFn) {
                    startOrResumePlaybackFn(false);
                } else if (msg.action === "prev" && playChunkAtIndexFn) {
                    if (state.chunks.length === 0) state.chunks = extractChapterChunks(state.chunkSize);
                    playChunkAtIndexFn(Math.max(0, state.currentIndex - 1));
                } else if (msg.action === "next" && playChunkAtIndexFn) {
                    if (state.chunks.length === 0) state.chunks = extractChapterChunks(state.chunkSize);
                    playChunkAtIndexFn(Math.min(state.chunks.length - 1, state.currentIndex + 1));
                } else if (msg.action === "stop" && stopPlaybackFn) {
                    stopPlaybackFn();
                }
                sendResponse({ ok: true });
                return true;
            }

            return false;
        });
    }

    function initFromStorage() {
        createFloatingWidget();
        if (typeof chrome !== "undefined" && chrome.storage && chrome.storage.local) {
            chrome.storage.local.get(["studioTtsConfig"], (res) => {
                if (res && res.studioTtsConfig) {
                    applyConfigFromPopup(res.studioTtsConfig);
                }
            });
        }
    }

    if (document.readyState === "loading") {
        document.addEventListener("DOMContentLoaded", initFromStorage);
    } else {
        initFromStorage();
    }
})();
