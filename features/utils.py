"""
Utility Functions Module

This module contains various utility functions used throughout the Movie Bot application,
including file management, time formatting, and helper functions.
"""

import asyncio
import html
from datetime import datetime, timezone

async def wait_for_user_input(chat_id: int, user_id: int, timeout: int = 60):
    """Wait for user input - replacement for client.listen"""
    from .config import user_input_events
    key = f"{chat_id}_{user_id}"
    event = asyncio.Event()
    user_input_events[key] = {'event': event, 'message': None}

    try:
        await asyncio.wait_for(event.wait(), timeout=timeout)
        return user_input_events[key]['message']
    except asyncio.TimeoutError:
        raise asyncio.TimeoutError("User input timeout")
    finally:
        # Clean up
        if key in user_input_events:
            del user_input_events[key]

def set_user_input(chat_id: int, user_id: int, message):
    """Set user input message - called from message handler"""
    from .config import user_input_events
    key = f"{chat_id}_{user_id}"
    if key in user_input_events:
        user_input_events[key]['message'] = message
        user_input_events[key]['event'].set()

async def cleanup_expired_bulk_downloads(bulk_downloads=None):
    """Remove bulk downloads older than 1 hour.

    Accepts an explicit dict for callers that already hold a reference (e.g.
    search.py passes the shared config.bulk_downloads); when called with no
    argument it operates on the shared config.bulk_downloads dict. This was
    previously duplicated with a conflicting signature in file_deletion.py.
    """
    if bulk_downloads is None:
        from .config import bulk_downloads

    current_time = datetime.now(timezone.utc)
    expired_keys = []

    for bulk_id, data in bulk_downloads.items():
        if (current_time - data['created_at']).total_seconds() > 3600:  # 1 hour
            expired_keys.append(bulk_id)

    for key in expired_keys:
        del bulk_downloads[key]

    if expired_keys:
        print(f"🧹 Cleaned up {len(expired_keys)} expired bulk downloads")

def get_readable_time(seconds):
    """Convert seconds to readable time format"""
    periods = [('d', 86400), ('h', 3600), ('m', 60), ('s', 1)]
    result = ''
    for period_name, period_seconds in periods:
        if seconds >= period_seconds:
            period_value, seconds = divmod(seconds, period_seconds)
            result += f'{int(period_value)}{period_name}'
    return result

def format_file_size(size_bytes):
    """Convert bytes to human readable format (GB, MB, KB)"""
    if not size_bytes or size_bytes == 0:
        return "N/A"

    # Convert to appropriate unit
    if size_bytes >= 1024**3:  # GB
        return f"{size_bytes / (1024**3):.1f}GB"
    elif size_bytes >= 1024**2:  # MB
        return f"{size_bytes / (1024**2):.0f}MB"
    elif size_bytes >= 1024:  # KB
        return f"{size_bytes / 1024:.0f}KB"
    else:
        return f"{size_bytes}B"

# Access-control helpers (check_banned, check_terms_acceptance,
# load_terms_and_privacy, should_process_command, require_not_banned,
# should_process_command_for_user) are canonical in user_management.py.
# Re-export them so existing importers keep working with a single
# implementation. The versions previously defined here diverged (local
# DB imports vs module-level, wrong chat-type comparisons, an
# unconditional group-command bypass).
from .user_management import (
    should_process_command,
    require_not_banned,
    should_process_command_for_user,
    load_terms_and_privacy,
    check_banned,
    check_terms_acceptance,
)

def group_recent_content(results):
    """Group database results by title with quality/episode consolidation and categorization"""
    # Use dictionaries to group by title first
    movies_dict = {}
    series_dict = {}

    for item in results:
        # Skip items without required fields
        if not item.get('title') or not item.get('type'):
            continue

        title = item.get('title', 'Unknown')
        content_type = item.get('type', 'Movie').lower()
        year = item.get('year')

        # Determine which dictionary to use
        target_dict = series_dict if content_type in ['series', 'tv', 'show'] else movies_dict

        # Initialize group data if title not seen before
        if title not in target_dict:
            target_dict[title] = {
                'title': title,
                'type': content_type,
                'year': year,
                'qualities': set(),
                'seasons_episodes': [],
                'count': 0
            }

        # Update existing group data
        group_data = target_dict[title]

        # Add quality if available
        quality = item.get('quality')
        if quality:
            group_data['qualities'].add(quality.upper())

        # Collect season/episode info for series
        if content_type in ['series', 'tv', 'show']:
            season = item.get('season')
            episode = item.get('episode')
            if season and episode:
                group_data['seasons_episodes'].append((season, episode))

        group_data['count'] += 1

    # Convert dictionaries to lists for processing
    movies = list(movies_dict.values())
    series = list(series_dict.values())

    # Process each category to create display names
    categorized_results = {
        'movies': [],
        'series': []
    }

    # Process movies
    for movie_data in movies:
        title, details = format_movie_group(movie_data)
        categorized_results['movies'].append({
            'title': title,
            'details': details,
            'count': movie_data['count'],
            'year': movie_data['year']
        })

    # Process series
    for series_data in series:
        title, details = format_series_group(series_data)
        categorized_results['series'].append({
            'title': title,
            'details': details,
            'count': series_data['count'],
            'year': series_data['year']
        })

    return categorized_results

