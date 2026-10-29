"""App paths, VLC discovery and persistent user settings."""
from __future__ import annotations

import json
import os
import sys
import threading
from pathlib import Path

APP_NAME = "Luminary"
APP_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = Path(os.environ.get("APPDATA", Path.home())) / APP_NAME
CACHE_DIR = DATA_DIR / "cache"
IMAGE_CACHE_DIR = CACHE_DIR / "images"
DB_PATH = DATA_DIR / "library.db"
SETTINGS_PATH = DATA_DIR / "settings.json"

VIDEO_EXTS = {
    ".mkv", ".mp4", ".m4v", ".avi", ".mov", ".wmv", ".webm", ".ts", ".m2ts",
    ".mpg", ".mpeg", ".flv", ".ogv", ".3gp",
}
SUBTITLE_EXTS = {".srt", ".ass", ".ssa", ".vtt", ".sub"}

DEFAULTS = {
    "library_folders": [],
    "tmdb_api_key": "",
    "volume": 80,
    "auto_next": True,
    "watched_threshold": 0.90,
    "window_geometry": None,
    "show_missing_episodes": True,
    "kind_overrides": {},
}

KIND_LABELS = {"movie": "Movies", "show": "TV Shows", "anime": "Anime", "auto": "Mixed (use subfolder names)"}


def ensure_dirs() -> None:
    for d in (DATA_DIR, CACHE_DIR, IMAGE_CACHE_DIR):
        d.mkdir(parents=True, exist_ok=True)


def find_vlc_dir() -> Path | None:
    """Locate a 64-bit VLC install that contains libvlc.dll."""
    candidates: list[Path] = []
    if sys.platform == "win32":
        try:
            import winreg

            for view in (winreg.KEY_WOW64_64KEY, 0):
                try:
                    with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\VideoLAN\VLC", 0,
                                        winreg.KEY_READ | view) as k:
                        val, _ = winreg.QueryValueEx(k, "InstallDir")
                        candidates.append(Path(val))
                except OSError:
                    pass
        except ImportError:
            pass
    candidates += [Path(r"C:\Program Files\VideoLAN\VLC"), Path(r"C:\Program Files (x86)\VideoLAN\VLC")]
    for c in candidates:
        if (c / "libvlc.dll").exists():
            return c
    return None


def prepare_vlc_env() -> Path | None:
    """Must run before `import vlc` so python-vlc loads the right DLLs."""
    vlc_dir = find_vlc_dir()
    if vlc_dir:
        os.environ.setdefault("PYTHON_VLC_LIB_PATH", str(vlc_dir / "libvlc.dll"))
        os.environ.setdefault("PYTHON_VLC_MODULE_PATH", str(vlc_dir / "plugins"))
        if hasattr(os, "add_dll_directory"):
            try:
                os.add_dll_directory(str(vlc_dir))
            except OSError:
                pass
    return vlc_dir


class Settings:
    """Tiny JSON-backed settings store."""

    def __init__(self, path: Path = SETTINGS_PATH):
        self.path = path
        self._lock = threading.Lock()
        self._data = dict(DEFAULTS)
        if path.exists():
            try:
                self._data.update(json.loads(path.read_text(encoding="utf-8")))
            except (OSError, ValueError):
                pass

    def folders(self) -> list[dict]:
        """Library folders as [{'path': str, 'kind': 'movie'|'show'|'anime'|'auto'}]."""
        out = []
        for f in self._data.get("library_folders") or []:
            if isinstance(f, str):
                out.append({"path": f, "kind": "auto"})
            elif isinstance(f, dict) and f.get("path"):
                out.append({"path": f["path"], "kind": f.get("kind") or "auto"})
        return out

    def set_folders(self, folders: list[dict]) -> None:
        self.set("library_folders", [{"path": f["path"], "kind": f.get("kind") or "auto"} for f in folders])

    def overrides(self) -> dict[str, str]:
        return dict(self._data.get("kind_overrides") or {})

    def set_override(self, path: str, kind: str) -> None:
        """Pin a file or series folder to a category (beats the folder's own category)."""
        self.set("kind_overrides", {**self.overrides(), path: kind})

    def get(self, key, default=None):
        return self._data.get(key, DEFAULTS.get(key, default))

    def set(self, key, value) -> None:
        with self._lock:
            self._data[key] = value
            self.path.parent.mkdir(parents=True, exist_ok=True)
            tmp = self.path.with_suffix(".tmp")
            tmp.write_text(json.dumps(self._data, indent=2), encoding="utf-8")
            os.replace(tmp, self.path)
