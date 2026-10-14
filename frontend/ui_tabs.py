"""Construcción modular y responsive de las pestañas de configuración del frontend CustomTkinter."""

import os
import customtkinter as ctk
from constants import (
    LANGUAGE_CHOICES,
    load_local_transcripts,
    scan_local_ref_files,
)


def build_voice_tab(app, tab_parent: ctk.CTkFrame) -> None:
    """Construye la Pestaña 1: Configuración de Voz, Clonación Zero-Shot y Estilo con layout 100% responsive."""
    tab_parent.grid_columnconfigure(0, weight=1)

    app.lbl_mode_desc = ctk.CTkLabel(
        tab_parent,
        text="🎙️ MODO CLONACIÓN ACTIVO: Usa OmniVoice Zero-Shot (GPU) con la transcripción real del Audio Base para clonar su voz exacta.",
        text_color="#34d399",
        font=("Helvetica", 12, "bold"),
        anchor="w",
        justify="left",
        wraplength=760,
    )
    app.lbl_mode_desc.grid(row=0, column=0, padx=8, pady=(4, 4), sticky="ew")

    # Caja de Audio de Referencia
    app.frame_ref_box = ctk.CTkFrame(tab_parent, corner_radius=8, fg_color="#1f2937")
    app.frame_ref_box.grid(row=1, column=0, padx=8, pady=3, sticky="ew")
    app.frame_ref_box.grid_columnconfigure(1, weight=1)

    row_ref1 = ctk.CTkFrame(app.frame_ref_box, fg_color="transparent")
    row_ref1.grid(row=0, column=0, columnspan=2, padx=10, pady=(6, 2), sticky="ew")
    row_ref1.grid_columnconfigure(1, weight=1)

    ctk.CTkLabel(
        row_ref1,
        text="🎙️ Audio Base a Clonar:",
        font=("Helvetica", 12, "bold"),
    ).grid(row=0, column=0, padx=(0, 6), pady=2, sticky="w")

    ref_choices = scan_local_ref_files()
    app.opt_ref_file = ctk.CTkOptionMenu(
        row_ref1,
        values=ref_choices,
        width=180,
        dynamic_resizing=False,
        command=app.on_select_ref_dropdown,
    )
    app.opt_ref_file.set("base_voice.mp3")
    app.opt_ref_file.grid(row=0, column=1, padx=(0, 6), pady=2, sticky="ew")

    app.btn_voice = ctk.CTkButton(
        row_ref1,
        text="📂 Subir MP3/WAV",
        command=app.upload_voice,
        width=128,
        height=28,
        corner_radius=6,
    )
    app.btn_voice.grid(row=0, column=2, padx=3, pady=2)

    app.btn_preview_ref = ctk.CTkButton(
        row_ref1,
        text="🎧 Escuchar Base",
        width=128,
        height=28,
        corner_radius=6,
        fg_color="#374151",
        hover_color="#4b5563",
        command=app.preview_reference_voice,
    )
    app.btn_preview_ref.grid(row=0, column=3, padx=3, pady=2)

    app.chk_xvector = ctk.CTkCheckBox(
        row_ref1,
        text="Auto-Transcribir (Whisper)",
        font=("Helvetica", 11),
        checkbox_width=18,
        checkbox_height=18,
    )
    app.chk_xvector.select()
    app.chk_xvector.grid(row=0, column=4, padx=(6, 0), pady=2, sticky="e")

    app.lbl_voice = ctk.CTkLabel(
        app.frame_ref_box,
        text=f"Archivo activo: {os.path.basename(app.reference_audio_path)} ({app.reference_audio_path})",
        text_color="#9ca3af",
        font=("Consolas", 10),
        anchor="w",
        justify="left",
        wraplength=740,
    )
    app.lbl_voice.grid(row=1, column=0, columnspan=2, padx=10, pady=(0, 2), sticky="ew")

    row_ref2 = ctk.CTkFrame(app.frame_ref_box, fg_color="transparent")
    row_ref2.grid(row=2, column=0, columnspan=2, padx=10, pady=(2, 6), sticky="ew")
    row_ref2.grid_columnconfigure(1, weight=1)

    ctk.CTkLabel(
        row_ref2,
        text="Transcripción del Audio Base:",
        font=("Helvetica", 11, "bold"),
    ).grid(row=0, column=0, padx=(0, 6), pady=2, sticky="w")

    app.entry_ref_text = ctk.CTkEntry(
        row_ref2,
        placeholder_text="Texto exacto dicho en el audio de referencia (se autocompleta con Whisper)...",
        height=28,
    )
    tmap = load_local_transcripts()
    default_tr = tmap.get(
        "base_voice.mp3",
        "Hola, soy Barbie, qué lindo tenerte por acá. Si buscas una voz cálida, cercana y natural, me encantaría darle vida a tu proyecto.",
    )
    app.entry_ref_text.insert(0, default_tr)
    app.entry_ref_text.grid(row=0, column=1, pady=2, sticky="ew")

    # Fila Idioma + Voz Predefinida (en Grid flexible para no cortar nunca)
    row_lang_spk = ctk.CTkFrame(tab_parent, fg_color="transparent")
    row_lang_spk.grid(row=2, column=0, padx=8, pady=4, sticky="ew")
    row_lang_spk.grid_columnconfigure(1, weight=1)
    row_lang_spk.grid_columnconfigure(3, weight=1)

    ctk.CTkLabel(
        row_lang_spk,
        text="🌎 Idioma:",
        font=("Helvetica", 12, "bold"),
    ).grid(row=0, column=0, padx=(0, 6), pady=2, sticky="w")

    app.opt_language = ctk.CTkOptionMenu(
        row_lang_spk,
        values=LANGUAGE_CHOICES,
        dynamic_resizing=False,
    )
    app.opt_language.set("Español (Latinoamérica / Argentina)")
    app.opt_language.grid(row=0, column=1, padx=(0, 12), pady=2, sticky="ew")

    ctk.CTkLabel(
        row_lang_spk,
        text="🗣️ Voz Nativa (Modo Texto a Voz):",
        font=("Helvetica", 12, "bold"),
    ).grid(row=0, column=2, padx=(0, 6), pady=2, sticky="w")

    app.opt_speaker = ctk.CTkOptionMenu(
        row_lang_spk,
        values=["maria", "lucia", "sofia", "tara", "leah", "javi", "ninguna"],
        dynamic_resizing=False,
    )
    app.opt_speaker.set("maria")
    app.opt_speaker.grid(row=0, column=3, pady=2, sticky="ew")

    # Filas de Prompts con soporte multilínea / ancho completo
    row_prompts = ctk.CTkFrame(tab_parent, fg_color="transparent")
    row_prompts.grid(row=3, column=0, padx=8, pady=(2, 4), sticky="ew")
    row_prompts.grid_columnconfigure(1, weight=1)

    ctk.CTkLabel(
        row_prompts,
        text="🎭 Instrucción de Estilo / Emoción:",
        font=("Helvetica", 11, "bold"),
        anchor="w",
    ).grid(row=0, column=0, padx=(0, 8), pady=3, sticky="w")

    app.entry_style_instruct = ctk.CTkEntry(
        row_prompts,
        placeholder_text="Dejar vacío en Clonación para timbre 100% puro, o ej: 'susurro suave'",
        height=28,
    )
    app.entry_style_instruct.grid(row=0, column=1, pady=3, sticky="ew")

    ctk.CTkLabel(
        row_prompts,
        text="✨ Descripción Diseño de Voz:",
        font=("Helvetica", 11, "bold"),
        anchor="w",
    ).grid(row=1, column=0, padx=(0, 8), pady=3, sticky="w")

    app.entry_voice_design = ctk.CTkEntry(
        row_prompts,
        placeholder_text="Ej: Voz femenina joven de 23 años, cálida, clara y natural con acento argentino",
        height=28,
    )
    app.entry_voice_design.insert(
        0, "Voz femenina joven de 23 años, cálida, clara y natural con acento argentino"
    )
    app.entry_voice_design.grid(row=1, column=1, pady=3, sticky="ew")


