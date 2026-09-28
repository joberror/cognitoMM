"""
TMDb API Integration Module

This module handles all interactions with The Movie Database (TMDb) API
for searching movies and TV series.
"""

import os
import re
import asyncio
import aiohttp
from typing import List, Dict, Optional
from datetime import datetime, timedelta
from .config import TMDB_API, WATCHLIST_IN_CINEMAS_DAYS
from fuzzywuzzy import fuzz
import random


TMDB_BASE_URL = "https://api.themoviedb.org/3"
TMDB_IMAGE_BASE = "https://image.tmdb.org/t/p/w500"

# Enrich new indexed entries with TMDb metadata (poster/genres/rating) when a
# TMDB_API key is configured. Set TMDB_ENRICH_INDEX=false to disable.
TMDB_ENRICH_INDEX = os.getenv("TMDB_ENRICH_INDEX", "true").lower() in ("1", "true", "yes")

# Cache for trending data (session-based)
_trending_cache = {
    "movies": {"data": None, "expires": None},
    "shows": {"data": None, "expires": None},
    "releases": {"data": None, "expires": None}
}
CACHE_TTL_MINUTES = 30


def get_cached_trending(category: str) -> Optional[List[Dict]]:
    """Get cached trending data if valid"""
    cache = _trending_cache.get(category)
    if cache and cache["data"] and cache["expires"]:
        if datetime.now() < cache["expires"]:
            return cache["data"]
    return None


def set_cached_trending(category: str, data: List[Dict]):
    """Set trending data in cache"""
    _trending_cache[category] = {
        "data": data,
        "expires": datetime.now() + timedelta(minutes=CACHE_TTL_MINUTES)
    }


async def search_tmdb(title: str, year: str, content_type: str) -> List[Dict]:
    """
    Search TMDb for movies or TV series
    
    Args:
        title: The title to search for
        year: The release year
        content_type: "Movie" or "Series"
    
    Returns:
        List of up to 5 results with title, year, overview, and IMDB ID
    """
    if not TMDB_API or TMDB_API == "your_api_key_here":
        return []
    
    # Determine endpoint based on content type
    endpoint = "movie" if content_type == "Movie" else "tv"
    search_url = f"{TMDB_BASE_URL}/search/{endpoint}"
    
    params = {
        "api_key": TMDB_API,
        "query": title,
        "language": "en-US",
        "page": 1
    }
    
    # Add year filter if provided
    if year and year.isdigit():
        if content_type == "Movie":
            params["year"] = year
        else:
            params["first_air_date_year"] = year
    
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(search_url, params=params, timeout=10) as response:
                if response.status != 200:
                    print(f"TMDb API error: {response.status}")
                    return []
                
                data = await response.json()
                results = data.get("results", [])
                
                # Process and format results
                formatted_results = []
                for item in results[:5]:  # Limit to top 5
                    # Get IMDB ID
                    imdb_id = await get_imdb_id(item.get("id"), endpoint)
                    
                    # Extract relevant data
                    result = {
                        "tmdb_id": item.get("id"),
                        "title": item.get("title") if content_type == "Movie" else item.get("name"),
                        "year": extract_year(item, content_type),
                        "overview": item.get("overview", "No overview available")[:150],  # Truncate
                        "imdb_id": imdb_id
                    }
                    
                    formatted_results.append(result)
                
                return formatted_results
    
    except aiohttp.ClientError as e:
        print(f"TMDb API connection error: {e}")
        return []
    except Exception as e:
        print(f"TMDb API error: {e}")
        return []


async def get_imdb_id(tmdb_id: int, content_type: str) -> Optional[str]:
    """
    Get IMDB ID from TMDb ID
    
    Args:
        tmdb_id: TMDb ID
        content_type: "movie" or "tv"
    
    Returns:
        IMDB ID (e.g., "tt1234567") or None
    """
    if not TMDB_API or TMDB_API == "your_api_key_here":
        return None
    
    details_url = f"{TMDB_BASE_URL}/{content_type}/{tmdb_id}/external_ids"
    
    params = {
        "api_key": TMDB_API
    }
    
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(details_url, params=params, timeout=10) as response:
                if response.status != 200:
                    return None
                
                data = await response.json()
                return data.get("imdb_id")
    
    except Exception as e:
        print(f"Error fetching IMDB ID: {e}")
        return None


