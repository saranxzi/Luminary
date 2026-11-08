"""Overlay HUD for the video player.

libVLC draws into a native child window; Qt cannot composite translucent widgets
over it. So the HUD is a separate frameless, per-pixel-translucent tool window
that tracks the video frame's geometry. It paints an (almost) invisible 1/255
alpha layer everywhere so it receives all mouse input.
"""
from __future__ import annotations

from PyQt6.QtCore import QPoint, QPointF, QRectF, Qt, QTimer, pyqtSignal
from PyQt6.QtGui import QColor, QCursor, QFontMetricsF, QLinearGradient, QPainter, QPainterPath, QPen
from PyQt6.QtWidgets import QGraphicsOpacityEffect, QHBoxLayout, QMenu, QVBoxLayout, QWidget

from . import icons
from . import theme as T
from .cards import draw_image
from .components import Anim, Label, TactileButton, fmt_time


class SeekBar(QWidget):
    seek_requested = pyqtSignal(int)   # ms
    scrubbing = pyqtSignal(bool)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedHeight(64)  # room above the track for the hover time bubble
        self.setMouseTracking(True)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.length = 0
        self.time = 0
        self.hover_x: float | None = None
        self.drag = False
        self.drag_ms = 0
        self.hov = 0.0
        self._a = Anim(self, "hov", T.DUR_FAST)
        self._throttle = QTimer(self, singleShot=True, interval=140)
        self._throttle.timeout.connect(lambda: self.seek_requested.emit(self.drag_ms))

    def set_state(self, time_ms: int, length_ms: int):
        if self.drag:
            return
        self.time, self.length = time_ms, length_ms
        self.update()

    def _track(self) -> QRectF:
        return QRectF(10, self.height() - 19, self.width() - 20, 6)

    def _ms_at(self, x: float) -> int:
        t = self._track()
        f = min(1.0, max(0.0, (x - t.left()) / t.width())) if t.width() > 0 else 0
        return int(f * self.length)

    def enterEvent(self, e):  # noqa: N802
        self._a.to(1.0)

    def leaveEvent(self, e):  # noqa: N802
        self.hover_x = None
        if not self.drag:
            self._a.to(0.0)
        self.update()

    def mousePressEvent(self, e):  # noqa: N802
        if e.button() == Qt.MouseButton.LeftButton and self.length:
            self.drag = True
            self.scrubbing.emit(True)
            self.drag_ms = self._ms_at(e.position().x())
            self.time = self.drag_ms
            self.seek_requested.emit(self.drag_ms)
            self.update()

    def mouseMoveEvent(self, e):  # noqa: N802
        self.hover_x = e.position().x()
        if self.drag:
            self.drag_ms = self._ms_at(self.hover_x)
            self.time = self.drag_ms
            if not self._throttle.isActive():
                self._throttle.start()
        self.update()

    def mouseReleaseEvent(self, e):  # noqa: N802
        if self.drag:
            self.drag = False
            self._throttle.stop()
            self.seek_requested.emit(self._ms_at(e.position().x()))
            self.scrubbing.emit(False)
            if not self.rect().contains(e.position().toPoint()):
                self._a.to(0.0)

    def paintEvent(self, _e):  # noqa: N802
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        t = self._track()
        grow = 4 * self.hov
        t.adjust(0, -grow / 2, 0, grow / 2)
        # hover / scrub time bubble
        if (self.hover_x is not None or self.drag) and self.length:
            hx = min(max(self.hover_x if self.hover_x is not None else t.left(), t.left()), t.right())
            ms = self._ms_at(hx) if not self.drag else self.drag_ms
            txt = fmt_time(ms / 1000)
            p.setFont(T.font(11.5, 650))
            fm = QFontMetricsF(p.font())
            bw = fm.horizontalAdvance(txt) + 22
            bx = min(max(hx - bw / 2, 0), self.width() - bw)
            bubble = QRectF(bx, 2, bw, 30)
            bp = QPainterPath()
            bp.addRoundedRect(bubble, 8, 8)
            p.fillPath(bp, QColor(16, 18, 24, 225))
            p.setPen(QColor("#ffffff"))
            p.drawText(bubble, Qt.AlignmentFlag.AlignCenter, txt)
        rad = t.height() / 2
        path = QPainterPath()
        path.addRoundedRect(t, rad, rad)
        p.fillPath(path, QColor(255, 255, 255, 60))
        if self.hover_x is not None and self.length:
            hx = min(max(self.hover_x, t.left()), t.right())
            hr = QRectF(t.left(), t.top(), hx - t.left(), t.height())
            hp = QPainterPath()
            hp.addRoundedRect(hr, rad, rad)
            p.fillPath(hp, QColor(255, 255, 255, 50))
        f = (self.time / self.length) if self.length else 0
        fr = QRectF(t.left(), t.top(), max(t.height(), t.width() * f), t.height())
        fp = QPainterPath()
        fp.addRoundedRect(fr, rad, rad)
        p.fillPath(fp, QColor(T.ACCENT_HI))
        knob = 7 + 3 * self.hov
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QColor("#ffffff"))
        p.drawEllipse(QPointF(fr.right(), t.center().y()), knob, knob)


