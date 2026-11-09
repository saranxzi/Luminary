"""Main window: sidebar navigation + stacked pages + background library worker."""
from __future__ import annotations

import os
import subprocess

from PyQt6.QtCore import QByteArray, QEvent, QObject, QRectF, Qt, QTimer
from PyQt6.QtGui import QKeySequence, QPainter, QShortcut
from PyQt6.QtWidgets import (QApplication, QFileDialog, QHBoxLayout, QLineEdit, QMainWindow, QMenu,
                             QStackedWidget, QVBoxLayout, QWidget)

from core import config
from core.db import Database
from core.tasks import LibraryWorker

from . import icons
from . import theme as T
from .components import Label, TactileButton, Toast, fade_in
from .detail_view import DetailView
from .dialogs import CategoryDialog, FixMatchDialog, SettingsDialog
from .home_view import HomeView
from .library_view import LibraryView
from .player_view import PlayerView


class Brand(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedHeight(64)

    def paintEvent(self, _e):  # noqa: N802
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
        dpr = self.devicePixelRatioF()
        logo = icons.app_icon_pixmap(int(30 * dpr))
        logo.setDevicePixelRatio(dpr)
        p.drawPixmap(19, 17, logo)
        p.setFont(T.font(13, 700, display=True))
        p.setPen(T.c(T.TEXT))
        p.drawText(QRectF(58, 18, 160, 28), Qt.AlignmentFlag.AlignVCenter, "Luminary")


class Sidebar(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedWidth(224)
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground)
        self.setStyleSheet(f"background: {T.SURFACE}; border-right: 1px solid {T.BORDER};")
        v = QVBoxLayout(self)
        v.setContentsMargins(12, 6, 12, 14)
        v.setSpacing(2)
        v.addWidget(Brand())
        v.addSpacing(10)
        self.nav: dict[str, TactileButton] = {}
        for key, label, icon in (("home", "Home", "home"), ("all", "Library", "grid"), ("movie", "Movies", "film"),
                                 ("show", "TV Shows", "tv"), ("anime", "Anime", "sparkles")):
            b = TactileButton(label, icon=icon, variant="nav", size="md", radius=9)
            b.setCheckable(True)
            b.align_left = True
            b.setFixedWidth(200)
            self.nav[key] = b
            v.addWidget(b)
        v.addStretch(1)
        self.status = Label("", 8.5, 500, T.TEXT_DIM, wrap=True)
        self.status.setStyleSheet(f"color: {T.TEXT_DIM}; border: none; padding: 0 8px;")
        v.addWidget(self.status)
        v.addSpacing(6)
        self.stats = Label("", 8.5, 500, T.TEXT_DIM)
        self.stats.setStyleSheet(f"color: {T.TEXT_DIM}; border: none; padding: 0 8px;")
        v.addWidget(self.stats)
        v.addSpacing(8)
        self.scan_btn = TactileButton("Scan library", icon="refresh", variant="nav", size="md", radius=9)
        self.settings_btn = TactileButton("Settings", icon="settings", variant="nav", size="md", radius=9)
        for b in (self.scan_btn, self.settings_btn):
            b.align_left = True
            b.setFixedWidth(200)
            v.addWidget(b)

    def select(self, key: str | None):
        for k, b in self.nav.items():
            b.setChecked(k == key)


class KeyRouter(QObject):
    """App-wide key filter: routes keys to the player while it is active."""

    def __init__(self, win):
        super().__init__(win)
        self.win = win

    def eventFilter(self, obj, ev):  # noqa: N802
        if ev.type() != QEvent.Type.KeyPress:
            return False
        if QApplication.activePopupWidget() is not None or QApplication.activeModalWidget() is not None:
            return False
        if self.win.player.active:
            return bool(self.win.player.handle_key(ev))
        if ev.key() == Qt.Key.Key_Escape and self.win.current[0] == "detail"                 and not isinstance(QApplication.focusWidget(), QLineEdit):
            self.win.back()
            return True
        return False


class MainWindow(QMainWindow):
    def __init__(self, db: Database, settings: config.Settings):
        super().__init__()
        self.db, self.settings = db, settings
        self.setWindowTitle("Luminary")
        self.setWindowIcon(icons.app_icon())
        self.setMinimumSize(980, 640)
        root = QWidget()
        root.setObjectName("Root")
        self.setCentralWidget(root)
        h = QHBoxLayout(root)
        h.setContentsMargins(0, 0, 0, 0)
        h.setSpacing(0)
        self.sidebar = Sidebar()
        h.addWidget(self.sidebar)
        self.stack = QStackedWidget()
        h.addWidget(self.stack, 1)

        self.home = HomeView(db)
        self.library = LibraryView(db)
        self.detail = DetailView(db, settings)
        self.player = PlayerView(db, settings, self)
        for w in (self.home, self.library, self.detail, self.player):
            self.stack.addWidget(w)
        self.toast = Toast(root)

        # navigation
        self.history: list[tuple] = []
        self.current: tuple = ("home",)
        self.sidebar.nav["home"].clicked.connect(lambda: self.go(("home",)))
        for k in ("all", "movie", "show", "anime"):
            self.sidebar.nav[k].clicked.connect(lambda _=False, k=k: self.go(("library", k)))
        self.sidebar.scan_btn.clicked.connect(lambda: self.start_worker(rescan=True))
        self.sidebar.settings_btn.clicked.connect(self.open_settings)

        self.home.open_media.connect(lambda mid: self.go(("detail", mid)))
        self.home.play.connect(self.play)
        self.home.navigate.connect(lambda k: self.go(("library", k)))
        self.home.context_item.connect(self.card_menu)
        self.home.add_folder.connect(self.add_folder_quick)
        self.library.open_media.connect(lambda mid: self.go(("detail", mid)))
        self.library.context_item.connect(self.card_menu)
        self.detail.back.connect(self.back)
        self.detail.play.connect(self.play)
        self.detail.fix_match.connect(self.fix_match)
        self.detail.refresh_meta.connect(self.refresh_metadata)
        self.detail.change_category.connect(self.change_category)
        self.detail.open_folder.connect(self.open_folder)
        self.detail.changed.connect(self._mark_dirty)
        self.player.closed.connect(self._player_closed)
        self.player.progress_changed.connect(self._mark_dirty)
        self.player.fullscreen_requested.connect(self._set_fullscreen)
        self.player.message.connect(lambda m: self.toast.show_message(m))

        QShortcut(QKeySequence("Ctrl+F"), self, activated=self._focus_search)
        QShortcut(QKeySequence("F5"), self, activated=lambda: self.start_worker(rescan=True))
        QShortcut(QKeySequence("Alt+Left"), self, activated=self._back_shortcut)
        self._router = KeyRouter(self)
        QApplication.instance().installEventFilter(self._router)

        self._refresh_timer = QTimer(self, singleShot=True, interval=350)
        self._refresh_timer.timeout.connect(self.refresh_views)
        self.worker: LibraryWorker | None = None
        self._queued_scan: bool | None = None
        self._was_maximized = False

        geo = settings.get("window_geometry")
        if geo:
            self.restoreGeometry(QByteArray.fromHex(geo.encode()))
        else:
            self.resize(1440, 900)

        self.go(("home",), push=False)
        QTimer.singleShot(300, lambda: self.start_worker(rescan=True))

    # ------------------------------------------------------------ navigation
    def go(self, target: tuple, push: bool = True):
        if push and target != self.current and self.current[0] != "player":
            self.history.append(self.current)
            self.history = self.history[-30:]
        self.current = target
        kind = target[0]
        self.sidebar.setVisible(kind != "player")
        if kind == "home":
            self.home.refresh()
            self._show(self.home)
            self.sidebar.select("home")
        elif kind == "library":
            self.library.set_kind(target[1])
            self._show(self.library)
            self.sidebar.select(target[1])
        elif kind == "detail":
            self.detail.show_media(target[1])
            self._show(self.detail)
            self.sidebar.select(None)
        self.setWindowTitle("Luminary")

    def _show(self, w):
        if self.stack.currentWidget() is not w:
            self.stack.setCurrentWidget(w)
            fade_in(w, T.DUR_BASE + 40)

    def back(self):
        if self.history:
            self.go(self.history.pop(), push=False)
        else:
            self.go(("home",), push=False)

    def _back_shortcut(self):
        if self.current[0] == "detail":
            self.back()

    def _focus_search(self):
        if self.current[0] != "library":
            self.go(("library", "all"))
        self.library.focus_search()

    # ------------------------------------------------------------ playback
    def play(self, media_id: int, episode_id=None):
        if self.player.open(media_id, episode_id):
            if self.current[0] != "player":
                self.history.append(self.current)
            self.current = ("player",)
            self.sidebar.hide()
            self.stack.setCurrentWidget(self.player)

    def _player_closed(self):
        self.back()
        self.refresh_views()

    def _set_fullscreen(self, on: bool):
        if on:
            self._was_maximized = self.isMaximized()
            self.showFullScreen()
        else:
            self.showMaximized() if self._was_maximized else self.showNormal()

    # ------------------------------------------------------------ refresh
    def _mark_dirty(self):
        self._refresh_timer.start()

    def refresh_views(self):
        cur = self.current[0]
        if cur == "home":
            self.home.refresh()
        elif cur == "library":
            self.library.refresh()
        elif cur == "detail":
            sb = self.detail.verticalScrollBar().value()
            self.detail.refresh()
            self.detail.verticalScrollBar().setValue(sb)
        c = self.db.counts()
        parts = []
        if c["mv"]:
            parts.append(f"{c['mv']} movie{'s' if c['mv'] != 1 else ''}")
        if c["sh"]:
            parts.append(f"{c['sh']} show{'s' if c['sh'] != 1 else ''}")
        if c["an"]:
            parts.append(f"{c['an']} anime")
        self.sidebar.stats.setText("  ·  ".join(parts))

    # ------------------------------------------------------------ worker
    def start_worker(self, rescan: bool = True):
        if not self.settings.get("library_folders"):
            self.refresh_views()
            return
        if self.worker and self.worker.isRunning():
            self._queued_scan = rescan or bool(self._queued_scan)
            return
        self.worker = LibraryWorker(self.db, self.settings, rescan)
        self.worker.status.connect(self.sidebar.status.setText)
        self.worker.library_changed.connect(self._mark_dirty)
        self.worker.item_updated.connect(lambda _id: self._mark_dirty())
        self.worker.finished_all.connect(self._worker_done)
        self.sidebar.scan_btn.setEnabled(False)
        self.worker.start()

    def _worker_done(self, summary: dict):
        self.sidebar.scan_btn.setEnabled(True)
        self.refresh_views()
        msg = []
        if summary.get("added"):
            msg.append(f"{summary['added']} new file{'s' if summary['added'] != 1 else ''}")
        if summary.get("removed"):
            msg.append(f"{summary['removed']} removed")
        if summary.get("failed"):
            msg.append(f"{summary['failed']} unmatched")
        if msg and self.current[0] != "player":
            self.toast.show_message("Library updated  ·  " + ", ".join(msg), "check-circle")
        if self._queued_scan is not None:
            q, self._queued_scan = self._queued_scan, None
            self.start_worker(q)

    def refresh_metadata(self, media_id: int):
        self.db.reset_metadata(media_id)
        self.start_worker(rescan=False)
        self.toast.show_message("Refreshing metadata…")

    # ------------------------------------------------------------ dialogs / menus
    def open_settings(self):
        d = SettingsDialog(self.settings, self)
        d.folders_changed.connect(self._folders_changed)
        d.refresh_all.connect(self._refresh_all)
        d.exec()

    def _refresh_all(self):
        self.db.reset_metadata(None)
        self.start_worker(rescan=True)

    def _folders_changed(self):
        self.start_worker(rescan=True)  # every scan re-resolves every file, so new categories apply

    def add_folder_quick(self):
        start = str(config.APP_DIR.parent)
        d = QFileDialog.getExistingDirectory(self, "Choose your media folder", start)
        if not d:
            return
        d = d.replace("/", "\\")
        kind = CategoryDialog.ask(self, d)
        if not kind:
            return
        folders = [f for f in self.settings.folders() if f["path"].lower() != d.lower()]
        folders.append({"path": d, "kind": kind})
        self.settings.set_folders(folders)
        self._folders_changed()

    def change_category(self, media_id: int, kind: str):
        """Pin a title to a category. Series are pinned by their folder when that folder holds
        nothing else; otherwise (and for movies) each file is pinned individually."""
        m = self.db.media(media_id)
        if not m or m["kind"] == kind:
            return
        files = self.db.media_files(media_id)
        folder = m.get("folder")
        own_folder = (m["kind"] != "movie" and folder and os.path.isdir(folder) and not any(
            row["media_id"] != media_id and os.path.normcase(p).startswith(os.path.normcase(os.path.join(folder, "")))
            for p, row in self.db.known_files().items()))
        for target in ([folder] if own_folder else files):
            self.settings.set_override(target, kind)
        self.toast.show_message(f"Moving to {config.KIND_LABELS[kind]}…")
        if self.current[0] == "detail":
            self.back()
        self.start_worker(rescan=True)

    def _category_menu(self, parent_menu: QMenu, media_id: int, current: str):
        sub = parent_menu.addMenu(icons.icon("grid"), "Change category")
        for k in ("movie", "show", "anime"):
            a = sub.addAction(config.KIND_LABELS[k], lambda k=k: self.change_category(media_id, k))
            a.setCheckable(True)
            a.setChecked(k == current)

    def fix_match(self, media_id: int):
        m = self.db.media(media_id)
        if not m:
            return
        d = FixMatchDialog(self.db, self.settings, m, self)
        d.applied.connect(lambda _id: (self.refresh_views(), self.toast.show_message("Match updated", "check-circle")))
        d.exec()

    def card_menu(self, item: dict, pos):
        m = item.get("media") or item
        ep = item.get("episode")
        menu = QMenu(self)
        if ep:
            menu.addAction(icons.icon("play"), f"Play episode {ep['number']}", lambda: self.play(m["id"], ep["id"]))
        else:
            menu.addAction(icons.icon("play"), "Play", lambda: self.play(m["id"], None))
        menu.addAction(icons.icon("info"), "Details", lambda: self.go(("detail", m["id"])))
        menu.addSeparator()
        full = self.db.media(m["id"])
        state = item.get("state") or next((x["state"] for x in self.db.library() if x["id"] == m["id"]), None)
        watched = state == "watched"
        menu.addAction(icons.icon("check"), "Mark unwatched" if watched else "Mark watched",
                       lambda: self._set_watched(m["id"], not watched))
        self._category_menu(menu, m["id"], (full or m)["kind"])
        menu.addAction(icons.icon("pencil"), "Fix match…", lambda: self.fix_match(m["id"]))
        menu.addAction(icons.icon("refresh"), "Refresh metadata", lambda: self.refresh_metadata(m["id"]))
        if full and full.get("folder"):
            menu.addAction(icons.icon("folder"), "Open folder", lambda: self.open_folder(m["id"]))
        menu.exec(pos)

    def _set_watched(self, media_id, watched):
        self.db.set_watched(media_id=media_id, watched=watched, owned_only=True)
        self.refresh_views()

    def open_folder(self, media_id: int):
        """Show a movie's file selected in Explorer, or open a series folder."""
        m = self.db.media(media_id)
        if not m:
            return
        if m["kind"] == "movie":
            path = self.db.movie_file(m["id"])
            if path and os.path.exists(path):
                subprocess.Popen(["explorer", "/select,", os.path.normpath(path)])
                return
        if m.get("folder") and os.path.isdir(m["folder"]):
            os.startfile(m["folder"])  # noqa: S606

    # ------------------------------------------------------------ window
    def showEvent(self, e):  # noqa: N802
        T.apply_dark_titlebar(self)
        super().showEvent(e)

    def closeEvent(self, e):  # noqa: N802
        self.player.shutdown()
        if not self.isFullScreen():
            self.settings.set("window_geometry", bytes(self.saveGeometry().toHex()).decode())
        if self.worker and self.worker.isRunning():
            self.worker.stop()
            self.worker.wait(10000)
        super().closeEvent(e)
