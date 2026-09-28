"""
Search Functionality Module

This module handles search functionality for the MovieBot.
It includes exact and fuzzy search, result formatting, and pagination.

The live /search and /recent command handlers live in commands.py; this module
provides the search engine (perform_search), the paginated result sender
(send_search_results), the shared page renderers used by the page:/back:
callbacks, the in-place pick filter view, and the inline query handler
(inline_handler).
"""

import asyncio
import re
import uuid
from datetime import datetime, timezone

from fuzzywuzzy import fuzz
from pyrogram.types import Message, InlineKeyboardMarkup, InlineKeyboardButton, LinkPreviewOptions

from .config import FUZZY_THRESHOLD
from .database import movies_col
from .utils import format_search_info, latest_copy


def is_exact_title(title, query):
    """True when a title is an EXACT match for the query (starts with it).

    The rule: the title starts with the query and the next character is not a
    letter (``Lucky`` is exact for ``Lucky``, ``Lucky 2`` too, but ``Luckily``
    is not). This powers the ``Titles Found: N (X Exact | Y Fuzzy)`` header.
    """
    q = (query or "").strip().lower()
    t = str(title or "").strip().lower()
    if not q or not t.startswith(q):
        return False
    return len(t) == len(q) or not t[len(q)].isalpha()


# ----------------------------------------------------------------------
# Search query parsing (``/search Dune 2021 1080p series``)
# ----------------------------------------------------------------------
# Trailing-token syntax (filters come AFTER the title so words inside the
# title are never eaten): a 4-digit year (1900-2099), a quality token
# (480p/720p/1080p/2160p/4k/UHD/FHD/HD/1080i/480i) and a type token
# (movie(s)/series/show(s)/tv). Explicit ``key:value`` forms
# (``year:2021 quality:1080p type:series``) may appear anywhere.

QUALITY_TOKENS = {
    "480p": "480p",
    "480i": "480i",
    "720p": "720p",
    "1080p": "1080p",
    "1080i": "1080i",
    "2160p": "2160p",
    "4k": "2160p",
    "uhd": "2160p",
    "fhd": "1080p",
    "fullhd": "1080p",
    "hd": "720p",
}

TYPE_TOKENS = {
    "movie": "Movie",
    "movies": "Movie",
    "film": "Movie",
    "films": "Movie",
    "series": "Series",
    "show": "Series",
    "shows": "Series",
    "tv": "Series",
    "serial": "Series",
}

_YEAR_RE = re.compile(r"^(19\d{2}|20\d{2})$")
_YEAR_KV_RE = re.compile(r"\byear\s*:\s*(19\d{2}|20\d{2})\b", re.IGNORECASE)
_QUALITY_KV_RE = re.compile(r"\bquality\s*:\s*([^\s]+)", re.IGNORECASE)
_TYPE_KV_RE = re.compile(r"\btype\s*:\s*(movies?|films?|series|shows?|tv|serial)\b", re.IGNORECASE)
_PAREN_YEAR_RE = re.compile(r"\(\s*(19\d{2}|20\d{2})\s*\)")
# Library facets (explicit key:value anywhere; quote multi-word values:
# lang:"dual audio"). Bare trailing `hdr` = any HDR.
_KV_VAL = r"(?:\"([^\"]+)\"|([^\s]+))"
_LANG_KV_RE = re.compile(r"\blang(?:uage)?\s*:\s*" + _KV_VAL, re.IGNORECASE)
_SUBS_KV_RE = re.compile(r"\bsubs?(?:titles)?\s*:\s*" + _KV_VAL, re.IGNORECASE)
_AUDIO_KV_RE = re.compile(r"\baudio\s*:\s*" + _KV_VAL, re.IGNORECASE)
_HDR_KV_RE = re.compile(r"\bhdr\s*:\s*" + _KV_VAL, re.IGNORECASE)

HDR_NAMES = {
    "dv": "Dolby Vision",
    "dolby vision": "Dolby Vision",
    "dovi": "Dolby Vision",
    "hdr10+": "HDR10+",
    "hdr10": "HDR10",
    "hdr": "HDR",
    "hlg": "HLG",
    "sdr": "SDR",
}

# A trailing type word is only a filter when the rest looks like a real
# title: stripping "Show" off "The Show" would leave a bare article, so a
# single remaining article ("the"/"a"/"an") keeps the token as title text.
# (Single-word titles with a filter — "Dune series" — still strip, since a
# bare "Dune series" title would otherwise match nothing.)
_ARTICLE_STOPWORDS = frozenset({"the", "a", "an"})

# DB projection for fuzzy candidate scans (kept narrow so a 500-doc scan
# stays cheap). Must include every field the renderers/grouping need.
_CANDIDATE_PROJECTION = {
    "title": 1, "year": 1, "quality": 1, "channel_title": 1,
    "message_id": 1, "channel_id": 1, "type": 1, "season": 1,
    "episode": 1, "rip": 1,
}

# Hard caps so one search can never pull an unbounded cursor into memory.
FUZZY_CANDIDATE_LIMIT = 500
FILTER_ONLY_LIMIT = 200
TEXT_SEARCH_LIMIT = 50


def _normalize_quality_token(token: str):
    """Map a raw quality token to the canonical DB quality (or None)."""
    if not token:
        return None
    t = str(token).strip().lower().strip("(),[]")
    if t in QUALITY_TOKENS:
        return QUALITY_TOKENS[t]
    # Fall back to the shared normalizer (handles 720/1080/2160/FHD/4K...).
    return normalize_resolution(t)


