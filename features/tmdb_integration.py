"""
TMDb API Integration Module

This module handles all interactions with The Movie Database (TMDb) API
for searching movies and TV series.
"""

import aiohttp
from typing import List, Dict, Optional
from .config import TMDB_API


TMDB_BASE_URL = "https://api.themoviedb.org/3"


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

