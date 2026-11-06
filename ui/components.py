"""Reusable, tactile UI primitives."""
from __future__ import annotations

from PyQt6.QtCore import (QEvent, QRectF, QSize, Qt, QTimer, QVariantAnimation,
                          pyqtSignal)
from PyQt6.QtGui import QColor, QFontMetricsF, QPainter, QPainterPath, QPen
from PyQt6.QtWidgets import (QAbstractButton, QGraphicsOpacityEffect, QHBoxLayout, QLabel,
                             QLineEdit, QSizePolicy, QWidget)

from . import icons
from . import theme as T


def _mix(a: QColor, b: QColor, t: float) -> QColor:
    return QColor.fromRgbF(
        a.redF() + (b.redF() - a.redF()) * t,
        a.greenF() + (b.greenF() - a.greenF()) * t,
        a.blueF() + (b.blueF() - a.blueF()) * t,
        a.alphaF() + (b.alphaF() - a.alphaF()) * t,
    )


class Anim:
    """Small helper: animate a float attribute on a widget and repaint."""

    def __init__(self, widget: QWidget, attr: str, duration: int = T.DUR_FAST, curve=None, on_change=None):
        self.w, self.attr = widget, attr
        self.a = QVariantAnimation(widget)
        self.a.setDuration(duration)
        self.a.setEasingCurve(curve or T.ease_out())
        self.a.valueChanged.connect(self._set)
        self.on_change = on_change

    def _set(self, v):
        setattr(self.w, self.attr, float(v))
        if self.on_change:
            self.on_change(float(v))
        self.w.update()

    def to(self, target: float, duration: int | None = None):
        self.a.stop()
        if duration is not None:
            self.a.setDuration(duration)
        self.a.setStartValue(float(getattr(self.w, self.attr)))
        self.a.setEndValue(float(target))
        self.a.start()


VARIANTS = {
    #            bg,                       bg_hover,                 fg,          border
    "primary": ("#f1f3f7", "#ffffff", "#0b0c10", None),
    "accent": (T.ACCENT, T.ACCENT_HI, "#ffffff", None),
    "secondary": ("rgba(255,255,255,0.07)", "rgba(255,255,255,0.12)", T.TEXT, T.BORDER),
    "ghost": ("rgba(255,255,255,0.0)", "rgba(255,255,255,0.07)", T.TEXT_MUTED, None),
    "glass": ("rgba(20,22,30,0.55)", "rgba(40,44,56,0.75)", T.TEXT, "rgba(255,255,255,0.10)"),
    "chip": ("rgba(255,255,255,0.04)", "rgba(255,255,255,0.08)", T.TEXT_MUTED, T.BORDER),
    "nav": ("rgba(255,255,255,0.0)", "rgba(255,255,255,0.05)", T.TEXT_MUTED, None),
    "hud": ("rgba(255,255,255,0.0)", "rgba(255,255,255,0.12)", "#ffffff", None),
}

SIZES = {"sm": (30, 10, 9.0, 15), "md": (38, 14, 9.75, 17), "lg": (46, 20, 10.5, 19),
         "hud": (52, 16, 11.5, 25), "xl": (64, 22, 12.5, 32)}


