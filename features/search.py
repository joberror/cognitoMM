"""
Search Functionality Module

This module handles search functionality for the MovieBot.
It includes exact and fuzzy search, result formatting, and pagination.
"""

import re
import asyncio
import uuid
from datetime import datetime, timezone

from fuzzywuzzy import fuzz
from hydrogram.types import Message, InlineKeyboardMarkup, InlineKeyboardButton

from .config import FUZZY_THRESHOLD
from .database import movies_col, users_col
from .utils import format_file_size


async def perform_search(query: str, exact_search: bool = False, fuzzy_threshold: int = None):
    """
    Perform a search for movies/series in the database.

    Args:
        query: Search query string
        exact_search: If True, only exact title matches are returned
        fuzzy_threshold: Threshold for fuzzy matching (default: FUZZY_THRESHOLD from config)

    Returns:
        List of matching results
    """
    if fuzzy_threshold is None:
        fuzzy_threshold = FUZZY_THRESHOLD

    if exact_search:
        # Exact search mode - only look for exact title matches
        exact_pattern = f"^{re.escape(query)}$"
        exact = await movies_col.find({"title": {"$regex": exact_pattern, "$options": "i"}}).to_list(length=None)
        return exact
    else:
        # Normal search - exact + fuzzy
        # Search for exact matches (no limit - show all results)
        exact = await movies_col.find({"title": {"$regex": query, "$options": "i"}}).to_list(length=None)

        # Search for fuzzy matches if we have less exact matches
        all_results = list(exact)
        if len(exact) < 50:  # Only do fuzzy search if we don't have many exact matches
            candidates = []
            cursor = movies_col.find({}, {"title": 1, "year": 1, "quality": 1, "channel_title": 1, "message_id": 1, "channel_id": 1, "type": 1, "season": 1, "episode": 1, "rip": 1}).limit(500)
            async for r in cursor:
                # Skip if already in exact matches
                if any(ex.get("_id") == r.get("_id") for ex in exact):
                    continue
                title = r.get("title", "")
                score = fuzz.partial_ratio(query.lower(), title.lower())
                if score >= fuzzy_threshold:
                    candidates.append((score, r))

            candidates = sorted(candidates, key=lambda x: x[0], reverse=True)
            all_results.extend([c[1] for c in candidates])

        return all_results


async def cmd_search(client, message: Message):
    """Handle search command"""
    uid = message.from_user.id
    parts = message.text.split()
    if len(parts) < 2:
        return await message.reply_text("Usage: /search <title>")

    # Check for exact search flag
    exact_search = False
    if parts[1] == "-e" and len(parts) >= 3:
        exact_search = True
        query = " ".join(parts[2:]).strip()
    else:
        query = " ".join(parts[1:]).strip()

    # record search history
    await users_col.update_one({"user_id": uid}, {"$push": {"search_history": {"q": query, "ts": datetime.now(timezone.utc)}}}, upsert=True)

    # Perform search using the extracted function
    all_results = await perform_search(query, exact_search=exact_search)

    if exact_search and not all_results:
        # No exact matches found - suggest normal search
        await message.reply_text(
            f"⚠️ No exact matches found for \"{query}\"\n\n"
            f"💡 **Try normal search:** /search {query}\n"
            f"🔍 Normal search finds partial and similar titles"
        )
        return

    if not all_results:
        return await message.reply_text("⚠️ No results found for your search.")

    # Create flashy, neat search results
    await send_search_results(client, message, all_results, query)


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


