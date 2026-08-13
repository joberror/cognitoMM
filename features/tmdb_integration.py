"""
TMDb API Integration Module

This module handles all interactions with The Movie Database (TMDb) API
for searching movies and TV series.
"""

import os
import aiohttp
from typing import List, Dict, Optional
from datetime import datetime, timedelta
from .config import TMDB_API
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

        # Create link
        if imdb_id:
            link = f"[IMDB](https://imdb.com/title/{imdb_id})"
        elif tmdb_id:
            media_type = "tv" if category == "shows" else "movie"
            link = f"[TMDB](https://themoviedb.org/{media_type}/{tmdb_id})"
        else:
            link = "N/A"

        if category == "releases":
            release_display = item.get("release_display", "N/A")
            lines.append(f"{i}. `{title}` - {rating}, {release_display}, {link}")
        else:
            year = item.get("year", "N/A")
            lines.append(f"{i}. `{title}` - {year}, {rating}, {link}")

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

