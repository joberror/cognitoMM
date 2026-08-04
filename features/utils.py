"""
Utility Functions Module

This module contains various utility functions used throughout the Movie Bot application,
including file management, time formatting, and helper functions.
"""

import asyncio
from datetime import datetime, timezone, timedelta

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
            'count': movie_data['count']
        })

    # Process series
    for series_data in series:
        title, details = format_series_group(series_data)
        categorized_results['series'].append({
            'title': title,
            'details': details,
            'count': series_data['count']
        })

    return categorized_results

def format_movie_group(group_data):
    """Format movie group with quality consolidation and year. Returns (title, details)."""
    title = group_data['title']
    year = group_data['year']
    qualities = sorted(group_data['qualities'])

    # Build details string (year + qualities)
    details_parts = []
    if year:
        details_parts.append(str(year))

    if qualities:
        if len(qualities) == 1:
            details_parts.append(f"({qualities[0]})")
        else:
            quality_str = " & ".join(qualities)
            details_parts.append(f"({quality_str})")

    details = " ".join(details_parts)
    return title, details

def format_series_group(group_data):
    """Format series group with season/episode consolidation and year. Returns (title, details)."""
    title = group_data['title']
    year = group_data['year']
    seasons_episodes = group_data['seasons_episodes']

    # Build details parts
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

            season_parts.append(f"S{season:02d}({episode_str})")

        episode_info = ", ".join(season_parts)
        details_parts.append(episode_info)

    details = " ".join(details_parts)
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
    """Format categorized results for display with context information (plain HTML, click-to-copy titles)"""
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

    # Display Movies section
    movies = categorized_results['movies']
    if movies:
        output_text += "<b>MOVIES</b>\n"
        output_text += "─" * 30 + "\n"
        for i, result in enumerate(movies, 1):
            title = result['title']
            details = result.get('details', '')
            if details:
                output_text += f"{i}. <code>{title}</code> {details}\n"
            else:
                output_text += f"{i}. <code>{title}</code>\n"
        output_text += "\n"

    # Display Series section
    series = categorized_results['series']
    if series:
        output_text += "<b>SERIES</b>\n"
        output_text += "─" * 30 + "\n"
        for i, result in enumerate(series, 1):
            title = result['title']
            details = result.get('details', '')
            if details:
                output_text += f"{i}. <code>{title}</code> {details}\n"
            else:
                output_text += f"{i}. <code>{title}</code>\n"
        output_text += "\n"

    # Calculate total items and check if we hit limit
    total_items = len(movies) + len(series)
    if total_items >= 20:
        output_text += "<i>..and more</i>"

    output_text += "\n<i>Tap any title to copy</i>"

    return output_text

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
