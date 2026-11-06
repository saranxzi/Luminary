"""Design tokens, fonts, global stylesheet and motion helpers."""
from __future__ import annotations

import ctypes
import sys

from PyQt6.QtCore import QEasingCurve, QPointF
from PyQt6.QtGui import QColor, QFont, QFontDatabase

# ---------------------------------------------------------------- colour tokens
BG = "#0b0c10"
SURFACE = "#111319"
ELEVATED = "#171a22"
ELEVATED_2 = "#1d2029"
BORDER = "rgba(255,255,255,0.07)"
BORDER_STRONG = "rgba(255,255,255,0.13)"
TEXT = "#f1f3f7"
TEXT_MUTED = "#9ba3b4"
TEXT_DIM = "#5f6778"
ACCENT = "#3b82f6"
ACCENT_HI = "#60a5fa"
SUCCESS = "#34d399"
WARN = "#fbbf24"
DANGER = "#f87171"


def c(hex_or_rgba: str, alpha: float | None = None) -> QColor:
    if hex_or_rgba.startswith("rgba"):
        r, g, b, a = [x.strip() for x in hex_or_rgba[5:-1].split(",")]
        col = QColor(int(r), int(g), int(b))
        col.setAlphaF(float(a))
    else:
        col = QColor(hex_or_rgba)
    if alpha is not None:
        col.setAlphaF(alpha)
    return col


# ---------------------------------------------------------------- motion
DUR_FAST = 150
DUR_BASE = 200
DUR_SLOW = 320


def ease_out() -> QEasingCurve:
    """cubic-bezier(0.16, 1, 0.3, 1) — the snappy decelerating curve."""
    e = QEasingCurve(QEasingCurve.Type.BezierSpline)
    e.addCubicBezierSegment(QPointF(0.16, 1.0), QPointF(0.3, 1.0), QPointF(1.0, 1.0))
    return e


def ease_in_out() -> QEasingCurve:
    e = QEasingCurve(QEasingCurve.Type.BezierSpline)
    e.addCubicBezierSegment(QPointF(0.65, 0.0), QPointF(0.35, 1.0), QPointF(1.0, 1.0))
    return e


# ---------------------------------------------------------------- fonts
FONT_FAMILY = "Segoe UI Variable Text"
FONT_DISPLAY = "Segoe UI Variable Display"


def setup_fonts(app) -> None:
    global FONT_FAMILY, FONT_DISPLAY
    fams = set(QFontDatabase.families())
    if FONT_FAMILY not in fams:
        FONT_FAMILY = "Segoe UI"
    if FONT_DISPLAY not in fams:
        FONT_DISPLAY = FONT_FAMILY
    f = QFont(FONT_FAMILY, 10)
    f.setHintingPreference(QFont.HintingPreference.PreferNoHinting)
    app.setFont(f)


def font(size: float, weight: int = 400, display: bool = False) -> QFont:
    f = QFont(FONT_DISPLAY if display else FONT_FAMILY)
    f.setPointSizeF(size)
    f.setWeight(QFont.Weight(weight))
    if display:
        f.setLetterSpacing(QFont.SpacingType.PercentageSpacing, 98)
    return f