def parse_search_query(raw: str) -> dict:
    """Split ``/search`` input into title + structured filters.

    Returns ``{"title": str, "year": int|None, "quality": str|None,
    "type": "Movie"|"Series"|None, "language": str|None,
    "subtitles": str|None, "audio": str|None, "hdr": str|True|None,
    "raw": str}``. Only TRAILING year/quality/type tokens are stripped so
    words inside the title are never eaten; the explicit ``year:/quality:/
    type:/lang:/subs:/audio:/hdr:`` forms are extracted from anywhere
    (quote multi-word values: ``lang:"dual audio"``). Bare trailing ``hdr``
    means any HDR copy. A lone year-like query (``/search 2012``) stays a
    title, not a filter.
    """
    text = (raw or "").strip()
    if not text:
        return {"title": "", "year": None, "quality": None, "type": None,
                "language": None, "subtitles": None, "audio": None,
                "hdr": None, "raw": raw or ""}

    year = None
    quality = None
    type_ = None
    language = None
    subtitles = None
    audio = None
    hdr = None

    def _kv_value(match):
        return (match.group(1) if match.group(1) is not None
                else match.group(2) or "").strip()

    # Explicit key:value forms (removed wherever they appear).
    m = _YEAR_KV_RE.search(text)
    if m:
        year = int(m.group(1))
        text = (_YEAR_KV_RE.sub(" ", text, count=1))
    m = _QUALITY_KV_RE.search(text)
    if m:
        quality = _normalize_quality_token(m.group(1))
        text = (_QUALITY_KV_RE.sub(" ", text, count=1))
    m = _TYPE_KV_RE.search(text)
    if m:
        type_ = TYPE_TOKENS.get(m.group(1).lower())
        text = (_TYPE_KV_RE.sub(" ", text, count=1))
    m = _LANG_KV_RE.search(text)
    if m:
        language = _kv_value(m) or None
        text = (_LANG_KV_RE.sub(" ", text, count=1))
    m = _SUBS_KV_RE.search(text)
    if m:
        subtitles = _kv_value(m) or None
        text = (_SUBS_KV_RE.sub(" ", text, count=1))
    m = _AUDIO_KV_RE.search(text)
    if m:
        audio = _kv_value(m) or None
        text = (_AUDIO_KV_RE.sub(" ", text, count=1))
    m = _HDR_KV_RE.search(text)
    if m:
        hdr = HDR_NAMES.get(_kv_value(m).lower(), _kv_value(m)) or None
        text = (_HDR_KV_RE.sub(" ", text, count=1))

    # Parenthesised year anywhere ("Dune (2021)") — parser-style filenames
    # use this shape, so users paste it naturally.
    m = _PAREN_YEAR_RE.search(text)
    if m and year is None:
        year = int(m.group(1))
        text = (_PAREN_YEAR_RE.sub(" ", text, count=1))

    text = re.sub(r"\s+", " ", text).strip()
    tokens = text.split()
    original_count = len(tokens)

    # Trailing filter tokens only (loop so "Dune 2021 1080p movie" all pops).
    # Bare `hdr` is the only library facet allowed unquoted (filenames never
    # end a title in it); lang/subs/audio stay key:value-only so title words
    # like "English" are never eaten.
    while tokens:
        t = tokens[-1].strip("(),[]")
        tl = t.lower()
        if _YEAR_RE.match(tl) and year is None:
            year = int(tl)
            tokens.pop()
            continue
        q = _normalize_quality_token(tl)
        if q is not None and quality is None and tl in QUALITY_TOKENS:
            quality = q
            tokens.pop()
            continue
        if tl in TYPE_TOKENS and type_ is None:
            remaining = tokens[:-1]
            if len(remaining) == 1 and remaining[0].lower() in _ARTICLE_STOPWORDS:
                break  # e.g. "The Show" — the word is the title, not a filter
            type_ = TYPE_TOKENS[tl]
            tokens.pop()
            continue
        if tl == "hdr" and hdr is None:
            hdr = True
            tokens.pop()
            continue
        break

    title = " ".join(tokens).strip(" -:;")
    if not title:
        # Everything was a filter token (e.g. "/search 2021" or
        # "/search 1080p"): keep the raw text as the title and drop the
        # filters so a film literally called "2012" still finds itself.
        # Multi-token filter-only queries ("/search 2021 1080p") keep the
        # filters with an empty title (list-all-matching).
        if original_count <= 1:
            return {"title": text.strip(" -:;"), "year": None,
                    "quality": None, "type": None, "language": None,
                    "subtitles": None, "audio": None, "hdr": None,
                    "raw": raw}
        title = ""

    return {"title": title, "year": year, "quality": quality, "type": type_,
            "language": language, "subtitles": subtitles, "audio": audio,
            "hdr": hdr, "raw": raw}


def _build_base_filter(year=None, quality=None, type_=None, language=None,
                     subtitles=None, audio=None, hdr=None) -> dict:
    """Mongo filter for the structured facets.

    Text facets (language/subtitles/audio/hdr-name) match case-insensitive
    exact against the parser's canonical values (Hindi, English Subs,
    Atmos, Dolby Vision...). ``hdr=True`` (bare ``hdr`` token) matches any
    copy carrying HDR metadata.
    """
    filt = {}
    if year is not None:
        try:
            y = int(year)
        except (TypeError, ValueError):
            y = None
        if y is not None:
            # Year is stored as int by the parser, but tolerate legacy
            # string values so old docs still match.
            filt["year"] = {"$in": [y, str(y)]}
    if quality:
        filt["quality"] = {"$regex": f"^{re.escape(str(quality))}$", "$options": "i"}
    if type_:
        t = str(type_).lower()
        if t == "movie":
            filt["type"] = {"$regex": "^movie$", "$options": "i"}
        elif t in ("series", "tv", "show"):
            filt["type"] = {"$regex": "^(series|tv|show)$", "$options": "i"}
    if language:
        filt["language"] = {"$regex": f"^{re.escape(str(language))}$", "$options": "i"}
    if subtitles:
        filt["subtitles"] = {"$regex": f"^{re.escape(str(subtitles))}$", "$options": "i"}
    if audio:
        filt["audio_codec"] = {"$regex": f"^{re.escape(str(audio))}$", "$options": "i"}
    if hdr is True:
        filt["hdr"] = {"$exists": True, "$ne": None}
    elif hdr:
        filt["hdr"] = {"$regex": f"^{re.escape(str(hdr))}$", "$options": "i"}
    return filt


