"""
Search Functionality Module

This module handles search functionality for the MovieBot.
It includes exact and fuzzy search, result formatting, and pagination.

The live /search and /recent command handlers live in commands.py; this module
provides the search engine (perform_search), the paginated result sender
(send_search_results), and the inline query handler (inline_handler).
"""

import asyncio
import re
import uuid
from datetime import datetime, timezone

from fuzzywuzzy import fuzz
from pyrogram.types import Message, InlineKeyboardMarkup, InlineKeyboardButton, LinkPreviewOptions

from .config import FUZZY_THRESHOLD
from .database import movies_col
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

    # Group duplicate copies (same title/year/type) so each line shows the
    # best-quality copy; groups with more than one copy get a "Pick" chooser.
    from .utils import group_duplicate_copies, pick_best_quality
    groups = group_duplicate_copies(page_results)

    # Create header
    search_text = f"```\n"
    search_text += f"Search: \"{query}\"\n"
    search_text += f"Total Results: {total_results} | Page {page}/{total_pages}\n\n"

    # Format each group (best copy) on current page
    button_data = []

    for i, group in enumerate(groups, start=start_idx + 1):
        best, others = pick_best_quality(group)
        result = best
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

        # Create result line in new refined format, marking duplicate copies
        line = f"{i}. {title} [{info_string}]"
        if others:
            line += f" 🔁+{len(others)}"
        search_text += line + "\n"

        # Store button data
        if channel_id and message_id:
            button_data.append({
                'number': i,
                'channel_id': channel_id,
                'message_id': message_id,
                'group_index': i - (start_idx + 1),
                'group_size': len(group),
            })

    search_text += f"```"

    # TMDb enrichment (cached per title; no-op without an API key) - a compact
    # details block below the results with rating/genres/IMDb links. Fetched
    # concurrently so a page of 9 results doesn't serialize 9 HTTP round-trips.
    from .tmdb_integration import enrich_title, format_enrichment_line
    best_copies = [pick_best_quality(group)[0] for group in groups]
    metas = await asyncio.gather(*[
        enrich_title(b.get("title"), b.get("year"), b.get("type", "Movie"))
        for b in best_copies
    ], return_exceptions=True)
    details_lines = []
    for i, (_, meta) in enumerate(zip(best_copies, metas), start=start_idx + 1):
        suffix = format_enrichment_line(meta if isinstance(meta, dict) else None)
        if suffix:
            details_lines.append(f"{i}. {suffix}")
    if details_lines:
        search_text += "\n" + "\n".join(details_lines)

    # Create buttons
    buttons = []
    if button_data:
        # Store search results for pagination (using UUID to avoid callback data size limits)
        search_id = str(uuid.uuid4())[:8]
        from .utils import cleanup_expired_bulk_downloads
        await cleanup_expired_bulk_downloads(bulk_downloads)

        bulk_downloads[search_id] = {
            'results': results,  # Store all results for pagination
            'groups': groups,    # Dedup groups for the quality chooser
            'query': query,
            'created_at': datetime.now(timezone.utc),
            'user_id': message.from_user.id
        }

        # Create individual file buttons in rows of 3 (Pick = multiple copies)
        current_row = []
        for btn in button_data:
            if btn['group_size'] > 1:
                current_row.append(
                    InlineKeyboardButton(
                        f"Pick [{btn['number']}]",
                        callback_data=f"choose:{search_id}:{btn['group_index']}"
                    )
                )
            else:
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
        link_preview_options=LinkPreviewOptions(is_disabled=True)
    )


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
    
    # Exact matches first
    exact_cursor = movies_col.find({"title": {"$regex": query, "$options": "i"}}).limit(10)
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