def extract_year(item: Dict, content_type: str) -> str:
    """
    Extract year from TMDb result
    
    Args:
        item: TMDb result item
        content_type: "Movie" or "Series"
    
    Returns:
        Year as string or "N/A"
    """
    if content_type == "Movie":
        date_str = item.get("release_date", "")
    else:
        date_str = item.get("first_air_date", "")
    
    if date_str and len(date_str) >= 4:
        return date_str[:4]
    
    return "N/A"


def format_tmdb_result(result: Dict, index: int) -> str:
    """
    Format a single TMDb result as a one-liner

    Args:
        result: TMDb result dictionary
        index: Result number (1-5)

    Returns:
        Formatted one-liner string
    """
    title = result.get("title", "Unknown")
    year = result.get("year", "N/A")
    overview = result.get("overview", "")[:80]  # Truncate to 80 chars

    # Create one-liner format
    return f"{index}. {title} ({year}) - {overview}..."


# ------------------------------------------------------------------ #
#  Release status (movies + series) for /watch                         #
# ------------------------------------------------------------------ #

# The four user-facing states. Movies get the first three, series the last two.
STATUS_RELEASED = "Released"      # movie: out on digital/physical
STATUS_UPCOMING = "Upcoming"      # movie: announced / in production
STATUS_IN_CINEMAS = "In Cinemas"  # movie: in a limited/premiere theatrical run
STATUS_CONTINUING = "Continuing"  # series: more seasons expected
STATUS_ENDED = "Ended"            # series: no more seasons planned
STATUS_UNKNOWN = "Unknown"        # TMDb unavailable or no data

# TMDb's own `status` strings we treat as "already out".
_MOVIE_RELEASED_TMDB = ("released",)
# TMDb series `status` values that mean the show is finished.
_SERIES_ENDED_TMDB = ("ended", "canceled")
# Release-date types from /movie/{id}/release_dates. A film that only has a
# Premiere (1) or a limited Theatrical (2) entry is still in its festival /
# platform-premiere run; a wide Theatrical (3) entry means it's in cinemas.
_RD_PREMERE = 1
_RD_THEATRICAL_LIMITED = 2
_RD_THEATRICAL = 3
_RD_WIDE_TYPES = (_RD_THEATRICAL,)


def normalize_content_type(raw) -> str:
    """Coerce a stored/parsed type into ``"Movie"`` or ``"Series"``.

    The indexer stores ``Movie``/``Series`` but metadata parsers and TMDb also
    emit ``TV``, ``tv``, ``show`` and ``Movie/Series`` hybrids, so every watch
    entry passes through here to keep one spelling in the database.
    """
    text = str(raw or "").strip().lower()
    if not text:
        return "Movie"
    # Word-ish match so compound spellings land too ("TV Series", "tv_show",
    # "Movie/Series"); "show"/"anime" are series even though they lack
    # "series".
    if "series" in text or re.search(r"\b(tv|show|anime)\b", text) or "tv_show" in text:
        return "Series"
    return "Movie"


def _parse_tmdb_date(value):
    """Parse a TMDb ``YYYY-MM-DD`` (or shorter) date into a ``date`` or None."""
    from datetime import date as _date

    if not value:
        return None
    text = str(value).strip()
    if len(text) < 10:
        text = f"{text}-01-01" if len(text) == 7 else text
    try:
        return _date.fromisoformat(text[:10])
    except ValueError:
        return None