def format_movie_group(group_data):
    """Format movie group with quality consolidation and year. Returns (title, details).

    Details are bracket-ready for the /search-style listing (dot-joined,
    lowercased qualities): ``2010.1080p`` / ``2010.1080p & 4k``."""
    title = group_data['title']
    year = group_data['year']
    qualities = sorted(group_data['qualities'])

    # Build details string (year + qualities), e.g. "2010.1080p & 4k"
    details_parts = []
    if year:
        details_parts.append(str(year))
    if qualities:
        details_parts.append(" & ".join(sorted(q.lower() for q in qualities)))

    details = ".".join(details_parts) if details_parts else ""
    return title, details

def format_series_group(group_data):
    """Format series group with season/episode consolidation and year. Returns (title, details)."""
    title = group_data['title']
    year = group_data['year']
    seasons_episodes = group_data['seasons_episodes']

    # Build details parts, bracket-ready for the /search-style listing
    # (dot-joined, compact ranges like ``S01E01-02``): "2008.S01E01-02, S02E01"
    details_parts = []
    if year:
        details_parts.append(str(year))

    if seasons_episodes:
        # Group by season
        season_groups = {}
        for season, episode in seasons_episodes:
            if season not in season_groups:
                season_groups[season] = []
            season_groups[season].append(episode)

        # Format each season's episode ranges
        season_parts = []
        for season in sorted(season_groups.keys()):
            episodes = sorted(season_groups[season])

            if len(episodes) == 1:
                episode_str = f"E{episodes[0]:02d}"
            else:
                # Create episode range
                first_ep = episodes[0]
                last_ep = episodes[-1]
                episode_str = f"E{first_ep:02d}-{last_ep:02d}"

            season_parts.append(f"S{season:02d}{episode_str}")

        details_parts.append(", ".join(season_parts))

    details = ".".join(details_parts) if details_parts else ""
    return title, details

def construct_final_caption(db_item, file_size_bytes=None, user_name="User"):
    """Construct a standardized caption from a database item."""
    if not db_item:
        return None

    # Extract Data
    title = db_item.get('title', 'Unknown Title').upper()
    
    # Handle Series Title
    type_ = db_item.get('type', 'Movie').lower()
    if type_ in ['series', 'tv', 'show'] and db_item.get('season') and db_item.get('episode'):
        season = int(db_item['season'])
        episode = int(db_item['episode'])
        title = f"`{title}` - S{season:02d}E{episode:02d}"

    # Copy-to-text format (monospace)
    title_formatted = f"{title}"

    year = db_item.get('year')
    quality = db_item.get('quality')
    rip = db_item.get('rip')
    audio = db_item.get('audio')
    ext = db_item.get('extension', 'MKV').replace('.', '').upper()
    
    # Combine quality fields
    quality_parts = []
    if quality: quality_parts.append(quality)
    if rip: quality_parts.append(rip)
    if audio: quality_parts.append(audio)
    quality_str = ", ".join(quality_parts)

    # Canonical size formatter; keep the caption clean when no size is known
    size_str = format_file_size(file_size_bytes) if file_size_bytes else ""

    # Disclaimer
    disclaimer = "<i>©️ All rights belong to respective owners • Shared as found publicly</i>"
    
    # Date Format: 12/18/2025 1:20 AM
    current_date = datetime.now().strftime("%m/%d/%Y %I:%M %p")

    # Build content lines
    lines = []
    lines.append(f"┏ 🏷 Name: {title_formatted}")
    lines.append("┃ ")
    
    if quality_str:
        lines.append(f"┠ ✨ Quality: {quality_str}")
        
    if size_str:
        lines.append(f"┠ ⚙️ Size: {size_str}")
        
    lines.append(f"┠ 💠 Type: {ext}")
    lines.append(f"┠ 👤 User: {user_name}")
    lines.append("┃")
    lines.append(f"┖ 📅 Date: {current_date}")
    
    lines.append("")
    lines.append(f"{disclaimer}")
    
    return "\n".join(lines)

