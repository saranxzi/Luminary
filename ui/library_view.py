"""Category page: watch statistics, search, status filters, sorting and the poster grid."""
from __future__ import annotations

from PyQt6.QtCore import QRectF, Qt, pyqtSignal
from PyQt6.QtGui import QColor, QPainter, QPainterPath, QPen
from PyQt6.QtWidgets import QComboBox, QHBoxLayout, QSizePolicy, QStackedLayout, QVBoxLayout, QWidget

from . import icons
from . import theme as T
from .cards import GridView, draw_progress
from .components import Anim, ChipGroup, Label, SearchBar, fmt_duration

TITLES = {"all": "Library", "movie": "Movies", "show": "TV Shows", "anime": "Anime"}


class StatTile(QWidget):
    def __init__(self, icon: str, label: str, parent=None):
        super().__init__(parent)
        self.icon, self.label = icon, label
        self.value, self.sub, self.frac = "", "", None
        self.setFixedHeight(96)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.hov = 0.0
        self._a = Anim(self, "hov", T.DUR_FAST)

    def set(self, value: str, sub: str, frac: float | None = None):
        self.value, self.sub, self.frac = value, sub, frac
        self.update()

    def enterEvent(self, e):  # noqa: N802
        self._a.to(1.0)

    def leaveEvent(self, e):  # noqa: N802
        self._a.to(0.0)

    def paintEvent(self, _e):  # noqa: N802
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        r = QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5)
        path = QPainterPath()
        path.addRoundedRect(r, 14, 14)
        p.fillPath(path, QColor(255, 255, 255, int(9 + 7 * self.hov)))
        p.setPen(QPen(QColor(255, 255, 255, int(16 + 14 * self.hov)), 1))
        p.drawPath(path)
        ib = QRectF(r.left() + 16, r.top() + 15, 26, 26)
        bp = QPainterPath()
        bp.addRoundedRect(ib, 8, 8)
        p.fillPath(bp, T.c(T.ACCENT, 0.16))
        icons.draw(p, self.icon, ib.adjusted(6, 6, -6, -6), T.c(T.ACCENT_HI))
        p.setPen(T.c(T.TEXT_MUTED))
        p.setFont(T.font(9, 600))
        p.drawText(QRectF(ib.right() + 10, ib.top(), r.width() - 70, ib.height()), Qt.AlignmentFlag.AlignVCenter,
                   self.label)
        p.setPen(T.c(T.TEXT))
        p.setFont(T.font(16, 700, display=True))
        p.drawText(QRectF(r.left() + 16, r.top() + 46, r.width() - 32, 26), Qt.AlignmentFlag.AlignVCenter, self.value)
        p.setPen(T.c(T.TEXT_DIM))
        p.setFont(T.font(8.5, 500))
        p.drawText(QRectF(r.left() + 16, r.top() + 70, r.width() - 32, 16), Qt.AlignmentFlag.AlignVCenter, self.sub)
        if self.frac is not None:
            draw_progress(p, QRectF(r.right() - 96, r.top() + 57, 80, 5), self.frac,
                          T.SUCCESS if self.frac >= 1 else T.ACCENT)