def derive_movie_status(release_date=None, tmdb_status=None,
                        theatrical_types=None, today=None) -> str:
    """Movie state from TMDb's ``release_date`` + ``status`` + release types.

    ``theatrical_types`` is the set of release-type ids from the
    ``/release_dates`` endpoint (3 = wide theatrical, 2 = limited, 1 =
    premiere). A film is *In Cinemas* while it has no wide-theatrical release
    yet but is already out somewhere and its earliest theatrical date is
    within ``WATCHLIST_IN_CINEMAS_DAYS`` — that is the festival / limited-run
    window before a wide rollout. Past that window we call it Released, since
    by then the wide release has happened even if TMDb never listed it.

    Falls back to the calendar when the release-types call is unavailable: a
    ``Released`` film dated in the future is treated as Upcoming rather than
    claiming a theatrical run we have no evidence for.
    """
    from datetime import date as _date, timedelta

    today = today or _date.today()
    released = str(tmdb_status or "").strip().lower() in _MOVIE_RELEASED_TMDB
    dt = _parse_tmdb_date(release_date)

    if not released:
        # TMDb marks unreleased films Post Production / In Production / Planned.
        # One exception: a film dated in the past but not yet flagged Released
        # is out (TMDb lags a few days behind wide releases), so treat it as
        # released rather than telling users an old film is "upcoming".
        if dt is not None and dt <= today:
            return STATUS_RELEASED
        return STATUS_UPCOMING

    if dt is not None and dt > today:
        # "Released" with a future date is TMDb pre-announcing the release.
        return STATUS_UPCOMING

    if theatrical_types is None:
        # No release_dates data — released, date in the past, nothing to add.
        return STATUS_RELEASED

    wide = bool(set(theatrical_types) & set(_RD_WIDE_TYPES))
    limited = set(theatrical_types) & {_RD_PREMERE, _RD_THEATRICAL_LIMITED}
    if not wide and limited and dt is not None:
        if dt >= today - timedelta(days=WATCHLIST_IN_CINEMAS_DAYS):
            return STATUS_IN_CINEMAS
    return STATUS_RELEASED


def derive_series_status(last_air_date=None, tmdb_status=None, next_episode=None,
                         today=None) -> str:
    """Series state: Continuing while more seasons are expected, else Ended.

    TMDb's ``status`` is authoritative (``Returning Series`` / ``In
    Production`` → Continuing, ``Ended`` / ``Canceled`` → Ended). The
    ``next_air_date``/``next_episode`` fields override it: an announced next
    season means Continuing even if the status hasn't flipped yet, and a show
    that already aired its finale with nothing announced is Ended.
    """
    text = str(tmdb_status or "").strip().lower()
    if text in _SERIES_ENDED_TMDB:
        # TMDb says finished, but a confirmed next episode wins (status lags
        # renewals by a season or two).
        if next_episode:
            return STATUS_CONTINUING
        return STATUS_ENDED
    if text:
        return STATUS_CONTINUING

    # No status from TMDb — infer from air dates so a partial payload still
    # renders something sensible.
    from datetime import date as _date, timedelta

    today = today or _date.today()
    if next_episode:
        return STATUS_CONTINUING
    dt = _parse_tmdb_date(last_air_date)
    if dt is None:
        return STATUS_UNKNOWN
    # Long-finished with nothing upcoming reads as Ended; recently airing
    # reads as Continuing.
    if today - dt > timedelta(days=365):
        return STATUS_ENDED
    return STATUS_CONTINUING


async def get_movie_release_types(tmdb_id: int) -> Optional[set]:
    """Set of release-type ids for a movie, or None when unavailable.

    Used only to separate "In Cinemas" from "Released"; a failure here just
    means the caller falls back to the calendar-only decision.
    """
    if not TMDB_API or TMDB_API == "your_api_key_here" or not tmdb_id:
        return None
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(
                f"{TMDB_BASE_URL}/movie/{tmdb_id}/release_dates",
                params={"api_key": TMDB_API},
                timeout=10,
            ) as response:
                if response.status != 200:
                    return None
                data = await response.json()
    except Exception as e:
        print(f"TMDb release_dates error: {e}")
        return None
    types = set()
    for country in (data or {}).get("results") or []:
        for release in country.get("release_dates") or []:
            if release.get("type") is not None:
                types.add(int(release["type"]))
    return types or None


