"""Controlador de reproducción de audio multiplataforma con liberación segura de descriptores WAV."""

import os
import sys
import glob
import time
import wave
import ctypes
import platform

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
    """Encapsula pygame.mixer con liberación explícita de archivos para evitar bloqueos en Windows."""

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
        self.current_mtime = 0.0
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

    @staticmethod
    def _get_wav_duration(filepath: str) -> float:
        """Calcula la duración leyendo únicamente la cabecera WAV sin duplicar el buffer en RAM."""
        try:
            with wave.open(filepath, "rb") as wf:
                frames = wf.getnframes()
                rate = wf.getframerate()
                if rate > 0:
                    return max(0.1, float(frames) / float(rate))
        except Exception:
            pass
        snd = pygame.mixer.Sound(filepath)
        return max(0.1, float(snd.get_length()))

    def stop(self) -> None:
        """Detiene la reproducción actual, reinicia la posición y libera el archivo WAV en el mixer."""
        if self.mixer_ready:
            try:
                pygame.mixer.music.stop()
                if hasattr(pygame.mixer.music, "unload"):
                    pygame.mixer.music.unload()
            except Exception:
                pass
        self.is_playing = False
        self.is_paused = False
        self.play_offset = 0.0
        self.current_file = ""
        self.current_mtime = 0.0

    def release_file(self) -> None:
        """Alias compatible con stop(): detiene y descarga el archivo actual del mixer."""
        self.stop()

    def pause(self) -> None:
        """Pausa la reproducción actual conservando la posición exacta."""
        if not self.mixer_ready or not self.is_playing or self.is_paused:
            return
        try:
            exact_pos = self.get_current_pos()
            pygame.mixer.music.stop()
            self.play_offset = exact_pos
            self.is_paused = True
        except Exception:
            pass

    def load_file(self, filepath: str, preserve_offset: bool = False) -> bool:
        if not self.mixer_ready and not self.init_mixer():
            return False
        if not os.path.exists(filepath):
            return False
        try:
            saved_offset = self.play_offset if preserve_offset else 0.0
            self.stop()
            self.audio_duration = self._get_wav_duration(filepath)
            pygame.mixer.music.load(filepath)
            self.current_file = filepath
            try:
                self.current_mtime = os.path.getmtime(filepath)
            except OSError:
                self.current_mtime = time.time()
            self.play_offset = min(saved_offset, max(0.0, self.audio_duration - 0.05))
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
        pos = min(self.audio_duration, self.play_offset + elapsed)
        if pos >= self.audio_duration - 0.05:
            self.is_playing = False
            self.is_paused = False
            self.play_offset = self.audio_duration
        return pos

    def toggle_play_pause(self, filepath: str) -> str:
        """Alterna Play/Pause liberando o recargando de forma segura. Retorna 'playing', 'paused' o 'error'."""
        if not self.mixer_ready and not self.init_mixer():
            return "no_device"
        if not os.path.exists(filepath):
            return "no_file"

        try:
            file_mtime = os.path.getmtime(filepath)
        except OSError:
            file_mtime = 0.0

        file_changed = abs(file_mtime - self.current_mtime) > 1e-3 if self.current_mtime > 0 else False
        if self.audio_duration <= 0.1 or self.current_file != filepath or file_changed:
            if not self.load_file(filepath, preserve_offset=not file_changed):
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