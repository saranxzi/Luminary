"""Poster / landscape cards: model, painter delegate, grid and row views."""
from __future__ import annotations

from PyQt6.QtCore import (QAbstractListModel, QModelIndex, QPointF, QRectF, QSize, Qt, QTimer,
                          pyqtSignal)
from PyQt6.QtGui import QColor, QFontMetricsF, QLinearGradient, QPainter, QPainterPath, QPen
from PyQt6.QtWidgets import QAbstractItemView, QListView, QStyledItemDelegate

from core import images

from . import icons
from . import theme as T
from .components import SmoothScroller, fmt_duration, fmt_runtime, install_row_wheel

ROLE = Qt.ItemDataRole.UserRole + 1
GAP = 22
TEXT_H = 50


class CardModel(QAbstractListModel):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.items: list[dict] = []

    def rowCount(self, parent=QModelIndex()):  # noqa: N802
        return 0 if parent.isValid() else len(self.items)

    def data(self, index, role=Qt.ItemDataRole.DisplayRole):
        if not index.isValid():
            return None
        it = self.items[index.row()]
        if role == ROLE:
            return it
        if role == Qt.ItemDataRole.DisplayRole:
            return it.get("title") or (it.get("media") or {}).get("title")
        if role == Qt.ItemDataRole.ToolTipRole:
            return None
        return None

    def set_items(self, items: list[dict]):
        self.beginResetModel()
        self.items = items
        self.endResetModel()


def _placeholder(p: QPainter, r: QRectF, title: str, radius: float):
    g = QLinearGradient(r.topLeft(), r.bottomRight())
    h = (sum(map(ord, title or "?")) * 37) % 360
    g.setColorAt(0, QColor.fromHsl(h, 60, 46))
    g.setColorAt(1, QColor.fromHsl((h + 40) % 360, 70, 22))
    path = QPainterPath()
    path.addRoundedRect(r, radius, radius)
    p.fillPath(path, g)
    p.setPen(QColor(255, 255, 255, 220))
    p.setFont(T.font(max(10.0, r.width() / 11), 700, display=True))
    p.drawText(r.adjusted(12, 12, -12, -12), Qt.AlignmentFlag.AlignCenter | Qt.TextFlag.TextWordWrap, title or "")


def draw_image(p: QPainter, url: str | None, r: QRectF, radius: float, fallback_title: str = "") -> bool:
    dpr = p.device().devicePixelRatioF() if p.device() else 1.0
    size = QSize(int(r.width() * dpr), int(r.height() * dpr))
    pm = images.loader().get_scaled(url, size) if url else None
    path = QPainterPath()
    path.addRoundedRect(r, radius, radius)
    if pm is None:
        if url:
            p.fillPath(path, T.c(T.ELEVATED))
        else:
            _placeholder(p, r, fallback_title, radius)
        return False
    pm.setDevicePixelRatio(dpr)
    p.save()
    p.setClipPath(path)
    p.drawPixmap(r.topLeft(), pm)
    p.restore()
    return True


def draw_progress(p: QPainter, r: QRectF, frac: float, color=T.ACCENT):
    track = QPainterPath()
    track.addRoundedRect(r, r.height() / 2, r.height() / 2)
    p.fillPath(track, QColor(255, 255, 255, 50))
    if frac > 0:
        f = QRectF(r)
        f.setWidth(max(r.height(), r.width() * min(1.0, frac)))
        fill = QPainterPath()
        fill.addRoundedRect(f, r.height() / 2, r.height() / 2)
        p.fillPath(fill, T.c(color))


def draw_pill(p: QPainter, x: float, y: float, text: str, bg: QColor, fg: QColor, icon: str | None = None,
              right_align: bool = False) -> QRectF:
    p.setFont(T.font(8.25, 700))
    fm = QFontMetricsF(p.font())
    w = fm.horizontalAdvance(text) + 14 + (16 if icon else 0)
    r = QRectF(x - w if right_align else x, y, w, 21)
    path = QPainterPath()
    path.addRoundedRect(r, 10.5, 10.5)
    p.fillPath(path, bg)
    tx = r.left() + 7
    if icon:
        icons.draw(p, icon, QRectF(tx - 1, r.center().y() - 6.5, 13, 13), fg)
        tx += 16
    p.setPen(fg)
    p.drawText(QRectF(tx, r.top(), w, r.height()), Qt.AlignmentFlag.AlignVCenter, text)
    return r


