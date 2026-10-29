"""Thin Qt-friendly wrapper around libVLC that renders into a native widget."""
from __future__ import annotations

from pathlib import Path

from PyQt6.QtCore import QObject, pyqtSignal

from . import config

config.prepare_vlc_env()
import vlc  # noqa: E402  (must come after prepare_vlc_env)


def _decode(name) -> str:
    return name.decode("utf-8", "replace") if isinstance(name, bytes) else str(name)


class VlcPlayer(QObject):
    """One libVLC instance + media player.

    VLC events arrive on VLC's own thread; the callbacks only emit Qt signals (which Qt
    queues onto the GUI thread) and never call back into libVLC, which could deadlock.
    """

    ended = pyqtSignal()
    error = pyqtSignal(str)
    tracks_ready = pyqtSignal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.instance = vlc.Instance(["--no-video-title-show", "--avcodec-hw=any", "--quiet",
                                      "--sub-autodetect-fuzzy=3"])
        if self.instance is None:
            raise RuntimeError("libVLC failed to initialise")
        self.mp = self.instance.media_player_new()
        self.mp.video_set_mouse_input(False)   # let the Qt overlay receive mouse/keyboard input
        self.mp.video_set_key_input(False)
        em = self.mp.event_manager()
        em.event_attach(vlc.EventType.MediaPlayerEndReached, lambda _e: self.ended.emit())
        em.event_attach(vlc.EventType.MediaPlayerEncounteredError, lambda _e: self.error.emit("playback error"))
        em.event_attach(vlc.EventType.MediaPlayerESAdded, lambda _e: self.tracks_ready.emit())

    def attach(self, widget) -> None:
        self.mp.set_hwnd(int(widget.winId()))

    def open(self, path: str, start_seconds: float = 0.0) -> None:
        media = self.instance.media_new_path(path)
        if start_seconds > 1:
            media.add_option(f":start-time={start_seconds:.1f}")
        p = Path(path)
        try:  # external subtitles named like the video ("Movie.en.srt")
            for sib in p.parent.iterdir():
                if sib.suffix.lower() in config.SUBTITLE_EXTS and sib.stem.lower().startswith(p.stem.lower()):
                    media.slaves_add(vlc.MediaSlaveType.subtitle, 0, sib.as_uri())
        except OSError:
            pass
        self.mp.set_media(media)
        media.release()
        self.mp.play()

    # ---- transport ----
    def toggle_pause(self):
        self.mp.pause()

    def stop(self):
        self.mp.stop()

    def is_playing(self) -> bool:
        return bool(self.mp.is_playing())

    def time_ms(self) -> int:
        return max(0, int(self.mp.get_time()))

    def length_ms(self) -> int:
        return max(0, int(self.mp.get_length()))

    def seek_ms(self, ms: int) -> None:
        length = self.length_ms()
        if length:
            ms = max(0, min(ms, length - 500))
        self.mp.set_time(int(ms))

    def seek_relative(self, delta_ms: int) -> None:
        self.seek_ms(self.time_ms() + delta_ms)

    # ---- audio ----
    def volume(self) -> int:
        return max(0, int(self.mp.audio_get_volume()))

    def set_volume(self, v: int) -> None:
        self.mp.audio_set_volume(max(0, min(100, int(v))))

    def is_muted(self) -> bool:
        return bool(self.mp.audio_get_mute())

    def set_muted(self, m: bool) -> None:
        self.mp.audio_set_mute(bool(m))

    def rate(self) -> float:
        return float(self.mp.get_rate())

    def set_rate(self, r: float) -> None:
        self.mp.set_rate(float(r))

    # ---- tracks ----
    def audio_tracks(self) -> list[tuple[int, str]]:
        return [(int(i), _decode(n)) for i, n in (self.mp.audio_get_track_description() or []) if int(i) >= 0]

    def audio_track(self) -> int:
        return int(self.mp.audio_get_track())

    def set_audio_track(self, track_id: int) -> None:
        self.mp.audio_set_track(int(track_id))

    def subtitle_tracks(self) -> list[tuple[int, str]]:
        """Includes (-1, 'Disable')."""
        return [(int(i), _decode(n)) for i, n in (self.mp.video_get_spu_description() or [])]

    def subtitle_track(self) -> int:
        return int(self.mp.video_get_spu())

    def set_subtitle_track(self, track_id: int) -> None:
        self.mp.video_set_spu(int(track_id))

    def add_subtitle_file(self, path: str) -> None:
        self.mp.add_slave(vlc.MediaSlaveType.subtitle, Path(path).as_uri(), True)

    def release(self):
        self.mp.stop()
        self.mp.release()
        self.instance.release()