class LibraryView(QWidget):
    open_media = pyqtSignal(int)
    context_item = pyqtSignal(dict, object)

    def __init__(self, db, parent=None):
        super().__init__(parent)
        self.db = db
        self.kind = "all"
        v = QVBoxLayout(self)
        v.setContentsMargins(0, 26, 0, 0)
        v.setSpacing(16)

        head = QHBoxLayout()
        head.setContentsMargins(40, 0, 40, 0)
        tcol = QVBoxLayout()
        tcol.setSpacing(2)
        self.title = Label("Library", 22, 700, display=True)
        self.count = Label("", 9.5, 500, T.TEXT_MUTED)
        tcol.addWidget(self.title)
        tcol.addWidget(self.count)
        head.addLayout(tcol)
        head.addStretch(1)
        self.search = SearchBar()
        self.search.search.connect(lambda _: self.refresh())
        head.addWidget(self.search, 0, Qt.AlignmentFlag.AlignVCenter)
        v.addLayout(head)

        self.stats = QWidget()
        sl = QHBoxLayout(self.stats)
        sl.setContentsMargins(40, 0, 40, 0)
        sl.setSpacing(12)
        self.t_progress = StatTile("check-circle", "Watched")
        self.t_left = StatTile("clock", "Left to watch")
        self.t_done = StatTile("eye", "Watched so far")
        self.t_active = StatTile("play", "In progress")
        for t in (self.t_progress, self.t_left, self.t_done, self.t_active):
            sl.addWidget(t)
        v.addWidget(self.stats)

        bar = QHBoxLayout()
        bar.setContentsMargins(40, 0, 40, 0)
        self.status = ChipGroup([("all", "All"), ("unwatched", "Unwatched"), ("in_progress", "In progress"),
                                 ("watched", "Watched")])
        self.status.changed.connect(lambda _: self.refresh())
        bar.addWidget(self.status)
        bar.addStretch(1)
        bar.addWidget(Label("Sort", 9, 500, T.TEXT_DIM))
        self.sort = QComboBox()
        for key, label in (("title", "Title"), ("added", "Recently added"), ("recent", "Recently watched"),
                           ("year", "Release year"), ("rating", "Rating")):
            self.sort.addItem(label, key)
        self.sort.setFixedWidth(170)
        self.sort.currentIndexChanged.connect(lambda _: self.refresh())
        bar.addWidget(self.sort)
        v.addLayout(bar)

        self.stack = QStackedLayout()
        self.grid = GridView()
        self.grid.activated_item.connect(lambda it: self.open_media.emit(it["id"]))
        self.grid.context_item.connect(self.context_item)
        self.stack.addWidget(self.grid)
        empty = QWidget()
        el = QVBoxLayout(empty)
        el.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.empty_title = Label("Nothing here yet", 13, 650, display=True)
        self.empty_sub = Label("", 10, 400, T.TEXT_MUTED)
        for w in (self.empty_title, self.empty_sub):
            w.setAlignment(Qt.AlignmentFlag.AlignCenter)
            el.addWidget(w)
        self.stack.addWidget(empty)
        v.addLayout(self.stack, 1)

    def set_kind(self, kind: str):
        self.kind = kind
        self.title.setText(TITLES.get(kind, "Library"))
        self.refresh()

    def focus_search(self):
        self.search.setFocus()
        self.search.selectAll()

    def _refresh_stats(self):
        s = self.db.stats(self.kind)
        self.stats.setVisible(s["titles"] > 0)
        if self.kind == "movie":
            done, total, noun = s["movies_watched"], s["movies"], "movies watched"
        elif self.kind in ("show", "anime"):
            done, total = s["episodes_watched"], s["episodes"]
            noun = f"episodes · {s['series_done']}/{s['series']} series finished"
        else:
            done = s["movies_watched"] + s["episodes_watched"]
            total, noun = s["movies"] + s["episodes"], "movies & episodes watched"
        self.t_progress.set(f"{done} / {total}", noun, done / total if total else None)
        remaining = total - done
        self.t_left.set(fmt_duration(s["left_s"]), f"{remaining} to go · estimated from runtimes")
        self.t_done.set(fmt_duration(s["watched_s"]), "time spent watching")
        self.t_active.set(str(s["in_progress"]), "titles started but not finished")

    def refresh(self):
        items = self.db.library(kind=self.kind, status=self.status.value, search=self.search.text().strip(),
                                sort=self.sort.currentData())
        sb = self.grid.verticalScrollBar().value()  # keep the scroll position across refreshes
        self.grid.set_items(items)
        self.grid.verticalScrollBar().setValue(sb)
        self._refresh_stats()
        total = len(self.db.library(kind=self.kind))
        noun = {"movie": "movie", "show": "show", "anime": "series"}.get(self.kind, "title")
        self.count.setText(f"{total} {noun if noun == 'series' or total == 1 else noun + 's'}")
        if items:
            self.stack.setCurrentIndex(0)
            return
        self.stack.setCurrentIndex(1)
        query = self.search.text().strip()
        if query:
            self.empty_title.setText("No matches")
            self.empty_sub.setText(f"Nothing in your library matches “{query}”.")
        elif self.status.value != "all":
            self.empty_title.setText("Nothing here")
            self.empty_sub.setText("No titles match this filter.")
        else:
            self.empty_title.setText("Nothing here yet")
            self.empty_sub.setText("Add a folder in Settings and Luminary will find everything in it.")
