"""Asynchronous image loading with a disk cache and memory-bounded pixmap caches."""
from __future__ import annotations

import hashlib
import threading
from collections import OrderedDict

import requests
from PyQt6.QtCore import QObject, QRunnable, QSize, Qt, QThreadPool, pyqtSignal
from PyQt6.QtGui import QImage, QPixmap

from . import config

_session = requests.Session()
_session.headers.update({"User-Agent": "Luminary/1.0"})
MAX_DECODED_WIDTH = 1920  # enough for a full-width backdrop; bounds memory per cached image


def _cache_path(url: str):
    return config.IMAGE_CACHE_DIR / f"{hashlib.sha1(url.encode('utf-8')).hexdigest()}.img"


def download(url: str) -> bytes | None:
    """Fetch through the disk cache (blocking; safe to call from several threads at once)."""
    p = _cache_path(url)
    try:
        if p.stat().st_size > 0:
            return p.read_bytes()
    except OSError:
        pass
    try:
        r = _session.get(url, timeout=20)
        r.raise_for_status()
        data = r.content
    except requests.RequestException:
        return None
    try:
        p.parent.mkdir(parents=True, exist_ok=True)
        tmp = p.with_name(f"{p.name}.{threading.get_ident()}.part")
        tmp.write_bytes(data)
        tmp.replace(p)
    except OSError:
        pass  # caching is best-effort; the bytes are still good
    return data


class _Signals(QObject):
    done = pyqtSignal(str, QImage)


class _Job(QRunnable):
    def __init__(self, url: str, signals: _Signals):
        super().__init__()
        self.url, self.signals = url, signals

    def run(self):
        img = QImage()
        try:
            data = download(self.url)
            if data:
                img.loadFromData(data)
                if not img.isNull() and img.width() > MAX_DECODED_WIDTH:
                    # scale in the worker thread so the UI never handles full-size originals
                    img = img.scaledToWidth(MAX_DECODED_WIDTH, Qt.TransformationMode.SmoothTransformation)
        finally:  # always report back, or the URL would stay "pending" forever
            self.signals.done.emit(self.url, img)


class _LruPixmaps:
    """Pixmap LRU bounded by memory, not entry count (a 4K backdrop ≠ a thumbnail)."""

    def __init__(self, budget_bytes: int):
        self.budget, self.used = budget_bytes, 0
        self.items: OrderedDict = OrderedDict()

    def get(self, key):
        pm = self.items.get(key)
        if pm is not None:
            self.items.move_to_end(key)
        return pm

    def put(self, key, pm: QPixmap):
        self.used += pm.width() * pm.height() * 4
        self.items[key] = pm
        while self.used > self.budget and len(self.items) > 1:
            _, old = self.items.popitem(last=False)
            self.used -= old.width() * old.height() * 4


class ImageLoader(QObject):
    """Call `get(url)`; returns a QPixmap if cached, else None and emits `ready(url)` later."""

    ready = pyqtSignal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._originals = _LruPixmaps(256 * 2**20)
        self._scaled = _LruPixmaps(192 * 2**20)
        self._pending: set[str] = set()
        self._failed: set[str] = set()
        self._pool = QThreadPool()
        self._pool.setMaxThreadCount(6)
        self._sig = _Signals()
        self._sig.done.connect(self._on_done)

    def get(self, url: str | None) -> QPixmap | None:
        if not url or url in self._failed:
            return None
        pm = self._originals.get(url)
        if pm is None and url not in self._pending:
            self._pending.add(url)
            self._pool.start(_Job(url, self._sig))
        return pm

    def get_scaled(self, url: str | None, size: QSize) -> QPixmap | None:
        """Pixmap scaled to cover `size` and centre-cropped, cached per size."""
        if not url:
            return None
        key = (url, size.width(), size.height())
        pm = self._scaled.get(key)
        if pm is not None:
            return pm
        src = self.get(url)
        if src is None:
            return None
        pm = src.scaled(size, Qt.AspectRatioMode.KeepAspectRatioByExpanding, Qt.TransformationMode.SmoothTransformation)
        x = max(0, (pm.width() - size.width()) // 2)
        y = max(0, (pm.height() - size.height()) // 2)
        pm = pm.copy(x, y, size.width(), size.height())
        self._scaled.put(key, pm)
        return pm

    def _on_done(self, url: str, img: QImage):
        self._pending.discard(url)
        if img.isNull():
            self._failed.add(url)
            return
        self._originals.put(url, QPixmap.fromImage(img))
        self.ready.emit(url)


_loader: ImageLoader | None = None


def loader() -> ImageLoader:
    global _loader
    if _loader is None:
        _loader = ImageLoader()
    return _loader
