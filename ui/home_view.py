"""Home: rotating featured hero and shelves."""
from __future__ import annotations

import datetime as _dt

from PyQt6.QtCore import QPropertyAnimation, QRectF, Qt, QTimer, pyqtSignal
from PyQt6.QtGui import QColor, QPainter, QPainterPath
from PyQt6.QtWidgets import (QGraphicsOpacityEffect, QHBoxLayout, QScrollArea, QSizePolicy, QVBoxLayout,
                             QWidget)

from core import images

from . import theme as T
from .backdrop import Backdrop
from .cards import RowView
from .components import Anim, Label, SmoothScroller, TactileButton, fmt_runtime


class LogoOrTitle(QWidget):
    """Shows the title's logo art if available, else a big display title."""

    def __init__(self, parent=None, max_h=110, font_size=30.0):
        super().__init__(parent)
        self.logo = None
        self.title = ""
        self.max_h = max_h
        self.font_size = font_size
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.setFixedHeight(max_h)
        images.loader().ready.connect(lambda u: self.update() if u == self.logo else None)

    def _font(self):
        size = self.font_size if len(self.title) < 22 else self.font_size * 0.78
        return T.font(size, 700, display=True)

    def set(self, title: str, logo: str | None):
        self.title, self.logo = title, logo
        if logo:
            self.setFixedHeight(self.max_h)
        else:
            from PyQt6.QtGui import QFontMetrics
            w = min(760, max(320, self.width() if self.width() > 100 else 700))
            br = QFontMetrics(self._font()).boundingRect(0, 0, w, 1000, Qt.TextFlag.TextWordWrap, title or " ")
            self.setFixedHeight(min(self.max_h + 40, br.height() + 4))
        self.update()

    def paintEvent(self, _e):  # noqa: N802
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
        pm = images.loader().get(self.logo) if self.logo else None
        if pm is not None and not pm.isNull():
            r = QRectF(0, 0, min(self.width(), 480), self.height())
            s = pm.size().scaled(int(r.width()), int(r.height()), Qt.AspectRatioMode.KeepAspectRatio)
            p.drawPixmap(QRectF(0, r.height() - s.height(), s.width(), s.height()), pm, QRectF(pm.rect()))
            return
        p.setFont(self._font())
        p.setPen(T.c(T.TEXT))
        p.drawText(QRectF(0, 0, min(self.width(), 760), self.height()),
                   Qt.AlignmentFlag.AlignBottom | Qt.AlignmentFlag.AlignLeft | Qt.TextFlag.TextWordWrap, self.title)


# ---------------------------------------------------------------- hero carousel
class HeroDots(QWidget):
    picked = pyqtSignal(int)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.n, self.i = 0, 0
        self.progress = 0.0
        self.setFixedHeight(20)
        self.setCursor(Qt.CursorShape.PointingHandCursor)

    def set(self, n, i):
        self.n, self.i = n, i
        self.setFixedWidth(max(0, n * 14 + 30))
        self.update()

    def mousePressEvent(self, e):  # noqa: N802
        x = 0.0
        for k in range(self.n):
            w = 40 if k == self.i else 8
            if x <= e.position().x() <= x + w + 6:
                self.picked.emit(k)
                return
            x += w + 6

    def paintEvent(self, _e):  # noqa: N802
        if self.n <= 1:
            return
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        x = 0.0
        for k in range(self.n):
            w = 40 if k == self.i else 8
            r = QRectF(x, 6, w, 8)
            path = QPainterPath()
            path.addRoundedRect(r, 4, 4)
            p.fillPath(path, QColor(255, 255, 255, 60 if k != self.i else 70))
            if k == self.i:
                f = QRectF(r.left(), r.top(), max(8, w * self.progress), 8)
                fp = QPainterPath()
                fp.addRoundedRect(f, 4, 4)
                p.fillPath(fp, QColor(255, 255, 255, 230))
            x += w + 6