def format_active_filters(year=None, quality=None, type_=None, language=None,
                          subtitles=None, audio=None, hdr=None) -> str:
    """Human line for the results header, e.g. ``year=2021 · 1080p · Series``."""
    parts = []
    if year is not None:
        parts.append(f"year={year}")
    if quality:
        parts.append(str(quality))
    if type_:
        parts.append(str(type_))
    if language:
        parts.append(f"lang={language}")
    if subtitles:
        parts.append(f"subs={subtitles}")
    if audio:
        parts.append(f"audio={audio}")
    if hdr is True:
        parts.append("HDR")
    elif hdr:
        parts.append(f"HDR={hdr}")
    return " · ".join(parts)


async def perform_search(query: str, exact_search: bool = False, fuzzy_threshold: int = None,
                         year=None, quality=None, type_=None, language=None,
                         subtitles=None, audio=None, hdr=None):
    """
    Perform a search for movies/series in the database.

    Args:
        query: Search query string (title text; may be the raw ``/search``
            input — trailing ``<year> <quality> <type>`` tokens and
            ``lang:/subs:/audio:/hdr:`` facets are parsed out automatically
            unless explicit facet kwargs are given).
        exact_search: If True, only exact title matches are returned
        fuzzy_threshold: Threshold for fuzzy matching (default: FUZZY_THRESHOLD from config)
        year: Optional year facet (int or str). Overrides any year parsed
            from ``query`` when not None.
        quality: Optional quality facet (e.g. "1080p"). Same override rule.
        type_: Optional "Movie" / "Series" facet. Same override rule.
        language: Optional audio-language facet (e.g. "Hindi"). Same rule.
        subtitles: Optional subtitle facet (e.g. "English Subs"). Same rule.
        audio: Optional audio-codec facet (e.g. "Atmos"). Same rule.
        hdr: Optional HDR facet (format name, or True for any HDR). Same rule.

    Returns:
        Dict with ``results`` (list of matching copy documents), ``exact_ids``
        (set of ``_id`` values whose title counts as an exact match - empty for
        ``exact_search`` mode where every result is exact), plus ``title``
        (parsed title text) and ``filters`` (applied facet dict).
    """
    if fuzzy_threshold is None:
        fuzzy_threshold = FUZZY_THRESHOLD

    # Split trailing "<year> <quality> <type>" tokens out of the raw input.
    # Explicit kwargs win over parsed tokens so programmatic callers can
    # override (e.g. history re-search passes the stored raw query through).
    parsed = parse_search_query(query)
    title = parsed["title"]
    if year is None:
        year = parsed["year"]
    if quality is None:
        quality = parsed["quality"]
    if type_ is None:
        type_ = parsed["type"]
    if language is None:
        language = parsed.get("language")
    if subtitles is None:
        subtitles = parsed.get("subtitles")
    if audio is None:
        audio = parsed.get("audio")
    if hdr is None:
        hdr = parsed.get("hdr")
    base_filter = _build_base_filter(year=year, quality=quality, type_=type_,
                                     language=language, subtitles=subtitles,
                                     audio=audio, hdr=hdr)
    filters = {"year": year, "quality": quality, "type": type_,
               "language": language, "subtitles": subtitles,
               "audio": audio, "hdr": hdr}

    def _with_title(extra: dict) -> dict:
        filt = dict(base_filter)
        filt.update(extra)
        return filt

    if exact_search:
        # Exact search mode - only look for exact title matches
        exact_pattern = f"^{re.escape(title)}$" if title else "^$"
        exact = await movies_col.find(
            _with_title({"title": {"$regex": exact_pattern, "$options": "i"}})
        ).to_list(length=None)
        return {"results": exact, "exact_ids": {r.get("_id") for r in exact},
                "title": title, "filters": filters}

    # Normal search: $text fast path -> regex substring -> fuzzy re-rank.
    # Every stage carries the facet filter server-side so a query like
    # "Dune 2021 1080p" never pulls unrelated copies into memory.
    seen_ids = set()
    all_results = []

    async def _text_candidates():
        if not title or len(title.strip()) < 3:
            return None
        try:
            filt = _with_title({"$text": {"$search": title}})
            cursor = movies_col.find(
                filt,
                {**_CANDIDATE_PROJECTION,
                 "score": {"$meta": "textScore"}},
            ).sort([("score", {"$meta": "textScore"})]).limit(TEXT_SEARCH_LIMIT)
            return await cursor.to_list(length=TEXT_SEARCH_LIMIT)
        except Exception:
            # No text index yet (old DBs) — fall through to regex + fuzzy.
            return None

    text_hits = await _text_candidates()
    if text_hits:
        all_results.extend(text_hits)
        seen_ids.update(r.get("_id") for r in text_hits)

    if title:
        # Substring stage (escaped: a query like "C++" must not be a regex).
        exact = await movies_col.find(
            _with_title({"title": {"$regex": re.escape(title), "$options": "i"}})
        ).to_list(length=None)
    else:
        # Filter-only query (e.g. "/search 2021 1080p"): list matching
        # copies, newest-indexed first is handled at render; cap the pull.
        exact = await movies_col.find(base_filter).to_list(length=FILTER_ONLY_LIMIT)
    for r in exact:
        if r.get("_id") not in seen_ids:
            all_results.append(r)
            seen_ids.add(r.get("_id"))

    # Fuzzy re-rank only when the cheap stages came up short, over a
    # facet-narrowed candidate set (was: unfiltered 500-doc scan + O(N*M)
    # duplicate check against exact hits).
    if title and len(all_results) < 50:
        candidates = []
        cursor = movies_col.find(base_filter, _CANDIDATE_PROJECTION).limit(FUZZY_CANDIDATE_LIMIT)
        ql = title.lower()
        async for r in cursor:
            if r.get("_id") in seen_ids:
                continue
            score = fuzz.partial_ratio(ql, str(r.get("title", "")).lower())
            if score >= fuzzy_threshold:
                candidates.append((score, r))

        candidates = sorted(candidates, key=lambda x: x[0], reverse=True)
        all_results.extend([c[1] for c in candidates])

    exact_ids = {r.get("_id") for r in all_results if is_exact_title(r.get("title"), title)}
    return {"results": all_results, "exact_ids": exact_ids,
            "title": title, "filters": filters}


# ----------------------------------------------------------------------
# Search result rendering helpers
#
# Shared by the initial /search send, the page:/back: callbacks and the
# in-place pick filter view so every render stays consistent.
# ----------------------------------------------------------------------