async def fetch_title_status(tmdb_id: int, content_type: str = "Movie") -> Dict:
    """Fetch TMDb details for a title and derive its watch status.

    Returns a dict with ``status`` (one of the STATUS_* constants), plus the
    identity fields the watchlist stores: ``title``, ``year``, ``type``,
    ``imdb_id``, and ``seasons``/``episodes`` for series. Returns ``{}`` when
    TMDb is unconfigured or the lookup fails, so callers can keep the stored
    value instead of blanking it.
    """
    ctype = normalize_content_type(content_type)
    if not TMDB_API or TMDB_API == "your_api_key_here" or not tmdb_id:
        return {}
    endpoint = "movie" if ctype == "Movie" else "tv"

    details = None
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(
                f"{TMDB_BASE_URL}/{endpoint}/{tmdb_id}",
                params={"api_key": TMDB_API, "language": "en-US"},
                timeout=10,
            ) as response:
                if response.status == 200:
                    details = await response.json()
    except Exception as e:
        print(f"TMDb status details error: {e}")
        return {}
    if not details:
        return {}

    if ctype == "Movie":
        release_types = await get_movie_release_types(tmdb_id)
        status = derive_movie_status(
            release_date=details.get("release_date"),
            tmdb_status=details.get("status"),
            theatrical_types=release_types,
        )
        out = {
            "title": details.get("title") or details.get("original_title"),
            "year": extract_year({"release_date": details.get("release_date")}, "Movie"),
            "type": "Movie",
            "imdb_id": details.get("imdb_id"),
            "status": status,
            "poster_url": (TMDB_IMAGE_BASE + details["poster_path"])
            if details.get("poster_path") else None,
            "rating": round(details.get("vote_average", 0) or 0, 1),
            "overview": (details.get("overview") or "")[:200],
        }
        return out

    status = derive_series_status(
        last_air_date=details.get("last_air_date"),
        tmdb_status=details.get("status"),
        next_episode=details.get("next_episode_to_air"),
    )
    return {
        "title": details.get("name") or details.get("original_name"),
        "year": extract_year({"first_air_date": details.get("first_air_date")}, "Series"),
        "type": "Series",
        "imdb_id": details.get("imdb_id"),
        "status": status,
        "seasons": details.get("number_of_seasons"),
        "episodes": details.get("number_of_episodes"),
        "poster_url": (TMDB_IMAGE_BASE + details["poster_path"])
        if details.get("poster_path") else None,
        "rating": round(details.get("vote_average", 0) or 0, 1),
        "overview": (details.get("overview") or "")[:200],
    }


