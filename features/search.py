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
import html
import re
import uuid
from datetime import datetime, timezone

from fuzzywuzzy import fuzz
from pyrogram.enums import ParseMode
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


def pick_callback(search_id, group_index, season=None, resolution=None, season_page=0):
    """Callback data for the pick filter view (6 colon-separated parts).

    Format: ``choose:{search_id}:{group_index}:{season}:{resolution}:{page}``
    where season is ``S02`` (or empty), resolution is ``1080p`` (or empty) and
    page is the 0-based season page (empty = page 0). The legacy 5-part format
    (no trailing page) is still accepted by the callback parser.
    """
    season_part = ""
    if season is not None:
        try:
            season_part = f"S{int(season):02d}"
        except (TypeError, ValueError):
            season_part = f"S{season}"
    page_part = str(season_page) if season_page else ""
    return f"choose:{search_id}:{group_index}:{season_part}:{resolution or ''}:{page_part}"


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


def build_search_page(results, query, page):
    """Build the paginated search-result text + per-line button metadata.

    Returns ``(search_text, button_data, groups, total_pages)``. The initial
    /search send, the page:/back: callbacks and history searches all render
    through here so every view stays identical.
    """
    from .utils import group_duplicate_copies, pick_best_quality

    # Pagination settings
    RESULTS_PER_PAGE = 9
    total_results = len(results)
    total_pages = max(1, (total_results + RESULTS_PER_PAGE - 1) // RESULTS_PER_PAGE)  # Ceiling division

    # Ensure page is within valid range
    page = max(1, min(page, total_pages))

    # Calculate start and end indices for current page
    start_idx = (page - 1) * RESULTS_PER_PAGE
    end_idx = min(start_idx + RESULTS_PER_PAGE, total_results)
    page_results = results[start_idx:end_idx]

    # Group duplicate copies (same title/year/type) so each line shows the
    # best-quality copy; groups with more than one copy get a "Pick" filter.
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
    return search_text, button_data, groups, total_pages


async def build_search_keyboard(search_id, total_results, page, total_pages,
                                groups, button_data, user_id, results,
                                season_pages=None):
    """Build the inline keyboard for a search results page.

    Single-copy groups get a ``Get [n]`` button; multi-copy groups get a
    ``Pick [n]`` button that filters the message in place (series with several
    seasons also get ``Pick[n][Sxx]`` shortcut buttons per season). Long-running
    series page through their shortcuts (``S◀`` / ``S▶``, ``season_pages`` maps
    group index -> season page) so every season has a one-click shortcut
    without opening the pick view first.
    """
    from .config import bulk_downloads
    from .premium_management import is_feature_premium_only, is_premium_user
    from .user_management import is_admin

    if not button_data:
        return None

    # Create individual file buttons in rows of 3
    buttons = []
    current_row = []
    for btn in button_data:
        group = groups[btn['group_index']]
        group_buttons = []

        if btn['group_size'] == 1:
            group_buttons.append(
                InlineKeyboardButton(
                    f"Get [{btn['number']}]",
                    callback_data=f"get_file:{btn['channel_id']}:{btn['message_id']}"
                )
            )
        else:
            # Multi-copy group: season picks for series + the all-copies pick.
            # Series with more than MAX_SEASON_BUTTONS seasons page through
            # their shortcut buttons (S◀ / S▶, one group at a time) - the
            # page: callback carries the group's season page so the results
            # list can rebuild in place with the next slice of Sxx buttons.
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


async def send_search_results(client, message: Message, results, query, page=1):
    """Send beautifully formatted search results with pagination.

    The search (and its dedup groups) is stored so the ``Pick`` buttons can
    filter the message in place later; the same renderers power the page:/
    back: callbacks.

    client is passed explicitly to avoid fragile relative import (previously caused
    ImportError: attempted relative import beyond top-level package)."""
    from .config import bulk_downloads

    total_results = len(results)
    search_text, button_data, groups, total_pages = build_search_page(results, query, page)

    # TMDb enrichment (cached per title; no-op without an API key) - a compact
    # details block below the results with rating/genres/IMDb links. Fetched
    # concurrently so a page of 9 results doesn't serialize 9 HTTP round-trips.
    from .tmdb_integration import enrich_title, format_enrichment_line
    from .utils import pick_best_quality
    best_copies = [pick_best_quality(group)[0] for group in groups]
    metas = await asyncio.gather(*[
        enrich_title(b.get("title"), b.get("year"), b.get("type", "Movie"))
        for b in best_copies
    ], return_exceptions=True)
    details_lines = []
    for i, (_, meta) in enumerate(zip(best_copies, metas), start=(page - 1) * 9 + 1):
        suffix = format_enrichment_line(meta if isinstance(meta, dict) else None)
        if suffix:
            details_lines.append(f"{i}. {suffix}")
    if details_lines:
        search_text += "\n" + "\n".join(details_lines)

    # Create keyboard
    keyboard = None
    if button_data:
        # Store search results for pagination (using UUID to avoid callback data size limits)
        search_id = str(uuid.uuid4())[:8]
        from .utils import cleanup_expired_bulk_downloads
        await cleanup_expired_bulk_downloads(bulk_downloads)

        bulk_downloads[search_id] = {
            'results': results,   # Store all results for pagination
            'groups': groups,     # Dedup groups for the pick filter view
            'query': query,
            'created_at': datetime.now(timezone.utc),
            'user_id': message.from_user.id,
            'page': page,
        }

        keyboard = await build_search_keyboard(
            search_id, total_results, page, total_pages, groups, button_data,
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
    search_text, button_data, groups, total_pages = build_search_page(results, query, page)
    total_results = len(results)
    search_data['page'] = page

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
                    season_page=0):
    """Build the in-place filtered view (text + keyboard) for one title.

    The search result message is replaced by ONLY this title's copies: movies
    list every copy; series dedupe per episode (best copy) and offer season
    filter buttons (paged for long-running series). A resolution filter row
    narrows by [720p]/[1080p]/[2160p].
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

    # Header (HTML - title escaped)
    header = f"🎞️ <b>{html.escape(str(title))}</b>"
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

    # Copy lines (series: dedupe per episode, best copy wins)
    lines = []
    get_buttons = []
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
            parts = [p for p in (best.get("quality"), best.get("rip")) if p]
            info = ".".join(parts) if parts else "N/A"
            label = f"S{s:02d}" + (f"E{e:02d}" if e is not None else "")
            line = f"{label} [{info}]"
            if others:
                line += f" 🔁+{len(others)}"
            lines.append(line)
            if best.get("channel_id") and best.get("message_id"):
                get_buttons.append((label, best))

        # Copies without season/episode metadata (whole-series packs etc.) are
        # listed individually so they stay reachable - and when NO episode keys
        # exist at all (season-less series group), this falls back to listing
        # every copy movie-style instead of rendering an empty view.
        unkeyed = [c for c in filtered if c.get("season") is None]
        extra_budget = MAX_PICK_LINES - len(lines)
        for i, c in enumerate(unkeyed[:max(0, extra_budget)], 1):
            details = ", ".join(x for x in (c.get("quality"), c.get("rip"),
                                            format_file_size(c.get("file_size")))
                                if x and x != "N/A")
            lines.append(f"{i}. {details or 'N/A'}")
            if c.get("channel_id") and c.get("message_id"):
                get_buttons.append((str(i), c))
    else:
        for i, c in enumerate(filtered[:MAX_PICK_LINES], 1):
            details = ", ".join(x for x in (c.get("quality"), c.get("rip"),
                                            format_file_size(c.get("file_size")))
                                if x and x != "N/A")
            lines.append(f"{i}. {details or 'N/A'}")
            if c.get("channel_id") and c.get("message_id"):
                get_buttons.append((str(i), c))

    text = header + "\n".join(lines)
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
                                            season_page=season_page),
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
                                                season_page=season_page - 1)))
            if season_page < season_pages - 1:
                paging_row.append(InlineKeyboardButton(
                    "S▶",
                    callback_data=pick_callback(search_id, group_index,
                                                resolution=resolution,
                                                season_page=season_page + 1)))
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
                                                season_page=season_page),
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

    buttons.append([InlineKeyboardButton("← Back", callback_data=f"back:{search_id}")])

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

    await callback_query.message.edit_text(
        text,
        reply_markup=keyboard,
        parse_mode=ParseMode.HTML,
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