MAX_SEASON_BUTTONS = 5   # per-group season pick shortcuts in the results list
MAX_PICK_SEASONS = 10    # season filter buttons PER PAGE in the pick view
MAX_PICK_LINES = 30      # max copy/episode lines shown in the pick view

SERIES_TYPES = {"series", "tv", "show"}


def normalize_resolution(quality):
    """Map a quality string to one of '720p'/'1080p'/'2160p' (or None)."""
    if not quality:
        return None
    q = str(quality).strip().lower()
    if q in ("2160p", "2160", "4k", "4kuhd", "uhd"):
        return "2160p"
    if q in ("1080p", "1080", "fullhd", "fhd"):
        return "1080p"
    if q in ("720p", "720", "hd"):
        return "720p"
    return None


def pick_callback(search_id, group_index, season=None, resolution=None, season_page=0,
                  prefix="choose"):
    """Callback data for the pick filter view (6 colon-separated parts).

    Format: ``{prefix}:{search_id}:{group_index}:{season}:{resolution}:{page}``
    where season is ``S02`` (or empty), resolution is ``1080p`` (or empty) and
    page is the 0-based season page (empty = page 0). The legacy 5-part format
    (no trailing page) is still accepted by the callback parser. ``prefix`` is
    ``choose`` for /search and ``genre_pick`` for /genres browsing.
    """
    season_part = ""
    if season is not None:
        try:
            season_part = f"S{int(season):02d}"
        except (TypeError, ValueError):
            season_part = f"S{season}"
    page_part = str(season_page) if season_page else ""
    return f"{prefix}:{search_id}:{group_index}:{season_part}:{resolution or ''}:{page_part}"


def is_series(copies):
    """True if a copy group is a series/show/tv."""
    return any((c.get("type") or "Movie").lower() in SERIES_TYPES for c in copies)


def _season_number(copy):
    """Coerce a copy's season to int (None when missing/malformed)."""
    s = copy.get("season")
    if s is None:
        return None
    try:
        return int(s)
    except (TypeError, ValueError):
        return None


def group_seasons(copies):
    """Sorted distinct season numbers present in a copy group."""
    return sorted({s for c in copies if (s := _season_number(c)) is not None})


def filter_copies(copies, season=None, resolution=None):
    """Filter a copy list by season (int) and/or normalized resolution."""
    filtered = copies
    if season is not None:
        filtered = [c for c in filtered if _season_number(c) == season]
    if resolution is not None:
        filtered = [c for c in filtered
                    if normalize_resolution(c.get("quality")) == resolution]
    return filtered


RESULTS_PER_PAGE = 9  # per-TITLE groups per page (not per copy)

# Shared Pick/Get hint shown on every /search and /genres <name> result page
# (single source so both surfaces can't drift apart).
SEARCH_HINT = (
    "Hint: Use\n"
    "Pick button below to select title, see, and get all relative files.\n"
    "Get button below to get latest file of each title."
)


def group_by_title(results):
    """Group copy documents into per-title buckets (case-insensitive title).

    Returns a list of groups (each a list of copy docs) so every title appears
    exactly once in the results list, with its file count derived from the
    group size.
    """
    buckets = {}
    order = []
    for entry in results:
        key = str(entry.get("title") or "Untitled").strip().lower()
        if key not in buckets:
            buckets[key] = []
            order.append(key)
        buckets[key].append(entry)
    return [buckets[key] for key in order]


def _copy_type_label(copy):
    """'Series' when the copy is a series/tv/show, else 'Movie'."""
    return "Series" if (copy.get("type") or "Movie").lower() in SERIES_TYPES else "Movie"


