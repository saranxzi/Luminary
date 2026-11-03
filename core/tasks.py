"""Background jobs: library scan + metadata enrichment, and a generic async runner."""
from __future__ import annotations

import sys

from PyQt6.QtCore import QObject, QRunnable, QThread, QThreadPool, pyqtSignal

from . import images, scraper
from .config import Settings
from .db import Database
from .scanner import scan


class _Stopped(Exception):
    pass


class LibraryWorker(QThread):
    status = pyqtSignal(str)                # human readable progress text
    library_changed = pyqtSignal()          # structure changed (items added/removed)
    item_updated = pyqtSignal(int)          # metadata for media id arrived
    finished_all = pyqtSignal(dict)

    def __init__(self, db: Database, settings: Settings, rescan: bool = True, parent=None):
        super().__init__(parent)
        self.db, self.settings, self.rescan = db, settings, rescan
        self._stop = False

    def stop(self):
        self._stop = True

    def _progress(self, name: str, i: int, n: int):
        if self._stop:
            raise _Stopped()
        self.status.emit(f"Scanning {i}/{n} · {name}")

    def run(self):
        summary = {"added": 0, "removed": 0, "matched": 0, "failed": 0}
        try:
            if self.rescan:
                self.status.emit("Scanning folders…")
                res = scan(self.db, self.settings.folders(), self._progress, overrides=self.settings.overrides())
                summary.update(added=res.added, removed=res.removed)
                if res.added or res.moved or res.removed:
                    self.library_changed.emit()
            pending = self.db.pending_metadata()
            tmdb = self.settings.get("tmdb_api_key") or ""
            for i, m in enumerate(pending, 1):
                if self._stop:
                    break
                self.status.emit(f"Fetching metadata {i}/{len(pending)} · {m['parsed_title']}")
                try:
                    result = scraper.auto_match(m, tmdb)
                except scraper.ScrapeError:
                    continue  # network trouble: leave pending, retry next launch
                except Exception:  # a bug in one provider must not stop the whole run
                    sys.excepthook(*sys.exc_info())
                    self.db.mark_meta_failed(m["id"])
                    summary["failed"] += 1
                    continue
                if result is None:
                    self.db.mark_meta_failed(m["id"])
                    summary["failed"] += 1
                    self.item_updated.emit(m["id"])
                    continue
                meta, eps = result
                self.db.apply_metadata(m["id"], meta, eps)
                for url in (meta.get("poster"), meta.get("backdrop"), meta.get("logo")):
                    if url:
                        images.download(url)
                summary["matched"] += 1
                self.item_updated.emit(m["id"])
        except _Stopped:
            pass
        except Exception:
            sys.excepthook(*sys.exc_info())  # logged to error.log by main.py
        finally:
            self.status.emit("")
            self.finished_all.emit(summary)


class _Sig(QObject):
    ok = pyqtSignal(object)
    err = pyqtSignal(str)


class _Run(QRunnable):
    def __init__(self, fn, args, kwargs, sig):
        super().__init__()
        self.fn, self.args, self.kwargs, self.sig = fn, args, kwargs, sig

    def run(self):
        try:
            self.sig.ok.emit(self.fn(*self.args, **self.kwargs))
        except Exception as e:  # noqa: BLE001
            self.sig.err.emit(str(e) or e.__class__.__name__)


_keep: set = set()


def run_async(fn, *args, on_done=None, on_error=None, **kwargs):
    """Run fn in the global thread pool; callbacks fire on the GUI thread."""
    sig = _Sig()
    _keep.add(sig)

    def done(v):
        _keep.discard(sig)
        if on_done:
            on_done(v)

    def fail(e):
        _keep.discard(sig)
        if on_error:
            on_error(e)

    sig.ok.connect(done)
    sig.err.connect(fail)
    QThreadPool.globalInstance().start(_Run(fn, args, kwargs, sig))