def card_subtitle(it: dict) -> list[str]:
    """'2009 · 1h 35m', '2001 · 52m left', '2004 · 98 left · 36h 40m', 'All 24 watched'."""
    bits = [str(it["year"])] if it.get("year") else []
    if it["kind"] == "movie":
        if it["state"] == "in_progress" and it.get("left_s"):
            bits.append(f"{fmt_duration(it['left_s'])} left")
        elif it.get("runtime"):
            bits.append(fmt_runtime(it["runtime"]))
        return bits
    owned, done = it.get("owned") or 0, it.get("owned_watched") or 0
    if it["state"] == "watched":
        return bits + [f"All {owned} watched"]
    if it["state"] == "unwatched":
        bits.append(f"{owned} episode{'s' if owned != 1 else ''}")
    else:
        bits.append(f"{owned - done} left")
    if it.get("left_s"):
        bits.append(fmt_duration(it["left_s"]))
    return bits


class CardDelegate(QStyledItemDelegate):
    """mode: 'poster' (2:3) or 'landscape' (16:9 continue-watching style)."""

    def __init__(self, view, mode="poster"):
        super().__init__(view)
        self.view = view
        self.mode = mode

    def sizeHint(self, option, index):  # noqa: N802
        return self.view.gridSize()

    def paint(self, p: QPainter, option, index):
        it = index.data(ROLE)
        if it is None:
            return
        p.save()
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
        hov = self.view.hover_value(index.row())
        cell = QRectF(option.rect)
        card_w = cell.width() - GAP
        x = cell.left() + GAP / 2
        if self.mode == "poster":
            img_h = card_w * 1.5
        else:
            img_h = card_w * 9 / 16
        lift = 4 * hov
        img = QRectF(x, cell.top() + 6 - lift, card_w, img_h)
        radius = 10.0

        # soft shadow grows on hover
        if hov > 0.01:
            for i, a in enumerate((26, 16, 9)):
                sr = img.adjusted(-i - 1, 2 + i * 2, i + 1, 4 + i * 3)
                sp = QPainterPath()
                sp.addRoundedRect(sr, radius + i, radius + i)
                p.fillPath(sp, QColor(0, 0, 0, int(a * 2.2 * hov)))

        if self.mode == "poster":
            self._paint_poster(p, it, img, radius, hov)
            text_top = img.bottom() + 10 + lift
            self._paint_poster_text(p, it, QRectF(x, text_top, card_w, TEXT_H - 8))
        else:
            self._paint_landscape(p, it, img, radius, hov)
            text_top = img.bottom() + 10 + lift
            self._paint_landscape_text(p, it, QRectF(x, text_top, card_w, TEXT_H))

        # hover border + focus ring
        border_a = 0.10 + 0.22 * hov
        p.setPen(QPen(QColor(255, 255, 255, int(255 * border_a)), 1))
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.drawRoundedRect(img.adjusted(0.5, 0.5, -0.5, -0.5), radius, radius)
        if self.view.hasFocus() and self.view.currentIndex() == index and self.view.keyboard_nav:
            p.setPen(QPen(T.c(T.ACCENT_HI), 2))
            p.drawRoundedRect(img.adjusted(-3, -3, 3, 3), radius + 3, radius + 3)
        p.restore()

    # -------------------------------------------------------------- poster
    def _paint_poster(self, p, it, r, radius, hov):
        draw_image(p, it.get("poster"), r, radius, it.get("title", ""))
        # bottom gradient for badges legibility
        state = it.get("state")
        if hov > 0.01:
            p.save()
            path = QPainterPath()
            path.addRoundedRect(r, radius, radius)
            p.setClipPath(path)
            p.fillRect(r, QColor(0, 0, 0, int(90 * hov)))
            p.restore()
            c = r.center()
            d = 52
            p.setOpacity(hov)
            p.setBrush(QColor(255, 255, 255, 235))
            p.setPen(Qt.PenStyle.NoPen)
            s = 0.85 + 0.15 * hov
            p.drawEllipse(QPointF(c.x(), c.y()), d / 2 * s, d / 2 * s)
            icons.draw(p, "play", QRectF(c.x() - 11 + 2, c.y() - 11, 22, 22), QColor("#0b0c10"))
            p.setOpacity(1.0)
        if state == "watched":
            r2 = QRectF(r.right() - 30, r.top() + 8, 22, 22)
            p.setBrush(QColor(11, 12, 16, 160))
            p.setPen(Qt.PenStyle.NoPen)
            p.drawEllipse(r2.adjusted(-1, -1, 1, 1))
            icons.draw(p, "check-filled", r2, T.c(T.SUCCESS))
        if it.get("kind") in ("show", "anime"):
            owned = it.get("owned") or 0
            ow = it.get("owned_watched") or 0
            if owned and state != "watched":
                left = owned - ow
                draw_pill(p, r.right() - 8, r.top() + 8, f"{left}", QColor(11, 12, 16, 200),
                          T.c(T.TEXT), right_align=True)
        frac = it.get("progress") or 0.0
        if state == "in_progress" and frac > 0:
            draw_progress(p, QRectF(r.left() + 10, r.bottom() - 13, r.width() - 20, 4), frac)

    def _paint_poster_text(self, p, it, r):
        p.setFont(T.font(9.75, 600))
        fm = QFontMetricsF(p.font())
        p.setPen(T.c(T.TEXT))
        title = fm.elidedText(it.get("title") or "", Qt.TextElideMode.ElideRight, r.width())
        p.drawText(QRectF(r.left(), r.top(), r.width(), 20), Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter, title)
        p.setFont(T.font(8.75, 400))
        p.setPen(T.c(T.TEXT_MUTED))
        sub = "  ·  ".join(card_subtitle(it))
        p.drawText(QRectF(r.left(), r.top() + 20, r.width(), 18), Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
                   QFontMetricsF(p.font()).elidedText(sub, Qt.TextElideMode.ElideRight, r.width()))

    # -------------------------------------------------------------- landscape
    def _paint_landscape(self, p, it, r, radius, hov):
        m = it.get("media") or it
        ep = it.get("episode")
        url = (ep or {}).get("still") or m.get("backdrop") or m.get("poster")
        draw_image(p, url, r, radius, m.get("title", ""))
        p.save()
        path = QPainterPath()
        path.addRoundedRect(r, radius, radius)
        p.setClipPath(path)
        g = QLinearGradient(r.left(), r.top() + r.height() * 0.35, r.left(), r.bottom())
        g.setColorAt(0, QColor(0, 0, 0, 0))
        g.setColorAt(1, QColor(0, 0, 0, 200))
        p.fillRect(r, g)
        if hov > 0.01:
            p.fillRect(r, QColor(0, 0, 0, int(60 * hov)))
        p.restore()
        c = r.center()
        d = 46 * (0.9 + 0.1 * hov)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QColor(255, 255, 255, int(40 + 195 * hov)))
        p.drawEllipse(QPointF(c.x(), c.y() - 6), d / 2, d / 2)
        icons.draw(p, "play", QRectF(c.x() - 10 + 2, c.y() - 16, 20, 20),
                   QColor("#0b0c10") if hov > 0.5 else QColor("#ffffff"))
        if ep:
            label = f"E{ep['number']}" if m.get("numbering") == "absolute" else f"S{ep['season']} · E{ep['number']}"
            draw_pill(p, r.left() + 10, r.bottom() - 32, label, QColor(11, 12, 16, 190), T.c(T.TEXT))
        frac = it.get("progress") or 0.0
        if frac > 0:
            draw_progress(p, QRectF(r.left() + 10, r.bottom() - 8, r.width() - 20, 3.5), frac)
        elif ep:
            draw_pill(p, r.right() - 10, r.bottom() - 32, "UP NEXT", T.c(T.ACCENT, 0.9), QColor("#ffffff"),
                      right_align=True)

    def _paint_landscape_text(self, p, it, r):
        m = it.get("media") or it
        ep = it.get("episode")
        p.setFont(T.font(9.75, 600))
        fm = QFontMetricsF(p.font())
        p.setPen(T.c(T.TEXT))
        p.drawText(QRectF(r.left(), r.top(), r.width(), 20), Qt.AlignmentFlag.AlignVCenter,
                   fm.elidedText(m.get("title") or "", Qt.TextElideMode.ElideRight, r.width()))
        p.setFont(T.font(8.75))
        p.setPen(T.c(T.TEXT_MUTED))
        fm2 = QFontMetricsF(p.font())
        if ep:
            sub = ep.get("title") or f"Episode {ep['number']}"
        else:
            rem = 0
            if m.get("duration"):
                rem = max(0, (m["duration"] - (m.get("position") or 0)) / 60)
            sub = f"{int(rem)} min left" if rem else (str(m.get("year") or ""))
        p.drawText(QRectF(r.left(), r.top() + 20, r.width(), 18), Qt.AlignmentFlag.AlignVCenter,
                   fm2.elidedText(sub, Qt.TextElideMode.ElideRight, r.width()))