async def search_watch_candidates(title: str, year=None, limit: int = 5) -> List[Dict]:
    """Search both TMDb movie and tv endpoints for watchlist candidates.

    A watch target is a *film or a show* and the user rarely says which, so we
    query both and merge. Each candidate carries everything needed to save it
    without a second round-trip: ``tmdb_id``, ``title``, ``year``, ``type``,
    ``imdb_id``, ``status`` and ``poster_url``.

    Results are ranked best-first: exact title matches, then popularity, so the
    disambiguation picker shows the most likely intent at the top.
    """
    if not TMDB_API or TMDB_API == "your_api_key_here" or not title:
        return []

    async def _collect(endpoint: str, ctype: str) -> List[Dict]:
        params = {"api_key": TMDB_API, "query": title, "language": "en-US", "page": 1}
        if year and str(year).isdigit():
            params["year" if endpoint == "movie" else "first_air_date_year"] = str(year)
        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(
                    f"{TMDB_BASE_URL}/search/{endpoint}", params=params, timeout=10
                ) as response:
                    if response.status != 200:
                        return []
                    data = await response.json()
        except Exception as e:
            print(f"TMDb watch search error ({endpoint}): {e}")
            return []

        out = []
        for item in (data or {}).get("results") or []:
            item_title = item.get("title") if endpoint == "movie" else item.get("name")
            if not item_title:
                continue
            release_date = (item.get("release_date") if endpoint == "movie"
                            else item.get("first_air_date"))
            out.append({
                "tmdb_id": item.get("id"),
                "title": item_title,
                "original_title": item.get("original_title") or item.get("original_name"),
                "year": extract_year({("release_date" if endpoint == "movie"
                                        else "first_air_date"): release_date}, ctype),
                "type": ctype,
                "imdb_id": None,
                "poster_url": (TMDB_IMAGE_BASE + item["poster_path"])
                if item.get("poster_path") else None,
                "overview": (item.get("overview") or "")[:120],
                "popularity": item.get("popularity") or 0,
            })
        return out

    movie_results, tv_results = await asyncio.gather(
        _collect("movie", "Movie"), _collect("tv", "Series"))

    # The search endpoint returns no imdb_id, so fetch it for the candidates
    # we actually show (bounded by `limit`).
    candidates = _rank_watch_candidates(title, movie_results + tv_results, limit)
    for cand in candidates:
        if not cand.get("imdb_id"):
            cand["imdb_id"] = await get_imdb_id(
                cand["tmdb_id"], "movie" if cand["type"] == "Movie" else "tv")

    # Fill in status for the shown candidates. Done after ranking so we only
    # spend API calls on what the user will actually see.
    for cand in candidates:
        if cand.get("status"):
            continue
        detail = await fetch_title_status(cand["tmdb_id"], cand["type"])
        if detail.get("status"):
            cand["status"] = detail["status"]
        if not cand.get("year") or cand["year"] == "N/A":
            if detail.get("year"):
                cand["year"] = detail["year"]
        if not cand.get("poster_url") and detail.get("poster_url"):
            cand["poster_url"] = detail["poster_url"]
    return candidates


def _rank_watch_candidates(query: str, candidates: List[Dict], limit: int) -> List[Dict]:
    """Order candidates best-first: exact title, then popularity, then year."""
    wanted = str(query or "").strip().lower()

    def sort_key(c):
        name = str(c.get("title") or "").strip().lower()
        orig = str(c.get("original_title") or "").strip().lower()
        if name == wanted or orig == wanted:
            tier = 0
        elif fuzz.partial_ratio(wanted, name) >= 90:
            tier = 1
        else:
            tier = 2
        return (tier, -(c.get("popularity") or 0), str(c.get("year") or ""))

    ranked = sorted(candidates, key=sort_key)
    # Drop duplicates TMDb returns for the same film across the two searches.
    seen, out = set(), []
    for cand in ranked:
        key = (cand.get("type"), cand.get("tmdb_id"))
        if key in seen:
            continue
        seen.add(key)
        out.append(cand)
    return out[:limit]


def is_ambiguous_title(query: str, candidates: List[Dict]) -> bool:
    """True when a query needs the user to disambiguate.

    We only auto-pick when there is exactly one plausible match whose title
    actually matches the query. Anything else (several remakes, a movie and a
    show with the same name, a fuzzy match) goes to the picker so the user
    never gets silently subscribed to the wrong film.
    """
    if not candidates:
        return False
    if len(candidates) > 1:
        return True
    cand = candidates[0]
    wanted = str(query or "").strip().lower()
    name = str(cand.get("title") or "").strip().lower()
    orig = str(cand.get("original_title") or "").strip().lower()
    if name == wanted or orig == wanted:
        # A unique exact match: auto-pick unless it is a Series, where the
        # user may have meant the identically-titled film.
        if cand.get("type") == "Series":
            return True
        return False
    # A single non-exact match still needs confirmation.
    return True


