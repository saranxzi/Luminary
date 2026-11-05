"""Walks library folders and keeps the database in step with what is on disk.

Every file is re-resolved on every scan (filename parsing is cheap), so a changed folder
category, a per-title override or a smarter parser re-files existing files automatically.
Only files whose assignment or size/mtime changed touch the database.
"""
from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from . import config
from .db import Database
from .parser import KIND_MOVIE, ParsedFile, normalize_key, parse_path

SKIP_DIRS = {"$recycle.bin", "system volume information", "__pycache__", "node_modules"}
SAMPLE_MAX_BYTES = 300 * 1024 * 1024


@dataclass
class ScanResult:
    added: int = 0      # files seen for the first time
    moved: int = 0      # known files re-filed (category change, override, parser improvement)
    removed: int = 0
    unchanged: int = 0
    total: int = 0


def iter_video_files(root: str):
    app_dir = os.path.normcase(str(config.APP_DIR))
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [d for d in dirnames
                       if not d.startswith(".") and d.lower() not in SKIP_DIRS
                       and not os.path.normcase(os.path.join(dirpath, d)).startswith(app_dir)]
        for f in filenames:
            if os.path.splitext(f)[1].lower() not in config.VIDEO_EXTS:
                continue
            full = os.path.join(dirpath, f)
            if "sample" in f.lower():
                try:
                    if os.path.getsize(full) < SAMPLE_MAX_BYTES:
                        continue
                except OSError:
                    continue
            yield full


def _norm_folders(folders) -> list[dict]:
    return [{"path": f, "kind": "auto"} if isinstance(f, str) else f for f in folders]


def _contains(folder: str, path: str) -> bool:
    nf, np = os.path.normcase(folder), os.path.normcase(path)
    return np == nf or np.startswith(os.path.join(nf, ""))


def classify(path: str, folders: list[dict], overrides: dict[str, str] | None = None):
    """(root, forced kind) for a file: the most specific override beats the folder category."""
    root = kind = None
    for f in _norm_folders(folders):
        if _contains(f["path"], path) and (root is None or len(f["path"]) > len(root)):
            root, kind = f["path"], (f["kind"] if f["kind"] != "auto" else None)
    best = None
    for pre, okind in (overrides or {}).items():
        if _contains(pre, path) and (best is None or len(pre) > len(best[0])):
            best = (pre, okind)
    if best:
        kind = best[1]
        if best[0] != path and os.path.isdir(best[0]) and kind != KIND_MOVIE:
            root = str(Path(best[0]).parent)  # the overridden folder is the series folder
    return root, kind


def media_key(pf: ParsedFile, path: str) -> str:
    if pf.kind == KIND_MOVIE:
        return f"movie:{os.path.normcase(path)}"
    return f"series:{normalize_key(pf.title)}"


def _target(pf: ParsedFile) -> tuple:
    if pf.kind == KIND_MOVIE:
        return None, None, None, 0
    return pf.season, pf.episode, pf.episode_end, int(pf.absolute)


def scan(db: Database, folders, progress: Callable[[str, int, int], None] | None = None,
         overrides: dict[str, str] | None = None) -> ScanResult:
    folders = _norm_folders(folders)
    res = ScanResult()
    known = db.known_files()
    keys = db.media_keys()
    found = list(dict.fromkeys(p for f in folders if os.path.isdir(f["path"]) for p in iter_video_files(f["path"])))
    res.total = len(found)
    seen: set[str] = set()
    for i, path in enumerate(found):
        if progress and (i % 10 == 0 or i == res.total - 1):
            progress(Path(path).name, i + 1, res.total)
        try:
            st = os.stat(path)
        except OSError:
            continue
        root, forced = classify(path, folders, overrides)
        pf = parse_path(path, root, forced)
        if pf is None:  # extras (trailers, featurettes…)
            continue
        seen.add(path)
        key, target = media_key(pf, path), _target(pf)
        prev, item = known.get(path), keys.get(key)
        if (prev and item and prev["media_id"] == item[0] and prev["size"] == st.st_size
                and abs((prev["mtime"] or 0) - st.st_mtime) < 1
                and (prev["season"], prev["episode"], prev["episode_end"], prev["absolute"]) == target
                and (forced is None or item[1] == pf.kind)):
            res.unchanged += 1
            continue
        folder = str(Path(path).parent) if pf.kind == KIND_MOVIE else pf.show_folder
        mid = db.upsert_media(key, pf.kind, pf.title, pf.year, folder, force_kind=forced is not None)
        keys[key] = (mid, pf.kind if forced or not item else item[1])
        db.add_file(path, st.st_size, st.st_mtime, mid, *target[:3], absolute=bool(target[3]))
        if prev:
            res.moved += 1
        else:
            res.added += 1
    gone = [p for p in known if p not in seen]
    db.remove_files(gone)
    db.finish_scan()
    res.removed = len(gone)
    return res