class TactileButton(QAbstractButton):
    """Button with hover brightening and a 0.97 press scale (Emil-style)."""

    def __init__(self, text: str = "", icon: str | None = None, variant: str = "secondary",
                 size: str = "md", parent=None, icon_only: bool = False, radius: float | None = None):
        super().__init__(parent)
        self.setText(text)
        self._icon = icon
        self.variant = variant
        self.size_key = size
        self.icon_only = icon_only or (not text and icon is not None)
        self.radius = radius
        self.hov = 0.0
        self.prs = 0.0
        self.chk = 0.0
        self._hov_anim = Anim(self, "hov", T.DUR_FAST)
        self._prs_anim = Anim(self, "prs", 90)
        self._chk_anim = Anim(self, "chk", T.DUR_BASE)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setFocusPolicy(Qt.FocusPolicy.TabFocus)
        self.toggled.connect(lambda on: self._chk_anim.to(1.0 if on else 0.0))
        self.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
        self.icon_color_override: str | None = None
        self.align_left = False
        self._kbd_focus = False

    def focusInEvent(self, e):  # noqa: N802
        self._kbd_focus = e.reason() in (Qt.FocusReason.TabFocusReason, Qt.FocusReason.BacktabFocusReason)
        super().focusInEvent(e)

    def focusOutEvent(self, e):  # noqa: N802
        self._kbd_focus = False
        super().focusOutEvent(e)

    def set_icon_name(self, name: str | None):
        if name == self._icon:
            return
        self._icon = name
        self.updateGeometry()
        self.update()

    def setText(self, text):  # noqa: N802
        super().setText(text)
        self.updateGeometry()

    def sizeHint(self):  # noqa: N802
        h, pad, fs, isz = SIZES[self.size_key]
        if self.icon_only:
            return QSize(h, h)
        fm = QFontMetricsF(T.font(fs, 600))
        w = fm.horizontalAdvance(self.text()) + pad * 2
        if self._icon:
            w += isz + 8
        return QSize(int(w + 0.5), h)

    def enterEvent(self, e):  # noqa: N802
        self._hov_anim.to(1.0)
        super().enterEvent(e)

    def leaveEvent(self, e):  # noqa: N802
        self._hov_anim.to(0.0)
        self._prs_anim.to(0.0)
        super().leaveEvent(e)

    def mousePressEvent(self, e):  # noqa: N802
        self._prs_anim.to(1.0, 90)
        super().mousePressEvent(e)

    def mouseReleaseEvent(self, e):  # noqa: N802
        self._prs_anim.to(0.0, T.DUR_BASE)
        super().mouseReleaseEvent(e)

    def paintEvent(self, _e):  # noqa: N802
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        h, pad, fs, isz = SIZES[self.size_key]
        r = QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5)
        s = 1.0 - 0.03 * self.prs
        p.translate(r.center())
        p.scale(s, s)
        p.translate(-r.center())
        bg, bgh, fg, border = VARIANTS[self.variant]
        bgc = _mix(T.c(bg), T.c(bgh), self.hov)
        fgc = T.c(fg)
        if self.variant in ("ghost", "nav", "chip"):
            fgc = _mix(T.c(fg), T.c(T.TEXT), self.hov)
        if self.isCheckable() and self.chk > 0:
            if self.variant == "chip":
                bgc = _mix(bgc, T.c("#f1f3f7"), self.chk)
                fgc = _mix(fgc, T.c("#0b0c10"), self.chk)
            elif self.variant == "nav":
                bgc = _mix(bgc, T.c("rgba(255,255,255,0.08)"), self.chk)
                fgc = _mix(fgc, T.c(T.TEXT), self.chk)
        if not self.isEnabled():
            p.setOpacity(0.4)
        rad = self.radius if self.radius is not None else (r.height() / 2 if self.variant in ("chip", "hud") or self.icon_only else 10)
        path = QPainterPath()
        path.addRoundedRect(r, rad, rad)
        p.fillPath(path, bgc)
        if border:
            p.setPen(QPen(T.c(border), 1))
            p.drawPath(path)
        if self.hasFocus() and self._kbd_focus:
            p.setPen(QPen(T.c(T.ACCENT_HI, 0.7), 1.5))
            p.drawRoundedRect(r.adjusted(1, 1, -1, -1), rad, rad)
        icol = T.c(self.icon_color_override) if self.icon_color_override else fgc
        if self.icon_only and self._icon:
            ir = QRectF(0, 0, isz, isz)
            ir.moveCenter(r.center())
            icons.draw(p, self._icon, ir, icol)
            return
        p.setFont(T.font(fs, 600))
        fm = QFontMetricsF(p.font())
        tw = fm.horizontalAdvance(self.text())
        total = tw + ((isz + 8) if self._icon else 0)
        x = r.left() + pad if self.align_left else r.center().x() - total / 2
        if self._icon:
            ir = QRectF(x, r.center().y() - isz / 2, isz, isz)
            icons.draw(p, self._icon, ir, icol)
            x += isz + 8
        p.setPen(fgc)
        p.drawText(QRectF(x, r.top(), tw + 2, r.height()), Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft,
                   self.text())


