"""Luminary — local media library & player."""
from __future__ import annotations

import sys
import threading
import traceback
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from core import config  # noqa: E402

config.ensure_dirs()
VLC_DIR = config.prepare_vlc_env()  # must run before anything imports python-vlc

from PyQt6.QtCore import QLockFile  # noqa: E402
from PyQt6.QtWidgets import QApplication, QMessageBox  # noqa: E402

LOG = config.DATA_DIR / "error.log"


def _excepthook(t, v, tb):
    """Log every uncaught error (also used by worker threads) and explain a damaged library."""
    msg = "".join(traceback.format_exception(t, v, tb))
    try:
        with LOG.open("a", encoding="utf-8") as f:
            f.write(msg + "\n")
    except OSError:
        pass
    if sys.__stderr__:
        sys.__stderr__.write(msg)
    if "malformed" in str(v) and not getattr(_excepthook, "warned", False) \
            and QApplication.instance() and threading.current_thread() is threading.main_thread():
        _excepthook.warned = True
        QMessageBox.warning(None, "Library damaged", "Luminary's library database is damaged. Restart Luminary "
                            "and it will repair itself (your watch progress is kept).")


def main() -> int:
    sys.excepthook = _excepthook
    if sys.platform == "win32":  # same ID as the Start-menu shortcut, so a pinned taskbar icon is this window
        import ctypes
        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID("Luminary.MediaLibrary")

    app = QApplication(sys.argv)
    app.setApplicationName(config.APP_NAME)
    from ui import theme
    theme.setup_fonts(app)
    app.setStyleSheet(theme.stylesheet())

    if VLC_DIR is None:
        QMessageBox.critical(None, "Luminary", "VLC (64-bit) was not found.\n\n"
                             "Install VLC from videolan.org and start Luminary again.")
        return 1

    # one Luminary at a time: two processes writing the library is how databases get hurt.
    # (A crashed instance's lock is detected through its dead process id and taken over.)
    lock = QLockFile(str(config.DATA_DIR / "luminary.lock"))
    lock.setStaleLockTime(0)
    if not lock.tryLock(200):
        QMessageBox.information(None, "Luminary", "Luminary is already running.")
        return 0

    from core import db_health
    from core.db import Database
    from ui.main_window import MainWindow

    repair = repair_error = None
    try:
        repair = db_health.ensure_healthy(config.DB_PATH, config.DATA_DIR / "backups")
    except Exception as e:  # never block startup on the health check itself, but say so
        _excepthook(type(e), e, e.__traceback__)
        repair_error = e
    db = Database(config.DB_PATH)
    win = MainWindow(db, config.Settings())
    win.show()
    if repair_error is not None:
        QMessageBox.warning(win, "Library needs repair",
                            "Luminary's library database is damaged and could not be repaired automatically:\n\n"
                            f"{repair_error}\n\nClose every Luminary window and start it again. Details: {LOG}")
    elif repair:
        QMessageBox.information(
            win, "Library repaired",
            "Luminary found damage in its library database and rebuilt it.\n\n"
            f"Recovered {repair.get('media', 0)} titles and {repair.get('episodes', 0)} episodes "
            f"(with watch progress).\nThe damaged copy was kept in:\n{repair['aside']}")
    code = app.exec()
    db.shutdown()
    lock.unlock()
    return code


if __name__ == "__main__":
    sys.exit(main())
