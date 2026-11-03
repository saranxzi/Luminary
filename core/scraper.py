"""Keyless metadata providers.

Movies : Cinemeta (IMDb-backed, no key) - optional TMDB if a key is configured.
Shows  : TVMaze (no key).
Anime  : AniList GraphQL for show info + TVMaze for per-episode titles.
"""
from __future__ import annotations

import html
import re
import threading
import time
from urllib.parse import quote

import requests

from .parser import normalize_key

UA = {"User-Agent": "Luminary/1.0 (local media library)"}
CINEMETA = "https://v3-cinemeta.strem.io"
TVMAZE = "https://api.tvmaze.com"
ANILIST = "https://graphql.anilist.co"
TMDB = "https://api.themoviedb.org/3"
TMDB_IMG = "https://image.tmdb.org/t/p"

_session = requests.Session()
_session.headers.update(UA)
_anilist_lock = threading.Lock()
_anilist_last = 0.0


class ScrapeError(Exception):
    pass


def _get(url: str, **kw):
    for attempt in range(3):
        try:
            r = _session.get(url, timeout=15, **kw)
            if r.status_code == 429:
                time.sleep(2 + attempt * 2)
                continue
            if r.status_code == 404:
                return None
            r.raise_for_status()
            return r.json()
        except (requests.RequestException, ValueError):
            if attempt == 2:
                raise ScrapeError(f"request failed: {url}")
            time.sleep(1)
    return None


def _anilist(query: str, variables: dict):
    global _anilist_last
    with _anilist_lock:  # AniList allows ~30 req/min when degraded; stay polite
        wait = 0.8 - (time.time() - _anilist_last)
        if wait > 0:
            time.sleep(wait)
        _anilist_last = time.time()
    for attempt in range(3):
        try:
            r = _session.post(ANILIST, json={"query": query, "variables": variables}, timeout=15)
            if r.status_code == 429:
                time.sleep(int(r.headers.get("Retry-After", 5)))
                continue
            r.raise_for_status()
            return r.json().get("data") or {}
        except (requests.RequestException, ValueError):
            if attempt == 2:
                raise ScrapeError("AniList request failed")
            time.sleep(1)
    return {}


def strip_html(s: str | None) -> str | None:
    if not s:
        return s
    s = re.sub(r"<br\s*/?>", "\n", s, flags=re.I)
    s = re.sub(r"<[^>]+>", "", s)
    s = html.unescape(s)
    s = re.sub(r"\(Source:[^)]*\)\s*$", "", s.strip()).strip()
    return re.sub(r"\n{3,}", "\n\n", s)


def _int(s) -> int | None:
    try:
        m = re.search(r"\d+", str(s))
        return int(m.group(0)) if m else None
    except (TypeError, ValueError):
        return None


def _float(s) -> float | None:
    try:
        return float(s)
    except (TypeError, ValueError):
        return None


def _pick(cands: list[dict], title: str, year: int | None) -> dict | None:
    if not cands:
        return None
    key = normalize_key(title)

    def score(c):
        s = 0
        ck = normalize_key(c.get("title") or "")
        if ck == key:
            s += 10
        elif key and (key in ck or ck in key):
            s += 4
        for alt in c.get("alt_titles") or []:
            if normalize_key(alt) == key:
                s += 8
                break
        if year and c.get("year"):
            d = abs(int(c["year"]) - year)
            s += 6 if d == 0 else (3 if d == 1 else -3)
        return s

    ranked = sorted(enumerate(cands), key=lambda ic: (-score(ic[1]), ic[0]))
    return ranked[0][1]


# ====================================================================== movies
def search_movies(query: str, tmdb_key: str = "") -> list[dict]:
    out = []
    if tmdb_key:
        try:
            data = _get(f"{TMDB}/search/movie", params={"api_key": tmdb_key, "query": query}) or {}
            for m in data.get("results", [])[:15]:
                out.append({"source": "tmdb", "id": str(m["id"]), "title": m.get("title"),
                            "year": _int((m.get("release_date") or "")[:4]),
                            "poster": f"{TMDB_IMG}/w342{m['poster_path']}" if m.get("poster_path") else None,
                            "overview": m.get("overview")})
        except ScrapeError:
            pass
    if not out:
        data = _get(f"{CINEMETA}/catalog/movie/top/search={quote(query)}.json") or {}
        for m in data.get("metas", [])[:15]:
            out.append({"source": "cinemeta", "id": m["id"], "title": m.get("name"),
                        "year": _int(m.get("releaseInfo")),
                        "poster": _metahub(m.get("poster"), "poster", "medium"), "overview": None})
    return out


def _metahub(url: str | None, kind: str, size: str) -> str | None:
    if not url:
        return None
    return re.sub(rf"/{kind}/(small|medium|large)/", f"/{kind}/{size}/", url)


