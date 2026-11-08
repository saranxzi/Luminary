"""In-window video player: hosts the libVLC surface and drives the overlay HUD."""
from __future__ import annotations

import ctypes
import os
import sys

from PyQt6.QtCore import QEvent, QRect, Qt, QTimer, pyqtSignal
from PyQt6.QtWidgets import QFileDialog, QFrame, QVBoxLayout, QWidget

from core.vlc_player import VlcPlayer

from .components import fmt_time
from .player_hud import PlayerHud

ES_CONTINUOUS, ES_SYSTEM_REQUIRED, ES_DISPLAY_REQUIRED = 0x80000000, 0x00000001, 0x00000002


def _keep_awake(on: bool):
    if sys.platform == "win32":
        flags = ES_CONTINUOUS | ((ES_SYSTEM_REQUIRED | ES_DISPLAY_REQUIRED) if on else 0)
        try:
            ctypes.windll.kernel32.SetThreadExecutionState(flags)
        except Exception:
            pass


class VideoSurface(QFrame):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setAttribute(Qt.WidgetAttribute.WA_NativeWindow)
        self.setAttribute(Qt.WidgetAttribute.WA_DontCreateNativeAncestors)
        self.setStyleSheet("background: #000;")
        self.setAutoFillBackground(True)


class PlayerView(QWidget):
    closed = pyqtSignal()                 # user left the player
    progress_changed = pyqtSignal()       # watch state changed (for library refresh)
    fullscreen_requested = pyqtSignal(bool)
    message = pyqtSignal(str)

    def __init__(self, db, settings, window: QWidget, parent=None):
        super().__init__(parent)
        self.active = False
        self.db, self.settings, self.window_ = db, settings, window
        self.setStyleSheet("background: #000;")
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        self.surface = VideoSurface(self)
        lay.addWidget(self.surface)

        self.vlc = VlcPlayer(self)
        self.vlc.attach(self.surface)
        self.vlc.ended.connect(self._on_ended)
        self.vlc.error.connect(self._on_error)
        self.vlc.tracks_ready.connect(lambda: self._prefs_timer.start())
        self.vlc.set_volume(int(settings.get("volume") or 80))

        self.hud = PlayerHud(self, window)
        self.fullscreen = False
        self.media: dict | None = None
        self.ep: dict | None = None
        self.path: str | None = None
        self._last_known_len = 0
        self._ended = False
        self._up_next: dict | None = None

        self._tick = QTimer(self, interval=250)
        self._tick.timeout.connect(self._on_tick)
        self._save = QTimer(self, interval=5000)
        self._save.timeout.connect(self.save_progress)
        self._prefs_timer = QTimer(self, singleShot=True, interval=500)
        self._prefs_timer.timeout.connect(self._apply_track_prefs)
        self._prefs_applied = False
        self._countdown = QTimer(self, interval=50)
        self._countdown.timeout.connect(self._countdown_tick)
        self._countdown_left = 0.0

        window.installEventFilter(self)

    # ------------------------------------------------------------ geometry sync for the HUD
    def eventFilter(self, obj, ev):  # noqa: N802
        if self.active and ev.type() in (QEvent.Type.Move, QEvent.Type.Resize, QEvent.Type.WindowStateChange,
                                         QEvent.Type.Show):
            QTimer.singleShot(0, self._sync_hud)
        if ev.type() == QEvent.Type.WindowStateChange and self.active:
            if self.window_.isMinimized():
                self.hud.hide()
            else:
                QTimer.singleShot(50, lambda: self.active and self.hud.activate())
        return False

    def resizeEvent(self, e):  # noqa: N802
        super().resizeEvent(e)
        self._sync_hud()

    def moveEvent(self, e):  # noqa: N802
        super().moveEvent(e)
        self._sync_hud()

    def _sync_hud(self):
        if not self.active:
            return
        tl = self.surface.mapToGlobal(self.surface.rect().topLeft())
        self.hud.sync_geometry(QRect(tl, self.surface.size()))

    # ------------------------------------------------------------ open / close
    def open(self, media_id: int, episode_id: int | None = None, from_start: bool = False):
        self.save_progress()
        m = self.db.media(media_id)
        if not m:
            return False
        ep = self.db.episode(episode_id) if episode_id else None
        if m["kind"] != "movie" and ep is None:
            ep = self.db.resume_episode(media_id)
        path = ep["file_path"] if ep else self.db.movie_file(media_id)
        if not path or not os.path.exists(path):
            self.message.emit("File not found — try rescanning your library")
            return False
        src = ep if ep else m
        pos = 0.0 if (from_start or src.get("watched")) else float(src.get("position") or 0)
        start = max(0.0, pos - 3) if pos > 10 else 0.0
        self.media, self.ep, self.path = m, ep, path
        self._ended = False
        self._prefs_applied = False
        self._last_known_len = int((src.get("duration") or 0) * 1000)
        self._cancel_up_next()
        self.active = True
        self.vlc.open(path, start)
        self.vlc.set_rate(1.0)
        self._update_titles()
        self._tick.start()
        self._save.start()
        _keep_awake(True)
        QTimer.singleShot(0, self._sync_hud)
        QTimer.singleShot(30, self.hud.activate)
        if start:
            QTimer.singleShot(700, lambda: self.hud.show_osd(f"Resumed at {fmt_time(start)}  ·  Home to restart", 2600))
        return True

    def close_player(self):
        if not self.active:
            return
        self.save_progress()
        self.active = False
        self._tick.stop()
        self._save.stop()
        self._countdown.stop()
        self.hud.deactivate()
        self.vlc.stop()
        _keep_awake(False)
        if self.fullscreen:
            self.toggle_fullscreen()
        self.media = self.ep = self.path = None
        self.closed.emit()

    def _update_titles(self):
        m, ep = self.media, self.ep
        if ep:
            lab = f"Episode {ep['number']}" if m.get("numbering") == "absolute" else f"Season {ep['season']} · Episode {ep['number']}"
            sub = lab + (f"  —  {ep['title']}" if ep.get("title") else "")
            has_prev = self.db.previous_episode(ep["id"]) is not None
            has_next = self.db.next_episode(ep["id"]) is not None
        else:
            sub = str(m.get("year") or "")
            has_prev = has_next = False
        self.hud.set_titles(m.get("title") or "", sub, has_prev, has_next)
        self.window_.setWindowTitle(f"{m.get('title')} — Luminary")

    # ------------------------------------------------------------ progress
    def save_progress(self):
        if not self.media or not self.path:
            return
        t = self.vlc.time_ms() / 1000
        length = (self.vlc.length_ms() or self._last_known_len) / 1000
        if length <= 0 or t <= 0:
            return
        threshold = float(self.settings.get("watched_threshold") or 0.9)
        if self.ep:
            became = self.db.set_progress(episode_id=self.ep["id"], position=t, duration=length, threshold=threshold)
            self.ep = self.db.episode(self.ep["id"])
        else:
            became = self.db.set_progress(media_id=self.media["id"], position=t, duration=length, threshold=threshold)
        self.progress_changed.emit()
        if became:
            self.hud.show_osd("Marked as watched  ✓", 1800)

    def _on_tick(self):
        if not self.active:
            return
        length = self.vlc.length_ms()
        if length:
            self._last_known_len = length
        self.hud.update_state(self.vlc.time_ms(), length, self.vlc.is_playing(), self.vlc.volume(),
                              self.vlc.is_muted(), self.fullscreen)

    # ------------------------------------------------------------ end / next
    def _on_ended(self):
        if not self.active or self._ended:
            return
        self._ended = True
        # record completion
        length = self._last_known_len / 1000
        if self.ep:
            self.db.set_progress(episode_id=self.ep["id"], position=length, duration=length, threshold=0.0)
        else:
            self.db.set_progress(media_id=self.media["id"], position=length, duration=length, threshold=0.0)
        self.progress_changed.emit()
        nxt = self.db.next_episode(self.ep["id"]) if self.ep else None
        if nxt and self.settings.get("auto_next"):
            self._up_next = nxt
            self.hud.upnext.set_episode(self.media, nxt)
            self.hud.upnext.show()
            self.hud.upnext.raise_()
            self.hud.show_controls()
            self._countdown_left = 8.0
            self._countdown.start()
        elif nxt:
            self._up_next = nxt
            self.hud.upnext.set_episode(self.media, nxt)
            self.hud.upnext.frac = 0
            self.hud.upnext.show()
        else:
            QTimer.singleShot(400, self.close_player)

    def _countdown_tick(self):
        self._countdown_left -= 0.05
        self.hud.upnext.frac = max(0.0, 1 - self._countdown_left / 8.0)
        self.hud.upnext.update()
        if self._countdown_left <= 0:
            self.accept_up_next()

    def accept_up_next(self):
        nxt = self._up_next
        self._cancel_up_next()
        if nxt:
            self.open(self.media["id"], nxt["id"])

    def cancel_up_next(self):
        self._cancel_up_next()
        if self._ended:
            self.close_player()

    def _cancel_up_next(self):
        self._countdown.stop()
        self.hud.upnext.hide()
        self._up_next = None

    def next_episode(self):
        if self.ep:
            nxt = self.db.next_episode(self.ep["id"])
            if nxt:
                self.save_progress()
                self.open(self.media["id"], nxt["id"])

    def prev_episode(self):
        if self.ep:
            prv = self.db.previous_episode(self.ep["id"])
            if prv:
                self.save_progress()
                self.open(self.media["id"], prv["id"], from_start=True)

    def _on_error(self, msg):
        self.message.emit(f"Couldn't play this file ({msg})")
        QTimer.singleShot(0, self.close_player)

    # ------------------------------------------------------------ transport (called by HUD / keys)
    def is_playing(self) -> bool:
        return self.vlc.is_playing()

    def toggle_pause(self):
        if self._ended and self.path:
            self.open(self.media["id"], self.ep["id"] if self.ep else None, from_start=True)
            return
        playing = self.vlc.is_playing()
        self.vlc.toggle_pause()
        self.hud.flash_center("pause" if playing else "play")
        if playing:
            self.save_progress()
            _keep_awake(False)
        else:
            _keep_awake(True)
        self.hud.show_controls()

    def seek_to(self, ms: int):
        self.vlc.seek_ms(ms)
        self._on_tick()

    def seek_by(self, delta_ms: int):
        self.vlc.seek_relative(delta_ms)
        self.hud.show_osd(("+" if delta_ms > 0 else "−") + f"{abs(delta_ms) // 1000}s", 700)
        self.hud.show_controls()
        self._on_tick()

    def on_scrub(self, on: bool):
        if not on:
            self.save_progress()

    def set_volume(self, v: int):
        self.vlc.set_volume(v)
        if v > 0 and self.vlc.is_muted():
            self.vlc.set_muted(False)
        self.settings.set("volume", int(v))
        self._on_tick()

    def change_volume(self, d: int):
        v = max(0, min(100, self.vlc.volume() + d))
        self.set_volume(v)
        self.hud.show_osd(f"Volume  {v}%", 900)

    def toggle_mute(self):
        m = not self.vlc.is_muted()
        self.vlc.set_muted(m)
        self.hud.show_osd("Muted" if m else f"Volume  {self.vlc.volume()}%", 900)
        self._on_tick()

    def set_rate(self, r: float):
        self.vlc.set_rate(r)
        self.hud.show_osd("Speed  " + ("normal" if r == 1 else f"{r:g}×"), 1000)

    def toggle_fullscreen(self):
        self.fullscreen = not self.fullscreen
        self.fullscreen_requested.emit(self.fullscreen)
        QTimer.singleShot(60, self._sync_hud)
        QTimer.singleShot(250, self._sync_hud)

    # ------------------------------------------------------------ tracks
    def choose_audio(self, tid: int, name: str):
        self.vlc.set_audio_track(tid)
        self._save_pref("audio", name)
        self.hud.show_osd(f"Audio  ·  {name}", 1400)

    def choose_subtitle(self, tid: int, name: str):
        self.vlc.set_subtitle_track(tid)
        self._save_pref("sub", "off" if tid == -1 else name)
        self.hud.show_osd("Subtitles off" if tid == -1 else f"Subtitles  ·  {name}", 1400)

    def cycle_subtitle(self):
        tracks = self.vlc.subtitle_tracks()
        if len(tracks) <= 1:
            self.hud.show_osd("No subtitles", 900)
            return
        ids = [t for t, _ in tracks]
        cur = self.vlc.subtitle_track()
        i = (ids.index(cur) + 1) % len(ids) if cur in ids else 0
        self.choose_subtitle(*tracks[i])

    def cycle_audio(self):
        tracks = self.vlc.audio_tracks()
        if len(tracks) <= 1:
            self.hud.show_osd(tracks[0][1] if tracks else "No audio", 900)
            return
        ids = [t for t, _ in tracks]
        cur = self.vlc.audio_track()
        i = (ids.index(cur) + 1) % len(ids) if cur in ids else 0
        self.choose_audio(*tracks[i])

    def load_subtitle_file(self):
        start = os.path.dirname(self.path) if self.path else ""
        fn, _ = QFileDialog.getOpenFileName(self.window_, "Load subtitles", start,
                                            "Subtitles (*.srt *.ass *.ssa *.vtt *.sub)")
        if fn:
            self.vlc.add_subtitle_file(fn)
            self.hud.show_osd(f"Loaded  ·  {os.path.basename(fn)}", 1500)

    def _save_pref(self, key, value):
        if not self.media:
            return
        prefs = dict(self.media.get("prefs") or {})
        prefs[key] = value
        self.db.set_prefs(self.media["id"], prefs)
        self.media["prefs"] = prefs

    def _apply_track_prefs(self):
        if self._prefs_applied or not self.active:
            return
        self._prefs_applied = True
        prefs = (self.media or {}).get("prefs") or {}
        audio = self.vlc.audio_tracks()
        subs = [t for t in self.vlc.subtitle_tracks() if t[0] != -1]
        if prefs.get("audio"):
            for tid, name in audio:
                if name == prefs["audio"]:
                    self.vlc.set_audio_track(tid)
                    break
        sp = prefs.get("sub")
        if sp == "off":
            self.vlc.set_subtitle_track(-1)
        elif sp:
            for tid, name in subs:
                if name == sp:
                    self.vlc.set_subtitle_track(tid)
                    break
        elif self.media and self.media["kind"] == "anime" and subs and self.vlc.subtitle_track() == -1:
            # anime almost always wants subtitles on by default
            self.vlc.set_subtitle_track(subs[0][0])

    # ------------------------------------------------------------ keyboard
    def handle_key(self, e) -> bool:
        if not self.active:
            return False
        k = e.key()
        mods = e.modifiers()
        if k in (Qt.Key.Key_Space, Qt.Key.Key_K, Qt.Key.Key_MediaPlay, Qt.Key.Key_MediaTogglePlayPause):
            self.toggle_pause()
        elif k in (Qt.Key.Key_Left, Qt.Key.Key_J, Qt.Key.Key_Right, Qt.Key.Key_L):
            step = 30_000 if mods & Qt.KeyboardModifier.ShiftModifier else                 5_000 if mods & Qt.KeyboardModifier.ControlModifier else 10_000
            self.seek_by(step if k in (Qt.Key.Key_Right, Qt.Key.Key_L) else -step)
        elif k == Qt.Key.Key_Up:
            self.change_volume(5)
        elif k == Qt.Key.Key_Down:
            self.change_volume(-5)
        elif k == Qt.Key.Key_F or (k in (Qt.Key.Key_Return, Qt.Key.Key_Enter) and mods & Qt.KeyboardModifier.AltModifier):
            self.toggle_fullscreen()
        elif k == Qt.Key.Key_M:
            self.toggle_mute()
        elif k in (Qt.Key.Key_N, Qt.Key.Key_MediaNext):
            self.next_episode()
        elif k in (Qt.Key.Key_P, Qt.Key.Key_MediaPrevious):
            self.prev_episode()
        elif k in (Qt.Key.Key_V, Qt.Key.Key_S):
            self.cycle_subtitle()
        elif k in (Qt.Key.Key_B, Qt.Key.Key_A):
            self.cycle_audio()
        elif k == Qt.Key.Key_Home:
            self.vlc.seek_ms(0)
            self.hud.show_osd("Restarted", 900)
        elif k == Qt.Key.Key_End and self._up_next is None and self.ep:
            self.next_episode()
        elif Qt.Key.Key_0 <= k <= Qt.Key.Key_9 and not mods:
            length = self.vlc.length_ms()
            if length:
                self.vlc.seek_ms(int(length * (k - Qt.Key.Key_0) / 10))
                self.hud.show_controls()
        elif k == Qt.Key.Key_BracketRight:
            self.set_rate(min(2.0, round(self.vlc.rate() + 0.25, 2)))
        elif k == Qt.Key.Key_BracketLeft:
            self.set_rate(max(0.25, round(self.vlc.rate() - 0.25, 2)))
        elif k == Qt.Key.Key_Escape:
            if self.fullscreen:
                self.toggle_fullscreen()
            else:
                self.close_player()
        elif k == Qt.Key.Key_Backspace:
            self.close_player()
        else:
            return False
        return True

    def shutdown(self):
        self.save_progress()
        self.hud.deactivate()
        _keep_awake(False)
        self.vlc.release()