class _HoverMixin:
    """Per-row hover values eased toward their targets (exponential ease-out)."""

    def _init_hover(self):
        self._hover: dict[int, float] = {}
        self._hover_row = -1
        self._ht = QTimer(self)
        self._ht.setInterval(14)
        self._ht.timeout.connect(self._tick)
        self.keyboard_nav = False
        self.setMouseTracking(True)
        images.loader().ready.connect(lambda _u: self.viewport().update())

    def hover_value(self, row: int) -> float:
        return self._hover.get(row, 0.0)

    def _set_hover_row(self, row: int):
        if row != self._hover_row:
            self._hover_row = row
            if row >= 0:
                self._hover.setdefault(row, 0.0)
            self._ht.start()

    def _tick(self):
        done = True
        for row in list(self._hover):
            target = 1.0 if row == self._hover_row else 0.0
            v = self._hover[row]
            nv = v + (target - v) * 0.28
            if abs(nv - target) < 0.01:
                nv = target
            else:
                done = False
            if nv == 0.0 and target == 0.0:
                del self._hover[row]
            else:
                self._hover[row] = nv
        self.viewport().update()
        if done:
            self._ht.stop()

    def mouseMoveEvent(self, e):  # noqa: N802
        self.keyboard_nav = False
        idx = self.indexAt(e.position().toPoint())
        self._set_hover_row(idx.row() if idx.isValid() else -1)
        self.viewport().setCursor(Qt.CursorShape.PointingHandCursor if idx.isValid() else Qt.CursorShape.ArrowCursor)
        super().mouseMoveEvent(e)

    def leaveEvent(self, e):  # noqa: N802
        self._set_hover_row(-1)
        super().leaveEvent(e)

    def keyPressEvent(self, e):  # noqa: N802
        self.keyboard_nav = True
        if e.key() in (Qt.Key.Key_Return, Qt.Key.Key_Enter) and self.currentIndex().isValid():
            self.activated_item.emit(self.currentIndex().data(ROLE))
            return
        super().keyPressEvent(e)
        self.viewport().update()

    def _emit_clicked(self, index):
        if index.isValid():
            self.activated_item.emit(index.data(ROLE))

    def contextMenuEvent(self, e):  # noqa: N802
        idx = self.indexAt(e.pos())
        if idx.isValid():
            self.context_item.emit(idx.data(ROLE), e.globalPos())


