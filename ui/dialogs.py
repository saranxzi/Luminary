"""Settings and Fix-match dialogs."""
from __future__ import annotations

from PyQt6.QtCore import QSize, Qt, pyqtSignal
from PyQt6.QtGui import QIcon
from PyQt6.QtWidgets import (QCheckBox, QDialog, QFileDialog, QHBoxLayout, QLineEdit, QListWidget,
                             QListWidgetItem, QSpinBox, QVBoxLayout)

from core import images, scraper
from core.tasks import run_async

from . import theme as T
from .components import ChipGroup, Label, TactileButton


class _Dialog(QDialog):
    def __init__(self, parent, title):
        super().__init__(parent)
        self.setWindowTitle(title)
        self.setModal(True)
        self.setStyleSheet(f"QDialog {{ background: {T.SURFACE}; }}")

    def showEvent(self, e):  # noqa: N802
        T.apply_dark_titlebar(self)
        super().showEvent(e)


def _section(text):
    return Label(text.upper(), 8.25, 700, T.TEXT_DIM)


class CategoryCard(TactileButton):
    """Large selectable option card."""

    def __init__(self, key, title, sub, icon, parent=None):
        super().__init__(title, icon=icon, variant="secondary", size="lg", parent=parent, radius=14)
        self.key, self.sub = key, sub
        self.setCheckable(True)
        self.setFixedSize(260, 104)

    def paintEvent(self, e):  # noqa: N802
        from PyQt6.QtCore import QRectF
        from PyQt6.QtGui import QPainter, QPainterPath, QPen

        from . import icons
        from .components import _mix
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        r = QRectF(self.rect()).adjusted(1, 1, -1, -1)
        s = 1.0 - 0.02 * self.prs
        p.translate(r.center())
        p.scale(s, s)
        p.translate(-r.center())
        bg = _mix(T.c("rgba(255,255,255,0.04)"), T.c("rgba(255,255,255,0.08)"), self.hov)
        bg = _mix(bg, T.c("rgba(59,130,246,0.16)"), self.chk)
        path = QPainterPath()
        path.addRoundedRect(r, 14, 14)
        p.fillPath(path, bg)
        p.setPen(QPen(_mix(T.c(T.BORDER), T.c(T.ACCENT_HI), self.chk), 1.5))
        p.drawPath(path)
        icons.draw(p, self._icon, QRectF(r.left() + 18, r.top() + 18, 24, 24),
                   _mix(T.c(T.TEXT_MUTED), T.c(T.ACCENT_HI), self.chk))
        p.setPen(T.c(T.TEXT))
        p.setFont(T.font(11, 650))
        p.drawText(QRectF(r.left() + 54, r.top() + 14, r.width() - 60, 30), Qt.AlignmentFlag.AlignVCenter,
                   self.text())
        p.setPen(T.c(T.TEXT_MUTED))
        p.setFont(T.font(8.75))
        p.drawText(QRectF(r.left() + 18, r.top() + 52, r.width() - 30, r.height() - 56),
                   Qt.AlignmentFlag.AlignTop | Qt.TextFlag.TextWordWrap, self.sub)


