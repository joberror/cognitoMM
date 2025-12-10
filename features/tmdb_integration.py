"""
TMDb API Integration Module

This module handles all interactions with The Movie Database (TMDb) API
for searching movies and TV series.
"""

import aiohttp
from typing import List, Dict, Optional
from datetime import datetime, timedelta
from .config import TMDB_API


TMDB_BASE_URL = "https://api.themoviedb.org/3"

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