def format_recent_output(categorized_results, total_files=None, total_movies=None, total_series=None, last_updated=None):
    """Format categorized results as plain HTML with click-to-copy search strings.

    Consolidated per-title lines (``N. <code>Title (year)</code> [details]``)
    grouped into MOVIES and SERIES sections, with the batch context (Updated /
    Files counts). Each line's copy target is the full ``Title (year)`` string
    (just the title when the year is missing) so tapping it yields a string
    ready to paste into /search; the year is dropped from the display bracket
    to avoid duplication. Copy targets are HTML-escaped so special characters
    (&, <, >) never break the message. Caller must send with ParseMode.HTML.
    """
    output_text = "<b>LAST BATCH UPDATE</b>\n\n"

    # Add context information
    if last_updated:
        output_text += f"Updated: {last_updated}\n"
    if total_files is not None:
        output_text += f"Files: {total_files}"
        if total_movies is not None and total_series is not None:
            output_text += f" (Movies: {total_movies} | Series: {total_series})"
        output_text += "\n"

    output_text += "\n"

    def _copy_target(title, year):
        """Full search-ready string: 'Title (year)' or 'Title' when no year."""
        return f"{title} ({year})" if year else title

    def _display_details(details, year):
        """Strip the leading '<year>.' segment from details since the year is
        already shown in the copy target (e.g. '2010.1080p' -> '1080p')."""
        if year and details:
            prefix = f"{year}."
            if details.startswith(prefix):
                return details[len(prefix):]
        return details

    # Display Movies section
    movies = categorized_results['movies']
    if movies:
        output_text += "<b>MOVIES</b>\n"
        output_text += "─" * 30 + "\n"
        for i, result in enumerate(movies, 1):
            year = result.get('year')
            copy_text = html.escape(_copy_target(result['title'], year))
            details = _display_details(result.get('details', ''), year)
            if details:
                output_text += f"{i}. <code>{copy_text}</code> [{details}]\n"
            else:
                output_text += f"{i}. <code>{copy_text}</code>\n"
        output_text += "\n"

    # Display Series section
    series = categorized_results['series']
    if series:
        output_text += "<b>SERIES</b>\n"
        output_text += "─" * 30 + "\n"
        for i, result in enumerate(series, 1):
            year = result.get('year')
            copy_text = html.escape(_copy_target(result['title'], year))
            details = _display_details(result.get('details', ''), year)
            if details:
                output_text += f"{i}. <code>{copy_text}</code> [{details}]\n"
            else:
                output_text += f"{i}. <code>{copy_text}</code>\n"
        output_text += "\n"

    # Calculate total items and check if we hit limit
    total_items = len(movies) + len(series)
    if total_items >= 20:
        output_text += "<i>..and more</i>\n"

    output_text += "<i>Tap any title to copy</i>"
    return output_text

# ------------------------------------------------------------------ #
#  Quality ranking & best-copy selection (search dedup / chooser)      #
# ------------------------------------------------------------------ #

# Resolution ranks: higher is better. Keys are matched as substrings of the
# stored quality string (e.g. "1080p", "4K UHD", "720p HEVC").
QUALITY_RANKS = {
    "2160p": 5, "4k": 5,
    "1080p": 4, "fhd": 4,
    "720p": 3, "hd": 3,
    "480p": 2,
    "360p": 1,
}


def quality_rank(quality) -> int:
    """Rank a quality string (e.g. '1080p', '4K') from 0 (unknown) to 5 (4K)."""
    q = str(quality or "").lower()
    for key, rank in QUALITY_RANKS.items():
        if key in q:
            return rank
    return 0


def pick_best_quality(entries) -> tuple:
    """Return (best, others) for a list of duplicate copies.

    ``best`` is the highest-ranked quality copy (ties broken by keeping the
    first-seen entry); ``others`` are the remaining copies in original order.
    """
    if not entries:
        return None, []
    best = entries[0]
    others = []
    for entry in entries[1:]:
        if quality_rank(entry.get("quality")) > quality_rank(best.get("quality")):
            others.append(best)
            best = entry
        else:
            others.append(entry)
    return best, others


def series_label(entry):
    """Season/episode label for a series entry: ``S02E08`` / ``S02`` / ``E08``.

    Returns ``""`` for movies, series without season/episode metadata, and
    malformed (non-numeric) values - the same coercion logic every formatter
    shares (string seasons exist in the wild).
    """
    movie_type = (entry.get("type") or "Movie").lower()
    season = entry.get("season")
    episode = entry.get("episode")
    if movie_type not in ("series", "tv", "show") or not (season or episode):
        return ""
    try:
        if season and episode:
            return f"S{int(season):02d}E{int(episode):02d}"
        if season:
            return f"S{int(season):02d}"
        if episode:
            return f"E{int(episode):02d}"
    except (TypeError, ValueError):
        return ""
    return ""