def build_search_page(results, query, page, exact_ids=None, filters=None):
    """Build the paginated search-result text + per-line button metadata.

    The result list is a code block of per-title lines:

        Search : Lucky
        Titles Found: 3 (1 Exact | 2 Fuzzy)
        Files Found: 15 (Movie - 5 | Series - 10)
        ...
        1. Lucky > 2 files > Latest: 1080p | 2.5GB | WebRip

    ``filters`` is the applied facet dict (``{"year","quality","type"}``) and
    renders as a ``Filters: ...`` header line when non-empty.

    Returns ``(search_text, button_data, groups, total_pages)`` where
    ``groups`` are ALL per-title groups (so the Pick view can index into the
    global list from any page) and button_data carries the global group index
    plus the LATEST copy's channel/message ids (the ``Get [n]`` target). The
    caller appends the TMDb Title(s) Information block via
    ``build_title_info_block`` so it survives pagination. The initial /search
    send, the page:/back: callbacks and history searches all render through
    here so every view stays identical.
    """
    from .utils import pick_best_quality

    groups = group_by_title(results)
    total_titles = len(groups)
    total_pages = max(1, (total_titles + RESULTS_PER_PAGE - 1) // RESULTS_PER_PAGE)
    page = max(1, min(page, total_pages))

    start_idx = (page - 1) * RESULTS_PER_PAGE
    page_groups = groups[start_idx:start_idx + RESULTS_PER_PAGE]

    # Exact/fuzzy title counts (exact = title starts with the query).
    exact_ids = exact_ids or set()
    exact_titles = sum(1 for g in groups
                       if any(c.get("_id") in exact_ids for c in g))
    fuzzy_titles = total_titles - exact_titles

    # File counts split by movie/series.
    movie_files = sum(1 for g in groups for c in g if _copy_type_label(c) == "Movie")
    series_files = len(results) - movie_files

    search_text = (
        f"```\n"
        f"Search : {query}\n"
    )
    if filters:
        filt_line = format_active_filters(
            year=filters.get("year"),
            quality=filters.get("quality"),
            type_=filters.get("type"),
            language=filters.get("language"),
            subtitles=filters.get("subtitles"),
            audio=filters.get("audio"),
            hdr=filters.get("hdr"),
        )
        if filt_line:
            search_text += f"Filters: {filt_line}\n"
    search_text += (
        f"Titles Found: {total_titles} ({exact_titles} Exact | {fuzzy_titles} Fuzzy)\n"
        f"Files Found: {len(results)} (Movie - {movie_files} | Series - {series_files})\n\n"
        f"{SEARCH_HINT}\n\n"
    )

    button_data = []
    for i, group in enumerate(page_groups, start=start_idx + 1):
        best, _ = pick_best_quality(group)
        latest = latest_copy(group)
        files = len(group)
        file_word = "file" if files == 1 else "files"

        # Latest-file info (episode first for series, then quality/size/rip).
        from .utils import format_latest_info
        latest_info = format_latest_info(latest)
        search_text += f"{i}. {best.get('title', 'Unknown Title')} > {files} {file_word} > Latest: {latest_info}\n"

        if latest.get("channel_id") and latest.get("message_id"):
            button_data.append({
                'number': i,
                'channel_id': latest['channel_id'],
                'message_id': latest['message_id'],
                'group_index': i - 1,       # global index into groups
                'group_size': len(group),
            })

    if total_pages > 1:
        search_text += f"\nPage {page}/{total_pages}\n"
    search_text += "```"

    return search_text, button_data, groups, total_pages


def build_title_info_block(groups, page, metas):
    """TMDb Title(s) Information block (outside the code block, links live).

    One line per title on the page, matching the result-list numbering:
    ``1. Lucky (Movie) - 2025 . ⭐️ 6.8 · 🎭 Animation, Action · [IMDb](url)``.
    ``metas`` maps global group index -> TMDb meta dict (or None).
    """
    from .utils import pick_best_quality

    start_idx = (page - 1) * RESULTS_PER_PAGE
    page_groups = groups[start_idx:start_idx + RESULTS_PER_PAGE]

    lines = []
    for i, group in enumerate(page_groups, start=start_idx + 1):
        best, _ = pick_best_quality(group)
        meta = metas.get(i - 1) if metas else None

        title = best.get("title") or "Unknown Title"
        type_label = _copy_type_label(best)
        line = f"{i}. {title} ({type_label})"
        year = best.get("year")
        if year:
            line += f" - {year}"

        extra = []
        if meta:
            if meta.get("rating"):
                extra.append(f"⭐️ {meta['rating']}")
            if meta.get("genres"):
                extra.append(f"🎭 {', '.join(meta['genres'][:3])}")
            if meta.get("imdb_id"):
                extra.append(f"[IMDb](https://imdb.com/title/{meta['imdb_id']})")
        if extra:
            line += " . " + " · ".join(extra)
        lines.append(line)

    if not lines:
        return ""
    separator = "=" * 70
    block = (
        f"\n{separator}\n"
        f"Title(s) Information\n\n"
        + "\n".join(lines) +
        f"\n{separator}\n"
    )
    return block


async def _fetch_metas(groups, indices):
    """Fetch TMDb metas for the groups at ``indices`` (concurrently, cached).

    Returns ``{global_group_index: meta_or_None}``. Uses the best-quality copy
    of each group; no-op (None metas) without a TMDb API key.
    """
    from .tmdb_integration import enrich_title
    from .utils import pick_best_quality

    best = [pick_best_quality(groups[i])[0] for i in indices]
    metas = await asyncio.gather(*[
        enrich_title(b.get("title"), b.get("year"), b.get("type", "Movie"))
        for b in best
    ], return_exceptions=True)
    return {i: (m if isinstance(m, dict) else None)
            for i, m in zip(indices, metas)}


async def build_search_keyboard(search_id, total_results, page, total_pages,
                                groups, button_data, user_id, results,
                                season_pages=None):
    """Build the inline keyboard for a search results page.

    Every title group gets BOTH a ``Pick [n]`` button (opens the in-place pick
    view) and a ``Get [n]`` button (fetches that title's LATEST file directly).
    Series with several seasons additionally get ``Pick[n][Sxx]`` shortcut
    buttons per season; long-running series page through their shortcuts
    (``S◀`` / ``S▶``, ``season_pages`` maps group index -> season page).
    """
    from .config import bulk_downloads
    from .premium_management import is_feature_premium_only, is_premium_user
    from .user_management import is_admin

    if not button_data:
        return None

    # Section 1: Pick buttons (season shortcuts + the all-copies pick), rows of 3.
    buttons = []
    current_row = []
    for btn in button_data:
        group = groups[btn['group_index']]
        group_buttons = []

        # Series with several seasons page through their shortcut buttons
        # (S◀ / S▶, one group at a time) - the page: callback carries the
        # group's season page so the results list can rebuild in place with
        # the next slice of Sxx buttons.
        if is_series(group):
            seasons = group_seasons(group)
            if len(seasons) > 1:
                # Clamp against stale/hand-crafted season pages so an
                # out-of-range page never renders an empty shortcut row.
                sp = (season_pages or {}).get(btn['group_index'], 0)
                max_sp = max(0, (len(seasons) + MAX_SEASON_BUTTONS - 1)
                             // MAX_SEASON_BUTTONS - 1)
                sp = max(0, min(sp, max_sp))
                start = sp * MAX_SEASON_BUTTONS
                for s in seasons[start:start + MAX_SEASON_BUTTONS]:
                    group_buttons.append(
                        InlineKeyboardButton(
                            f"Pick[{btn['number']}][S{s:02d}]",
                            callback_data=pick_callback(search_id, btn['group_index'], season=s)
                        )
                    )
                if len(seasons) > MAX_SEASON_BUTTONS:
                    if sp > 0:
                        group_buttons.append(InlineKeyboardButton(
                            "S◀",
                            callback_data=f"page:{search_id}:{page}:{btn['group_index']}:{sp - 1}"))
                    if start + MAX_SEASON_BUTTONS < len(seasons):
                        group_buttons.append(InlineKeyboardButton(
                            "S▶",
                            callback_data=f"page:{search_id}:{page}:{btn['group_index']}:{sp + 1}"))

        group_buttons.append(
            InlineKeyboardButton(
                f"Pick [{btn['number']}]",
                callback_data=pick_callback(search_id, btn['group_index'])
            )
        )
        for gb in group_buttons:
            current_row.append(gb)
            if len(current_row) == 3:
                buttons.append(current_row)
                current_row = []
    if current_row:
        buttons.append(current_row)

    # Section 2: Get buttons - one per title, pointing at its LATEST copy.
    current_row = []
    for btn in button_data:
        current_row.append(InlineKeyboardButton(
            f"Get [{btn['number']}]",
            callback_data=f"get_file:{btn['channel_id']}:{btn['message_id']}"
        ))
        if len(current_row) == 3:
            buttons.append(current_row)
            current_row = []
    if current_row:
        buttons.append(current_row)

    # Create navigation row with Prev, Get All, and Next buttons
    nav_row = []

    # Previous button
    if page > 1:
        nav_row.append(
            InlineKeyboardButton(
                "← Prev",
                callback_data=f"page:{search_id}:{page-1}"
            )
        )

    # Get All button (for all results, not just current page)
    if total_results > 1:
        # Check if Get All is premium-only
        show_get_all = True
        if await is_feature_premium_only("get_all"):
            # Only show if user is premium or admin
            if not await is_admin(user_id) and not await is_premium_user(user_id):
                show_get_all = False

        if show_get_all:
            # Generate bulk download ID for all results
            bulk_id = str(uuid.uuid4())[:8]
            bulk_downloads[bulk_id] = {
                'files': [{'channel_id': r.get('channel_id'), 'message_id': r.get('message_id')}
                         for r in results if r.get('channel_id') and r.get('message_id')][:10],
                'created_at': datetime.now(timezone.utc),
                'user_id': user_id
            }

            nav_row.append(
                InlineKeyboardButton(
                    f"Get All ({total_results})",
                    callback_data=f"bulk:{bulk_id}"
                )
            )

    # Next button
    if page < total_pages:
        nav_row.append(
            InlineKeyboardButton(
                "Next →",
                callback_data=f"page:{search_id}:{page+1}"
            )
        )

    # Add navigation row if it has buttons
    if nav_row:
        buttons.append(nav_row)

    return InlineKeyboardMarkup(buttons) if buttons else None


async def send_search_results(client, message: Message, results, query, page=1,
                              exact_ids=None, filters=None):
    """Send beautifully formatted search results with pagination.

    The search (its per-title groups, exact/fuzzy split and TMDb metas) is
    stored so the ``Pick``/``Get`` buttons keep working and the Title(s)
    Information block survives page navigation; the same renderers power the
    page:/back: callbacks.

    client is passed explicitly to avoid fragile relative import (previously caused
    ImportError: attempted relative import beyond top-level package)."""
    from .config import bulk_downloads

    search_text, button_data, groups, total_pages = build_search_page(
        results, query, page, exact_ids=exact_ids, filters=filters)

    # TMDb enrichment (cached per title; no-op without an API key) - the
    # Title(s) Information block below the results with rating/genres/IMDb
    # links. Fetched concurrently so a page of titles doesn't serialize HTTP
    # round-trips, then stored so pagination doesn't lose it.
    page_indices = list(range((page - 1) * RESULTS_PER_PAGE,
                              min(page * RESULTS_PER_PAGE, len(groups))))
    metas = await _fetch_metas(groups, page_indices)
    search_text += build_title_info_block(groups, page, metas)

    # Create keyboard
    keyboard = None
    if button_data:
        # Store search results for pagination (using UUID to avoid callback data size limits)
        search_id = str(uuid.uuid4())[:8]
        from .utils import cleanup_expired_bulk_downloads
        await cleanup_expired_bulk_downloads(bulk_downloads)

        bulk_downloads[search_id] = {
            'results': results,   # Store all results for pagination
            'groups': groups,     # Per-title groups for the pick filter view
            'query': query,
            'exact_ids': set(exact_ids or ()),
            'filters': filters,   # Applied facets so pagination re-renders them
            'metas': metas,       # global group index -> TMDb meta (or None)
            'created_at': datetime.now(timezone.utc),
            'user_id': message.from_user.id,
            'page': page,
        }

        keyboard = await build_search_keyboard(
            search_id, len(results), page, total_pages, groups, button_data,
            message.from_user.id, results)

    # Send message
    await message.reply_text(
        search_text,
        reply_markup=keyboard,
        link_preview_options=LinkPreviewOptions(is_disabled=True)
    )


async def render_search_page(callback_query, search_data, page, search_id):
    """Re-render a stored search into the current message (page:/back:)."""
    results = search_data['results']
    query = search_data['query']
    exact_ids = search_data.get("exact_ids")
    search_text, button_data, groups, total_pages = build_search_page(
        results, query, page, exact_ids=exact_ids,
        filters=search_data.get("filters"))
    total_results = len(results)
    search_data['page'] = page

    # Title(s) Information must survive pagination: reuse the metas already
    # fetched for stored pages and fetch only the ones this page still needs.
    metas = dict(search_data.get("metas") or {})
    page_indices = list(range((page - 1) * RESULTS_PER_PAGE,
                              min(page * RESULTS_PER_PAGE, len(groups))))
    missing = [i for i in page_indices if i not in metas]
    if missing:
        metas.update(await _fetch_metas(groups, missing))
        search_data["metas"] = metas
    search_text += build_title_info_block(groups, page, metas)

    keyboard = None
    if button_data:
        keyboard = await build_search_keyboard(
            search_id, total_results, page, total_pages, groups, button_data,
            callback_query.from_user.id, results,
            season_pages=search_data.get("season_pages"))

    await callback_query.edit_message_text(
        search_text,
        reply_markup=keyboard,
        link_preview_options=LinkPreviewOptions(is_disabled=True)
    )


def build_pick_view(search_id, group_index, copies, season=None, resolution=None,
                    season_page=0, prefix="choose", back_prefix=None):
    """Build the in-place filtered view (text + keyboard) for one title.

    The result message is replaced by ONLY this title's copies: movies list
    every copy; series dedupe per episode (best copy) and offer season filter
    buttons (paged for long-running series). A resolution filter row narrows
    by [720p]/[1080p]/[2160p].

    ``prefix``/``back_prefix`` let non-search surfaces reuse the view: /search
    uses ``choose``/``back``, /genres browsing uses ``genre_pick``/
    ``genre_back`` (the Back button then restores the genre page, not a
    search page).
    """
    from .utils import pick_best_quality

    title = copies[0].get("title", "Unknown")
    year = copies[0].get("year")
    series = is_series(copies)

    # Season + resolution filter state (drop stale values). Resolution buttons
    # reflect the copies available within the ACTIVE season, so they never
    # lead straight to an empty view.
    seasons = group_seasons(copies)
    if season is not None and season not in seasons:
        season = None
    res_base = filter_copies(copies, season=season)
    resolutions = sorted({r for r in (normalize_resolution(c.get("quality")) for c in res_base) if r})
    if resolution is not None and resolution not in resolutions:
        resolution = None

    filtered = filter_copies(copies, season=season, resolution=resolution)

    # Header (markdown - the copy list below is a code block)
    header = f"🎞️ **{title}**"
    if year:
        header += f" ({year})"
    if season is not None:
        header += f" · S{season:02d}"
    if resolution is not None:
        header += f" · {resolution}"
    header += f" — {len(filtered)} copy" if len(filtered) == 1 else f" — {len(filtered)} copies"
    if series and len(seasons) > 1:
        header += f" across {len(seasons)} seasons"
    header += "\n"

    # Copy lines (series: dedupe per episode, best copy wins) in the pick-view
    # format: ``1. Lucky (2025) - 2.5GB | WebRip | 1080p`` inside a code block.
    from .utils import format_pick_line

    lines = []
    get_buttons = []
    n = 1
    if series:
        episodes = {}
        for c in filtered:
            key = (c.get("season"), c.get("episode"))
            episodes.setdefault(key, []).append(c)
        ordered = sorted(
            (k for k in episodes if k[0] is not None),
            key=lambda k: (k[0], k[1] if k[1] is not None else 0),
        )
        for key in ordered[:MAX_PICK_LINES]:
            s, e = key
            ep_copies = episodes[key]
            best, others = pick_best_quality(ep_copies)
            label = f"S{s:02d}" + (f"E{e:02d}" if e is not None else "")
            lines.append(format_pick_line(n, best, dup_count=len(others)))
            n += 1
            if best.get("channel_id") and best.get("message_id"):
                get_buttons.append((label, best))

        # Copies without season/episode metadata (whole-series packs etc.) are
        # listed individually so they stay reachable - and when NO episode keys
        # exist at all (season-less series group), this falls back to listing
        # every copy movie-style instead of rendering an empty view.
        unkeyed = [c for c in filtered if c.get("season") is None]
        extra_budget = MAX_PICK_LINES - len(lines)
        for c in unkeyed[:max(0, extra_budget)]:
            lines.append(format_pick_line(n, c))
            if c.get("channel_id") and c.get("message_id"):
                get_buttons.append((str(n), c))
            n += 1
    else:
        for c in filtered[:MAX_PICK_LINES]:
            lines.append(format_pick_line(n, c))
            if c.get("channel_id") and c.get("message_id"):
                get_buttons.append((str(n), c))
            n += 1

    text = header + "```\n" + "\n".join(lines) + "\n```"
    if len(filtered) > MAX_PICK_LINES:
        text += f"\n… showing first {MAX_PICK_LINES} — filter by season/resolution above"

    # Buttons
    buttons = []

    # Season filter row(s) - series with several seasons. Long-running series
    # page through the seasons (MAX_PICK_SEASONS per page) so every season is
    # reachable: the S◀/S▶ buttons move across pages (clearing any active
    # season filter, since the user is navigating to another page's seasons),
    # and a clicked season button remembers its page so the view stays put.
    if series and len(seasons) > 1:
        season_pages = max(1, (len(seasons) + MAX_PICK_SEASONS - 1) // MAX_PICK_SEASONS)
        if season is not None:
            # Snap to the page that actually contains the active season.
            season_page = next(
                (p for p in range(season_pages)
                 if season in seasons[p * MAX_PICK_SEASONS:(p + 1) * MAX_PICK_SEASONS]),
                0)
        else:
            season_page = max(0, min(season_page, season_pages - 1))

        page_seasons = seasons[season_page * MAX_PICK_SEASONS:(season_page + 1) * MAX_PICK_SEASONS]
        row = []
        for s in page_seasons:
            active = s == season
            row.append(InlineKeyboardButton(
                f"S{s:02d}" + (" ✓" if active else ""),
                callback_data=pick_callback(search_id, group_index,
                                            season=None if active else s,
                                            resolution=resolution,
                                            season_page=season_page,
                                            prefix=prefix),
            ))
            if len(row) == 5:
                buttons.append(row)
                row = []
        if row:
            buttons.append(row)

        if season_pages > 1:
            paging_row = []
            if season_page > 0:
                paging_row.append(InlineKeyboardButton(
                    "S◀",
                    callback_data=pick_callback(search_id, group_index,
                                                resolution=resolution,
                                                season_page=season_page - 1,
                                                prefix=prefix)))
            if season_page < season_pages - 1:
                paging_row.append(InlineKeyboardButton(
                    "S▶",
                    callback_data=pick_callback(search_id, group_index,
                                                resolution=resolution,
                                                season_page=season_page + 1,
                                                prefix=prefix)))
            if paging_row:
                buttons.append(paging_row)

            first_s, last_s = page_seasons[0], page_seasons[-1]
            text += (f"\n… S{first_s:02d}–S{last_s:02d} shown"
                     f" (page {season_page + 1}/{season_pages})")

    # Resolution filter row (keeps the current season page so filtering from
    # page 2 of a long series doesn't jump the view back to page 1)
    if resolutions:
        row = []
        for res in ("720p", "1080p", "2160p"):
            if res in resolutions:
                active = res == resolution
                row.append(InlineKeyboardButton(
                    f"[{res}]" + (" ✓" if active else ""),
                    callback_data=pick_callback(search_id, group_index,
                                                season=season,
                                                resolution=None if active else res,
                                                season_page=season_page,
                                                prefix=prefix),
                ))
        if row:
            buttons.append(row)

    # Get buttons (rows of 3)
    row = []
    for label, copy in get_buttons:
        row.append(InlineKeyboardButton(
            f"Get [{label}]",
            callback_data=f"get_file:{copy['channel_id']}:{copy['message_id']}",
        ))
        if len(row) == 3:
            buttons.append(row)
            row = []
    if row:
        buttons.append(row)

    back_data = f"{back_prefix or 'back'}:{search_id}"
    buttons.append([InlineKeyboardButton("← Back", callback_data=back_data)])

    return text, InlineKeyboardMarkup(buttons) if buttons else None


async def render_pick_view(callback_query, search_data, group_index, search_id,
                           season=None, resolution=None, season_page=0):
    """Edit the search message in place to the filtered view of one title.

    Returns True when the view was rendered, False when the search expired or
    the group index is out of range (the caller answers with an error toast).
    """
    groups = search_data.get("groups") or []
    if group_index >= len(groups) or not groups[group_index]:
        return False

    copies = groups[group_index]
    text, keyboard = build_pick_view(search_id, group_index, copies, season=season,
                                     resolution=resolution, season_page=season_page)

    # Default (markdown) parse mode: the copy list renders as a code block.
    await callback_query.message.edit_text(
        text,
        reply_markup=keyboard,
        link_preview_options=LinkPreviewOptions(is_disabled=True),
    )
    return True


async def inline_handler(client, inline_query):
    """Handle inline queries for the bot"""
    from .config import FUZZY_THRESHOLD
    from .database import movies_col, users_col
    from fuzzywuzzy import fuzz
    from pyrogram.types import InlineQueryResultArticle, InputTextMessageContent
    from datetime import datetime, timezone
    
    query = inline_query.query.strip()
    if not query:
        return
    
    # Track inline search
    user_id = inline_query.from_user.id
    try:
        await users_col.update_one(
            {"user_id": user_id},
            {"$inc": {"inline_search_count": 1}},
            upsert=True
        )
    except Exception as e:
        print(f"⚠️ Failed to track inline search for user {user_id}: {e}")
    
    # Search for movies matching the query
    results = []
    
    # Exact matches first (escaped: inline text is raw user input)
    exact_cursor = movies_col.find({"title": {"$regex": re.escape(query), "$options": "i"}}).limit(10)
    exact_results = await exact_cursor.to_list(length=10)

    # Attach TMDb poster thumbnails to the first few exact matches (cached per
    # title; no-op when no TMDB_API key is configured).
    from .tmdb_integration import enrich_title
    poster_map = {}
    metas = await asyncio.gather(*[
        enrich_title(r.get("title"), r.get("year"), r.get("type", "Movie"))
        for r in exact_results[:5]
    ], return_exceptions=True)
    for r, meta in zip(exact_results[:5], metas):
        if isinstance(meta, dict) and meta.get("poster_url"):
            poster_map[r.get("_id")] = meta["poster_url"]

    # Add exact matches to results
    for result in exact_results:
        title = result.get('title', 'Unknown')
        year = result.get('year', '')
        quality = result.get('quality', '')

        # /search-style bracket info (same dot-joined formatter as the
        # results list): "The Matrix [1080p.1999]"
        display_text = f"{title} [{format_search_info(result)}]"

        results.append(
            InlineQueryResultArticle(
                title=display_text,
                description=f"Quality: {quality or 'N/A'} | Year: {year or 'N/A'}",
                input_message_content=InputTextMessageContent(
                    f"🎬 **{title}**\n"
                    f"📅 Year: {year or 'N/A'}\n"
                    f"🎞️ Quality: {quality or 'N/A'}\n"
                    f"📺 Channel: {result.get('channel_title', 'N/A')}"                    ),
                thumbnail_url=poster_map.get(result.get('_id')),
                id=f"movie_{result.get('_id')}"
            )
        )
    
    # If we have less than 5 exact results, add fuzzy matches
    if len(exact_results) < 5:
        fuzzy_cursor = movies_col.find({}).limit(50)
        all_movies = await fuzzy_cursor.to_list(length=50)
        
        # Calculate fuzzy scores
        fuzzy_candidates = []
        for movie in all_movies:
            # Skip if already in exact results
            if any(exact.get('_id') == movie.get('_id') for exact in exact_results):
                continue
                
            title = movie.get('title', '')
            score = fuzz.partial_ratio(query.lower(), title.lower())
            if score >= FUZZY_THRESHOLD:
                fuzzy_candidates.append((score, movie))
        
        # Sort by score and take top matches
        fuzzy_candidates.sort(key=lambda x: x[0], reverse=True)
        
        for score, movie in fuzzy_candidates[:5]:  # Take top 5 fuzzy matches
            title = movie.get('title', 'Unknown')
            year = movie.get('year', '')
            quality = movie.get('quality', '')

            # /search-style bracket info with the ~ fuzzy-match marker
            display_text = f"{title} [{format_search_info(movie)}]"

            results.append(
                InlineQueryResultArticle(
                    title=f"~{display_text}",  # Add ~ to indicate fuzzy match
                    description=f"Quality: {quality or 'N/A'} | Year: {year or 'N/A'} | Match: {score}%",
                    input_message_content=InputTextMessageContent(
                        f"🎬 **{title}**\n"
                        f"📅 Year: {year or 'N/A'}\n"
                        f"🎞️ Quality: {quality or 'N/A'}\n"
                        f"📺 Channel: {movie.get('channel_title', 'N/A')}\n"
                        f"🔍 Fuzzy Match: {score}%"
                    ),
                    thumbnail_url=None,
                    id=f"fuzzy_{movie.get('_id')}"
                )
            )
    
    # Answer the inline query
    if results:
        await client.answer_inline_query(inline_query.id, results, cache_time=300)
    else:
        # No results found
        await client.answer_inline_query(
            inline_query.id,
            [
                InlineQueryResultArticle(
                    title="No Results",
                    description=f"No movies found for '{query}'",
                    input_message_content=InputTextMessageContent(
                        f"🔍 **No Results Found**\n\n"
                        f"No movies found matching '{query}'.\n\n"
                        f"💡 Try:\n"
                        f"• Different keywords\n"
                        f"• Partial titles\n"
                        f"• Check spelling"
                    ),
                    id="no_results"
                )
            ],
            cache_time=60
        )