async def send_search_results(client, message: Message, results, query, page=1):
    """Send beautifully formatted search results with pagination.
    
    client is passed explicitly to avoid fragile relative import (previously caused
    ImportError: attempted relative import beyond top-level package)."""
    from .config import bulk_downloads
    # Pagination settings
    RESULTS_PER_PAGE = 9
    total_results = len(results)
    total_pages = (total_results + RESULTS_PER_PAGE - 1) // RESULTS_PER_PAGE  # Ceiling division

    # Ensure page is within valid range
    page = max(1, min(page, total_pages))

    # Calculate start and end indices for current page
    start_idx = (page - 1) * RESULTS_PER_PAGE
    end_idx = min(start_idx + RESULTS_PER_PAGE, total_results)
    page_results = results[start_idx:end_idx]

    # Create header
    search_text = f"```\n"
    search_text += f"Search: \"{query}\"\n"
    search_text += f"Total Results: {total_results} | Page {page}/{total_pages}\n\n"

    # Format each result on current page
    button_data = []

    for i, result in enumerate(page_results, start=start_idx + 1):
        title = result.get('title', 'Unknown Title')
        year = result.get('year')
        quality = result.get('quality')
        rip = result.get('rip')
        movie_type = result.get('type', 'Movie')
        season = result.get('season')
        episode = result.get('episode')
        file_size = result.get('file_size')
        channel_id = result.get('channel_id')
        message_id = result.get('message_id')

        # Format file size
        size_str = format_file_size(file_size)

        # Format quality (resolution)
        quality_str = quality if quality else ""

        # Format season/episode info for series
        series_info = ""
        if movie_type.lower() in ['series', 'tv', 'show'] and (season or episode):
            if season and episode:
                series_info = f"S{season:02d}E{episode:02d}"
            elif season:
                series_info = f"S{season:02d}"
            elif episode:
                series_info = f"E{episode:02d}"

        # Format year
        year_str = str(year) if year else ""

        # Format rip type (BluRay, WEBRip, etc.)
        rip_str = ""
        if rip and rip.lower() in ['bluray', 'blu-ray', 'bdrip', 'bd']:
            rip_str = "Blu"
        elif rip and 'web' in rip.lower():
            rip_str = "Web"
        elif rip and 'hd' in rip.lower():
            rip_str = "HD"

        # Build info string: [size.quality.series_info.year.rip]
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

        info_string = ".".join(info_parts) if info_parts else "N/A"

        # Create result line in new refined format
        search_text += f"{i}. {title} [{info_string}]\n"

        # Store button data
        if channel_id and message_id:
            button_data.append({
                'number': i,
                'channel_id': channel_id,
                'message_id': message_id
            })

    search_text += f"```"

    # Create buttons
    buttons = []
    if button_data:
        # Create individual file buttons in rows of 3
        current_row = []
        for btn in button_data:
            current_row.append(
                InlineKeyboardButton(
                    f"Get [{btn['number']}]",
                    callback_data=f"get_file:{btn['channel_id']}:{btn['message_id']}"
                )
            )

            # Add row when we have 3 buttons or it's last button
            if len(current_row) == 3 or btn == button_data[-1]:
                buttons.append(current_row)
                current_row = []

        # Create navigation row with Prev, Get All, and Next buttons
        nav_row = []

        # Store search results for pagination (using UUID to avoid callback data size limits)
        search_id = str(uuid.uuid4())[:8]
        from .file_deletion import cleanup_expired_bulk_downloads
        await cleanup_expired_bulk_downloads(bulk_downloads)

        bulk_downloads[search_id] = {
            'results': results,  # Store all results for pagination
            'query': query,
            'created_at': datetime.now(timezone.utc),
            'user_id': message.from_user.id
        }

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
            from .premium_management import is_feature_premium_only, is_premium_user
            from .user_management import is_admin

            show_get_all = True
            if await is_feature_premium_only("get_all"):
                # Only show if user is premium or admin
                uid = message.from_user.id
                if not await is_admin(uid) and not await is_premium_user(uid):
                    show_get_all = False

            if show_get_all:
                # Generate bulk download ID for all results
                bulk_id = str(uuid.uuid4())[:8]
                bulk_downloads[bulk_id] = {
                    'files': [{'channel_id': r.get('channel_id'), 'message_id': r.get('message_id')}
                             for r in results if r.get('channel_id') and r.get('message_id')][:10],
                    'created_at': datetime.now(timezone.utc),
                    'user_id': message.from_user.id
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

    # Create keyboard
    keyboard = InlineKeyboardMarkup(buttons) if buttons else None

    # Send message
    await message.reply_text(
        search_text,
        reply_markup=keyboard,
        disable_web_page_preview=True
    )


async def cmd_recent(client, message: Message):
    """Handle /recent command to display recently added content"""
    # Import client and channels_col here to avoid circular imports
    from ..main import channels_col
    from .user_management import check_banned, log_action
    
    # Check if user is banned
    if await check_banned(message):
        return
    
    try:
        # Database query with error handling
        cursor = movies_col.find(
            {},
            {
                "title": 1,
                "type": 1,
                "quality": 1,
                "season": 1,
                "episode": 1,
                "year": 1,
                "indexed_at": 1,
                "_id": 1
            }
        ).sort("indexed_at", -1).limit(100)
        
        raw_results = await cursor.to_list(length=100)
        
        # Handle empty results
        if not raw_results:
            await message.reply_text(
                "📭 **No Content Found**\n\n"
                "The database doesn't contain any indexed content yet.\n\n"
                "💡 Add channels and enable indexing to see recent content here."
            )
            return
        
        # Calculate statistics
        total_files = len(raw_results)
        total_movies = len([r for r in raw_results if r.get('type', 'Movie').lower() not in ['series', 'tv', 'show']])
        total_series = len([r for r in raw_results if r.get('type', 'Movie').lower() in ['series', 'tv', 'show']])
        
        # Get last updated time from most recent item
        last_updated = None
        if raw_results:
            last_indexed = raw_results[0].get('indexed_at')
            if last_indexed:
                # Format datetime for display
                last_updated = last_indexed.strftime('%Y-%m-%d %H:%M:%S UTC')
        
        # Process and format results
        grouped_results = group_recent_content(raw_results)
        formatted_output = format_recent_output(grouped_results, total_files, total_movies, total_series, last_updated)
        
        # Send response
        await message.reply_text(formatted_output, disable_web_page_preview=True)
        
        # Log successful usage
        await log_action("recent_command", by=message.from_user.id, extra={
            "results_count": len(raw_results),
            "grouped_count": len(grouped_results),
            "total_files": total_files,
            "total_movies": total_movies,
            "total_series": total_series
        })
        
    except Exception as e:
        # Comprehensive error handling
        await log_action("recent_command_error", by=message.from_user.id, extra={
            "error": str(e),
            "error_type": "general"
        })
        
        await message.reply_text(
            "❌ **Error**\n\n"
            "Unable to fetch recent content. Please try again later."
        )


async def inline_handler(client, inline_query):
    """Handle inline queries for the bot"""
    from .config import FUZZY_THRESHOLD
    from .database import movies_col, users_col
    from fuzzywuzzy import fuzz
    from hydrogram.types import InlineQueryResultArticle, InputTextMessageContent
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
    
    # Exact matches first
    exact_cursor = movies_col.find({"title": {"$regex": query, "$options": "i"}}).limit(10)
    exact_results = await exact_cursor.to_list(length=10)
    
    # Add exact matches to results
    for result in exact_results:
        title = result.get('title', 'Unknown')
        year = result.get('year', '')
        quality = result.get('quality', '')
        
        display_text = f"{title} {year}" if year else title
        if quality:
            display_text += f" ({quality})"
            
        results.append(
            InlineQueryResultArticle(
                title=display_text,
                description=f"Quality: {quality or 'N/A'} | Year: {year or 'N/A'}",
                input_message_content=InputTextMessageContent(
                    f"🎬 **{title}**\n"
                    f"📅 Year: {year or 'N/A'}\n"
                    f"🎞️ Quality: {quality or 'N/A'}\n"
                    f"📺 Channel: {result.get('channel_title', 'N/A')}"
                ),
                thumb_url=None,
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
            
            display_text = f"{title} {year}" if year else title
            if quality:
                display_text += f" ({quality})"
                
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
                    thumb_url=None,
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