def build_engine_tab(app, tab_parent: ctk.CTkFrame) -> None:
    """Construye la Pestaña 2: Parámetros de Difusión OmniVoice, Muestreo LLM GGUF y DSP."""
    tab_parent.grid_columnconfigure(0, weight=0, minsize=175)
    tab_parent.grid_columnconfigure(1, weight=1)
    tab_parent.grid_columnconfigure(2, weight=0, minsize=175)
    tab_parent.grid_columnconfigure(3, weight=1)

    ctk.CTkLabel(
        tab_parent,
        text="⚡ Parámetros OmniVoice GPU (Difusión Zero-Shot) & Post-Procesado de Audio:",
        font=("Helvetica", 11, "bold"),
        text_color="#60a5fa",
        anchor="w",
    ).grid(row=0, column=0, columnspan=4, padx=8, pady=(2, 2), sticky="w")

    # Fila 1: Pasos de Difusión + CFG Scale
    app.lbl_steps = ctk.CTkLabel(
        tab_parent, text="Pasos Difusión (12=GPU Rápido): 12", anchor="w", font=("Helvetica", 11)
    )
    app.lbl_steps.grid(row=1, column=0, padx=8, pady=2, sticky="w")
    app.slider_steps = ctk.CTkSlider(
        tab_parent,
        from_=6,
        to=32,
        number_of_steps=26,
        command=lambda v: app.lbl_steps.configure(text=f"Pasos Difusión (12=GPU Rápido): {int(v)}"),
    )
    app.slider_steps.set(12)
    app.slider_steps.grid(row=1, column=1, padx=8, pady=2, sticky="ew")

    app.lbl_cfg = ctk.CTkLabel(
        tab_parent, text="Fidelidad / CFG Scale: 2.0", anchor="w", font=("Helvetica", 11)
    )
    app.lbl_cfg.grid(row=1, column=2, padx=8, pady=2, sticky="w")
    app.slider_cfg = ctk.CTkSlider(
        tab_parent,
        from_=0.5,
        to=5.0,
        number_of_steps=45,
        command=lambda v: app.lbl_cfg.configure(text=f"Fidelidad / CFG Scale: {float(v):.1f}"),
    )
    app.slider_cfg.set(2.0)
    app.slider_cfg.grid(row=1, column=3, padx=8, pady=2, sticky="ew")

    # Fila 2: Pitch Fino + Velocidad
    app.lbl_pitch = ctk.CTkLabel(
        tab_parent, text="Ajuste Tono Fino: +0.0 st", anchor="w", font=("Helvetica", 11)
    )
    app.lbl_pitch.grid(row=2, column=0, padx=8, pady=2, sticky="w")
    app.slider_pitch = ctk.CTkSlider(
        tab_parent,
        from_=-6.0,
        to=6.0,
        number_of_steps=24,
        command=lambda v: app.lbl_pitch.configure(text=f"Ajuste Tono Fino: {float(v):+.1f} st"),
    )
    app.slider_pitch.set(0.0)
    app.slider_pitch.grid(row=2, column=1, padx=8, pady=2, sticky="ew")

    app.lbl_speed = ctk.CTkLabel(
        tab_parent, text="Velocidad de Habla: 1.00x", anchor="w", font=("Helvetica", 11)
    )
    app.lbl_speed.grid(row=2, column=2, padx=8, pady=2, sticky="w")
    app.slider_speed = ctk.CTkSlider(
        tab_parent,
        from_=0.5,
        to=2.0,
        number_of_steps=60,
        command=lambda v: app.lbl_speed.configure(text=f"Velocidad de Habla: {float(v):.2f}x"),
    )
    app.slider_speed.set(1.0)
    app.slider_speed.grid(row=2, column=3, padx=8, pady=2, sticky="ew")

    ctk.CTkLabel(
        tab_parent,
        text="🧠 Parámetros Muestreo LLM (Orpheus GGUF), Semilla y Hilos de CPU:",
        font=("Helvetica", 11, "bold"),
        text_color="#a78bfa",
        anchor="w",
    ).grid(row=3, column=0, columnspan=4, padx=8, pady=(4, 2), sticky="w")

    # Fila 4: Temperatura + Top-K
    app.lbl_temp = ctk.CTkLabel(
        tab_parent, text="Expresividad (Temp): 0.60", anchor="w", font=("Helvetica", 11)
    )
    app.lbl_temp.grid(row=4, column=0, padx=8, pady=2, sticky="w")
    app.slider_temp = ctk.CTkSlider(
        tab_parent,
        from_=0.1,
        to=1.5,
        number_of_steps=70,
        command=lambda v: app.lbl_temp.configure(text=f"Expresividad (Temp): {float(v):.2f}"),
    )
    app.slider_temp.set(0.60)
    app.slider_temp.grid(row=4, column=1, padx=8, pady=2, sticky="ew")

    app.lbl_topk = ctk.CTkLabel(
        tab_parent, text="Top-K: 50", anchor="w", font=("Helvetica", 11)
    )
    app.lbl_topk.grid(row=4, column=2, padx=8, pady=2, sticky="w")
    app.slider_topk = ctk.CTkSlider(
        tab_parent,
        from_=1,
        to=100,
        number_of_steps=99,
        command=lambda v: app.lbl_topk.configure(text=f"Top-K: {int(v)}"),
    )
    app.slider_topk.set(50)
    app.slider_topk.grid(row=4, column=3, padx=8, pady=2, sticky="ew")

    # Fila 5: Top-P + Repeat Penalty
    app.lbl_topp = ctk.CTkLabel(
        tab_parent, text="Top-P (Nucleus): 0.90", anchor="w", font=("Helvetica", 11)
    )
    app.lbl_topp.grid(row=5, column=0, padx=8, pady=2, sticky="w")
    app.slider_topp = ctk.CTkSlider(
        tab_parent,
        from_=0.10,
        to=1.00,
        number_of_steps=45,
        command=lambda v: app.lbl_topp.configure(text=f"Top-P (Nucleus): {float(v):.2f}"),
    )
    app.slider_topp.set(0.90)
    app.slider_topp.grid(row=5, column=1, padx=8, pady=2, sticky="ew")

    app.lbl_reppen = ctk.CTkLabel(
        tab_parent, text="Penaliz. Repetición: 1.12", anchor="w", font=("Helvetica", 11)
    )
    app.lbl_reppen.grid(row=5, column=2, padx=8, pady=2, sticky="w")
    app.slider_reppen = ctk.CTkSlider(
        tab_parent,
        from_=1.00,
        to=1.50,
        number_of_steps=50,
        command=lambda v: app.lbl_reppen.configure(text=f"Penaliz. Repetición: {float(v):.2f}"),
    )
    app.slider_reppen.set(1.12)
    app.slider_reppen.grid(row=5, column=3, padx=8, pady=2, sticky="ew")

    # Fila 6: Max Audio Tokens + Semilla / Hilos / Switches
    app.lbl_maxtok = ctk.CTkLabel(
        tab_parent, text="Máx. Tokens Audio: 700", anchor="w", font=("Helvetica", 11)
    )
    app.lbl_maxtok.grid(row=6, column=0, padx=8, pady=2, sticky="w")
    app.slider_maxtok = ctk.CTkSlider(
        tab_parent,
        from_=140,
        to=1680,
        number_of_steps=220,
        command=lambda v: app.lbl_maxtok.configure(text=f"Máx. Tokens Audio: {int(v)}"),
    )
    app.slider_maxtok.set(700)
    app.slider_maxtok.grid(row=6, column=1, padx=8, pady=2, sticky="ew")

    frame_hw = ctk.CTkFrame(tab_parent, fg_color="transparent")
    frame_hw.grid(row=6, column=2, columnspan=2, padx=8, pady=2, sticky="ew")

    ctk.CTkLabel(frame_hw, text="Seed:", font=("Helvetica", 11)).pack(side="left", padx=(0, 3))
    app.entry_seed = ctk.CTkEntry(frame_hw, width=55, height=24)
    app.entry_seed.insert(0, "-1")
    app.entry_seed.pack(side="left", padx=(0, 8))

    ctk.CTkLabel(frame_hw, text="Hilos CPU:", font=("Helvetica", 11)).pack(side="left", padx=(0, 3))
    app.opt_threads = ctk.CTkOptionMenu(frame_hw, values=["2", "4", "6", "8"], width=58, height=24)
    app.opt_threads.set("6")
    app.opt_threads.pack(side="left", padx=(0, 8))

    app.sw_denoise = ctk.CTkSwitch(
        frame_hw, text="Denoise", font=("Helvetica", 11), switch_width=32, switch_height=16
    )
    app.sw_denoise.select()
    app.sw_denoise.pack(side="left", padx=(0, 6))

    app.sw_autoclone = ctk.CTkSwitch(
        frame_hw, text="Shift +3.5st", font=("Helvetica", 11), switch_width=32, switch_height=16
    )
    app.sw_autoclone.deselect()
    app.sw_autoclone.pack(side="left")
