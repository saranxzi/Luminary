"""Title detail page: hero, actions, info and the episode guide."""
from __future__ import annotations

import os

from PyQt6.QtCore import QPointF, QRectF, Qt, pyqtSignal
from PyQt6.QtGui import QColor, QFontMetricsF, QPainter, QPainterPath, QPen
from PyQt6.QtWidgets import QHBoxLayout, QMenu, QScrollArea, QVBoxLayout, QWidget

from core import images

from . import icons
from . import theme as T
from .backdrop import Backdrop
from .cards import draw_image, draw_pill, draw_progress
from .components import (Anim, ChipGroup, Label, SmoothScroller, TactileButton, fmt_duration, fmt_runtime,
                         fmt_time)
from .home_view import LogoOrTitle

PAGE = 50


def _two_lines(fm: QFontMetricsF, text: str, width: float) -> list[str]:
    words = (text or "").replace("\n", " ").split()
    lines, cur = [], ""
    for i, w in enumerate(words):
        t = (cur + " " + w).strip()
        if fm.horizontalAdvance(t) <= width:
            cur = t
            continue
        lines.append(cur)
        if len(lines) == 1:
            rest = " ".join(words[i:])
            lines.append(fm.elidedText(rest, Qt.TextElideMode.ElideRight, width))
            return lines
        cur = w
    if cur:
        lines.append(cur)
    return lines[:2]