class ChipGroup(QWidget):
    """Exclusive set of pill chips."""

    changed = pyqtSignal(str)

    def __init__(self, options: list[tuple[str, str]], parent=None, size: str = "sm"):
        super().__init__(parent)
        lay = QHBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(6)
        self.size_key = size
        self.buttons: dict[str, TactileButton] = {}
        self.options: list[tuple[str, str]] = []
        self.value = ""
        self.set_options(options)

    def set_value(self, key: str, emit: bool = False):
        for k, b in self.buttons.items():
            b.setChecked(k == key)
        changed = key != self.value
        self.value = key
        if emit and changed:
            self.changed.emit(key)

    def set_options(self, options: list[tuple[str, str]], value: str | None = None):
        self.options = list(options)
        lay = self.layout()
        for b in self.buttons.values():
            lay.removeWidget(b)
            b.deleteLater()
        self.buttons.clear()
        for key, label in options:
            b = TactileButton(label, variant="chip", size=self.size_key)
            b.setCheckable(True)
            b.clicked.connect(lambda _=False, k=key: self.set_value(k, emit=True))
            lay.addWidget(b)
            self.buttons[key] = b
        if options:
            self.value = value if value in self.buttons else options[0][0]
            self.buttons[self.value].setChecked(True)


class SearchBar(QLineEdit):
    """Search field with icon, clear affordance and debounced `search` signal."""

    search = pyqtSignal(str)

    def __init__(self, placeholder="Search your library", parent=None):
        super().__init__(parent)
        self.setPlaceholderText(placeholder)
        self.setClearButtonEnabled(True)
        self.setMinimumWidth(260)
        self.setFixedHeight(38)
        self.setStyleSheet("QLineEdit { padding-left: 36px; border-radius: 10px; }")
        self._t = QTimer(self, singleShot=True, interval=160)
        self._t.timeout.connect(lambda: self.search.emit(self.text().strip()))
        self.textChanged.connect(lambda _: self._t.start())

    def keyPressEvent(self, e):  # noqa: N802
        if e.key() == Qt.Key.Key_Escape:
            if self.text():
                self.clear()
            else:
                self.clearFocus()
            return
        super().keyPressEvent(e)

    def paintEvent(self, e):  # noqa: N802
        super().paintEvent(e)
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        icons.draw(p, "search", QRectF(12, (self.height() - 16) / 2, 16, 16),
                   T.c(T.TEXT_MUTED if self.hasFocus() else T.TEXT_DIM))


class Label(QLabel):
    def __init__(self, text="", size=10.0, weight=400, color=T.TEXT, display=False, parent=None, wrap=False):
        super().__init__(text, parent)
        self.setFont(T.font(size, weight, display))
        self.setStyleSheet(f"color: {color};")
        self.setWordWrap(wrap)
        if wrap:
            self.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Minimum)


