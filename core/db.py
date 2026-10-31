"""SQLite persistence: library items, episodes, scanned files and watch state."""
from __future__ import annotations

import json
import sqlite3
import threading
import time
from pathlib import Path

SCHEMA = """
CREATE TABLE IF NOT EXISTS media (
    id INTEGER PRIMARY KEY,
    key TEXT UNIQUE NOT NULL,          -- movie: 'movie:<path>', series: 'series:<normalized title>'
    kind TEXT NOT NULL,                -- movie | show | anime
    title TEXT NOT NULL,
    parsed_title TEXT NOT NULL,
    parsed_year INTEGER,
    year INTEGER,
    overview TEXT,
    genres TEXT,                       -- json list
    cast_list TEXT,                    -- json list
    director TEXT,
    rating REAL,
    runtime INTEGER,                   -- minutes
    poster TEXT,
    backdrop TEXT,
    logo TEXT,
    ext_source TEXT,
    ext_id TEXT,
    imdb_id TEXT,
    total_episodes INTEGER,
    status TEXT,
    numbering TEXT DEFAULT 'seasons',  -- seasons | absolute
    folder TEXT,
    meta_status TEXT DEFAULT 'pending',-- pending | ok | failed
    match_locked INTEGER DEFAULT 0,
    available INTEGER DEFAULT 1,
    added_at REAL,
    -- movie watch state
    watched INTEGER DEFAULT 0,
    position REAL DEFAULT 0,
    duration REAL DEFAULT 0,
    last_played REAL,
    prefs TEXT                         -- json: preferred audio/subtitle tracks
);
CREATE TABLE IF NOT EXISTS episodes (
    id INTEGER PRIMARY KEY,
    media_id INTEGER NOT NULL REFERENCES media(id) ON DELETE CASCADE,
    season INTEGER NOT NULL,
    number INTEGER NOT NULL,
    title TEXT,
    overview TEXT,
    still TEXT,
    air_date TEXT,
    runtime INTEGER,
    file_path TEXT,
    watched INTEGER DEFAULT 0,
    position REAL DEFAULT 0,
    duration REAL DEFAULT 0,
    last_played REAL,
    UNIQUE(media_id, season, number)
);
CREATE INDEX IF NOT EXISTS ix_ep_media ON episodes(media_id, season, number);
CREATE INDEX IF NOT EXISTS ix_ep_file ON episodes(file_path);
CREATE TABLE IF NOT EXISTS files (
    path TEXT PRIMARY KEY,
    size INTEGER,
    mtime REAL,
    media_id INTEGER REFERENCES media(id) ON DELETE CASCADE,
    season INTEGER,
    episode INTEGER,
    episode_end INTEGER,
    absolute INTEGER DEFAULT 0         -- episode number counts across the whole series
);
"""

# best known length of an episode in seconds: measured duration, else metadata runtime
_EP_LENGTH = "COALESCE(NULLIF(e.duration, 0), e.runtime * 60, s.runtime * 60, 0)"


def _row(r: sqlite3.Row | None) -> dict | None:
    if r is None:
        return None
    d = dict(r)
    for k in ("genres", "cast_list", "prefs"):
        if k in d and isinstance(d[k], str):
            try:
                d[k] = json.loads(d[k])
            except ValueError:
                d[k] = None
    return d


class _Rows:
    """Eagerly fetched result set (so no cursor outlives the lock)."""

    def __init__(self, rows, lastrowid):
        self._rows = rows
        self.lastrowid = lastrowid

    def fetchone(self):
        return self._rows[0] if self._rows else None

    def fetchall(self):
        return list(self._rows)

    def __iter__(self):
        return iter(self._rows)


class _LockedConnection:
    """One SQLite connection shared by every thread; each statement, and each
    `with conn:` transaction block, runs under a single re-entrant lock."""

    def __init__(self, raw: sqlite3.Connection, lock: threading.RLock):
        self.raw, self.lock = raw, lock

    def execute(self, sql, args=()):
        with self.lock:
            cur = self.raw.execute(sql, args)
            return _Rows(cur.fetchall(), cur.lastrowid)

    def executescript(self, script):
        with self.lock:
            self.raw.executescript(script)

    def commit(self):
        with self.lock:
            self.raw.commit()

    def __enter__(self):
        self.lock.acquire()
        self.raw.__enter__()
        return self

    def __exit__(self, *exc):
        try:
            return self.raw.__exit__(*exc)
        finally:
            self.lock.release()