class GridView(_HoverMixin, QListView):
    activated_item = pyqtSignal(dict)
    context_item = pyqtSignal(dict, object)

    def __init__(self, parent=None, min_card: int = 172):
        super().__init__(parent)
        self.min_card = min_card
        self.model_ = CardModel(self)
        self.setModel(self.model_)
        self.setItemDelegate(CardDelegate(self, "poster"))
        self.setViewMode(QListView.ViewMode.IconMode)
        self.setMovement(QListView.Movement.Static)
        self.setResizeMode(QListView.ResizeMode.Adjust)
        self.setUniformItemSizes(True)
        self.setWrapping(True)
        self.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.setVerticalScrollMode(QAbstractItemView.ScrollMode.ScrollPerPixel)
        self.verticalScrollBar().setSingleStep(34)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.setFrameShape(QListView.Shape.NoFrame)
        self.setStyleSheet("QListView { background: transparent; border: none; }")
        self.setViewportMargins(18, 0, 18, 0)
        self._init_hover()
        self.clicked.connect(self._emit_clicked)
        SmoothScroller(self)

    def set_items(self, items):
        self._hover.clear()
        self.model_.set_items(items)

    def resizeEvent(self, e):  # noqa: N802
        self._relayout()
        super().resizeEvent(e)

    def _relayout(self):
        avail = self.viewport().width() - 2
        if avail <= 0:
            return
        cols = max(2, int(avail // (self.min_card + GAP)))
        cell_w = avail // cols
        card_w = cell_w - GAP
        cell_h = int(card_w * 1.5 + TEXT_H + 22)
        self.setGridSize(QSize(int(cell_w), cell_h))


class RowView(_HoverMixin, QListView):
    """Single horizontal row of cards."""

    activated_item = pyqtSignal(dict)
    context_item = pyqtSignal(dict, object)

    def __init__(self, mode="landscape", card_w=300, parent=None):
        super().__init__(parent)
        self.mode = mode
        self.model_ = CardModel(self)
        self.setModel(self.model_)
        self.setItemDelegate(CardDelegate(self, mode))
        self.setFlow(QListView.Flow.LeftToRight)
        self.setWrapping(False)
        self.setUniformItemSizes(True)
        self.setMovement(QListView.Movement.Static)
        self.setHorizontalScrollMode(QAbstractItemView.ScrollMode.ScrollPerPixel)
        self.horizontalScrollBar().setSingleStep(40)
        self.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        self.setFrameShape(QListView.Shape.NoFrame)
        self.setStyleSheet("QListView { background: transparent; border: none; }")
        self.setViewportMargins(18, 0, 18, 0)
        self._init_hover()
        self.clicked.connect(self._emit_clicked)
        self.set_card_width(card_w)
        install_row_wheel(self)

    def set_card_width(self, card_w: int):
        img_h = card_w * (1.5 if self.mode == "poster" else 9 / 16)
        cell = QSize(card_w + GAP, int(img_h + TEXT_H + 26))
        self.setGridSize(cell)
        self.setFixedHeight(cell.height() + 12)

    def set_items(self, items):
        self._hover.clear()
        self.model_.set_items(items)