async def get_trending_movies(time_window: str = "week", use_cache: bool = True) -> List[Dict]:
    """
    Get trending movies from TMDb

    Args:
        time_window: "day" or "week"
        use_cache: Whether to use cached data if available

    Returns:
        List of top 10 trending movies
    """
    # Check cache first
    if use_cache:
        cached = get_cached_trending("movies")
        if cached:
            return cached

    if not TMDB_API or TMDB_API == "your_api_key_here":
        return []

    url = f"{TMDB_BASE_URL}/trending/movie/{time_window}"
    params = {"api_key": TMDB_API, "language": "en-US"}

    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(url, params=params, timeout=10) as response:
                if response.status != 200:
                    return []

                data = await response.json()
                results = data.get("results", [])[:10]

                formatted = []
                for item in results:
                    imdb_id = await get_imdb_id(item.get("id"), "movie")
                    release_date = item.get("release_date", "")
                    year = release_date[:4] if release_date else "N/A"

                    formatted.append({
                        "title": item.get("title", "Unknown"),
                        "year": year,
                        "rating": round(item.get("vote_average", 0), 1),
                        "imdb_id": imdb_id,
                        "tmdb_id": item.get("id")
                    })

                # Cache the results
                set_cached_trending("movies", formatted)
                return formatted
    except Exception as e:
        print(f"Error fetching trending movies: {e}")
        return []


async def get_trending_shows(time_window: str = "week", use_cache: bool = True) -> List[Dict]:
    """
    Get trending TV shows from TMDb

    Args:
        time_window: "day" or "week"
        use_cache: Whether to use cached data if available

    Returns:
        List of top 10 trending shows
    """
    # Check cache first
    if use_cache:
        cached = get_cached_trending("shows")
        if cached:
            return cached

    if not TMDB_API or TMDB_API == "your_api_key_here":
        return []

    url = f"{TMDB_BASE_URL}/trending/tv/{time_window}"
    params = {"api_key": TMDB_API, "language": "en-US"}

    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(url, params=params, timeout=10) as response:
                if response.status != 200:
                    return []

                data = await response.json()
                results = data.get("results", [])[:10]

                formatted = []
                for item in results:
                    imdb_id = await get_imdb_id(item.get("id"), "tv")
                    first_air = item.get("first_air_date", "")
                    year = first_air[:4] if first_air else "N/A"

                    formatted.append({
                        "title": item.get("name", "Unknown"),
                        "year": year,
                        "rating": round(item.get("vote_average", 0), 1),
                        "imdb_id": imdb_id,
                        "tmdb_id": item.get("id")
                    })

                # Cache the results
                set_cached_trending("shows", formatted)
                return formatted
    except Exception as e:
        print(f"Error fetching trending shows: {e}")
        return []


async def get_new_releases(use_cache: bool = True) -> List[Dict]:
    """
    Get new movie releases (now playing and upcoming)

    Args:
        use_cache: Whether to use cached data if available

    Returns:
        List of top 10 new releases
    """
    # Check cache first
    if use_cache:
        cached = get_cached_trending("releases")
        if cached:
            return cached

    if not TMDB_API or TMDB_API == "your_api_key_here":
        return []

    url = f"{TMDB_BASE_URL}/movie/now_playing"
    params = {"api_key": TMDB_API, "language": "en-US", "region": "US"}

    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(url, params=params, timeout=10) as response:
                if response.status != 200:
                    return []

                data = await response.json()
                results = data.get("results", [])[:10]

                today = datetime.now().date()
                formatted = []

                for item in results:
                    imdb_id = await get_imdb_id(item.get("id"), "movie")
                    release_date_str = item.get("release_date", "")

                    # Determine release status
                    release_display = "N/A"
                    if release_date_str:
                        try:
                            release_date = datetime.strptime(release_date_str, "%Y-%m-%d").date()
                            if release_date > today:
                                release_display = "Cinema"
                            else:
                                release_display = release_date.strftime("%d/%m")
                        except ValueError:
                            release_display = "N/A"

                    formatted.append({
                        "title": item.get("title", "Unknown"),
                        "rating": round(item.get("vote_average", 0), 1),
                        "release_display": release_display,
                        "imdb_id": imdb_id,
                        "tmdb_id": item.get("id")
                    })

                # Cache the results
                set_cached_trending("releases", formatted)
                return formatted
    except Exception as e:
        print(f"Error fetching new releases: {e}")
        return []