class VolumeSlider(QWidget):
    changed = pyqtSignal(int)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedSize(132, 44)
        self.value = 80
        self.drag = False
        self.setCursor(Qt.CursorShape.PointingHandCursor)

    def set_value(self, v: int):
        v = max(0, min(100, int(v)))
        if v != self.value:
            self.value = v
            self.update()

    def _from_x(self, x):
        v = int(round((x - 9) / (self.width() - 18) * 100))
        self.set_value(v)
        self.changed.emit(self.value)

    def mousePressEvent(self, e):  # noqa: N802
        self.drag = True
        self._from_x(e.position().x())

    def mouseMoveEvent(self, e):  # noqa: N802
        if self.drag:
            self._from_x(e.position().x())

    def mouseReleaseEvent(self, e):  # noqa: N802
        self.drag = False

    def paintEvent(self, _e):  # noqa: N802
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        t = QRectF(9, self.height() / 2 - 3, self.width() - 18, 6)
        path = QPainterPath()
        path.addRoundedRect(t, 3, 3)
        p.fillPath(path, QColor(255, 255, 255, 60))
        f = QRectF(t.left(), t.top(), max(6, t.width() * self.value / 100), t.height())
        fp = QPainterPath()
        fp.addRoundedRect(f, 3, 3)
        p.fillPath(fp, QColor("#ffffff"))
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QColor("#ffffff"))
        p.drawEllipse(QPointF(f.right(), t.center().y()), 8, 8)