class Hero(Backdrop):
    play = pyqtSignal(int, object)
    details = pyqtSignal(int)
    INTERVAL = 9000

    def __init__(self, parent=None):
        super().__init__(parent, height=460, art_left=0.18)
        self.items: list[dict] = []
        self.i = 0
        self.hovered = False
        lay = QVBoxLayout(self)
        lay.setContentsMargins(48, 30, 48, 36)
        self.greeting = Label("", 10, 600, T.TEXT_MUTED)
        lay.addWidget(self.greeting)
        lay.addStretch(1)

        self.content = QWidget()
        cl = QVBoxLayout(self.content)
        cl.setContentsMargins(0, 0, 0, 0)
        cl.setSpacing(0)
        self.kicker = Label("", 9, 700, T.ACCENT_HI)
        self.title = LogoOrTitle(max_h=116, font_size=38)
        self.meta = Label("", 10.5, 500, "#d5dae4")
        self.over = Label("", 11, 400, "#b9c0cd", wrap=True)
        self.over.setMaximumWidth(600)
        cl.addWidget(self.kicker)
        cl.addSpacing(8)
        cl.addWidget(self.title)
        cl.addSpacing(18)
        cl.addWidget(self.meta)
        cl.addSpacing(10)
        cl.addWidget(self.over)
        cl.addSpacing(22)
        btns = QHBoxLayout()
        btns.setSpacing(10)
        self.play_btn = TactileButton("Play", icon="play", variant="primary", size="lg")
        self.info_btn = TactileButton("More info", icon="info", variant="glass", size="lg")
        btns.addWidget(self.play_btn)
        btns.addWidget(self.info_btn)
        btns.addStretch(1)
        cl.addLayout(btns)
        self.fx = QGraphicsOpacityEffect(self.content)
        self.fx.setOpacity(1.0)
        self.content.setGraphicsEffect(self.fx)
        lay.addWidget(self.content)

        bottom = QHBoxLayout()
        bottom.addStretch(1)
        self.dots = HeroDots()
        self.dots.picked.connect(lambda k: self.show_index(k, user=True))
        bottom.addWidget(self.dots)
        lay.addSpacing(8)
        lay.addLayout(bottom)

        self.play_btn.clicked.connect(self._play)
        self.info_btn.clicked.connect(lambda: self.items and self.details.emit(self.items[self.i]["media"]["id"]))
        self.elapsed = 0
        self.tick = QTimer(self, interval=50)
        self.tick.timeout.connect(self._tick)
        self.fade = 1.0
        self._fade = Anim(self, "fade", T.DUR_BASE, on_change=lambda v: self.fx.setOpacity(v))

    def _greet(self) -> str:
        h = _dt.datetime.now().hour
        return "Good morning" if 5 <= h < 12 else "Good afternoon" if h < 17 else "Good evening"

    def set_items(self, items: list[dict]):
        key = [(it["media"]["id"], (it.get("episode") or {}).get("id")) for it in items]
        old = [(it["media"]["id"], (it.get("episode") or {}).get("id")) for it in self.items]
        self.items = items
        self.greeting.setText(self._greet())
        if key != old or self.i >= len(items):
            self.i = 0
        if items:
            self._fill(animate=False)
            self.elapsed = 0
            self.tick.start()
        else:
            self.tick.stop()
        self.dots.set(len(items), self.i)

    def _tick(self):
        if self.hovered or len(self.items) <= 1 or not self.isVisible():
            return
        self.elapsed += 50
        self.dots.progress = min(1.0, self.elapsed / self.INTERVAL)
        self.dots.update()
        if self.elapsed >= self.INTERVAL:
            self.show_index((self.i + 1) % len(self.items))

    def show_index(self, k: int, user: bool = False):
        if not self.items or k == self.i and not user:
            return
        self.i = k
        self.elapsed = 0
        self.dots.progress = 0
        self.dots.set(len(self.items), k)
        self._fade.to(0.0, 140)
        QTimer.singleShot(150, lambda: (self._fill(animate=True), self._fade.to(1.0, 360)))

    def _fill(self, animate: bool):
        it = self.items[self.i]
        m, ep = it["media"], it.get("episode")
        self.set_image(m.get("backdrop"), m.get("poster"), animate=animate)
        self.title.set(m.get("title") or "", m.get("logo"))
        self.kicker.setText(it.get("kicker", ""))
        bits = []
        if ep:
            lab = f"Episode {ep['number']}" if m.get("numbering") == "absolute" else f"S{ep['season']} · E{ep['number']}"
            bits.append(lab + (f"  “{ep['title']}”" if ep.get("title") else ""))
        else:
            if m.get("year"):
                bits.append(str(m["year"]))
            if m.get("runtime") and m["kind"] == "movie":
                bits.append(fmt_runtime(m["runtime"]))
            if m.get("genres"):
                bits.append(" / ".join(m["genres"][:3]))
        if m.get("rating"):
            bits.append(f"★ {m['rating']:.1f}")
        self.meta.setText("    ·    ".join(bits))
        over = (ep or {}).get("overview") or m.get("overview") or ""
        if len(over) > 240:
            over = over[:240].rsplit(" ", 1)[0] + "…"
        self.over.setText(over)
        prog = it.get("progress") or 0
        if ep:
            lab = f"E{ep['number']}" if m.get("numbering") == "absolute" else f"S{ep['season']} E{ep['number']}"
            self.play_btn.setText(("Resume " if prog else "Play ") + lab)
        else:
            self.play_btn.setText("Resume" if prog else "Play")
        self.play_btn.updateGeometry()

    def _play(self):
        if self.items:
            it = self.items[self.i]
            self.play.emit(it["media"]["id"], (it.get("episode") or {}).get("id"))

    def enterEvent(self, e):  # noqa: N802
        self.hovered = True

    def leaveEvent(self, e):  # noqa: N802
        self.hovered = False