class CategoryDialog(_Dialog):
    """Asks what kind of media a folder holds, so nothing has to be guessed."""

    OPTIONS = [
        ("movie", "Movies", "Every video is a separate film.", "film"),
        ("show", "TV Shows", "Series with seasons and episodes.", "tv"),
        ("anime", "Anime", "Anime series, including absolute numbering (001–366).", "sparkles"),
        ("auto", "Mixed", "Has Movies / Shows / Anime subfolders; sort by their names.", "grid"),
    ]

    def __init__(self, path: str, current: str | None = None, parent=None):
        super().__init__(parent, "Choose a category")
        import os

        from PyQt6.QtWidgets import QGridLayout
        self.kind = current
        v = QVBoxLayout(self)
        v.setContentsMargins(28, 24, 28, 22)
        v.setSpacing(10)
        v.addWidget(Label("What's in this folder?", 16, 700, display=True))
        pl = Label(path, 9.25, 500, T.TEXT_MUTED)
        pl.setWordWrap(True)
        v.addWidget(pl)
        hint = None
        try:
            subs = {d.lower() for d in os.listdir(path) if os.path.isdir(os.path.join(path, d))}
            found = [n for n in ("Movies", "Films", "Shows", "TV Shows", "Series", "Anime") if n.lower() in subs]
            if found:
                hint = f"Found {', '.join(found)} subfolders. “Mixed” sorts them by those names."
                self.kind = self.kind or "auto"
        except OSError:
            pass
        v.addSpacing(6)
        grid = QGridLayout()
        grid.setSpacing(12)
        self.cards = {}
        for i, (key, title, sub, icon) in enumerate(self.OPTIONS):
            c = CategoryCard(key, title, sub, icon)
            c.clicked.connect(lambda _=False, k=key: self._pick(k))
            grid.addWidget(c, i // 2, i % 2)
            self.cards[key] = c
        v.addLayout(grid)
        if hint:
            v.addWidget(Label(hint, 9, 500, T.ACCENT_HI))
        v.addSpacing(8)
        br = QHBoxLayout()
        br.addStretch(1)
        cancel = TactileButton("Cancel", variant="ghost")
        self.ok = TactileButton("Add folder" if current is None else "Save", variant="primary")
        cancel.clicked.connect(self.reject)
        self.ok.clicked.connect(self.accept)
        br.addWidget(cancel)
        br.addWidget(self.ok)
        v.addLayout(br)
        self._pick(self.kind)

    def _pick(self, key):
        self.kind = key
        for k, c in self.cards.items():
            c.setChecked(k == key)
        self.ok.setEnabled(key is not None)

    @staticmethod
    def ask(parent, path: str, current: str | None = None) -> str | None:
        d = CategoryDialog(path, current, parent)
        return d.kind if d.exec() and d.kind else None


class SettingsDialog(_Dialog):
    folders_changed = pyqtSignal()
    refresh_all = pyqtSignal()

    def __init__(self, settings, parent=None):
        super().__init__(parent, "Settings")
        self.settings = settings
        self.resize(620, 560)
        v = QVBoxLayout(self)
        v.setContentsMargins(28, 24, 28, 22)
        v.setSpacing(10)
        v.addWidget(Label("Settings", 17, 700, display=True))
        v.addSpacing(6)

        v.addWidget(_section("Library folders"))
        v.addWidget(Label("Each folder has a category, so Luminary never has to guess what's inside.", 9.25, 400,
                          T.TEXT_MUTED))
        self.folders = QListWidget()
        self.folders.setMinimumHeight(130)
        self._folders = [dict(f) for f in settings.folders()]
        self._render_folders()
        self.folders.itemDoubleClicked.connect(lambda _: self._recategorize())
        v.addWidget(self.folders)
        fr = QHBoxLayout()
        add = TactileButton("Add folder", icon="folder-plus", variant="secondary", size="sm")
        cat = TactileButton("Change category", icon="pencil", variant="ghost", size="sm")
        rem = TactileButton("Remove", icon="trash", variant="ghost", size="sm")
        add.clicked.connect(self._add)
        cat.clicked.connect(self._recategorize)
        rem.clicked.connect(self._remove)
        fr.addWidget(add)
        fr.addWidget(cat)
        fr.addWidget(rem)
        fr.addStretch(1)
        v.addLayout(fr)
        v.addSpacing(10)

        v.addWidget(_section("Playback"))
        row = QHBoxLayout()
        row.addWidget(Label("Mark as watched after", 9.75))
        self.threshold = QSpinBox()
        self.threshold.setRange(50, 100)
        self.threshold.setSuffix(" %")
        self.threshold.setValue(int(round(float(settings.get("watched_threshold") or 0.9) * 100)))
        self.threshold.setFixedWidth(90)
        row.addWidget(self.threshold)
        row.addStretch(1)
        v.addLayout(row)
        self.auto_next = QCheckBox("Automatically play the next episode")
        self.auto_next.setChecked(bool(settings.get("auto_next")))
        v.addWidget(self.auto_next)
        v.addSpacing(10)

        v.addWidget(_section("Metadata"))
        v.addWidget(Label("Movies use Cinemeta, shows use TVMaze, anime uses AniList — no account needed.\n"
                          "Optionally add a free TMDB API key for TMDB movie data.", 9.25, 400, T.TEXT_MUTED))
        self.tmdb = QLineEdit(settings.get("tmdb_api_key") or "")
        self.tmdb.setPlaceholderText("TMDB API key (optional)")
        self.tmdb.setEchoMode(QLineEdit.EchoMode.PasswordEchoOnEdit)
        v.addWidget(self.tmdb)
        mr = QHBoxLayout()
        refresh = TactileButton("Refresh all metadata", icon="refresh", variant="secondary", size="sm")
        refresh.clicked.connect(self._refresh_all)
        mr.addWidget(refresh)
        mr.addStretch(1)
        v.addLayout(mr)
        v.addStretch(1)

        br = QHBoxLayout()
        br.addStretch(1)
        cancel = TactileButton("Cancel", variant="ghost")
        save = TactileButton("Save", variant="primary")
        cancel.clicked.connect(self.reject)
        save.clicked.connect(self._save)
        br.addWidget(cancel)
        br.addWidget(save)
        v.addLayout(br)
        self._orig = [dict(f) for f in self._folders]

    def _render_folders(self):
        from core.config import KIND_LABELS
        sel = self.folders.currentRow()
        self.folders.clear()
        for f in self._folders:
            it = QListWidgetItem(f"{f['path']}\n{KIND_LABELS.get(f['kind'], f['kind'])}")
            it.setSizeHint(QSize(0, 52))
            self.folders.addItem(it)
        if 0 <= sel < self.folders.count():
            self.folders.setCurrentRow(sel)

    def _add(self):
        d = QFileDialog.getExistingDirectory(self, "Choose a media folder")
        if not d:
            return
        d = d.replace("/", "\\")
        if any(f["path"].lower() == d.lower() for f in self._folders):
            return
        kind = CategoryDialog.ask(self, d)
        if kind:
            self._folders.append({"path": d, "kind": kind})
            self._render_folders()

    def _recategorize(self):
        row = self.folders.currentRow()
        if row < 0:
            return
        f = self._folders[row]
        kind = CategoryDialog.ask(self, f["path"], f["kind"])
        if kind and kind != f["kind"]:
            f["kind"] = kind
            self._render_folders()

    def _remove(self):
        row = self.folders.currentRow()
        if row >= 0:
            self._folders.pop(row)
            self._render_folders()

    def _refresh_all(self):
        self._save(close=False)
        self.refresh_all.emit()
        self.accept()

    def _save(self, close=True):
        self.settings.set_folders(self._folders)
        self.settings.set("watched_threshold", self.threshold.value() / 100)
        self.settings.set("auto_next", self.auto_next.isChecked())
        self.settings.set("tmdb_api_key", self.tmdb.text().strip())
        if self._folders != self._orig:
            self._orig = [dict(f) for f in self._folders]
            self.folders_changed.emit()
        if close:
            self.accept()


class FixMatchDialog(_Dialog):
    applied = pyqtSignal(int)

    def __init__(self, db, settings, media: dict, parent=None):
        super().__init__(parent, "Fix match")
        self.db, self.settings, self.media = db, settings, media
        self.resize(640, 600)
        self.results: list[dict] = []
        v = QVBoxLayout(self)
        v.setContentsMargins(28, 24, 28, 22)
        v.setSpacing(10)
        v.addWidget(Label("Fix match", 17, 700, display=True))
        v.addWidget(Label(f"Pick the correct title for “{media['parsed_title']}”.", 9.5, 400, T.TEXT_MUTED))
        self.kind = ChipGroup([("movie", "Movie"), ("show", "TV Show"), ("anime", "Anime")])
        self.kind.set_value(media["kind"])
        v.addWidget(self.kind)
        sr = QHBoxLayout()
        self.q = QLineEdit(media["parsed_title"])
        self.q.returnPressed.connect(self._search)
        go = TactileButton("Search", icon="search", variant="secondary")
        go.clicked.connect(self._search)
        sr.addWidget(self.q, 1)
        sr.addWidget(go)
        v.addLayout(sr)
        self.status = Label("", 9, 500, T.TEXT_MUTED)
        v.addWidget(self.status)
        self.list = QListWidget()
        self.list.setIconSize(QSize(46, 69))
        self.list.setWordWrap(True)
        self.list.itemDoubleClicked.connect(lambda _: self._apply())
        v.addWidget(self.list, 1)
        br = QHBoxLayout()
        br.addStretch(1)
        cancel = TactileButton("Cancel", variant="ghost")
        self.use = TactileButton("Use this match", icon="check", variant="primary")
        cancel.clicked.connect(self.reject)
        self.use.clicked.connect(self._apply)
        br.addWidget(cancel)
        br.addWidget(self.use)
        v.addLayout(br)
        images.loader().ready.connect(self._img_ready)
        self.kind.changed.connect(lambda _: self._search())
        self._search()

    def _search(self):
        q = self.q.text().strip()
        if not q:
            return
        self.status.setText("Searching…")
        self.list.clear()
        kind = self.kind.value
        run_async(scraper.search, kind, q, self.settings.get("tmdb_api_key") or "",
                  on_done=self._show, on_error=lambda e: self.status.setText(f"Search failed: {e}"))

    def _show(self, results):
        self.results = results
        self.list.clear()
        self.status.setText(f"{len(results)} results" if results else "No results — try a different title or type")
        for i, r in enumerate(results):
            text = f"{r['title']}" + (f"  ({r['year']})" if r.get("year") else "")
            ov = (r.get("overview") or "").replace("\n", " ")
            if ov:
                text += "\n" + (ov[:140] + "…" if len(ov) > 140 else ov)
            it = QListWidgetItem(text)
            it.setData(Qt.ItemDataRole.UserRole, i)
            it.setSizeHint(QSize(0, 84))
            pm = images.loader().get(r.get("poster"))
            if pm is not None:
                it.setIcon(QIcon(pm))
            self.list.addItem(it)
        if results:
            self.list.setCurrentRow(0)

    def _img_ready(self, url):
        for i in range(self.list.count()):
            it = self.list.item(i)
            r = self.results[it.data(Qt.ItemDataRole.UserRole)]
            if r.get("poster") == url:
                pm = images.loader().get(url)
                if pm is not None:
                    it.setIcon(QIcon(pm))

    def _apply(self):
        it = self.list.currentItem()
        if not it:
            return
        cand = self.results[it.data(Qt.ItemDataRole.UserRole)]
        kind = self.kind.value
        self.status.setText("Fetching details…")
        self.use.setEnabled(False)

        def fetch():
            return scraper.fetch(kind, cand, self.media.get("numbering") or "seasons",
                                 self.settings.get("tmdb_api_key") or "")

        def done(res):
            meta, eps = res
            if kind != self.media["kind"]:
                self.db.set_kind(self.media["id"], kind)
            self.db.apply_metadata(self.media["id"], meta, eps, lock=True)
            self.applied.emit(self.media["id"])
            self.accept()

        def fail(e):
            self.use.setEnabled(True)
            self.status.setText(f"Couldn't fetch details: {e}")

        run_async(fetch, on_done=done, on_error=fail)