class Database:
    def __init__(self, path: str | Path):
        self.path = str(path)
        self.write_lock = threading.RLock()
        raw = sqlite3.connect(self.path, timeout=30, check_same_thread=False)
        raw.row_factory = sqlite3.Row
        raw.execute("PRAGMA journal_mode=WAL")
        raw.execute("PRAGMA foreign_keys=ON")
        raw.execute("PRAGMA synchronous=FULL")
        self._raw = raw
        self.conn = _LockedConnection(raw, self.write_lock)
        with self.write_lock:
            self.conn.executescript(SCHEMA)
            for table, col, ddl in (("media", "parsed_year", "INTEGER"), ("media", "logo", "TEXT"),
                                    ("media", "numbering", "TEXT DEFAULT 'seasons'"),
                                    ("files", "absolute", "INTEGER DEFAULT 0")):
                cols = {r["name"] for r in self.conn.execute(f"PRAGMA table_info({table})")}
                if col not in cols:
                    self.conn.execute(f"ALTER TABLE {table} ADD COLUMN {col} {ddl}")
            self.conn.commit()

    def shutdown(self):
        with self.write_lock:
            try:
                self._raw.execute("PRAGMA wal_checkpoint(TRUNCATE)")
            except sqlite3.Error:
                pass
            self._raw.close()

    # ------------------------------------------------------------------ scanning
    def known_files(self) -> dict[str, dict]:
        return {r["path"]: dict(r) for r in self.conn.execute(
            "SELECT path, size, mtime, media_id, season, episode, episode_end, absolute FROM files")}

    def media_keys(self) -> dict[str, tuple[int, str]]:
        return {r["key"]: (r["id"], r["kind"]) for r in self.conn.execute("SELECT id, key, kind FROM media")}

    def upsert_media(self, key: str, kind: str, title: str, year: int | None, folder: str | None,
                     force_kind: bool = False) -> int:
        """Find or create a library item. A forced kind (folder category / override) wins."""
        with self.write_lock, self.conn:
            r = self.conn.execute("SELECT id, kind FROM media WHERE key=?", (key,)).fetchone()
            if r:
                self.conn.execute("UPDATE media SET available=1 WHERE id=?", (r["id"],))
                if force_kind and r["kind"] != kind:
                    self.conn.execute("UPDATE media SET kind=?, meta_status='pending', match_locked=0 WHERE id=?",
                                      (kind, r["id"]))
                return r["id"]
            return self.conn.execute(
                "INSERT INTO media(key,kind,title,parsed_title,parsed_year,year,folder,added_at) VALUES(?,?,?,?,?,?,?,?)",
                (key, kind, title, title, year, year, folder, time.time())).lastrowid

    def add_file(self, path: str, size: int, mtime: float, media_id: int, season: int | None = None,
                 episode: int | None = None, episode_end: int | None = None, absolute: bool = False) -> None:
        """Record a file and link it to its episode(s); any previous link of this file is moved."""
        with self.write_lock, self.conn:
            self.conn.execute(
                "INSERT OR REPLACE INTO files(path,size,mtime,media_id,season,episode,episode_end,absolute) "
                "VALUES(?,?,?,?,?,?,?,?)", (path, size, mtime, media_id, season, episode, episode_end, int(absolute)))
            if episode is None and season is None:  # movie
                self.conn.execute("UPDATE episodes SET file_path=NULL WHERE file_path=?", (path,))
            elif episode is None:  # unnumbered file in a series -> Specials (season 0)
                self.conn.execute("UPDATE episodes SET file_path=NULL WHERE file_path=? AND NOT (media_id=? AND season=0)",
                                  (path, media_id))
                if self.conn.execute("SELECT 1 FROM episodes WHERE file_path=?", (path,)).fetchone() is None:
                    n = self.conn.execute("SELECT COALESCE(MAX(number),0)+1 FROM episodes WHERE media_id=? AND season=0",
                                          (media_id,)).fetchone()[0]
                    self.conn.execute("INSERT INTO episodes(media_id,season,number,title,file_path) VALUES(?,?,?,?,?)",
                                      (media_id, 0, n, Path(path).stem, path))
            else:
                last = max(episode, episode_end or episode)
                self.conn.execute(
                    "UPDATE episodes SET file_path=NULL WHERE file_path=? "
                    "AND NOT (media_id=? AND season=? AND number BETWEEN ? AND ?)",
                    (path, media_id, season, episode, last))
                for n in range(episode, last + 1):
                    self.conn.execute(
                        "INSERT INTO episodes(media_id,season,number,file_path) VALUES(?,?,?,?) "
                        "ON CONFLICT(media_id,season,number) DO UPDATE SET file_path=excluded.file_path",
                        (media_id, season, n, path))

    def remove_files(self, paths: list[str]) -> None:
        if not paths:
            return
        with self.write_lock, self.conn:
            for p in paths:
                self.conn.execute("UPDATE episodes SET file_path=NULL WHERE file_path=?", (p,))
                self.conn.execute("DELETE FROM files WHERE path=?", (p,))

    def media_files(self, media_id: int) -> list[str]:
        return [r["path"] for r in self.conn.execute("SELECT path FROM files WHERE media_id=? ORDER BY path",
                                                     (media_id,))]

    def finish_scan(self) -> None:
        """Availability, numbering style and orphan clean-up after files moved around."""
        with self.write_lock, self.conn:
            self.conn.execute("UPDATE media SET available = EXISTS(SELECT 1 FROM files f WHERE f.media_id = media.id)")
            # a series counts episodes absolutely unless some file carries a real season number
            for r in self.conn.execute(
                    "SELECT m.id, m.numbering, NOT EXISTS(SELECT 1 FROM files f WHERE f.media_id=m.id "
                    "AND f.episode IS NOT NULL AND f.season != 0 AND f.absolute = 0) AS abs "
                    "FROM media m WHERE m.kind != 'movie' AND m.available = 1").fetchall():
                numbering = "absolute" if r["abs"] else "seasons"
                if numbering != r["numbering"]:
                    self.conn.execute("UPDATE media SET numbering=?, meta_status='pending' WHERE id=?",
                                      (numbering, r["id"]))
            # items that lost all their files and carry no watch history are just noise
            self.conn.execute(
                "DELETE FROM media WHERE available = 0 AND watched = 0 AND COALESCE(position, 0) = 0 "
                "AND NOT EXISTS(SELECT 1 FROM episodes e WHERE e.media_id = media.id "
                "AND (e.watched = 1 OR e.position > 0))")

    def pending_metadata(self) -> list[dict]:
        rows = self.conn.execute(
            "SELECT * FROM media WHERE meta_status='pending' AND available=1 ORDER BY id").fetchall()
        return [_row(r) for r in rows]

    def reset_metadata(self, media_id: int | None = None) -> None:
        """Queue a metadata refresh: one title (also unlocking a manual match) or every unlocked title."""
        with self.write_lock, self.conn:
            if media_id is None:
                self.conn.execute("UPDATE media SET meta_status='pending' WHERE match_locked=0")
            else:
                self.conn.execute("UPDATE media SET meta_status='pending', match_locked=0 WHERE id=?", (media_id,))

    # ------------------------------------------------------------------ metadata
    def apply_metadata(self, media_id: int, meta: dict, episodes: list[dict] | None = None,
                       lock: bool = False) -> None:
        cols = ["title", "year", "overview", "genres", "cast_list", "director", "rating", "runtime",
                "poster", "backdrop", "logo", "ext_source", "ext_id", "imdb_id", "total_episodes", "status"]
        vals = []
        sets = []
        for c in cols:
            if c in meta and meta[c] is not None:
                v = meta[c]
                if c in ("genres", "cast_list"):
                    v = json.dumps(v)
                sets.append(f"{c}=?")
                vals.append(v)
        sets.append("meta_status='ok'")
        if lock:
            sets.append("match_locked=1")
        with self.write_lock, self.conn:
            self.conn.execute(f"UPDATE media SET {', '.join(sets)} WHERE id=?", (*vals, media_id))
            if episodes is not None:
                # clear old metadata for episodes we no longer know about, keep files/watch state
                self.conn.execute(
                    "UPDATE episodes SET title=NULL, overview=NULL, still=NULL, air_date=NULL WHERE media_id=?",
                    (media_id,))
                for ep in episodes:
                    self.conn.execute(
                        "INSERT INTO episodes(media_id,season,number,title,overview,still,air_date,runtime) "
                        "VALUES(?,?,?,?,?,?,?,?) ON CONFLICT(media_id,season,number) DO UPDATE SET "
                        "title=excluded.title, overview=excluded.overview, still=excluded.still, "
                        "air_date=excluded.air_date, runtime=excluded.runtime",
                        (media_id, ep["season"], ep["number"], ep.get("title"), ep.get("overview"),
                         ep.get("still"), ep.get("air_date"), ep.get("runtime")))
                # drop metadata-only rows that are no longer in the guide and have no file / watch state
                known = {(e["season"], e["number"]) for e in episodes}
                for r in self.conn.execute(
                        "SELECT id, season, number FROM episodes WHERE media_id=? AND file_path IS NULL "
                        "AND watched=0 AND position=0", (media_id,)).fetchall():
                    if (r["season"], r["number"]) not in known:
                        self.conn.execute("DELETE FROM episodes WHERE id=?", (r["id"],))

    def mark_meta_failed(self, media_id: int) -> None:
        with self.write_lock, self.conn:
            self.conn.execute("UPDATE media SET meta_status='failed' WHERE id=?", (media_id,))

    def set_kind(self, media_id: int, kind: str) -> None:
        with self.write_lock, self.conn:
            self.conn.execute("UPDATE media SET kind=? WHERE id=?", (kind, media_id))

    def set_prefs(self, media_id: int, prefs: dict) -> None:
        with self.write_lock, self.conn:
            self.conn.execute("UPDATE media SET prefs=? WHERE id=?", (json.dumps(prefs), media_id))

    # ------------------------------------------------------------------ reading
    def media(self, media_id: int) -> dict | None:
        return _row(self.conn.execute("SELECT * FROM media WHERE id=?", (media_id,)).fetchone())

    def movie_file(self, media_id: int) -> str | None:
        r = self.conn.execute("SELECT path FROM files WHERE media_id=? ORDER BY size DESC LIMIT 1",
                              (media_id,)).fetchone()
        return r["path"] if r else None

    def episodes(self, media_id: int) -> list[dict]:
        rows = self.conn.execute(
            "SELECT * FROM episodes WHERE media_id=? ORDER BY season, number", (media_id,)).fetchall()
        return [dict(r) for r in rows]

    def episode(self, episode_id: int) -> dict | None:
        r = self.conn.execute("SELECT * FROM episodes WHERE id=?", (episode_id,)).fetchone()
        return dict(r) if r else None

    def library(self, kind: str = "all", status: str = "all", search: str = "", sort: str = "title") -> list[dict]:
        where = ["m.available=1"]
        args: list = []
        if kind in ("movie", "show", "anime"):
            where.append("m.kind=?")
            args.append(kind)
        if search:
            where.append("(m.title LIKE ? OR m.parsed_title LIKE ?)")
            args += [f"%{search}%", f"%{search}%"]
        order = {
            "title": "m.title COLLATE NOCASE",
            "added": "m.added_at DESC",
            "year": "m.year DESC",
            "rating": "m.rating DESC",
            "recent": "COALESCE(lp, 0) DESC",
        }.get(sort, "m.title COLLATE NOCASE")
        # per-series episode aggregates (specials, season 0, don't count toward progress)
        sql = f"""
            WITH ep AS (
              SELECT e.media_id,
                SUM(e.file_path IS NOT NULL) AS owned,
                SUM(e.file_path IS NOT NULL AND e.watched = 1) AS owned_watched,
                COUNT(*) AS known_eps,
                SUM(e.watched = 0 AND e.position > 0) AS eps_in_progress,
                SUM(CASE WHEN e.file_path IS NOT NULL AND e.watched = 0
                    THEN MAX({_EP_LENGTH} - e.position, 0) ELSE 0 END) AS left_s,
                SUM(CASE WHEN e.watched = 1 THEN {_EP_LENGTH} ELSE 0 END) AS watched_s,
                MAX(e.last_played) AS lp
              FROM episodes e JOIN media s ON s.id = e.media_id
              WHERE e.season != 0
              GROUP BY e.media_id)
            SELECT m.*, COALESCE(ep.owned, 0) AS owned, COALESCE(ep.owned_watched, 0) AS owned_watched,
                   COALESCE(ep.known_eps, 0) AS known_eps, COALESCE(ep.eps_in_progress, 0) AS eps_in_progress,
                   COALESCE(ep.left_s, 0) AS left_s, COALESCE(ep.watched_s, 0) AS watched_s,
                   CASE WHEN m.kind = 'movie' THEN m.last_played ELSE ep.lp END AS lp
            FROM media m LEFT JOIN ep ON ep.media_id = m.id
            WHERE {' AND '.join(where)} ORDER BY {order}
        """
        out = []
        for r in self.conn.execute(sql, args).fetchall():
            d = _row(r)
            if d["kind"] == "movie":
                length = d["duration"] or (d["runtime"] or 0) * 60
                d["left_s"] = 0 if d["watched"] else max(length - (d["position"] or 0), 0)
                d["watched_s"] = length if d["watched"] else 0
            d["state"] = self._state(d)
            d["progress"] = self._progress_fraction(d)
            out.append(d)
        if status in ("watched", "in_progress"):
            out = [d for d in out if d["state"] == status]
        elif status == "unwatched":
            out = [d for d in out if d["state"] != "watched"]
        return out

    @staticmethod
    def _state(d: dict) -> str:
        if d["kind"] == "movie":
            if d["watched"]:
                return "watched"
            return "in_progress" if d["position"] and d["position"] > 0 else "unwatched"
        owned, ow = d["owned"], d["owned_watched"]
        if owned and ow >= owned:
            return "watched"
        return "in_progress" if ow or d["eps_in_progress"] else "unwatched"

    @staticmethod
    def _progress_fraction(d: dict) -> float:
        if d["kind"] == "movie":
            if d["watched"]:
                return 1.0
            return (d["position"] / d["duration"]) if d["duration"] else 0.0
        return d["owned_watched"] / d["owned"] if d["owned"] else 0.0

    def stats(self, kind: str = "all") -> dict:
        """Watch statistics for a category page (durations in seconds; estimates where
        a file was never played and only the metadata runtime is known)."""
        lib = self.library(kind=kind)
        movies = [d for d in lib if d["kind"] == "movie"]
        series = [d for d in lib if d["kind"] != "movie"]
        return {
            "titles": len(lib),
            "movies": len(movies), "movies_watched": sum(d["watched"] for d in movies),
            "series": len(series), "series_done": sum(d["state"] == "watched" for d in series),
            "episodes": sum(d["owned"] for d in series),
            "episodes_watched": sum(d["owned_watched"] for d in series),
            "in_progress": sum(d["state"] == "in_progress" for d in lib),
            "left_s": sum(d["left_s"] for d in lib),
            "watched_s": sum(d["watched_s"] for d in lib),
        }

    def counts(self) -> dict:
        r = self.conn.execute(
            "SELECT SUM(kind='movie') mv, SUM(kind='show') sh, SUM(kind='anime') an FROM media WHERE available=1"
        ).fetchone()
        return {k: (r[k] or 0) for k in ("mv", "sh", "an")}

    # ------------------------------------------------------------------ playback targets
    def next_episode(self, episode_id: int) -> dict | None:
        ep = self.episode(episode_id)
        if not ep:
            return None
        r = self.conn.execute(
            "SELECT * FROM episodes WHERE media_id=? AND (season>? OR (season=? AND number>?)) "
            "AND file_path IS NOT NULL ORDER BY season, number LIMIT 1",
            (ep["media_id"], ep["season"], ep["season"], ep["number"])).fetchone()
        return dict(r) if r else None

    def previous_episode(self, episode_id: int) -> dict | None:
        ep = self.episode(episode_id)
        if not ep:
            return None
        r = self.conn.execute(
            "SELECT * FROM episodes WHERE media_id=? AND (season<? OR (season=? AND number<?)) "
            "AND file_path IS NOT NULL ORDER BY season DESC, number DESC LIMIT 1",
            (ep["media_id"], ep["season"], ep["season"], ep["number"])).fetchone()
        return dict(r) if r else None

    def resume_episode(self, media_id: int) -> dict | None:
        """In-progress episode if any, else the next owned unwatched episode after the
        most recently played one, else the first owned unwatched one."""
        r = self.conn.execute(
            "SELECT * FROM episodes WHERE media_id=? AND file_path IS NOT NULL AND watched=0 AND position>0 "
            "ORDER BY last_played DESC LIMIT 1", (media_id,)).fetchone()
        if r:
            return dict(r)
        last = self.conn.execute(
            "SELECT * FROM episodes WHERE media_id=? AND last_played IS NOT NULL ORDER BY last_played DESC LIMIT 1",
            (media_id,)).fetchone()
        if last:
            r = self.conn.execute(
                "SELECT * FROM episodes WHERE media_id=? AND file_path IS NOT NULL AND watched=0 "
                "AND (season>? OR (season=? AND number>?)) ORDER BY season, number LIMIT 1",
                (media_id, last["season"], last["season"], last["number"])).fetchone()
            if r:
                return dict(r)
        r = self.conn.execute(  # specials (season 0) only after the regular episodes
            "SELECT * FROM episodes WHERE media_id=? AND file_path IS NOT NULL AND watched=0 "
            "ORDER BY season = 0, season, number LIMIT 1", (media_id,)).fetchone()
        return dict(r) if r else None

    def continue_watching(self, limit: int = 20) -> list[dict]:
        """Movies in progress + one entry per series (in-progress or up-next episode)."""
        items: list[dict] = []
        for r in self.conn.execute(
                "SELECT * FROM media WHERE kind='movie' AND available=1 AND watched=0 AND position>0 "
                "AND last_played IS NOT NULL").fetchall():
            d = _row(r)
            items.append({"media": d, "episode": None, "last_played": d["last_played"],
                          "progress": d["position"] / d["duration"] if d["duration"] else 0.0})
        for r in self.conn.execute(
                "SELECT media_id, MAX(last_played) lp FROM episodes WHERE last_played IS NOT NULL "
                "GROUP BY media_id").fetchall():
            m = self.media(r["media_id"])
            if not m or not m["available"]:
                continue
            ep = self.resume_episode(r["media_id"])
            if not ep:
                continue
            items.append({"media": m, "episode": ep, "last_played": r["lp"],
                          "progress": ep["position"] / ep["duration"] if ep["duration"] else 0.0})
        items.sort(key=lambda x: x["last_played"] or 0, reverse=True)
        return items[:limit]

    # ------------------------------------------------------------------ watch state
    def set_progress(self, *, media_id: int | None = None, episode_id: int | None = None,
                     position: float, duration: float, threshold: float = 0.9) -> bool:
        """Store playback position; returns True if this crossed into 'watched'."""
        table, ident = ("episodes", episode_id) if episode_id is not None else ("media", media_id)
        now = time.time()
        finished = duration > 0 and position / duration >= threshold
        with self.write_lock, self.conn:
            prev = self.conn.execute(f"SELECT watched FROM {table} WHERE id=?", (ident,)).fetchone()
            if finished:
                self.conn.execute(
                    f"UPDATE {table} SET watched=1, position=0, duration=?, last_played=? WHERE id=?",
                    (duration, now, ident))
            else:
                self.conn.execute(
                    f"UPDATE {table} SET position=?, duration=?, last_played=? WHERE id=?",
                    (position, duration, now, ident))
        return bool(finished and prev is not None and not prev["watched"])

    def set_watched(self, *, media_id: int | None = None, episode_id: int | None = None,
                    watched: bool = True, owned_only: bool = False) -> None:
        w = 1 if watched else 0
        with self.write_lock, self.conn:
            if episode_id is not None:
                self.conn.execute("UPDATE episodes SET watched=?, position=0 WHERE id=?", (w, episode_id))
                return
            m = self.conn.execute("SELECT kind FROM media WHERE id=?", (media_id,)).fetchone()
            if m is None:
                return
            if m["kind"] == "movie":
                self.conn.execute("UPDATE media SET watched=?, position=0 WHERE id=?", (w, media_id))
                return
            sql = "UPDATE episodes SET watched=?, position=0 WHERE media_id=?"
            if owned_only:
                sql += " AND file_path IS NOT NULL"
            self.conn.execute(sql, (w, media_id))
