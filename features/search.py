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


async def perform_search(query: str, exact_search: bool = False, fuzzy_threshold: int = None):
    """
    Perform a search for movies/series in the database.

    Args:
        query: Search query string
        exact_search: If True, only exact title matches are returned
        fuzzy_threshold: Threshold for fuzzy matching (default: FUZZY_THRESHOLD from config)

    Returns:
        Dict with ``results`` (list of matching copy documents), ``exact_ids``
        (set of ``_id`` values whose title counts as an exact match - empty for
        ``exact_search`` mode where every result is exact).
    """
    if fuzzy_threshold is None:
        fuzzy_threshold = FUZZY_THRESHOLD

    if exact_search:
        # Exact search mode - only look for exact title matches
        exact_pattern = f"^{re.escape(query)}$"
        exact = await movies_col.find({"title": {"$regex": exact_pattern, "$options": "i"}}).to_list(length=None)
        return {"results": exact, "exact_ids": {r.get("_id") for r in exact}}
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

        exact_ids = {r.get("_id") for r in all_results if is_exact_title(r.get("title"), query)}
        return {"results": all_results, "exact_ids": exact_ids}


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


def build_search_page(results, query, page, exact_ids=None):
    """Build the paginated search-result text + per-line button metadata.

    The result list is a code block of per-title lines:

        Search : Lucky
        Titles Found: 3 (1 Exact | 2 Fuzzy)
        Files Found: 15 (Movie - 5 | Series - 10)
        ...
        1. Lucky > 2 files > Latest: 1080p | 2.5GB | WebRip

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
                              exact_ids=None):
    """Send beautifully formatted search results with pagination.

    The search (its per-title groups, exact/fuzzy split and TMDb metas) is
    stored so the ``Pick``/``Get`` buttons keep working and the Title(s)
    Information block survives page navigation; the same renderers power the
    page:/back: callbacks.

    client is passed explicitly to avoid fragile relative import (previously caused
    ImportError: attempted relative import beyond top-level package)."""
    from .config import bulk_downloads

    search_text, button_data, groups, total_pages = build_search_page(
        results, query, page, exact_ids=exact_ids)

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
        results, query, page, exact_ids=exact_ids)
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