class UpNextCard(QWidget):
    accept = pyqtSignal()
    cancel = pyqtSignal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedSize(520, 156)
        self.media = None
        self.ep = None
        self.frac = 0.0
        self.play_btn = TactileButton("Play now", icon="play", variant="primary", size="md", parent=self)
        self.cancel_btn = TactileButton("Cancel", variant="glass", size="md", parent=self)
        self.play_btn.clicked.connect(self.accept)
        self.cancel_btn.clicked.connect(self.cancel)
        self.play_btn.move(226, 102)
        self.cancel_btn.move(226 + self.play_btn.sizeHint().width() + 8, 102)
        self.play_btn.resize(self.play_btn.sizeHint())
        self.cancel_btn.resize(self.cancel_btn.sizeHint())

    def set_episode(self, media, ep):
        self.media, self.ep = media, ep
        self.update()

    def paintEvent(self, _e):  # noqa: N802
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        r = QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5)
        path = QPainterPath()
        path.addRoundedRect(r, 14, 14)
        p.fillPath(path, QColor(18, 20, 27, 236))
        p.setPen(QPen(QColor(255, 255, 255, 28), 1))
        p.drawPath(path)
        if not self.ep:
            return
        th = QRectF(14, 14, 196, 110)
        draw_image(p, self.ep.get("still") or self.media.get("backdrop"), th, 9, "")
        # countdown bar under thumbnail
        bar = QRectF(th.left(), th.bottom() + 10, th.width(), 4)
        p.fillRect(bar, QColor(255, 255, 255, 40))
        p.fillRect(QRectF(bar.left(), bar.top(), bar.width() * self.frac, bar.height()), QColor(T.ACCENT_HI))
        x, w = 226, self.width() - 240
        p.setPen(QColor(T.ACCENT_HI))
        p.setFont(T.font(9, 700))
        p.drawText(QRectF(x, 14, w, 20), Qt.AlignmentFlag.AlignVCenter, "UP NEXT")
        p.setPen(QColor(T.TEXT))
        p.setFont(T.font(12.5, 650))
        n = self.ep["number"]
        lab = f"Episode {n}" if self.media.get("numbering") == "absolute" else f"S{self.ep['season']} · E{n}"
        p.drawText(QRectF(x, 36, w, 26), Qt.AlignmentFlag.AlignVCenter, lab)
        p.setPen(QColor(T.TEXT_MUTED))
        p.setFont(T.font(10.5))
        fm = QFontMetricsF(p.font())
        p.drawText(QRectF(x, 62, w, 24), Qt.AlignmentFlag.AlignVCenter,
                   fm.elidedText(self.ep.get("title") or "", Qt.TextElideMode.ElideRight, w))


