"""Full-bleed backdrop art with gradients that melt into the page background (cross-fades on change)."""
from __future__ import annotations

from PyQt6.QtCore import QRectF, QSize, Qt
from PyQt6.QtGui import QColor, QLinearGradient, QPainter, QRadialGradient
from PyQt6.QtWidgets import QWidget

from core import images

from . import theme as T
from .components import Anim


class Backdrop(QWidget):
    def __init__(self, parent=None, height: int = 460, art_left: float = 0.22):
        super().__init__(parent)
        self.url: str | None = None
        self.fallback: str | None = None
        self.prev: tuple[str | None, str | None] = (None, None)
        self.mix = 1.0
        self.art_left = art_left
        self._mix_anim = Anim(self, "mix", 700, curve=T.ease_in_out())
        self.setMinimumHeight(height)
        images.loader().ready.connect(self._on_ready)

    def set_image(self, url: str | None, fallback: str | None = None, animate: bool = False):
        if (url, fallback) == (self.url, self.fallback):
            return
        if animate and (self.url or self.fallback):
            self.prev = (self.url, self.fallback)
            self.mix = 0.0
            self._mix_anim.to(1.0)
        else:
            self.prev = (None, None)
            self.mix = 1.0
        self.url, self.fallback = url, fallback
        self.update()

    def _on_ready(self, url):
        if url in (self.url, self.fallback, *self.prev):
            self.update()

    def _art(self, urls, art: QRectF):
        dpr = self.devicePixelRatioF()
        for u in urls:
            if u:
                pm = images.loader().get_scaled(u, QSize(int(art.width() * dpr), int(art.height() * dpr)))
                if pm is not None:
                    pm.setDevicePixelRatio(dpr)
                    return pm
        return None

    def paintEvent(self, _e):  # noqa: N802
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
        r = QRectF(self.rect())
        p.fillRect(r, T.c(T.BG))
        # art occupies the right part so text on the left stays readable
        art = QRectF(r.width() * self.art_left, 0, r.width() * (1 - self.art_left), r.height())
        cur = self._art((self.url, self.fallback), art)
        if self.mix < 1.0:
            prev = self._art(self.prev, art)
            if prev is not None:
                p.setOpacity(0.92 * (1 - self.mix))
                p.drawPixmap(art.topLeft(), prev)
        if cur is not None:
            p.setOpacity(0.92 * self.mix)
            p.drawPixmap(art.topLeft(), cur)
        p.setOpacity(1.0)
        bg = T.c(T.BG)
        clear = QColor(bg)
        clear.setAlpha(0)
        g = QLinearGradient(art.left(), 0, art.left() + art.width() * 0.55, 0)
        g.setColorAt(0, bg)
        g.setColorAt(0.35, QColor(bg.red(), bg.green(), bg.blue(), 200))
        g.setColorAt(1, clear)
        p.fillRect(r, g)
        g2 = QLinearGradient(0, r.height() * 0.45, 0, r.height())
        g2.setColorAt(0, clear)
        g2.setColorAt(1, bg)
        p.fillRect(r, g2)
        g3 = QLinearGradient(0, 0, 0, 90)
        g3.setColorAt(0, QColor(bg.red(), bg.green(), bg.blue(), 150))
        g3.setColorAt(1, clear)
        p.fillRect(r, g3)
        if cur is None:
            rg = QRadialGradient(r.width() * 0.75, r.height() * 0.2, r.width() * 0.5)
            rg.setColorAt(0, T.c(T.ACCENT, 0.16))
            rg.setColorAt(1, QColor(0, 0, 0, 0))
            p.fillRect(r, rg)
        p.setPen(Qt.PenStyle.NoPen)