# ---------------------------------------------------------------- shelves
class Shelf(QWidget):
    see_all = pyqtSignal(str)

    def __init__(self, title: str, key: str, mode: str, card_w: int, parent=None):
        super().__init__(parent)
        self.key = key
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(6)
        head = QHBoxLayout()
        head.setContentsMargins(48, 0, 40, 0)
        head.setSpacing(6)
        self.label = Label(title, 14, 700, display=True)
        self.count = Label("", 10, 600, T.TEXT_DIM)
        head.addWidget(self.label)
        head.addSpacing(6)
        head.addWidget(self.count, 0, Qt.AlignmentFlag.AlignBottom)
        head.addStretch(1)
        self.more = TactileButton("See all", variant="ghost", size="sm")
        self.more.clicked.connect(lambda: self.see_all.emit(self.key))
        self.left = TactileButton(icon="chevron-left", variant="secondary", size="sm")
        self.right = TactileButton(icon="chevron-right", variant="secondary", size="sm")
        head.addWidget(self.more)
        head.addSpacing(6)
        head.addWidget(self.left)
        head.addWidget(self.right)
        lay.addLayout(head)
        self.row = RowView(mode, card_w)
        self.row.setViewportMargins(37, 0, 37, 0)
        lay.addWidget(self.row)
        self._anim = QPropertyAnimation(self.row.horizontalScrollBar(), b"value", self)
        self._anim.setDuration(T.DUR_SLOW + 120)
        self._anim.setEasingCurve(T.ease_out())
        self.left.clicked.connect(lambda: self._page(-1))
        self.right.clicked.connect(lambda: self._page(1))
        bar = self.row.horizontalScrollBar()
        bar.rangeChanged.connect(lambda *_: self._sync_arrows())
        bar.valueChanged.connect(lambda *_: self._sync_arrows())
        self.row.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)

    def _page(self, d):
        bar = self.row.horizontalScrollBar()
        step = int(self.row.viewport().width() * 0.85)
        self._anim.stop()
        self._anim.setStartValue(bar.value())
        self._anim.setEndValue(max(bar.minimum(), min(bar.maximum(), bar.value() + d * step)))
        self._anim.start()

    def _sync_arrows(self):
        bar = self.row.horizontalScrollBar()
        scrollable = bar.maximum() > 0
        self.left.setVisible(scrollable)
        self.right.setVisible(scrollable)
        self.left.setEnabled(bar.value() > bar.minimum())
        self.right.setEnabled(bar.value() < bar.maximum())

    def set_items(self, items, total: int | None = None):
        self.row.set_items(items)
        n = total if total is not None else len(items)
        self.count.setText(str(n) if n else "")
        self.setVisible(bool(items))
        QTimer.singleShot(0, self._sync_arrows)