class Toast(QWidget):
    """Transient message pill anchored to the bottom-centre of its parent."""

    def __init__(self, parent: QWidget):
        super().__init__(parent)
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        self.text = ""
        self.icon = None
        self.opacity = 0.0
        self.offset = 0.0
        self._a = Anim(self, "opacity", T.DUR_BASE)
        self._o = Anim(self, "offset", T.DUR_SLOW)
        self._hide = QTimer(self, singleShot=True)
        self._hide.timeout.connect(lambda: self._a.to(0.0, T.DUR_SLOW))
        self.hide()

    def show_message(self, text: str, icon: str | None = None, ms: int = 2200):
        self.text, self.icon = text, icon
        fm = QFontMetricsF(T.font(9.75, 600))
        w = int(fm.horizontalAdvance(text) + 44 + (26 if icon else 0))
        par = self.parentWidget()
        self.setGeometry((par.width() - w) // 2, par.height() - 90, w, 44)
        self.show()
        self.raise_()
        self.offset = 10.0
        self._o.to(0.0)
        self._a.to(1.0)
        self._hide.start(ms)

    def paintEvent(self, _e):  # noqa: N802
        if self.opacity <= 0.01:
            return
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.setOpacity(self.opacity)
        p.translate(0, self.offset)
        r = QRectF(self.rect()).adjusted(1, 1, -1, -1)
        p.setPen(QPen(T.c(T.BORDER_STRONG), 1))
        p.setBrush(T.c(T.ELEVATED_2))
        p.drawRoundedRect(r, r.height() / 2, r.height() / 2)
        x = 22
        if self.icon:
            icons.draw(p, self.icon, QRectF(x - 2, r.center().y() - 9, 18, 18), T.c(T.SUCCESS))
            x += 26
        p.setFont(T.font(9.75, 600))
        p.setPen(T.c(T.TEXT))
        p.drawText(QRectF(x, 0, r.width(), r.height() + 2), Qt.AlignmentFlag.AlignVCenter, self.text)


def fade_in(widget: QWidget, duration: int = T.DUR_BASE):
    """Opacity entrance for a page; the effect is removed afterwards so it costs nothing at rest."""
    eff = QGraphicsOpacityEffect(widget)
    eff.setOpacity(0.0)
    widget.setGraphicsEffect(eff)
    a = QVariantAnimation(widget)
    a.setDuration(duration)
    a.setEasingCurve(T.ease_out())
    a.setStartValue(0.0)
    a.setEndValue(1.0)
    a.valueChanged.connect(lambda v: eff.setOpacity(float(v)))
    a.finished.connect(lambda: widget.setGraphicsEffect(None))
    a.start(QVariantAnimation.DeletionPolicy.DeleteWhenStopped)


def fmt_time(seconds: float) -> str:
    seconds = max(0, int(seconds))
    h, rem = divmod(seconds, 3600)
    m, s = divmod(rem, 60)
    return f"{h}:{m:02d}:{s:02d}" if h else f"{m}:{s:02d}"


def fmt_duration(seconds: float) -> str:
    """Compact human duration: 45m, 3h 05m, 120h."""
    h, m = divmod(int(seconds // 60), 60)
    if h >= 100:
        return f"{h}h"
    return f"{h}h {m:02d}m" if h else f"{m}m"


def fmt_runtime(minutes: int | None) -> str:
    if not minutes:
        return ""
    h, m = divmod(int(minutes), 60)
    return f"{h}h {m}m" if h else f"{m}m"


class SmoothScroller(QWidget):
    """Eased wheel scrolling for a QAbstractScrollArea (mouse wheels only; trackpads pass through)."""

    def __init__(self, area, step: float = 1.15, duration: int = 280):
        super().__init__(area)
        self.hide()
        self.area = area
        self.bar = area.verticalScrollBar()
        self.step = step
        self.target = None
        self.anim = QVariantAnimation(self)
        self.anim.setDuration(duration)
        self.anim.setEasingCurve(T.ease_out())
        self.anim.valueChanged.connect(lambda v: v is not None and self.bar.setValue(int(round(v))))
        self.anim.finished.connect(lambda: setattr(self, "target", None))
        area.viewport().installEventFilter(self)
        area._smooth = self

    def scroll_by(self, dy: float):
        cur = self.target if self.target is not None else float(self.bar.value())
        self.target = float(max(self.bar.minimum(), min(self.bar.maximum(), cur - dy)))
        self.anim.stop()
        self.anim.setStartValue(float(self.bar.value()))
        self.anim.setEndValue(self.target)
        self.anim.start()

    def eventFilter(self, obj, ev):  # noqa: N802
        if ev.type() == QEvent.Type.Wheel and not ev.pixelDelta().y() and not ev.angleDelta().x() \
                and not ev.modifiers() & Qt.KeyboardModifier.ShiftModifier:
            self.scroll_by(ev.angleDelta().y() * self.step)
            return True
        return False


def install_row_wheel(view):
    """Horizontal rows: Shift+wheel / trackpad scrolls the row, a plain wheel scrolls the page."""
    from PyQt6.QtWidgets import QScrollArea

    class _F(QWidget):
        def eventFilter(self, obj, ev):  # noqa: N802
            if ev.type() != QEvent.Type.Wheel:
                return False
            dx, dy = ev.angleDelta().x(), ev.angleDelta().y()
            if dx or ev.modifiers() & Qt.KeyboardModifier.ShiftModifier:
                bar = view.horizontalScrollBar()
                bar.setValue(bar.value() - (dx or dy))
                return True
            w = view.parentWidget()
            while w is not None and not isinstance(w, QScrollArea):
                w = w.parentWidget()
            if w is not None:
                if getattr(w, "_smooth", None) is not None and not ev.pixelDelta().y():
                    w._smooth.scroll_by(dy * w._smooth.step)
                else:
                    vb = w.verticalScrollBar()
                    vb.setValue(vb.value() - (ev.pixelDelta().y() or dy))
            return True

    f = _F(view)
    view.viewport().installEventFilter(f)
    return f