class EpisodeRow(QWidget):
    play = pyqtSignal(int)
    toggle_watched = pyqtSignal(int, bool)

    H = 116

    def __init__(self, media: dict, ep: dict, parent=None):
        super().__init__(parent)
        self.media, self.ep = media, ep
        self.owned = bool(ep.get("file_path"))
        self.hov = 0.0
        self._a = Anim(self, "hov", T.DUR_FAST)
        self.setFixedHeight(self.H)
        self.setMouseTracking(True)
        self.setCursor(Qt.CursorShape.PointingHandCursor if self.owned else Qt.CursorShape.ArrowCursor)
        self.btn = TactileButton(icon="check-filled" if ep["watched"] else "circle", variant="ghost", size="md",
                                 parent=self)
        self.btn.setToolTip("Mark unwatched" if ep["watched"] else "Mark watched")
        self.btn.icon_color_override = T.SUCCESS if ep["watched"] else T.TEXT_DIM
        self.btn.clicked.connect(lambda: self.toggle_watched.emit(self.ep["id"], not self.ep["watched"]))
        images.loader().ready.connect(self._img_ready)

    def _img_ready(self, url):
        if url in (self.ep.get("still"), self.media.get("backdrop")):
            self.update()

    def resizeEvent(self, e):  # noqa: N802
        self.btn.move(self.width() - 50, (self.H - 38) // 2)

    def enterEvent(self, e):  # noqa: N802
        self._a.to(1.0)

    def leaveEvent(self, e):  # noqa: N802
        self._a.to(0.0)

    def mouseReleaseEvent(self, e):  # noqa: N802
        if self.owned and e.button() == Qt.MouseButton.LeftButton and self.rect().contains(e.position().toPoint()):
            self.play.emit(self.ep["id"])

    def paintEvent(self, _e):  # noqa: N802
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
        r = QRectF(self.rect()).adjusted(0, 4, 0, -4)
        if self.hov > 0.01 and self.owned:
            path = QPainterPath()
            path.addRoundedRect(r, 12, 12)
            p.fillPath(path, QColor(255, 255, 255, int(12 * self.hov)))
        if not self.owned:
            p.setOpacity(0.42)
        th = QRectF(r.left() + 10, r.top() + 8, 160, 90)
        url = self.ep.get("still") or self.media.get("backdrop") or self.media.get("poster")
        draw_image(p, url, th, 8, "")
        if self.owned:
            if self.hov > 0.01:
                p.save()
                p.setOpacity(self.hov)
                c = th.center()
                p.setPen(Qt.PenStyle.NoPen)
                p.setBrush(QColor(255, 255, 255, 235))
                p.drawEllipse(QPointF(c.x(), c.y()), 18, 18)
                icons.draw(p, "play", QRectF(c.x() - 8 + 1.5, c.y() - 8, 16, 16), QColor("#0b0c10"))
                p.restore()
            dur, pos = self.ep.get("duration") or 0, self.ep.get("position") or 0
            if pos > 0 and dur > 0 and not self.ep["watched"]:
                draw_progress(p, QRectF(th.left() + 8, th.bottom() - 9, th.width() - 16, 3.5), pos / dur)
        p.setPen(QPen(QColor(255, 255, 255, 22), 1))
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.drawRoundedRect(th.adjusted(0.5, 0.5, -0.5, -0.5), 8, 8)

        x = th.right() + 18
        w = r.width() - x - 70
        num = self.ep["number"]
        title = self.ep.get("title") or f"Episode {num}"
        p.setFont(T.font(10.25, 600))
        fm = QFontMetricsF(p.font())
        p.setPen(T.c(T.TEXT))
        head = f"{num}.  {title}"
        p.drawText(QRectF(x, th.top(), w, 22), Qt.AlignmentFlag.AlignVCenter,
                   fm.elidedText(head, Qt.TextElideMode.ElideRight, w))
        p.setFont(T.font(8.75, 500))
        p.setPen(T.c(T.TEXT_DIM))
        meta = []
        if self.ep.get("air_date"):
            meta.append(self.ep["air_date"])
        if self.ep.get("runtime"):
            meta.append(f"{self.ep['runtime']}m")
        if self.owned and self.ep.get("position") and not self.ep["watched"] and self.ep.get("duration"):
            meta.append(f"{fmt_time(self.ep['duration'] - self.ep['position'])} left")
        mx = x
        if not self.owned:
            pr = draw_pill(p, x, th.top() + 25, "NOT IN LIBRARY", QColor(255, 255, 255, 18), T.c(T.TEXT_MUTED))
            mx = pr.right() + 10
        p.setFont(T.font(8.75, 500))
        p.setPen(T.c(T.TEXT_DIM))
        p.drawText(QRectF(mx, th.top() + 24, w, 22), Qt.AlignmentFlag.AlignVCenter, "  ·  ".join(meta))
        p.setFont(T.font(9.25))
        p.setPen(T.c(T.TEXT_MUTED))
        fm2 = QFontMetricsF(p.font())
        for i, line in enumerate(_two_lines(fm2, self.ep.get("overview") or "", w)):
            p.drawText(QRectF(x, th.top() + 50 + i * 19, w, 19), Qt.AlignmentFlag.AlignVCenter, line)


class DetailView(QScrollArea):
    back = pyqtSignal()
    play = pyqtSignal(int, object)          # media_id, episode_id|None
    fix_match = pyqtSignal(int)
    refresh_meta = pyqtSignal(int)
    change_category = pyqtSignal(int, str)
    open_folder = pyqtSignal(int)
    changed = pyqtSignal()

    def __init__(self, db, settings, parent=None):
        super().__init__(parent)
        self.db, self.settings = db, settings
        self.media: dict | None = None
        self.page_key = None
        self.setWidgetResizable(True)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        SmoothScroller(self)
        body = QWidget()
        self.setWidget(body)
        v = QVBoxLayout(body)
        v.setContentsMargins(0, 0, 0, 48)
        v.setSpacing(0)

        # ---------------- hero
        self.hero = Backdrop(height=520)
        hl = QVBoxLayout(self.hero)
        hl.setContentsMargins(40, 22, 40, 26)
        top = QHBoxLayout()
        self.back_btn = TactileButton("Back", icon="back", variant="glass", size="md")
        self.back_btn.clicked.connect(self.back)
        top.addWidget(self.back_btn)
        top.addStretch(1)
        hl.addLayout(top)
        hl.addStretch(1)
        self.kicker = Label("", 8.5, 700, T.ACCENT_HI)
        self.title = LogoOrTitle(max_h=120, font_size=34)
        self.meta = Label("", 9.75, 500, T.TEXT_MUTED)
        self.genres = Label("", 9.25, 500, T.TEXT_DIM)
        self.overview = Label("", 10.5, 400, "#c9cfdb", wrap=True)
        self.overview.setMaximumWidth(640)
        hl.addWidget(self.kicker)
        hl.addSpacing(6)
        hl.addWidget(self.title)
        hl.addSpacing(18)
        hl.addWidget(self.meta)
        hl.addSpacing(4)
        hl.addWidget(self.genres)
        hl.addSpacing(12)
        hl.addWidget(self.overview)
        hl.addSpacing(20)
        actions = QHBoxLayout()
        actions.setSpacing(10)
        self.play_btn = TactileButton("Play", icon="play", variant="primary", size="lg")
        self.play_btn.clicked.connect(self._play_main)
        self.watched_btn = TactileButton("Mark watched", icon="check", variant="glass", size="lg")
        self.watched_btn.clicked.connect(self._toggle_all_watched)
        self.folder_btn = TactileButton(icon="folder", variant="glass", size="lg")
        self.folder_btn.setToolTip("Open folder")
        self.folder_btn.clicked.connect(lambda: self.open_folder.emit(self.media["id"]))
        self.more_btn = TactileButton(icon="more", variant="glass", size="lg")
        self.more_btn.setToolTip("More")
        self.more_btn.clicked.connect(self._more_menu)
        for b in (self.play_btn, self.watched_btn, self.folder_btn, self.more_btn):
            actions.addWidget(b)
        actions.addStretch(1)
        hl.addLayout(actions)
        v.addWidget(self.hero)

        # ---------------- movie info
        self.info = QWidget()
        il = QHBoxLayout(self.info)
        il.setContentsMargins(40, 18, 40, 0)
        il.setSpacing(48)
        self.info_cols: list[tuple[Label, Label]] = []
        for _ in range(3):
            col = QVBoxLayout()
            col.setSpacing(4)
            a = Label("", 8.25, 700, T.TEXT_DIM)
            b = Label("", 9.75, 400, T.TEXT_MUTED, wrap=True)
            b.setMaximumWidth(420)
            b.setMinimumWidth(180)
            col.addWidget(a)
            col.addWidget(b)
            col.addStretch(1)
            il.addLayout(col)
            self.info_cols.append((a, b))
        il.addStretch(1)
        v.addWidget(self.info)

        # ---------------- episodes
        self.eps_box = QWidget()
        el = QVBoxLayout(self.eps_box)
        el.setContentsMargins(30, 10, 30, 0)
        el.setSpacing(12)
        eh = QHBoxLayout()
        eh.setContentsMargins(10, 0, 10, 0)
        self.eps_title = Label("Episodes", 15, 700, display=True)
        self.eps_stats = Label("", 9.5, 500, T.TEXT_MUTED)
        eh.addWidget(self.eps_title)
        eh.addSpacing(12)
        eh.addWidget(self.eps_stats, 0, Qt.AlignmentFlag.AlignBottom)
        eh.addStretch(1)
        self.missing_btn = TactileButton("Show missing", icon="eye", variant="chip", size="sm")
        self.missing_btn.setCheckable(True)
        self.missing_btn.setChecked(bool(settings.get("show_missing_episodes")))
        self.missing_btn.set_icon_name("eye" if self.missing_btn.isChecked() else "eye-off")
        self.missing_btn.toggled.connect(self._missing_toggled)
        self.season_watch_btn = TactileButton("Mark these watched", icon="check", variant="chip", size="sm")
        self.season_watch_btn.clicked.connect(self._mark_page)
        eh.addWidget(self.missing_btn)
        eh.addWidget(self.season_watch_btn)
        el.addLayout(eh)
        self.pages = ChipGroup([])
        pw = QHBoxLayout()
        pw.setContentsMargins(10, 0, 10, 4)
        pw.addWidget(self.pages)
        pw.addStretch(1)
        el.addLayout(pw)
        self.page_stats = Label("", 9.25, 500, T.TEXT_DIM)
        self.page_stats.setContentsMargins(12, 0, 10, 0)
        el.addWidget(self.page_stats)
        self.pages.changed.connect(self._page_changed)
        self.list_host = QWidget()
        self.list_lay = QVBoxLayout(self.list_host)
        self.list_lay.setContentsMargins(0, 0, 0, 0)
        self.list_lay.setSpacing(2)
        el.addWidget(self.list_host)
        v.addWidget(self.eps_box)
        v.addStretch(1)

    # ------------------------------------------------------------ population
    def show_media(self, media_id: int):
        self.page_key = None
        self.media = self.db.media(media_id)
        self.refresh()
        self.verticalScrollBar().setValue(0)

    def refresh(self):
        if not self.media:
            return
        m = self.media = self.db.media(self.media["id"])
        if m is None:
            self.back.emit()
            return
        self.hero.set_image(m.get("backdrop"), m.get("poster"))
        self.title.set(m.get("title") or "", m.get("logo"))
        kind_label = {"movie": "MOVIE", "show": "TV SERIES", "anime": "ANIME"}[m["kind"]]
        if m.get("meta_status") == "failed":
            kind_label += "  ·  NO METADATA MATCH — USE ⋯ › FIX MATCH"
        self.kicker.setText(kind_label)
        bits = []
        if m.get("year"):
            bits.append(str(m["year"]))
        if m.get("runtime"):
            bits.append(fmt_runtime(m["runtime"]) + (" / ep" if m["kind"] != "movie" else ""))
        if m.get("rating"):
            bits.append(f"★ {m['rating']:.1f}")
        if m.get("status") and m["kind"] != "movie":
            bits.append(m["status"])
        self.meta.setText("   ·   ".join(bits))
        self.genres.setText("  /  ".join(m.get("genres") or []))
        self.genres.setVisible(bool(m.get("genres")))
        ov = m.get("overview") or ""
        self.overview.setText(ov if len(ov) < 520 else ov[:520].rsplit(" ", 1)[0] + "…")
        self.overview.setToolTip(ov if len(ov) >= 520 else "")
        self.folder_btn.setEnabled(bool(m.get("folder")))
        if m["kind"] == "movie":
            self._refresh_movie(m)
        else:
            self._refresh_series(m)

    def _refresh_movie(self, m):
        self.eps_box.hide()
        self.info.show()
        pos = m.get("position") or 0
        if pos > 5 and not m["watched"]:
            self.play_btn.setText(f"Resume from {fmt_time(pos)}")
        else:
            self.play_btn.setText("Play again" if m["watched"] else "Play")
        self.play_btn.setEnabled(bool(self.db.movie_file(m["id"])))
        self._set_watched_btn(bool(m["watched"]))
        path = self.db.movie_file(m["id"]) or ""
        size = ""
        try:
            size = f"{os.path.getsize(path) / 1024 ** 3:.2f} GB"
        except OSError:
            pass
        fields = [("DIRECTOR", m.get("director") or "—"),
                  ("CAST", ", ".join(m.get("cast_list") or []) or "—"),
                  ("FILE", f"{os.path.basename(path)}\n{size}")]
        for (a, b), (k, val) in zip(self.info_cols, fields):
            a.setText(k)
            b.setText(val)
        self.play_btn.updateGeometry()

    def _refresh_series(self, m):
        self.info.hide()
        self.eps_box.show()
        eps = self.db.episodes(m["id"])
        self._eps = eps
        owned = [e for e in eps if e.get("file_path")]
        regular_owned = [e for e in owned if e["season"] != 0]
        ow = sum(1 for e in regular_owned if e["watched"])
        total = max(sum(1 for e in eps if e["season"] != 0), m.get("total_episodes") or 0)
        stats = self._progress_text(m, regular_owned)
        if total > len(regular_owned):
            stats += f"  ·  {len(regular_owned)} of {total} in library"
        self.eps_stats.setText(stats)
        self.missing_btn.setVisible(len(eps) > len(owned))
        nxt = self.db.resume_episode(m["id"])
        self._resume_ep = nxt
        if nxt:
            verb = "Resume" if (nxt.get("position") or 0) > 5 else "Play"
            lab = f"E{nxt['number']}" if m.get("numbering") == "absolute" else f"S{nxt['season']} E{nxt['number']}"
            self.play_btn.setText(f"{verb} {lab}")
            self.play_btn.setEnabled(True)
        elif owned:
            self._resume_ep = owned[0]
            self.play_btn.setText("Watch again")
            self.play_btn.setEnabled(True)
        else:
            self.play_btn.setText("Play")
            self.play_btn.setEnabled(False)
        self._set_watched_btn(bool(regular_owned) and ow == len(regular_owned))
        # pages: seasons, or ranges of 50 for long absolute-numbered anime; specials last
        visible = eps if self.missing_btn.isChecked() else owned
        regular = [e for e in visible if e["season"] != 0]
        pages = []
        if m.get("numbering") == "absolute" or len({e["season"] for e in regular}) <= 1:
            nums = [e["number"] for e in regular]
            hi = max(nums, default=0)
            if hi > PAGE:
                for start in range(1, hi + 1, PAGE):
                    end = min(start + PAGE - 1, hi)
                    if any(start <= n <= end for n in nums):
                        pages.append((f"r{start}-{end}", f"{start}–{end}"))
            elif regular:
                pages = [("all", "All episodes")]
        else:
            pages = [(f"s{n}", f"Season {n}") for n in sorted({e["season"] for e in regular})]
        if any(e["season"] == 0 for e in visible):
            pages.append(("s0", "Specials"))
        if self.page_key not in [k for k, _ in pages]:
            # default to the page containing the resume episode
            self.page_key = pages[0][0] if pages else None
            if nxt:
                for k, _ in pages:
                    if self._in_page(nxt, k):
                        self.page_key = k
                        break
        self.pages.set_options(pages, self.page_key)
        self.pages.setVisible(len(pages) > 1)
        self._fill_page()

    @staticmethod
    def _in_page(ep, key) -> bool:
        if key is None:
            return True
        if key.startswith("s"):
            return ep["season"] == int(key[1:])
        if ep["season"] == 0:
            return False
        if key == "all":
            return True
        lo, hi = key[1:].split("-")
        return int(lo) <= ep["number"] <= int(hi)

    @staticmethod
    def _progress_text(m: dict, owned: list[dict]) -> str:
        """'41 / 139 watched · 98 to go · 36h 40m left' for the given owned episodes."""
        done = sum(1 for e in owned if e["watched"])
        left = len(owned) - done
        if not owned:
            return "None in your library"
        if not left:
            return f"All {len(owned)} watched"
        secs = sum(max((e.get("duration") or (e.get("runtime") or m.get("runtime") or 0) * 60)
                       - (e.get("position") or 0), 0) for e in owned if not e["watched"])
        text = f"{done} / {len(owned)} watched  ·  {left} to go"
        return text + (f"  ·  {fmt_duration(secs)} left" if secs else "")

    def _page_eps(self):
        show_missing = self.missing_btn.isChecked()
        return [e for e in self._eps if self._in_page(e, self.page_key) and (show_missing or e.get("file_path"))]

    def _fill_page(self):
        while self.list_lay.count():
            w = self.list_lay.takeAt(0).widget()
            if w:
                w.deleteLater()
        label = dict(self.pages.options).get(self.page_key, "")
        page_owned = [e for e in self._eps if self._in_page(e, self.page_key) and e.get("file_path")]
        self.page_stats.setText(f"{label}  ·  {self._progress_text(self.media, page_owned)}"
                                if len(self.pages.options) > 1 else "")
        self.page_stats.setVisible(len(self.pages.options) > 1)
        for e in self._page_eps():
            row = EpisodeRow(self.media, e)
            row.play.connect(lambda eid: self.play.emit(self.media["id"], eid))
            row.toggle_watched.connect(self._toggle_ep)
            self.list_lay.addWidget(row)

    # ------------------------------------------------------------ actions
    def _set_watched_btn(self, watched: bool):
        self._all_watched = watched
        self.watched_btn.setText("Watched" if watched else "Mark watched")
        self.watched_btn.set_icon_name("check-filled" if watched else "check")
        self.watched_btn.icon_color_override = T.SUCCESS if watched else None
        self.watched_btn.updateGeometry()

    def _play_main(self):
        m = self.media
        if m["kind"] == "movie":
            self.play.emit(m["id"], None)
        elif self._resume_ep:
            self.play.emit(m["id"], self._resume_ep["id"])

    def _watch_state_changed(self):
        sb = self.verticalScrollBar().value()
        self.refresh()
        self.verticalScrollBar().setValue(sb)
        self.changed.emit()

    def _toggle_all_watched(self):
        self.db.set_watched(media_id=self.media["id"], watched=not self._all_watched, owned_only=True)
        self._watch_state_changed()

    def _toggle_ep(self, eid, watched):
        self.db.set_watched(episode_id=eid, watched=watched)
        self._watch_state_changed()

    def _mark_page(self):
        eps = [e for e in self._page_eps() if e.get("file_path")]
        target = not all(e["watched"] for e in eps)
        for e in eps:
            self.db.set_watched(episode_id=e["id"], watched=target)
        self._watch_state_changed()

    def _page_changed(self, key):
        self.page_key = key
        self._fill_page()

    def _missing_toggled(self, on):
        self.settings.set("show_missing_episodes", bool(on))
        self.missing_btn.set_icon_name("eye" if on else "eye-off")
        if self.media and self.media["kind"] != "movie":
            self._refresh_series(self.media)

    def _more_menu(self):
        menu = QMenu(self)
        menu.addAction("Fix match…", lambda: self.fix_match.emit(self.media["id"]))
        menu.addAction("Refresh metadata", lambda: self.refresh_meta.emit(self.media["id"]))
        sub = menu.addMenu("Change category")
        for k, label in (("movie", "Movies"), ("show", "TV Shows"), ("anime", "Anime")):
            a = sub.addAction(label, lambda k=k: self.change_category.emit(self.media["id"], k))
            a.setCheckable(True)
            a.setChecked(self.media["kind"] == k)
        menu.exec(self.more_btn.mapToGlobal(self.more_btn.rect().bottomLeft()))
