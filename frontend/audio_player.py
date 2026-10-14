"""Controlador de reproducción de audio con soporte WSLg PulseAudio y pausa instantánea (buffer=256)."""

import os
import sys
import glob
import time
import ctypes
import platform

# Configurar PulseAudio de WSLg antes de importar pygame para evitar errores de ALSA card 0
if platform.system() == "Linux" and os.path.exists("/mnt/wslg/PulseServer"):
    os.environ.setdefault("PULSE_SERVER", "unix:/mnt/wslg/PulseServer")
    os.environ.setdefault("SDL_AUDIODRIVER", "pulseaudio")
    site_pkgs = [p for p in sys.path if "site-packages" in p]
    for sp in site_pkgs:
        libs_dir = os.path.join(sp, "pygame.libs")
        if os.path.isdir(libs_dir):
            for pattern, link_name in [
                ("libpulsecommon-*.so*", None),
                ("libpulse-*.so*", "libpulse.so.0"),
                ("libpulse-simple-*.so*", "libpulse-simple.so.0"),
            ]:
                matches = glob.glob(os.path.join(libs_dir, pattern))
                if matches:
                    target = matches[0]
                    if link_name:
                        link_path = os.path.join(libs_dir, link_name)
                        if not os.path.exists(link_path):
                            try:
                                os.symlink(os.path.basename(target), link_path)
                            except OSError:
                                pass
                        target = link_path
                    try:
                        ctypes.CDLL(target, mode=ctypes.RTLD_GLOBAL)
                    except OSError:
                        pass

import pygame


class AudioPlayerController:
    """Encapsula pygame.mixer con corte inmediato de buffer para pausar/buscar sin retraso."""

    def __init__(self):
        self.mixer_ready = False
        self.is_playing = False
        self.is_paused = False
        self.is_muted = False
        self.volume = 0.85
        self.audio_duration = 0.0
        self.play_start_wall = 0.0
        self.play_offset = 0.0
        self.current_file = ""
        self.init_mixer()

    def init_mixer(self) -> bool:
        try:
            pygame.mixer.pre_init(frequency=24000, size=-16, channels=1, buffer=256)
            pygame.mixer.init(frequency=24000, size=-16, channels=1, buffer=256)
            pygame.mixer.music.set_volume(self.volume)
            self.mixer_ready = True
        except Exception as e:
            print(f"Advertencia: No se pudo iniciar pygame.mixer ({e})")
            self.mixer_ready = False
        return self.mixer_ready

    def load_file(self, filepath: str) -> bool:
        if not self.mixer_ready and not self.init_mixer():
            return False
        if not os.path.exists(filepath):
            return False
        try:
            if self.is_playing:
                pygame.mixer.music.stop()
            snd = pygame.mixer.Sound(filepath)
            self.audio_duration = max(0.1, float(snd.get_length()))
            pygame.mixer.music.load(filepath)
            self.current_file = filepath
            self.play_offset = 0.0
            self.is_playing = False
            self.is_paused = False
            return True
        except Exception as e:
            print(f"Error cargando archivo WAV en reproductor: {e}")
            return False

    def get_current_pos(self) -> float:
        if not self.is_playing or self.is_paused:
            return self.play_offset
        elapsed = time.time() - self.play_start_wall
        return min(self.audio_duration, self.play_offset + elapsed)

    def toggle_play_pause(self, filepath: str) -> str:
        """Alterna Play/Pause con vaciado inmediato de buffer. Retorna 'playing', 'paused' o 'error'."""
        if not self.mixer_ready and not self.init_mixer():
            return "no_device"
        if not os.path.exists(filepath):
            return "no_file"
        if self.audio_duration <= 0.1 or self.current_file != filepath:
            if not self.load_file(filepath):
                return "error"

        try:
            if self.is_playing and not self.is_paused:
                exact_pos = self.get_current_pos()
                pygame.mixer.music.stop()
                self.play_offset = exact_pos
                self.is_paused = True
                return "paused"
            else:
                if self.play_offset >= self.audio_duration - 0.12:
                    self.play_offset = 0.0
                pygame.mixer.music.load(filepath)
                pygame.mixer.music.play(start=self.play_offset)
                pygame.mixer.music.set_volume(0.0 if self.is_muted else self.volume)
                self.play_start_wall = time.time()
                self.is_playing = True
                self.is_paused = False
                return "playing"
        except Exception as e:
            print(f"Error en reproducción: {e}")
            return "error"

    def seek_to_percent(self, pct: float) -> float:
        if self.audio_duration <= 0 or not self.mixer_ready:
            return 0.0
        self.play_offset = max(0.0, min(self.audio_duration - 0.05, (pct / 100.0) * self.audio_duration))
        if self.is_playing and not self.is_paused:
            try:
                pygame.mixer.music.play(start=self.play_offset)
                self.play_start_wall = time.time()
            except Exception:
                pass
        return self.play_offset

    def set_volume(self, val: float) -> bool:
        self.volume = max(0.0, min(1.0, float(val)))
        self.is_muted = self.volume == 0.0
        if self.mixer_ready:
            pygame.mixer.music.set_volume(0.0 if self.is_muted else self.volume)
        return self.is_muted

    def toggle_mute(self) -> bool:
        self.is_muted = not self.is_muted
        if self.mixer_ready:
            pygame.mixer.music.set_volume(0.0 if self.is_muted else self.volume)
        return self.is_muted

    def is_busy(self) -> bool:
        return bool(self.mixer_ready and pygame.mixer.music.get_busy())

    def stop(self) -> None:
        if self.mixer_ready:
            try:
                pygame.mixer.music.stop()
            except Exception:
                pass
        self.is_playing = False
        self.is_paused = False
        self.play_offset = 0.0