def fetch_movie(source: str, ext_id: str, tmdb_key: str = "") -> dict:
    if source == "tmdb":
        m = _get(f"{TMDB}/movie/{ext_id}", params={"api_key": tmdb_key, "append_to_response": "credits"})
        if not m:
            raise ScrapeError("not found")
        crew = (m.get("credits") or {}).get("crew") or []
        return {
            "title": m.get("title"), "year": _int((m.get("release_date") or "")[:4]),
            "overview": m.get("overview"), "genres": [g["name"] for g in m.get("genres", [])],
            "cast_list": [c["name"] for c in ((m.get("credits") or {}).get("cast") or [])[:8]],
            "director": ", ".join(c["name"] for c in crew if c.get("job") == "Director") or None,
            "rating": _float(m.get("vote_average")), "runtime": m.get("runtime"),
            "poster": f"{TMDB_IMG}/w500{m['poster_path']}" if m.get("poster_path") else None,
            "backdrop": f"{TMDB_IMG}/w1280{m['backdrop_path']}" if m.get("backdrop_path") else None,
            "ext_source": "tmdb", "ext_id": str(ext_id), "imdb_id": m.get("imdb_id"),
        }
    data = _get(f"{CINEMETA}/meta/movie/{ext_id}.json") or {}
    m = data.get("meta")
    if not m:
        raise ScrapeError("not found")
    return {
        "title": m.get("name"), "year": _int(m.get("releaseInfo") or m.get("year")),
        "overview": m.get("description"), "genres": m.get("genres") or m.get("genre") or [],
        "cast_list": (m.get("cast") or [])[:8],
        "director": ", ".join(m.get("director") or []) or None,
        "rating": _float(m.get("imdbRating")), "runtime": _int(m.get("runtime")),
        "poster": _metahub(m.get("poster"), "poster", "medium"),
        "backdrop": _metahub(m.get("background"), "background", "large"),
        "logo": m.get("logo"),
        "ext_source": "cinemeta", "ext_id": m.get("id") or ext_id, "imdb_id": m.get("imdb_id"),
    }


# ====================================================================== tv (TVMaze)
def search_shows(query: str) -> list[dict]:
    data = _get(f"{TVMAZE}/search/shows", params={"q": query}) or []
    out = []
    for hit in data[:15]:
        s = hit["show"]
        out.append({"source": "tvmaze", "id": str(s["id"]), "title": s.get("name"),
                    "year": _int((s.get("premiered") or "")[:4]),
                    "poster": (s.get("image") or {}).get("medium"),
                    "overview": strip_html(s.get("summary"))})
    return out


def tvmaze_episodes(show_id: str, absolute: bool) -> list[dict]:
    data = _get(f"{TVMAZE}/shows/{show_id}/episodes") or []
    eps = [e for e in data if e.get("number") is not None]
    eps.sort(key=lambda e: (e.get("season") or 0, e.get("number") or 0))
    seasons = sorted({e["season"] for e in eps})
    out = []
    for idx, e in enumerate(eps, start=1):
        if absolute:
            season, number = 1, idx
        else:
            # TVMaze sometimes uses years as season numbers; renumber 1..n in that case
            season = seasons.index(e["season"]) + 1 if seasons and seasons[0] > 100 else e["season"]
            number = e["number"]
        out.append({"season": season, "number": number, "title": e.get("name"),
                    "overview": strip_html(e.get("summary")),
                    "still": (e.get("image") or {}).get("original") or (e.get("image") or {}).get("medium"),
                    "air_date": e.get("airdate"), "runtime": e.get("runtime")})
    return out


def _tvmaze_backdrop(show_id: str) -> str | None:
    try:
        imgs = _get(f"{TVMAZE}/shows/{show_id}/images") or []
    except ScrapeError:
        return None
    bgs = [i for i in imgs if i.get("type") == "background"]
    bgs.sort(key=lambda i: (not i.get("main"),))
    if bgs:
        return bgs[0]["resolutions"]["original"]["url"]
    return None


def fetch_show(show_id: str, absolute: bool = False) -> tuple[dict, list[dict]]:
    s = _get(f"{TVMAZE}/shows/{show_id}")
    if not s:
        raise ScrapeError("not found")
    meta = {
        "title": s.get("name"), "year": _int((s.get("premiered") or "")[:4]),
        "overview": strip_html(s.get("summary")), "genres": s.get("genres") or [],
        "rating": _float((s.get("rating") or {}).get("average")),
        "runtime": s.get("averageRuntime") or s.get("runtime"),
        "poster": (s.get("image") or {}).get("original"),
        "backdrop": _tvmaze_backdrop(show_id),
        "ext_source": "tvmaze", "ext_id": str(show_id),
        "imdb_id": (s.get("externals") or {}).get("imdb"), "status": s.get("status"),
    }
    eps = tvmaze_episodes(show_id, absolute)
    meta["total_episodes"] = len(eps)
    return meta, eps


