"""Inline stroke icons (24px grid), rendered via QtSvg and tinted on demand."""
from __future__ import annotations

from functools import lru_cache

from PyQt6.QtCore import QByteArray, QRectF, Qt
from PyQt6.QtGui import QColor, QIcon, QLinearGradient, QPainter, QPainterPath, QPixmap
from PyQt6.QtSvg import QSvgRenderer

_F = 'fill="currentColor" stroke="none"'

PATHS = {
    "play": f'<path {_F} d="M7 4.2v15.6a1 1 0 0 0 1.52.85l12.5-7.8a1 1 0 0 0 0-1.7L8.52 3.35A1 1 0 0 0 7 4.2z"/>',
    "pause": f'<rect {_F} x="6" y="4" width="4.2" height="16" rx="1.2"/><rect {_F} x="13.8" y="4" width="4.2" height="16" rx="1.2"/>',
    "back": '<path d="m12 19-7-7 7-7"/><path d="M19 12H5"/>',
    "search": '<circle cx="11" cy="11" r="7.5"/><path d="m20.5 20.5-4.2-4.2"/>',
    "check": '<path d="M20 6 9 17l-5-5"/>',
    "check-circle": '<circle cx="12" cy="12" r="9.5"/><path d="m8.5 12 2.5 2.5 4.5-5"/>',
    "check-filled": f'<circle {_F} cx="12" cy="12" r="11"/><path stroke="#0b0c10" stroke-width="2.6" d="m7.5 12.2 3 3 6-6.4"/>',
    "circle": '<circle cx="12" cy="12" r="9.5"/>',
    "x": '<path d="M18 6 6 18"/><path d="m6 6 12 12"/>',
    "folder": '<path d="M20 20a2 2 0 0 0 2-2V8a2 2 0 0 0-2-2h-7.9a2 2 0 0 1-1.69-.9L9.6 3.9A2 2 0 0 0 7.93 3H4a2 2 0 0 0-2 2v13a2 2 0 0 0 2 2Z"/>',
    "folder-plus": '<path d="M20 20a2 2 0 0 0 2-2V8a2 2 0 0 0-2-2h-7.9a2 2 0 0 1-1.69-.9L9.6 3.9A2 2 0 0 0 7.93 3H4a2 2 0 0 0-2 2v13a2 2 0 0 0 2 2Z"/><path d="M12 10v6M9 13h6"/>',
    "settings": '<path d="M4 21v-7M4 10V3M12 21v-9M12 8V3M20 21v-5M20 12V3M1 14h6M9 8h6M17 16h6"/>',
    "home": '<path d="M3 10.5 12 3l9 7.5V20a1 1 0 0 1-1 1h-5v-6h-6v6H4a1 1 0 0 1-1-1z"/>',
    "film": '<rect x="3" y="3" width="18" height="18" rx="2.5"/><path d="M7.5 3v18M16.5 3v18M3 7.5h4.5M3 12h18M3 16.5h4.5M16.5 7.5H21M16.5 16.5H21"/>',
    "tv": '<rect x="2" y="7" width="20" height="14" rx="2.5"/><path d="m17 2-5 5-5-5"/>',
    "sparkles": '<path d="M11 3.5l1.8 4.9 4.9 1.8-4.9 1.8L11 16.9l-1.8-4.9-4.9-1.8 4.9-1.8z"/><path d="M18.5 14.5l.9 2.3 2.3.9-2.3.9-.9 2.3-.9-2.3-2.3-.9 2.3-.9z"/>',
    "grid": '<rect x="3" y="3" width="7" height="7" rx="1.6"/><rect x="14" y="3" width="7" height="7" rx="1.6"/><rect x="3" y="14" width="7" height="7" rx="1.6"/><rect x="14" y="14" width="7" height="7" rx="1.6"/>',
    "refresh": '<path d="M21 12a9 9 0 1 1-2.64-6.36L21 8"/><path d="M21 3v5h-5"/>',
    "next": f'<path {_F} d="M5 5.2v13.6a1 1 0 0 0 1.5.86l10-6.8a1 1 0 0 0 0-1.72l-10-6.8A1 1 0 0 0 5 5.2z"/><path d="M19.5 5v14"/>',
    "prev": f'<path {_F} d="M19 5.2v13.6a1 1 0 0 1-1.5.86l-10-6.8a1 1 0 0 1 0-1.72l10-6.8A1 1 0 0 1 19 5.2z"/><path d="M4.5 5v14"/>',
    "back10": '<path d="M3.5 12a8.5 8.5 0 1 0 2.6-6.1L3.5 8.5"/><path d="M3.5 3.5v5h5"/>'
              '<text x="12.4" y="15.6" font-size="7.6" font-weight="700" text-anchor="middle" '
              'font-family="Segoe UI" fill="currentColor" stroke="none">10</text>',
    "fwd10": '<path d="M20.5 12a8.5 8.5 0 1 1-2.6-6.1l2.6 2.6"/><path d="M20.5 3.5v5h-5"/>'
             '<text x="11.6" y="15.6" font-size="7.6" font-weight="700" text-anchor="middle" '
             'font-family="Segoe UI" fill="currentColor" stroke="none">10</text>',
    "volume-2": '<path d="M11 5 6 9H2v6h4l5 4z"/><path d="M15.5 8.5a5 5 0 0 1 0 7"/><path d="M19 5a10 10 0 0 1 0 14"/>',
    "volume-1": '<path d="M11 5 6 9H2v6h4l5 4z"/><path d="M15.5 8.5a5 5 0 0 1 0 7"/>',
    "volume-x": '<path d="M11 5 6 9H2v6h4l5 4z"/><path d="m22 9-6 6"/><path d="m16 9 6 6"/>',
    "captions": '<rect x="2" y="5" width="20" height="14" rx="3"/><path d="M7 15h4M14 15h3M7 11h2M12 11h5"/>',
    "audio": '<path d="M2 10v3M6 6v11M10 3v18M14 8v7M18 5v13M22 10v3"/>',
    "maximize": '<path d="M8 3H5a2 2 0 0 0-2 2v3M21 8V5a2 2 0 0 0-2-2h-3M3 16v3a2 2 0 0 0 2 2h3M16 21h3a2 2 0 0 0 2-2v-3"/>',
    "minimize": '<path d="M8 3v3a2 2 0 0 1-2 2H3M21 8h-3a2 2 0 0 1-2-2V3M3 16h3a2 2 0 0 1 2 2v3M16 21v-3a2 2 0 0 1 2-2h3"/>',
    "gauge": '<path d="m12 14 4-4"/><path d="M3.34 19a10 10 0 1 1 17.32 0"/>',
    "more": f'<circle {_F} cx="5" cy="12" r="1.6"/><circle {_F} cx="12" cy="12" r="1.6"/><circle {_F} cx="19" cy="12" r="1.6"/>',
    "star": f'<path {_F} d="M12 2.5l2.9 6.1 6.6.8-4.9 4.6 1.3 6.6L12 17.3l-5.9 3.3 1.3-6.6-4.9-4.6 6.6-.8z"/>',
    "clock": '<circle cx="12" cy="12" r="9.5"/><path d="M12 7v5l3.5 2"/>',
    "pencil": '<path d="M17 3a2.85 2.83 0 1 1 4 4L7.5 20.5 2 22l1.5-5.5Z"/>',
    "eye": '<path d="M2 12s3.5-7 10-7 10 7 10 7-3.5 7-10 7S2 12 2 12z"/><circle cx="12" cy="12" r="3"/>',
    "eye-off": '<path d="M2 12s3.5-7 10-7 10 7 10 7-3.5 7-10 7S2 12 2 12z"/><circle cx="12" cy="12" r="3"/><path d="M3 3l18 18"/>',
    "plus": '<path d="M12 5v14M5 12h14"/>',
    "trash": '<path d="M3 6h18M8 6V4h8v2M19 6l-1 14H6L5 6"/>',
    "chevron-down": '<path d="m6 9 6 6 6-6"/>',
    "chevron-right": '<path d="m9 18 6-6-6-6"/>',
    "chevron-left": '<path d="m15 18-6-6 6-6"/>',
    "list": '<path d="M8 6h13M8 12h13M8 18h13"/><path d="M3.5 6h.01M3.5 12h.01M3.5 18h.01"/>',
    "info": '<circle cx="12" cy="12" r="9.5"/><path d="M12 16v-4.5M12 8h.01"/>',
    "library": '<path d="M4 4v16M9 4v16"/><path d="m14 4.5 4.5 15.5"/>',
}


