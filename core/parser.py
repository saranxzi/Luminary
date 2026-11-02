"""Path → (kind, title, season, episode) resolution for movies, TV shows and anime.

Modelled on Kodi's ``tvshowmatching`` and Jellyfin's Emby.Naming:

* an ordered list of episode rules — strict patterns (``S01E02``, ``1x02``,
  ``Season 1 Episode 2``) first, optimistic ones (``- 07``, bare ``07``) last;
* seasons can come from the filename or from ``Season N`` / ``S01`` / ``Specials`` folders;
* extras (trailers, featurettes, behind the scenes, samples…) are skipped;
* the user's folder category (``force_kind``) always beats guessing.

Only the path is used — no network, no third-party parser.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import PurePath

KIND_MOVIE, KIND_SHOW, KIND_ANIME = "movie", "show", "anime"
SERIES_KINDS = (KIND_SHOW, KIND_ANIME)

_CATEGORY_DIRS = {
    "movies": KIND_MOVIE, "movie": KIND_MOVIE, "films": KIND_MOVIE, "film": KIND_MOVIE,
    "shows": KIND_SHOW, "tv": KIND_SHOW, "tv shows": KIND_SHOW, "tvshows": KIND_SHOW, "series": KIND_SHOW,
    "anime": KIND_ANIME, "animes": KIND_ANIME,
}
_EXTRAS_DIRS = {
    "extras", "extra", "featurettes", "featurette", "behind the scenes", "deleted scenes", "interviews",
    "scenes", "shorts", "trailers", "trailer", "samples", "sample", "other", "backdrops", "theme-music",
    "clips", "bonus",
}
_EXTRAS_SUFFIX_RE = re.compile(
    r"[-_. ](?:trailer|sample|featurette|behindthescenes|deleted|deletedscene|interview|scene|short|other|extra)$",
    re.I)

_JUNK = [
    r"\d{3,4}[pi]", r"[248]k", r"uhd", r"hdr10\+?", r"hdr", r"dv", r"dovi", r"sdr",
    r"[xh]\.?26[45]", r"hevc", r"avc", r"av1", r"xvid", r"divx", r"vp9",
    r"1[02][ ._-]?bits?", r"8[ ._-]?bits?", r"hi10p?",
    r"flac", r"aac(?:[ ._]?\d\.\d)?", r"e?-?ac-?3", r"ddp?\+?(?:[ ._]?\d\.\d)?", r"dts(?:-?hd)?(?:[ ._]?ma)?",
    r"truehd", r"atmos", r"opus", r"mp3", r"lpcm", r"\d\.\d",
    r"blu-?ray", r"bd(?:rip|remux)?", r"brrip", r"web-?dl", r"web-?rip", r"web", r"hdtv", r"hdrip",
    r"dvd(?:rip|scr)?", r"remux", r"amzn", r"nf", r"dsnp", r"hmax", r"atvp", r"cr",
    r"remastered", r"extended", r"unrated", r"uncut", r"directors?[ ._]?cut", r"proper", r"repack", r"limited",
    r"imax", r"multi", r"dual(?:[ ._-]?audio)?", r"subbed", r"dubbed", r"internal", r"complete",
]
_JUNK_RE = re.compile(r"(?<![a-z0-9])(?:" + "|".join(_JUNK) + r")(?![a-z0-9])", re.I)
_BRACKETS_RE = re.compile(r"\[[^\]]*\]|\{[^}]*\}")
_BRACKET_EP_RE = re.compile(r"\[(\d{1,4})(?:v\d)?\]")       # "[Group] Title [05][1080p]"
_GROUP_TAG_RE = re.compile(r"^\s*\[[^\]]+\]")               # leading release-group tag (anime style)
_PAREN_YEAR_RE = re.compile(r"\((19\d{2}|20\d{2})\)")
_YEAR_RE = re.compile(r"(?<![0-9])(19[2-9]\d|20[0-4]\d)(?![0-9])")
_TRAILING_GROUP_RE = re.compile(r"-[A-Za-z0-9]+$")          # "...x265-GalaxyRG265"

_SEASON_DIR_RE = re.compile(
    r"(?<![a-z0-9])(?:season|series|saison|staffel|temporada)[ ._-]*(\d{1,3})(?![0-9])|^s(\d{1,3})(?![0-9a-z])", re.I)
_SPECIALS_DIR_RE = re.compile(r"^(?:specials?|ova|ovas|oad|omake)$", re.I)

_NUM_END = r"(?:v\d)?(?![0-9])"  # optional "v2" revision suffix, then no more digits

# ---- episode rules: (name, regex, gives_season). Order matters: strict → optimistic.
_RULES: list[tuple[str, re.Pattern, bool]] = [
    # S01E02, S01 E02, S01.E02, S01E02E03, S01E02-E03, S01E02-03
    ("sxe", re.compile(r"(?<![a-z0-9])s(\d{1,3})[ ._-]*e(\d{1,4})(?:(?:[ ._]*-[ ._]*e?|[ ._]*e)(\d{1,4}))*"
                       + _NUM_END, re.I), True),
    # Season 1 Episode 2 / Season 1, Ep 2
    ("words", re.compile(r"season[ ._-]*(\d{1,3})[ ._,-]*(?:episode|ep)[ ._-]*(\d{1,4})" + _NUM_END, re.I), True),
    # 1x02, 1x02-1x03
    ("nxn", re.compile(r"(?<![a-z0-9])(\d{1,2})x(\d{2,3})(?:[ ._]*-[ ._]*(?:\d{1,2}x)?(\d{2,3}))?" + _NUM_END,
                       re.I), True),
    # anime: "Title S2 - 05", "Title 2nd Season - 05"
    ("anime_season", re.compile(r"(?<![a-z0-9])(?:s(\d{1,2})|(\d{1,2})(?:st|nd|rd|th)[ ._]+season)[ ._]+-[ ._]+(\d{1,4})"
                                + _NUM_END, re.I), True),
    # Episode 5, Ep05, Ep.5, E05, E05-E06
    ("ep", re.compile(r"(?<![a-z0-9])(?:episode|ep|e)[ ._-]*(\d{1,4})(?:[ ._]*-[ ._]*(?:episode|ep|e)?[ ._]*(\d{1,4}))?"
                      + _NUM_END, re.I), False),
    # optimistic: "Title - 07", "Title - 07 - Name", "Title - 07v2"
    ("dash", re.compile(r"[ ._]-[ ._]*(\d{1,4})" + _NUM_END + r"(?:[ ._]*-[ ._]*(\d{1,4})" + _NUM_END + r")?"), False),
    # optimistic: leading "07 - Name" / "07.mkv" or bare "Bleach 001"
    ("bare", re.compile(r"(?<![a-z0-9.])(\d{1,4})" + _NUM_END + r"(?![a-z])", re.I), False),
]
_STRICT = {"sxe", "words", "nxn", "anime_season", "ep"}


@dataclass(frozen=True)
class ParsedFile:
    kind: str
    title: str
    year: int | None = None
    season: int | None = None        # 0 = specials; None for movies
    episode: int | None = None       # None for movies and unnumbered extras in a series
    episode_end: int | None = None   # multi-episode files (S01E01-E02)
    absolute: bool = False           # number counts across the whole series (anime-style)
    show_folder: str | None = None   # folder that groups the series (for "open folder")


@dataclass(frozen=True)
class _Episode:
    season: int | None
    episode: int
    episode_end: int | None
    start: int           # where the episode marker begins (title is what precedes it)
    rule: str


# ----------------------------------------------------------------------------- text helpers
def _seps(s: str) -> str:
    """Underscores and dots act as word separators in release names ("Mr. Robot" stays readable)."""
    s = s.replace("_", " ")
    if s.count(".") >= 2 or (" " not in s and "." in s):
        s = re.sub(r"(?<!\s[A-Z])\.(?!\s)", " ", s)
    return s


def _blank_junk(s: str) -> str:
    """Replace quality tags with spaces of equal length so match offsets stay valid."""
    return _JUNK_RE.sub(lambda m: " " * len(m.group(0)), s)


def clean_title(raw: str) -> str:
    s = _BRACKETS_RE.sub(" ", raw)
    s = _JUNK_RE.sub(" ", _seps(s))
    s = re.sub(r"\(\s*\)|[()]", " ", s)
    return re.sub(r"\s{2,}", " ", s).strip(" -._,")


def normalize_key(title: str) -> str:
    return re.sub(r"[^a-z0-9]+", "", title.lower())


def _is_year(num: str) -> bool:
    return len(num) == 4 and _YEAR_RE.fullmatch(num) is not None


def folder_title(name: str) -> tuple[str, int | None]:
    """'Bleach [BD] [1080p]' -> ('Bleach', None); '[2004] [Season 1] Bleach' -> ('Bleach', 2004)."""
    m = re.search(r"[\[(](19\d{2}|20\d{2})[\])]", name) or _YEAR_RE.search(name)
    year = int(m.group(1)) if m else None
    s = _SEASON_DIR_RE.sub(" ", _BRACKETS_RE.sub(" ", name))
    s = _YEAR_RE.sub(" ", clean_title(s))
    return re.sub(r"\s{2,}", " ", s).strip(" -._"), year


def _season_of_folder(name: str) -> int | None:
    if _SPECIALS_DIR_RE.match(name.strip()):
        return 0
    m = _SEASON_DIR_RE.search(name)
    return int(m.group(1) or m.group(2)) if m else None


# ----------------------------------------------------------------------------- episode detection
def _prepare(stem: str) -> str:
    s = _BRACKET_EP_RE.sub(lambda m: f" - {m.group(1)} ", stem)   # [05] -> " - 05 "
    s = _BRACKETS_RE.sub(lambda m: " " * len(m.group(0)), s)
    return _blank_junk(_seps(s))


def find_episode(stem: str, optimistic: bool, show_kind: str | None = None,
                 folder_season: int | None = None) -> _Episode | None:
    text = _prepare(stem)
    for name, rx, gives_season in _RULES:
        if name not in _STRICT and not optimistic:
            break
        for m in rx.finditer(text):
            g = [x for x in m.groups()]
            if name == "anime_season":
                season, ep, end = int(g[0] or g[1]), int(g[2]), None
            elif gives_season:
                season, ep = int(g[0]), int(g[1])
                end = int(g[2]) if len(g) > 2 and g[2] else None
            else:
                if _is_year(g[0]):
                    continue
                season, ep, end = None, int(g[0]), (int(g[1]) if len(g) > 1 and g[1] else None)
                if name == "bare" and show_kind == KIND_SHOW and folder_season and len(g[0]) in (3, 4) \
                        and g[0].startswith(str(folder_season)) and len(g[0]) - len(str(folder_season)) == 2:
                    season, ep = folder_season, int(g[0][len(str(folder_season)):])  # Kodi "101" style
            if end is not None and end <= ep:
                end = None
            return _Episode(season, ep, end, m.start(), name)
    return None


# ----------------------------------------------------------------------------- resolution
def _rel_parts(p: PurePath, root: str | None) -> list[str]:
    if root:
        try:
            return list(p.parent.relative_to(PurePath(root)).parts)
        except ValueError:
            pass
    return list(p.parent.parts[1:])


def is_extra(path: str, root: str | None = None) -> bool:
    p = PurePath(path)
    return any(d.lower() in _EXTRAS_DIRS for d in _rel_parts(p, root)) or bool(_EXTRAS_SUFFIX_RE.search(p.stem))


def parse_path(path: str, root: str | None = None, force_kind: str | None = None) -> ParsedFile | None:
    """Resolve a video file. Returns None for extras (trailers, featurettes, samples…).

    ``root`` is the library folder the file was found in; ``force_kind`` is that folder's
    category (or a per-title override) and is never second-guessed.
    """
    p = PurePath(path)
    if is_extra(path, root):
        return None
    parts = _rel_parts(p, root)
    stem = _TRAILING_GROUP_RE.sub("", p.stem) if _JUNK_RE.search(p.stem[-24:]) else p.stem
    force_kind = force_kind if force_kind in (KIND_MOVIE, KIND_SHOW, KIND_ANIME) else None

    # walk folders upward: season folder(s), then the series folder, stopping at a category folder
    category = None
    folder_season = season_year = None
    show_dir_index = None
    for i in range(len(parts) - 1, -1, -1):
        name = parts[i]
        if name.lower() in _CATEGORY_DIRS:
            category = _CATEGORY_DIRS[name.lower()]
            break
        s = _season_of_folder(name)
        if s is not None:
            if folder_season is None:
                folder_season, season_year = s, folder_title(name)[1]
            continue
        if show_dir_index is None:
            show_dir_index = i
    hint = force_kind or category

    if hint == KIND_MOVIE:
        return _movie(p, stem, parts)

    in_series_context = hint in SERIES_KINDS or folder_season is not None
    ep = find_episode(stem, optimistic=in_series_context, show_kind=hint, folder_season=folder_season)
    if ep is None and not in_series_context:
        # anime release naming ("[Group] Title - 07") is a strong enough signal on its own
        if _GROUP_TAG_RE.match(stem):
            ep = find_episode(stem, optimistic=True)
            if ep is None or ep.rule not in ("dash", "anime_season", "ep", "sxe"):
                ep = None
        if ep is None:
            return _movie(p, stem, parts)

    kind = hint if hint in SERIES_KINDS else (KIND_ANIME if _GROUP_TAG_RE.match(stem) else KIND_SHOW)

    # series title: the series folder, else a "Show Season 1" folder, else the filename prefix.
    # Without a category, a folder only names the series if it agrees with the filename
    # (a loose "Downloads\Severance.S02E03.mkv" is Severance, not "Downloads").
    prefix = stem[: ep.start] if ep else stem
    file_title = clean_title(_YEAR_RE.sub(" ", prefix))
    show_folder, title, year = None, "", season_year
    if show_dir_index is not None:
        ftitle, fyear = folder_title(parts[show_dir_index])
        fk, sk = normalize_key(ftitle), normalize_key(file_title)
        if hint in SERIES_KINDS or not sk or (fk and (fk in sk or sk in fk)):
            title, year = ftitle, fyear or year
            up = len(parts) - 1 - show_dir_index          # how many levels above the file's folder
            show_folder = str(p.parent if up == 0 else p.parent.parents[up - 1])
    if not title:
        for d in reversed(parts):
            if _season_of_folder(d) is not None:
                t, y = folder_title(d)
                if t:
                    title, year = t, year or y
                    break
    if not title:
        title, year = file_title, year or _year_in(prefix)
    if not title and root and force_kind:
        title, year = folder_title(PurePath(root).name)
        show_folder = show_folder or str(root)
    title = title or clean_title(stem)
    show_folder = show_folder or str(p.parent)

    if ep is None:  # unnumbered file inside a series -> Specials
        return ParsedFile(kind, title, year, 0, None, None, False, show_folder)

    season = ep.season if ep.season is not None else folder_season
    # absolute numbering: no season in the filename and no "Season 2+" folder
    absolute = ep.season is None and (folder_season in (None, 1)) and (kind == KIND_ANIME or folder_season is None)
    if season is None:
        season = 1
    return ParsedFile(kind, title, year, season, ep.episode, ep.episode_end, absolute, show_folder)


def _year_in(s: str) -> int | None:
    m = _PAREN_YEAR_RE.search(s)
    if m:
        return int(m.group(1))
    years = [y for y in _YEAR_RE.finditer(_seps(s)) if y.start() > 0]
    return int(years[-1].group(1)) if years else None


def _movie(p: PurePath, stem: str, parts: list[str]) -> ParsedFile:
    norm = _seps(stem)
    m = _PAREN_YEAR_RE.search(stem)
    if m:
        year, title = int(m.group(1)), clean_title(stem[: m.start()])
    else:
        # last year-like token that isn't the very first word ("2001 A Space Odyssey 1968")
        years = [y for y in _YEAR_RE.finditer(norm) if y.start() > 0]
        year = int(years[-1].group(1)) if years else None
        title = clean_title(norm[: years[-1].start()]) if years else clean_title(stem)
    # "Heat (1995)/heat-1080p.mkv" or "Heat (1995)/movie.mkv": the movie folder knows better
    if parts and parts[-1].lower() not in _CATEGORY_DIRS:
        ftitle, fyear = folder_title(parts[-1])
        if ftitle and fyear and (year is None or len(title) <= 3):
            title, year = ftitle, fyear
    return ParsedFile(KIND_MOVIE, title or clean_title(stem), year)