def format_trending_list(items: List[Dict], category: str) -> str:
    """
    Format trending list for display

    Args:
        items: List of trending items
        category: "movies", "shows", or "releases"

    Returns:
        Formatted string for display
    """
    if not items:
        return "No data available."

    lines = []

    for i, item in enumerate(items, 1):
        title = item.get("title", "Unknown")
        rating = item.get("rating", 0)
        imdb_id = item.get("imdb_id")
        tmdb_id = item.get("tmdb_id")

        # Create link (kept clickable - NOT wrapped in a code block, since
        # markdown links don't render inside code fences)
        if imdb_id:
            link = f"[IMDb](https://imdb.com/title/{imdb_id})"
        elif tmdb_id:
            media_type = "tv" if category == "shows" else "movie"
            link = f"[TMDB](https://themoviedb.org/{media_type}/{tmdb_id})"
        else:
            link = "N/A"

        # /search-style line: N. Title [year] ⭐rating · link
        year = item.get("year") or item.get("release_display") or "N/A"
        rating_part = f" ⭐{rating}" if rating else ""
        lines.append(f"{i}. {title} [{year}]{rating_part} · {link}")

    return "\n".join(lines)


# ------------------------------------------------------------------ #
#  Title enrichment (posters, genres, ratings for indexed/search content) #
# ------------------------------------------------------------------ #

# TTL cache keyed by (content_type|title|year) so repeat displays and
# per-episode series indexing only cost one TMDb lookup per unique title.
_enrich_cache: Dict[str, dict] = {}
_ENRICH_CACHE_TTL = timedelta(hours=6)


def _enrich_key(title: str, year=None, content_type: str = "Movie") -> str:
    return f"{(content_type or 'Movie').lower()}|{str(title or '').strip().lower()}|{year or ''}"


def get_cached_enrichment(title: str, year=None, content_type: str = "Movie") -> Optional[Dict]:
    """Return cached enrichment data if still fresh, else None."""
    item = _enrich_cache.get(_enrich_key(title, year, content_type))
    if item and item.get("expires") and datetime.now() < item["expires"]:
        return item["data"]
    return None


def set_cached_enrichment(title: str, year=None, content_type: str = "Movie", data=None):
    """Cache enrichment data (data=None caches a miss so we don't re-hit TMDb)."""
    _enrich_cache[_enrich_key(title, year, content_type)] = {
        "data": data,
        "expires": datetime.now() + _ENRICH_CACHE_TTL,
    }