class PlayerHud(QWidget):
    def __init__(self, ctl, owner: QWidget):
        super().__init__(owner, Qt.WindowType.Tool | Qt.WindowType.FramelessWindowHint |
                         Qt.WindowType.NoDropShadowWindowHint | Qt.WindowType.WindowDoesNotAcceptFocus)
        self.ctl = ctl
        self.owner = owner
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating)
        self.setMouseTracking(True)
        self.reveal = 1.0
        self._reveal_anim = Anim(self, "reveal", T.DUR_SLOW, on_change=self._apply_reveal)
        self.flash = 0.0
        self.flash_icon = "play"
        self._flash_anim = Anim(self, "flash", 520, curve=T.ease_out())
        self.osd_text = ""
        self.osd = 0.0
        self._osd_anim = Anim(self, "osd", T.DUR_BASE)
        self._osd_timer = QTimer(self, singleShot=True)
        self._osd_timer.timeout.connect(lambda: self._osd_anim.to(0.0, T.DUR_SLOW))
        self.scrubbing = False
        self.menu_open = False

        # ---------------- top bar
        self.top = QWidget(self)
        tl = QHBoxLayout(self.top)
        tl.setContentsMargins(30, 24, 30, 0)
        tl.setSpacing(16)
        self.back_btn = TactileButton(icon="back", variant="hud", size="hud")
        self.back_btn.setToolTip("Back (Esc)")
        self.back_btn.clicked.connect(ctl.close_player)
        tl.addWidget(self.back_btn, 0, Qt.AlignmentFlag.AlignTop)
        tcol = QVBoxLayout()
        tcol.setSpacing(2)
        self.title = Label("", 18, 700, "#ffffff", display=True)
        self.subtitle = Label("", 12, 500, "#c3c9d6")
        tcol.addWidget(self.title)
        tcol.addWidget(self.subtitle)
        tl.addLayout(tcol, 1)

        # ---------------- bottom bar
        self.bottom = QWidget(self)
        bl = QVBoxLayout(self.bottom)
        bl.setContentsMargins(28, 0, 28, 22)
        bl.setSpacing(0)
        self.seek = SeekBar()
        self.seek.seek_requested.connect(ctl.seek_to)
        self.seek.scrubbing.connect(self._set_scrubbing)
        bl.addWidget(self.seek)
        bl.addSpacing(6)
        row = QHBoxLayout()
        row.setSpacing(6)

        def hb(icon, tip, fn, size="hud"):
            b = TactileButton(icon=icon, variant="hud", size=size)
            b.setToolTip(tip)
            b.clicked.connect(fn)
            return b

        self.play_btn = hb("pause", "Play / Pause (Space)", ctl.toggle_pause, "xl")
        self.back10 = hb("back10", "Back 10s (←)", lambda: ctl.seek_by(-10_000))
        self.fwd10 = hb("fwd10", "Forward 10s (→)", lambda: ctl.seek_by(10_000))
        self.prev_btn = hb("prev", "Previous episode (P)", ctl.prev_episode)
        self.next_btn = hb("next", "Next episode (N)", ctl.next_episode)
        self.vol_btn = hb("volume-2", "Mute (M)", ctl.toggle_mute)
        self.vol = VolumeSlider()
        self.vol.changed.connect(ctl.set_volume)
        self.time_lbl = Label("0:00 / 0:00", 12.5, 600, "#e6e9f0")
        for w in (self.play_btn, self.back10, self.fwd10, self.prev_btn, self.next_btn, self.vol_btn, self.vol):
            row.addWidget(w, 0, Qt.AlignmentFlag.AlignVCenter)
        row.addSpacing(14)
        row.addWidget(self.time_lbl)
        row.addStretch(1)
        self.speed_btn = hb("gauge", "Playback speed  ( [ / ] )", self._speed_menu)
        self.audio_btn = hb("audio", "Audio track (B)", self._audio_menu)
        self.sub_btn = hb("captions", "Subtitles (V)", self._sub_menu)
        self.fs_btn = hb("maximize", "Fullscreen (F)", ctl.toggle_fullscreen)
        for w in (self.speed_btn, self.audio_btn, self.sub_btn, self.fs_btn):
            row.addWidget(w)
        bl.addLayout(row)

        self.top_fx = QGraphicsOpacityEffect(self.top)
        self.bottom_fx = QGraphicsOpacityEffect(self.bottom)
        self.top.setGraphicsEffect(self.top_fx)
        self.bottom.setGraphicsEffect(self.bottom_fx)

        self.upnext = UpNextCard(self)
        self.upnext.hide()
        self.upnext.accept.connect(ctl.accept_up_next)
        self.upnext.cancel.connect(ctl.cancel_up_next)

        # activity detection: poll the cursor so child widgets don't swallow motion
        self._last_cursor = QPoint()
        self._poll = QTimer(self, interval=120)
        self._poll.timeout.connect(self._poll_cursor)
        self._hide_timer = QTimer(self, singleShot=True, interval=2600)
        self._hide_timer.timeout.connect(self._auto_hide)
        self._click = QTimer(self, singleShot=True, interval=230)
        self._click.timeout.connect(ctl.toggle_pause)

    # ------------------------------------------------------------ lifecycle
    def activate(self):
        self.show()
        self.raise_()
        self._poll.start()
        self.show_controls()

    def deactivate(self):
        self._poll.stop()
        self._hide_timer.stop()
        self.upnext.hide()
        self.hide()

    def sync_geometry(self, rect):
        if self.geometry() != rect:
            self.setGeometry(rect)

    def resizeEvent(self, e):  # noqa: N802
        w, h = self.width(), self.height()
        th = self.top.sizeHint().height() + 10
        self.top.setGeometry(0, 0, w, th)
        bh = self.bottom.sizeHint().height()
        self.bottom.setGeometry(0, h - bh, w, bh)
        self.upnext.move(w - self.upnext.width() - 28, h - bh - self.upnext.height() - 12)

    # ------------------------------------------------------------ reveal / auto-hide
    def _apply_reveal(self, v):
        self.top_fx.setOpacity(v)
        self.bottom_fx.setOpacity(v)
        vis = v > 0.02
        self.top.setVisible(vis)
        self.bottom.setVisible(vis)

    def show_controls(self):
        if self.reveal < 1.0:
            self._reveal_anim.to(1.0, T.DUR_BASE)
        self.unsetCursor()
        self._hide_timer.start()

    def _auto_hide(self):
        if self.scrubbing or self.menu_open or not self.ctl.is_playing():
            self._hide_timer.start()
            return
        pos = self.mapFromGlobal(QCursor.pos())
        over_controls = (self.top.isVisible() and self.top.geometry().contains(pos) and pos.y() < 110) or \
            (self.bottom.isVisible() and self.bottom.geometry().contains(pos)) or \
            (self.upnext.isVisible() and self.upnext.geometry().contains(pos))
        if over_controls and self.rect().contains(pos):
            self._hide_timer.start()
            return
        self._reveal_anim.to(0.0, T.DUR_SLOW + 120)
        self.setCursor(Qt.CursorShape.BlankCursor)

    def _poll_cursor(self):
        pos = QCursor.pos()
        if pos != self._last_cursor:
            self._last_cursor = pos
            if self.geometry().contains(pos):
                self.show_controls()

    def _set_scrubbing(self, on):
        self.scrubbing = on
        self.ctl.on_scrub(on)

    # ------------------------------------------------------------ state from controller
    def set_titles(self, title: str, subtitle: str, has_prev: bool, has_next: bool):
        self.title.setText(title)
        self.subtitle.setText(subtitle)
        self.subtitle.setVisible(bool(subtitle))
        self.prev_btn.setVisible(has_prev)
        self.next_btn.setVisible(has_next)
        self.resizeEvent(None)

    def update_state(self, time_ms, length_ms, playing, volume, muted, fullscreen):
        self.seek.set_state(time_ms, length_ms)
        if length_ms:
            self.time_lbl.setText(f"{fmt_time(time_ms / 1000)} / {fmt_time(length_ms / 1000)}")
        self.play_btn.set_icon_name("pause" if playing else "play")
        self.vol.set_value(volume)
        self.vol_btn.set_icon_name("volume-x" if muted or volume == 0 else "volume-1" if volume < 50 else "volume-2")
        self.fs_btn.set_icon_name("minimize" if fullscreen else "maximize")

    def flash_center(self, icon: str):
        self.flash_icon = icon
        self.flash = 0.0
        self._flash_anim.a.stop()
        self._flash_anim.a.setStartValue(0.0)
        self._flash_anim.a.setEndValue(1.0)
        self._flash_anim.a.start()

    def show_osd(self, text: str, ms: int = 1400):
        self.osd_text = text
        self._osd_anim.to(1.0, T.DUR_FAST)
        self._osd_timer.start(ms)

    # ------------------------------------------------------------ menus
    def _run_menu(self, menu: QMenu, anchor: QWidget):
        self.menu_open = True
        self.show_controls()
        menu.setFont(T.font(12, 500))
        menu.setStyleSheet("QMenu { padding: 8px; border-radius: 12px; }"
                           "QMenu::item { padding: 10px 40px 10px 16px; border-radius: 8px; }"
                           "QMenu::indicator { width: 18px; height: 18px; left: 10px; }"
                           "QMenu::section { font-size: 9pt; padding: 8px 16px 6px; }")
        pos = anchor.mapToGlobal(QPoint(0, 0))
        menu.adjustSize()
        menu.exec(QPoint(pos.x() + anchor.width() - menu.sizeHint().width(), pos.y() - menu.sizeHint().height() - 8))
        self.menu_open = False
        self.show_controls()

    def _audio_menu(self):
        menu = QMenu(self)
        menu.addSection("Audio")
        cur = self.ctl.vlc.audio_track()
        tracks = self.ctl.vlc.audio_tracks()
        if not tracks:
            menu.addAction("No audio tracks").setEnabled(False)
        for tid, name in tracks:
            a = menu.addAction(name)
            a.setCheckable(True)
            a.setChecked(tid == cur)
            a.triggered.connect(lambda _=False, t=tid, n=name: self.ctl.choose_audio(t, n))
        self._run_menu(menu, self.audio_btn)

    def _sub_menu(self):
        menu = QMenu(self)
        menu.addSection("Subtitles")
        cur = self.ctl.vlc.subtitle_track()
        tracks = self.ctl.vlc.subtitle_tracks() or [(-1, "Disable")]
        for tid, name in tracks:
            a = menu.addAction("Off" if tid == -1 else name)
            a.setCheckable(True)
            a.setChecked(tid == cur)
            a.triggered.connect(lambda _=False, t=tid, n=name: self.ctl.choose_subtitle(t, n))
        menu.addSeparator()
        menu.addAction("Load subtitle file…", self.ctl.load_subtitle_file)
        self._run_menu(menu, self.sub_btn)

    def _speed_menu(self):
        menu = QMenu(self)
        menu.addSection("Speed")
        cur = self.ctl.vlc.rate()
        for r in (0.5, 0.75, 1.0, 1.25, 1.5, 1.75, 2.0):
            a = menu.addAction("Normal" if r == 1.0 else f"{r:g}×")
            a.setCheckable(True)
            a.setChecked(abs(cur - r) < 0.01)
            a.triggered.connect(lambda _=False, v=r: self.ctl.set_rate(v))
        self._run_menu(menu, self.speed_btn)

    # ------------------------------------------------------------ input
    def mousePressEvent(self, e):  # noqa: N802
        self.owner.activateWindow()
        was_hidden = self.reveal < 0.5
        self.show_controls()
        if e.button() != Qt.MouseButton.LeftButton:
            return
        pos = e.position().toPoint()
        for w in (self.top, self.bottom, self.upnext):
            if w.isVisible() and w.geometry().contains(pos) and not was_hidden:
                return
        self._click.start()

    def mouseDoubleClickEvent(self, e):  # noqa: N802
        self._click.stop()
        if e.button() == Qt.MouseButton.LeftButton:
            self.ctl.toggle_fullscreen()

    def wheelEvent(self, e):  # noqa: N802
        d = e.angleDelta().y()
        if d:
            self.ctl.change_volume(5 if d > 0 else -5)

    def keyPressEvent(self, e):  # noqa: N802
        self.ctl.handle_key(e)

    # ------------------------------------------------------------ paint
    def paintEvent(self, _e):  # noqa: N802
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        r = QRectF(self.rect())
        p.fillRect(r, QColor(0, 0, 0, 1))  # hit-test layer
        if self.reveal > 0.01:
            g = QLinearGradient(0, 0, 0, 190)
            g.setColorAt(0, QColor(0, 0, 0, int(180 * self.reveal)))
            g.setColorAt(1, QColor(0, 0, 0, 1))
            p.fillRect(QRectF(0, 0, r.width(), 190), g)
            g2 = QLinearGradient(0, r.height() - 270, 0, r.height())
            g2.setColorAt(0, QColor(0, 0, 0, 1))
            g2.setColorAt(1, QColor(0, 0, 0, int(215 * self.reveal)))
            p.fillRect(QRectF(0, r.height() - 270, r.width(), 270), g2)
        if 0.0 < self.flash < 1.0:
            a = 1.0 - self.flash
            s = 0.8 + 0.35 * self.flash
            c = r.center()
            d = 116 * s
            p.setOpacity(a)
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(QColor(0, 0, 0, 120))
            p.drawEllipse(c, d / 2, d / 2)
            isz = 48 * s
            icons.draw(p, self.flash_icon, QRectF(c.x() - isz / 2 + (3 if self.flash_icon == "play" else 0),
                                                  c.y() - isz / 2, isz, isz), QColor("#ffffff"))
            p.setOpacity(1.0)
        if self.osd > 0.01 and self.osd_text:
            p.setOpacity(self.osd)
            p.setFont(T.font(14.5, 650))
            fm = QFontMetricsF(p.font())
            w = fm.horizontalAdvance(self.osd_text) + 44
            box = QRectF(r.right() - w - 32, 32 + (1 - self.osd) * -6, w, 54)
            path = QPainterPath()
            path.addRoundedRect(box, 14, 14)
            p.fillPath(path, QColor(16, 18, 24, 215))
            p.setPen(QColor("#ffffff"))
            p.drawText(box, Qt.AlignmentFlag.AlignCenter, self.osd_text)
            p.setOpacity(1.0)
