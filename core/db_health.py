"""Startup integrity check, automatic salvage of a damaged library, and rolling backups."""
from __future__ import annotations

import datetime as dt
import os
import shutil
import sqlite3
from pathlib import Path

from .db import SCHEMA

TABLES = ("media", "episodes", "files")
KEEP_BACKUPS = 5


def is_healthy(path: Path) -> bool:
    """Full integrity_check (also validates indexes; the library is small, so this is fast)."""
    return (not path.exists()) or _integrity_ok(path)


def _salvage_rows(src: sqlite3.Connection, table: str) -> tuple[list[str], list[tuple]]:
    cols = [r[1] for r in src.execute(f"PRAGMA table_info({table})")]
    sel = ", ".join(cols)
    try:
        return cols, src.execute(f"SELECT {sel} FROM {table} NOT INDEXED").fetchall()
    except sqlite3.Error:
        pass
    # damaged b-tree: probe rowids one by one and keep whatever is readable
    rows = []
    try:
        hi = src.execute(f"SELECT MAX(rowid) FROM {table} NOT INDEXED").fetchone()[0] or 0
    except sqlite3.Error:
        hi = 0
    hi = max(hi, 20000)
    misses = 0
    for rid in range(1, hi + 1):
        try:
            r = src.execute(f"SELECT {sel} FROM {table} WHERE rowid=?", (rid,)).fetchone()
        except sqlite3.Error:
            r = None
        if r is None:
            misses += 1
            if misses > 5000 and rid > 1000:
                break
            continue
        misses = 0
        rows.append(r)
    return cols, rows


class RepairError(RuntimeError):
    pass


def _integrity_ok(path: Path) -> bool:
    try:
        c = sqlite3.connect(path.as_posix(), timeout=30)
        try:
            return c.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
        finally:
            c.close()
    except sqlite3.Error:
        return False


def repair(path: Path) -> dict:
    """Rebuild `path` from every readable row.

    The damaged files are copied aside first; the clean database is built in a temp file,
    verified, and then atomically swapped in with os.replace (never delete-then-recreate).
    """
    stamp = dt.datetime.now().strftime("%Y%m%d-%H%M%S")
    aside = path.parent / f"corrupt-{stamp}"
    aside.mkdir(parents=True, exist_ok=True)
    parts = [Path(str(path) + s) for s in ("", "-wal", "-shm") if Path(str(path) + s).exists()]
    for f in parts:  # keep an exact copy of what was there
        shutil.copy2(f, aside / f.name)
    damaged = aside / path.name
    fresh = path.with_name(path.name + ".rebuild")
    fresh.unlink(missing_ok=True)
    src = sqlite3.connect(damaged.as_posix(), timeout=30)
    dst = sqlite3.connect(fresh.as_posix())
    dst.executescript(SCHEMA)
    report = {"aside": str(aside)}
    for table in TABLES:
        try:
            cols, rows = _salvage_rows(src, table)
        except sqlite3.Error:
            report[table] = 0
            continue
        dcols = [r[1] for r in dst.execute(f"PRAGMA table_info({table})")]
        if table == "media":
            for col in cols:
                if col not in dcols:
                    dst.execute(f"ALTER TABLE media ADD COLUMN {col}")
            dcols = [r[1] for r in dst.execute(f"PRAGMA table_info({table})")]
        keep = [c for c in cols if c in dcols]
        idx = [cols.index(c) for c in keep]
        if table == "episodes":
            # prefer rows that carry watch state when duplicates collide on (media, season, number)
            wi, pi = cols.index("watched"), cols.index("position")
            rows.sort(key=lambda r: (-(r[wi] or 0), -(r[pi] or 0)))
        sql = f"INSERT OR IGNORE INTO {table} ({', '.join(keep)}) VALUES ({', '.join('?' * len(keep))})"
        n = 0
        for r in rows:
            try:
                dst.execute(sql, [r[i] for i in idx])
                n += 1
            except sqlite3.Error:
                pass
        report[table] = n
    dst.commit()
    # anything referencing a missing parent is dropped; files get re-scanned anyway
    dst.execute("DELETE FROM episodes WHERE media_id NOT IN (SELECT id FROM media)")
    dst.execute("DELETE FROM files WHERE media_id NOT IN (SELECT id FROM media)")
    # episode guides may have lost rows: re-fetch them (watch state lives on, keyed by season/number)
    dst.execute("UPDATE media SET meta_status='pending' WHERE kind IN ('show','anime')")
    dst.commit()
    src.close()
    dst.close()
    if not _integrity_ok(fresh):
        raise RepairError("rebuilt database failed its integrity check")
    # stale WAL/SHM belong to the damaged file; they must not be replayed onto the new one
    for s in ("-wal", "-shm"):
        try:
            Path(str(path) + s).unlink(missing_ok=True)
        except OSError as e:
            fresh.unlink(missing_ok=True)
            raise RepairError(f"the library is still open by another program ({e})") from e
    os.replace(fresh, path)
    if not _integrity_ok(path):
        raise RepairError("the repaired library did not stick (file replaced or locked by another program)")
    report["verified"] = True
    return report


def backup(path: Path, backup_dir: Path) -> Path | None:
    """One consistent snapshot per day (sqlite backup API), keeping the newest few."""
    if not path.exists():
        return None
    backup_dir.mkdir(parents=True, exist_ok=True)
    out = backup_dir / f"library-{dt.date.today():%Y-%m-%d}.db"
    if not out.exists() or not _integrity_ok(out):  # never keep a damaged snapshot as "today's"
        tmp = out.with_suffix(".tmp")
        tmp.unlink(missing_ok=True)
        src = sqlite3.connect(path.as_posix(), timeout=30)
        dst = sqlite3.connect(tmp.as_posix())
        try:
            src.backup(dst)
        finally:
            dst.close()
            src.close()
        os.replace(tmp, out)
    for old in sorted(backup_dir.glob("library-*.db"))[:-KEEP_BACKUPS]:
        old.unlink(missing_ok=True)
    return out


def ensure_healthy(path: Path, backup_dir: Path) -> dict | None:
    """Run at startup before the app opens the database. Returns a repair report if one was needed."""
    report = None
    if not is_healthy(path):
        report = repair(path)
    try:
        backup(path, backup_dir)
    except sqlite3.Error:
        pass
    return report