class HomeView(QScrollArea):
    open_media = pyqtSignal(int)
    play = pyqtSignal(int, object)            # media_id, episode_id|None
    context_item = pyqtSignal(dict, object)
    navigate = pyqtSignal(str)               # library section key
    add_folder = pyqtSignal()

    def __init__(self, db, parent=None):
        super().__init__(parent)
        self.db = db
        self.setWidgetResizable(True)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        SmoothScroller(self)
        body = QWidget()
        self.setWidget(body)
        self.v = QVBoxLayout(body)
        self.v.setContentsMargins(0, 0, 0, 48)
        self.v.setSpacing(28)

        self.hero = Hero()
        self.hero.play.connect(self.play)
        self.hero.details.connect(self.open_media)
        self.v.addWidget(self.hero)

        self.shelves: dict[str, Shelf] = {}
        for key, title, mode, w in (
            ("continue", "Continue Watching", "landscape", 340),
            ("start", "Start Something New", "poster", 176),
            ("recent", "Recently Added", "poster", 176),
            ("library", "Your Library", "poster", 176),
            ("movie", "Movies", "poster", 176),
            ("anime", "Anime", "poster", 176),
            ("show", "TV Shows", "poster", 176),
        ):
            s = Shelf(title, key, mode, w)
            if key in ("continue", "start"):
                s.more.hide()
            s.see_all.connect(lambda k: self.navigate.emit("all" if k in ("recent", "library") else k))
            s.row.activated_item.connect(self._activated(key))
            s.row.context_item.connect(self.context_item)
            self.shelves[key] = s
            self.v.addWidget(s)

        # empty state
        self.empty = QWidget()
        el = QVBoxLayout(self.empty)
        el.setContentsMargins(48, 80, 48, 0)
        el.setAlignment(Qt.AlignmentFlag.AlignLeft)
        el.addWidget(Label("Your library is empty", 20, 700, display=True))
        el.addSpacing(6)
        el.addWidget(Label("Add a folder and choose what's in it (movies, TV shows or anime). Luminary\n"
                           "scans it once, finds every file and pulls posters, synopses and episode guides.",
                           11, 400, T.TEXT_MUTED))
        el.addSpacing(16)
        b = TactileButton("Add a media folder", icon="folder-plus", variant="accent", size="lg")
        b.clicked.connect(self.add_folder)
        el.addWidget(b)
        self.v.addWidget(self.empty)
        self.v.addStretch(1)

    def resizeEvent(self, e):  # noqa: N802
        super().resizeEvent(e)
        h = int(min(660, max(460, self.viewport().height() * 0.64)))
        if self.hero.height() != h:
            self.hero.setFixedHeight(h)

    def _activated(self, key):
        def f(item):
            if key == "continue":
                m = item["media"]
                self.play.emit(m["id"], (item.get("episode") or {}).get("id"))
            else:
                self.open_media.emit(item["id"])
        return f

    def refresh(self):
        cw = self.db.continue_watching()
        lib = self.db.library(sort="added")
        has_any = bool(lib)
        self.empty.setVisible(not has_any)

        # featured: what you're watching first, then unstarted titles with good art
        featured = []
        for it in cw[:3]:
            featured.append({**it, "kicker": "CONTINUE WATCHING" if it.get("progress") else "UP NEXT"})
        seen = {f["media"]["id"] for f in featured}
        fresh = [m for m in lib if m["id"] not in seen and m["state"] == "unwatched"]
        fresh.sort(key=lambda m: (not m.get("backdrop"), -(m.get("added_at") or 0)))
        for m in fresh[: 6 - len(featured)]:
            featured.append({"media": m, "episode": None, "progress": 0,
                             "kicker": {"movie": "MOVIE", "show": "TV SERIES", "anime": "ANIME"}[m["kind"]]
                             + "  ·  NOT STARTED"})
        if not featured and lib:
            featured = [{"media": lib[0], "episode": None, "progress": 0, "kicker": "IN YOUR LIBRARY"}]
        self.hero.setVisible(bool(featured))
        self.hero.set_items(featured)

        self.shelves["continue"].set_items(cw)
        unstarted = [m for m in lib if m["state"] == "unwatched"]
        self.shelves["start"].set_items(unstarted[:24], len(unstarted))
        small = len(lib) <= 12
        self.shelves["library"].set_items(sorted(lib, key=lambda m: (m["title"] or "").lower()) if small else [])
        self.shelves["recent"].set_items([] if small else lib[:20])
        for k in ("movie", "anime", "show"):
            items = [] if small else [m for m in lib if m["kind"] == k]
            self.shelves[k].set_items(sorted(items, key=lambda m: (m["title"] or "").lower())[:30], len(items))