async def enrich_title(title: str, year=None, content_type: str = "Movie", use_cache: bool = True) -> Optional[Dict]:
    """
    Fetch TMDb details (poster, rating, genres, overview, imdb_id) for a title.

    Uses the TMDb search endpoint (title+year) then the details endpoint (genre
    names, overview). Results are cached per title+year for 6 hours.

    Returns a dict or None when the API is unconfigured, nothing matches, or
    the network fails - callers must tolerate None.
    """
    if not TMDB_API or TMDB_API == "your_api_key_here" or not title:
        return None

    if use_cache:
        cached = get_cached_enrichment(title, year, content_type)
        if cached is not None:
            return cached

    endpoint = "movie" if (content_type or "Movie") == "Movie" else "tv"
    params = {"api_key": TMDB_API, "query": title, "language": "en-US", "page": 1}
    if year and str(year).isdigit():
        if endpoint == "movie":
            params["year"] = str(year)
        else:
            params["first_air_date_year"] = str(year)

    data = None
    try:
        async with aiohttp.ClientSession() as session:
            for attempt in range(3):
                async with session.get(f"{TMDB_BASE_URL}/search/{endpoint}", params=params, timeout=10) as response:
                    if response.status == 200:
                        data = await response.json()
                        break
                    # Non-200 (typically 429 rate limit on bulk backfills) - back
                    # off and retry so throttled titles aren't counted as misses.
                    if attempt < 2:
                        await asyncio.sleep(1.5 * (attempt + 1))
    except Exception as e:
        # Network/API error: do NOT cache a miss (6h TTL would block re-enriching
        # a title after a transient outage). Only genuine no-results are cached.
        print(f"TMDb enrich search error: {e}")
        return None

    results = (data or {}).get("results", [])
    if not results:
        # Genuine no-match - cache the miss so we don't re-hit TMDb repeatedly.
        set_cached_enrichment(title, year, content_type, None)
        return None

    item = results[0]
    tmdb_id = item.get("id")

    # Details call for genre names + full overview (search results only carry
    # numeric genre ids).
    details = None
    try:
        async with aiohttp.ClientSession() as session:
            for attempt in range(3):
                async with session.get(
                    f"{TMDB_BASE_URL}/{endpoint}/{tmdb_id}",
                    params={"api_key": TMDB_API, "language": "en-US"},
                    timeout=10,
                ) as response:
                    if response.status == 200:
                        details = await response.json()
                        break
                    if attempt < 2:
                        await asyncio.sleep(1.5 * (attempt + 1))
    except Exception as e:
        print(f"TMDb enrich details error: {e}")
        # Details failure is not a no-match - skip caching so a later call can
        # pick up genre names/overview once the API recovers.
        return None

    source = details or item
    # The details response includes imdb_id directly - no extra external_ids
    # call needed (saves 1/3 of the API calls on bulk enrichment runs).
    imdb_id = source.get("imdb_id") or (await get_imdb_id(tmdb_id, endpoint) if not details else None)

    enrichment = {
        "poster_url": (TMDB_IMAGE_BASE + item["poster_path"]) if item.get("poster_path") else None,
        "rating": round(source.get("vote_average", 0) or 0, 1),
        "genres": [g.get("name") for g in (source.get("genres") or []) if g.get("name")],
        "overview": (source.get("overview") or "")[:200],
        "imdb_id": imdb_id,
        "tmdb_id": tmdb_id,
    }
    if endpoint == "tv":
        # Real TMDb totals so listings can show DB counts vs the real ones
        # (e.g. ``3 seasons [5], 20 eps [35]``).
        enrichment["seasons"] = source.get("number_of_seasons")
        enrichment["episodes"] = source.get("number_of_episodes")
    set_cached_enrichment(title, year, content_type, enrichment)
    return enrichment


def format_enrichment_line(meta: Optional[Dict]) -> str:
    """One-line enrichment suffix: ⭐ rating · 🎭 genres · IMDb link."""
    if not meta:
        return ""
    parts = []
    if meta.get("rating"):
        parts.append(f"⭐ {meta['rating']}")
    if meta.get("genres"):
        parts.append(f"🎭 {', '.join(meta['genres'][:3])}")
    line = " · ".join(parts)
    if meta.get("imdb_id"):
        line += f" · [IMDb](https://imdb.com/title/{meta['imdb_id']})"
    return line


async def get_random_background_image() -> Optional[str]:
    """Get a random background image from trending movies"""
    if not TMDB_API:
        return None
        
    url = f"{TMDB_BASE_URL}/trending/movie/week"
    params = {"api_key": TMDB_API}
    
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(url, params=params, timeout=5) as response:
                if response.status == 200:
                    data = await response.json()
                    results = data.get("results", [])
                    if results:
                        # Filter results with backdrop
                        valid_results = [r for r in results if r.get("backdrop_path")]
                        if valid_results:
                            item = random.choice(valid_results)
                            return f"https://image.tmdb.org/t/p/original{item['backdrop_path']}"
    except Exception as e:
        print(f"Error fetching background image: {e}")
        
    return None