# ---------------------------------------------------------------- stylesheet
QSS = f"""
* {{ outline: none; }}
QWidget {{ color: {TEXT}; background: transparent; selection-background-color: {ACCENT}; }}
QMainWindow, #Root {{ background: {BG}; }}
QToolTip {{ background: {ELEVATED_2}; color: {TEXT}; border: 1px solid {BORDER_STRONG};
            border-radius: 6px; padding: 5px 8px; }}

QScrollArea {{ border: none; background: transparent; }}
QScrollArea > QWidget > QWidget {{ background: transparent; }}
QScrollBar:vertical {{ background: transparent; width: 10px; margin: 4px 2px; }}
QScrollBar::handle:vertical {{ background: rgba(255,255,255,0.10); border-radius: 3px; min-height: 40px; }}
QScrollBar::handle:vertical:hover {{ background: rgba(255,255,255,0.22); }}
QScrollBar:horizontal {{ background: transparent; height: 8px; margin: 2px 4px; }}
QScrollBar::handle:horizontal {{ background: rgba(255,255,255,0.10); border-radius: 3px; min-width: 40px; }}
QScrollBar::handle:horizontal:hover {{ background: rgba(255,255,255,0.22); }}
QScrollBar::add-line, QScrollBar::sub-line, QScrollBar::add-page, QScrollBar::sub-page {{
    background: none; border: none; width: 0; height: 0; }}

QLineEdit {{ background: {ELEVATED}; border: 1px solid {BORDER}; border-radius: 9px;
             padding: 8px 12px; color: {TEXT}; selection-background-color: {ACCENT}; }}
QLineEdit:focus {{ border: 1px solid rgba(96,165,250,0.55); background: {ELEVATED_2}; }}
QLineEdit::placeholder {{ color: {TEXT_DIM}; }}

QMenu {{ background: {ELEVATED}; border: 1px solid {BORDER_STRONG}; border-radius: 10px; padding: 6px; }}
QMenu::item {{ padding: 7px 26px 7px 12px; border-radius: 6px; color: {TEXT}; }}
QMenu::item:selected {{ background: rgba(255,255,255,0.07); }}
QMenu::item:disabled {{ color: {TEXT_DIM}; }}
QMenu::separator {{ height: 1px; background: {BORDER}; margin: 5px 6px; }}
QMenu::indicator {{ width: 14px; height: 14px; left: 6px; }}
QMenu::section {{ color: {TEXT_DIM}; padding: 6px 12px 4px; font-size: 8pt; text-transform: uppercase; }}

QComboBox {{ background: {ELEVATED}; border: 1px solid {BORDER}; border-radius: 8px; padding: 6px 10px; }}
QComboBox:hover {{ border-color: {BORDER_STRONG}; }}
QComboBox::drop-down {{ border: none; width: 22px; }}
QComboBox QAbstractItemView {{ background: {ELEVATED}; border: 1px solid {BORDER_STRONG};
    selection-background-color: rgba(255,255,255,0.08); padding: 4px; border-radius: 8px; }}

QListWidget {{ background: {SURFACE}; border: 1px solid {BORDER}; border-radius: 10px; padding: 4px; }}
QListWidget::item {{ padding: 8px 10px; border-radius: 6px; }}
QListWidget::item:selected {{ background: rgba(59,130,246,0.18); color: {TEXT}; }}
QListWidget::item:hover {{ background: rgba(255,255,255,0.05); }}

QCheckBox {{ spacing: 8px; }}
QCheckBox::indicator {{ width: 16px; height: 16px; border-radius: 5px; border: 1px solid {BORDER_STRONG};
                        background: {ELEVATED}; }}
QCheckBox::indicator:checked {{ background: {ACCENT}; border-color: {ACCENT}; image: url(__CHECK__); }}

QSpinBox {{ background: {ELEVATED}; border: 1px solid {BORDER}; border-radius: 8px; padding: 6px 8px; }}

QDialog {{ background: {SURFACE}; }}
QLabel {{ background: transparent; }}
"""


def stylesheet() -> str:
    """QSS with generated assets (e.g. the checkbox tick) resolved to files."""
    from core import config
    tick = config.CACHE_DIR / "check.svg"
    try:
        tick.parent.mkdir(parents=True, exist_ok=True)
        tick.write_text('<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" stroke="#ffffff" '
                        'stroke-width="3.2" stroke-linecap="round" stroke-linejoin="round"><path d="M20 6 9 17l-5-5"/></svg>',
                        encoding="utf-8")
    except OSError:
        pass
    return QSS.replace("__CHECK__", tick.as_posix())


def apply_dark_titlebar(widget) -> None:
    """Ask DWM for a dark title bar (+ Mica-free solid caption colour) on Windows 11."""
    if sys.platform != "win32":
        return
    try:
        hwnd = int(widget.winId())
        dwm = ctypes.windll.dwmapi
        val = ctypes.c_int(1)
        dwm.DwmSetWindowAttribute(hwnd, 20, ctypes.byref(val), ctypes.sizeof(val))  # immersive dark
        col = ctypes.c_int(0x00100C0B)  # caption colour = BG (0x00BBGGRR)
        dwm.DwmSetWindowAttribute(hwnd, 35, ctypes.byref(col), ctypes.sizeof(col))
    except Exception:
        pass