def format_rip_label(rip):
    """Human display label for a rip/source value (WebRip, Blu-ray, HDTV...).

    Falls back to the raw value when the rip is unknown.
    """
    if not rip:
        return ""
    r = str(rip).strip().lower()
    if "remux" in r:
        return "Remux"
    if r in ("bluray", "blu-ray", "bdrip", "bd", "brrip"):
        return "Blu-ray"
    if "web" in r:
        return "WebRip"
    if "hdtv" in r or r == "hd":
        return "HDTV"
    if "dvd" in r:
        return "DVD"
    return str(rip).strip()


def format_latest_info(entry):
    """Latest-file info for a search-list line: ``S02E08 | 1080p | 890MB | WebRip``.

    The series episode prefix comes first when present, then quality, size and
    rip label (``|``-joined). ``N/A`` when nothing is known.
    """
    parts = []
    label = series_label(entry)
    if label:
        parts.append(label)
    for v in (entry.get("quality"), format_file_size(entry.get("file_size")),
              format_rip_label(entry.get("rip"))):
        if v and v != "N/A":
            parts.append(v)
    return " | ".join(parts) if parts else "N/A"


def format_pick_info(entry):
    """Pick-view file info: ``2.5GB | WebRip | 1080p`` (size | rip | quality)."""
    parts = []
    size = format_file_size(entry.get("file_size"))
    if size != "N/A":
        parts.append(size)
    rip = format_rip_label(entry.get("rip"))
    if rip:
        parts.append(rip)
    quality = entry.get("quality")
    if quality:
        parts.append(str(quality))
    return " | ".join(parts) if parts else "N/A"


def format_pick_line(number, entry, dup_count=0):
    """One pick-view copy line: ``1. Lucky (2025) - 2.5GB | WebRip | 1080p``.

    Series copies carry the season/episode prefix after the year
    (``2. Show (2015) - S02E08 | 890MB | WebRip | 1080p``). ``entry`` is a DB
    document; ``dup_count`` appends the `` 🔁+N`` duplicate marker.
    """
    title = entry.get("title") or "Unknown Title"
    year = entry.get("year")
    line = f"{number}. {title}"
    if year:
        line += f" ({year})"
    label = series_label(entry)
    info = format_pick_info(entry)
    body = f"{label} | {info}" if label else info
    line += f" - {body}"
    if dup_count:
        line += f" 🔁+{dup_count}"
    return line


def latest_copy(copies):
    """The most recently indexed copy of a group (indexed_at desc, then
    message_id desc as a stable tiebreak).

    Shared by /search (the ``Latest:`` info + Get [n] target) and /genres
    browsing so both surfaces pick the same file.
    """
    def key(c):
        ts = c.get("indexed_at")
        if not isinstance(ts, datetime):
            ts = datetime.min
        # Mixed naive/aware timestamps crash comparisons - normalize to UTC.
        if ts.tzinfo is None:
            ts = ts.replace(tzinfo=timezone.utc)
        return (ts, c.get("message_id") or 0)
    return max(copies, key=key)


def format_search_info(entry):
    """Dot-joined info string for a /search-style line.

    ``size.quality.series.year.rip`` (or ``N/A`` when nothing is known).
    Shared by surfaces that render the bracket info without a line number
    (inline search results).
    """
    year = entry.get("year")
    quality = entry.get("quality")
    rip = entry.get("rip")
    file_size = entry.get("file_size")

    size_str = format_file_size(file_size)
    quality_str = quality if quality else ""

    # Season/episode info (coerced to int - string seasons exist in the wild).
    series_info = series_label(entry)

    year_str = str(year) if year else ""

    # Short rip label (Blu/Web/HD), matching the search line style.
    rip_str = ""
    if rip and rip.lower() in ("bluray", "blu-ray", "bdrip", "bd"):
        rip_str = "Blu"
    elif rip and "web" in rip.lower():
        rip_str = "Web"
    elif rip and "hd" in rip.lower():
        rip_str = "HD"

    info_parts = []
    if size_str != "N/A":
        info_parts.append(size_str)
    if quality_str:
        info_parts.append(quality_str)
    if series_info:
        info_parts.append(series_info)
    if year_str:
        info_parts.append(year_str)
    if rip_str:
        info_parts.append(rip_str)
    return ".".join(info_parts) if info_parts else "N/A"


async def resolve_chat_ref(ref: str, client):
    """Use client to resolve a channel reference (id, t.me/slug, @username)."""
    r = ref.strip()
    if r.startswith("t.me/"):
        r = r.split("t.me/")[-1]
    # try numeric
    try:
        cid = int(r)
        return await client.get_chat(cid)
    except Exception:
        pass
    # try username or slug
    return await client.get_chat(r)