def _svg(name: str, color: str, stroke: float) -> bytes:
    body = PATHS[name]
    return (f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" color="{color}" '
            f'stroke="{color}" stroke-width="{stroke}" stroke-linecap="round" stroke-linejoin="round">'
            f'{body.replace("currentColor", color)}</svg>').encode()


@lru_cache(maxsize=512)
def pixmap(name: str, color: str = "#f1f3f7", size: int = 20, dpr: float = 2.0, stroke: float = 2.0) -> QPixmap:
    r = QSvgRenderer(QByteArray(_svg(name, color, stroke)))
    px = int(size * dpr)
    pm = QPixmap(px, px)
    pm.fill(Qt.GlobalColor.transparent)
    p = QPainter(pm)
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    r.render(p, QRectF(0, 0, px, px))
    p.end()
    pm.setDevicePixelRatio(dpr)
    return pm


def icon(name: str, color: str = "#f1f3f7", size: int = 20) -> QIcon:
    return QIcon(pixmap(name, color, size))


def draw(p: QPainter, name: str, rect: QRectF, color: QColor | str, stroke: float = 2.0) -> None:
    col = color.name(QColor.NameFormat.HexArgb) if isinstance(color, QColor) else color
    if isinstance(color, QColor):
        col = color.name()  # svg wants #rrggbb; alpha via painter opacity
        old = p.opacity()
        p.setOpacity(old * color.alphaF())
    dpr = p.device().devicePixelRatioF() if p.device() else 2.0
    pm = pixmap(name, col, int(round(rect.width())), max(2.0, dpr), stroke)
    p.drawPixmap(rect.toRect() if hasattr(rect, "toRect") else rect, pm)
    if isinstance(color, QColor):
        p.setOpacity(old)


def app_icon_pixmap(size: int) -> QPixmap:
    """Luminary's app icon: a gradient rounded square with a play glyph."""
    pm = QPixmap(size, size)
    pm.fill(Qt.GlobalColor.transparent)
    p = QPainter(pm)
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    inset = size * 0.04
    r = QRectF(inset, inset, size - 2 * inset, size - 2 * inset)
    g = QLinearGradient(r.topLeft(), r.bottomRight())
    g.setColorAt(0, QColor("#60a5fa"))
    g.setColorAt(1, QColor("#6366f1"))
    path = QPainterPath()
    path.addRoundedRect(r, size * 0.24, size * 0.24)
    p.fillPath(path, g)
    draw(p, "play", QRectF(size * 0.29, size * 0.25, size * 0.5, size * 0.5), QColor("#ffffff"))
    p.end()
    return pm


def app_icon() -> QIcon:
    ic = QIcon()
    for s in (16, 24, 32, 48, 64, 128, 256):
        ic.addPixmap(app_icon_pixmap(s))
    return ic