# ====================================================================== anime (AniList)
_ANI_FIELDS = """
id idMal format status episodes duration averageScore genres description(asHtml:false)
title { romaji english native } synonyms
startDate { year } coverImage { extraLarge large } bannerImage
"""


def search_anime(query: str) -> list[dict]:
    q = "query($s:String){Page(perPage:15){media(search:$s,type:ANIME,sort:SEARCH_MATCH){" + _ANI_FIELDS + "}}}"
    data = _anilist(q, {"s": query})
    out = []
    for m in (data.get("Page") or {}).get("media") or []:
        t = m.get("title") or {}
        out.append({"source": "anilist", "id": str(m["id"]),
                    "title": t.get("english") or t.get("romaji"),
                    "alt_titles": [x for x in (t.get("romaji"), t.get("english"), *(m.get("synonyms") or [])) if x],
                    "year": (m.get("startDate") or {}).get("year"),
                    "poster": (m.get("coverImage") or {}).get("large"),
                    "overview": strip_html(m.get("description")), "_raw": m})
    return out


def fetch_anime(anilist_id: str, absolute: bool = True, raw: dict | None = None) -> tuple[dict, list[dict] | None]:
    m = raw
    if m is None:
        q = "query($id:Int){Media(id:$id,type:ANIME){" + _ANI_FIELDS + "}}"
        m = (_anilist(q, {"id": int(anilist_id)}) or {}).get("Media")
    if not m:
        raise ScrapeError("not found")
    t = m.get("title") or {}
    title = t.get("english") or t.get("romaji")
    year = (m.get("startDate") or {}).get("year")
    meta = {
        "title": title, "year": year, "overview": strip_html(m.get("description")),
        "genres": m.get("genres") or [],
        "rating": (m["averageScore"] / 10.0) if m.get("averageScore") else None,
        "runtime": m.get("duration"),
        "poster": (m.get("coverImage") or {}).get("extraLarge") or (m.get("coverImage") or {}).get("large"),
        "backdrop": m.get("bannerImage"),
        "ext_source": "anilist", "ext_id": str(m["id"]), "total_episodes": m.get("episodes"),
        "status": (m.get("status") or "").replace("_", " ").title() or None,
    }
    # episode titles from TVMaze, matched by title + year and sanity-checked on count
    episodes = None
    names = [x for x in (t.get("english"), t.get("romaji")) if x]
    for name in names:
        try:
            cands = search_shows(name)
        except ScrapeError:
            break
        best = _pick(cands, name, year)
        if not best:
            continue
        if year and best.get("year") and abs(best["year"] - year) > 1:
            continue
        try:
            eps = tvmaze_episodes(best["id"], absolute)
        except ScrapeError:
            break
        if m.get("episodes") and absolute and abs(len(eps) - m["episodes"]) > max(3, m["episodes"] * 0.1):
            continue
        # TVMaze lists the broadcast slot (30m); AniList's duration is the real runtime (24m)
        episodes = [{**e, "runtime": None} for e in eps] if meta["runtime"] else eps
        # TVMaze backgrounds are full 16:9 art; AniList banners are thin strips
        meta["backdrop"] = _tvmaze_backdrop(best["id"]) or meta["backdrop"]
        break
    if episodes is None and m.get("episodes") and absolute:
        episodes = [{"season": 1, "number": n} for n in range(1, m["episodes"] + 1)]
    return meta, episodes


# ====================================================================== dispatch
def search(kind: str, query: str, tmdb_key: str = "") -> list[dict]:
    if kind == "movie":
        return search_movies(query, tmdb_key)
    if kind == "anime":
        return search_anime(query)
    return search_shows(query)


def fetch(kind: str, cand: dict, numbering: str = "seasons", tmdb_key: str = "") -> tuple[dict, list[dict] | None]:
    absolute = numbering == "absolute"
    if kind == "movie":
        return fetch_movie(cand["source"], cand["id"], tmdb_key), None
    if cand["source"] == "anilist":
        return fetch_anime(cand["id"], absolute, cand.get("_raw"))
    return fetch_show(cand["id"], absolute)


def auto_match(media: dict, tmdb_key: str = "") -> tuple[dict, list[dict] | None] | None:
    title, kind = media["parsed_title"], media["kind"]
    year = media.get("parsed_year") or media.get("year")
    cands = search(kind, title, tmdb_key)
    best = _pick(cands, title, year)
    if best is None and kind == "anime":  # fall back to TVMaze
        best = _pick(search_shows(title), title, year)
    if best is None:
        return None
    meta, eps = fetch(kind, best, media.get("numbering") or "seasons", tmdb_key)
    try:
        if year and meta.get("year") and abs(int(meta["year"]) - int(year)) == 1:
            meta["year"] = year  # release-name year usually matches the original premiere
    except (TypeError, ValueError):
        pass
    return meta, eps
