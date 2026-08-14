"""
Command Handling Module

This module contains all command handlers for the Telegram Movie Bot.
It handles user commands, admin commands, and all related functionality.
"""

import os
import re
import asyncio
import uuid
import logging
from datetime import datetime, timezone, timedelta
from fuzzywuzzy import fuzz
from pyrogram import Client, filters
from pyrogram.types import Message, InlineQuery, InlineQueryResultArticle, InputTextMessageContent, InlineKeyboardMarkup, InlineKeyboardButton, CallbackQuery, LinkPreviewOptions
from pyrogram.enums import ParseMode, ChatType

# Import from our modules
from .config import API_ID, API_HASH, BOT_TOKEN, BOT_ID, MONGO_URI, MONGO_DB, ADMINS, LOG_CHANNEL, FUZZY_THRESHOLD, AUTO_INDEX_DEFAULT, temp_data, user_input_events, bulk_downloads, START_MESSAGE, SUPPORT_LINK
from .database import mongo, db, movies_col, users_col, channels_col, settings_col, logs_col, requests_col, user_request_limits_col, premium_users_col, premium_features_col, ensure_indexes
from .utils import get_readable_time, wait_for_user_input, set_user_input, cleanup_expired_bulk_downloads, resolve_chat_ref

from .user_management import get_user_doc, is_admin, is_banned, has_accepted_terms, load_terms_and_privacy, log_action, check_banned, check_terms_acceptance, should_process_command, require_not_banned
from .file_deletion import track_file_for_deletion
from .config import indexing_lock, message_queue
from .statistics_store import indexing_stats
from .indexing import start_indexing_process, save_file_to_db, process_message_queue
from .search import send_search_results
from .utils import format_file_size, group_recent_content, format_recent_output
from .request_management import check_rate_limits, update_user_limits, check_duplicate_request, validate_imdb_link, get_queue_position, MAX_PENDING_REQUESTS_PER_USER
from .tmdb_integration import search_tmdb, format_tmdb_result, get_random_background_image
from .premium_management import is_premium_user, get_premium_user, add_premium_user, edit_premium_user, remove_premium_user, get_days_remaining, is_feature_premium_only, toggle_feature, add_premium_feature, get_all_premium_features, get_all_premium_users
from .broadcast import cmd_broadcast
from .statistics import (
    collect_comprehensive_stats,
    collect_quick_stats,
    format_stats_output,
    format_quick_stats_output,
    export_stats_json,
    export_stats_csv,
    collect_user_stats,
    format_user_stats_output
)
from .database_scan import scan_message_range

# -------------------------
# Command Handler
# -------------------------
async def handle_command(client, message: Message):
    """Handle bot commands"""
    if not message.text:
        return

    # Access control: only handle commands from allowed contexts (private
    # chats, admins, or registered/enabled monitored channels). Commands from
    # random groups are silently ignored so the bot doesn't respond there.
    if not await should_process_command(message):
        return

    # Parse command
    parts = message.text.split()
    if not parts:
        return

    command = parts[0].lower()
    # Remove bot username if present
    if '@' in command:
        command = command.split('@')[0]

    # Remove leading slash
    if command.startswith('/'):
        command = command[1:]

    # Check if user is banned (except for start command)
    if command != 'start' and await check_banned(message):
        return

    # Check if user has accepted terms (except for start command)
    if command != 'start' and not await check_terms_acceptance(message):
        return

    # Route commands
    if command == 'start':
        await cmd_start(client, message)
    elif command == 'help':
        await cmd_help(client, message)
    elif command == 'search' or command == 'f':
        await cmd_search(client, message)
    # REMOVED COMMANDS: search_year, search_quality, file_info
    # These commands were deemed unoptimized and unnecessary
    # elif command == 'search_year':
    #     await cmd_search_year(client, message)
    # elif command == 'search_quality':
    #     await cmd_search_quality(client, message)
    # elif command == 'file_info':
    #     await cmd_file_info(client, message)

    elif command == 'my_history':
        await cmd_my_history(client, message)
    elif command == 'my_stat':
        await cmd_my_stat(client, message)
    elif command == 'request':
        await cmd_request(client, message)
    # Admin commands
    elif command == 'request_list':
        await cmd_request_list(client, message)
    elif command == 'manage_channel' or command == 'mc':
        await cmd_manage_channel(client, message)
    elif command == 'add_channel':
        await cmd_add_channel(client, message)
    elif command == 'remove_channel':
        await cmd_remove_channel(client, message)
    elif command == 'index_channel':
        await cmd_index_channel(client, message)
    elif command == 'toggle_indexing':
        await cmd_toggle_indexing(client, message)
    elif command == 'promote':
        await cmd_promote(client, message)
    elif command == 'demote':
        await cmd_demote(client, message)
    elif command == 'ban_user':
        await cmd_ban_user(client, message)
    elif command == 'unban_user':
        await cmd_unban_user(client, message)
    elif command == 'reset':
        await cmd_reset(client, message)
    elif command == 'reset_channel':
        await cmd_reset_channel(client, message)
    elif command == 'recent':
        await cmd_recent(client, message)
    elif command == 'trending':
        await cmd_trending(client, message)
    elif command == 'indexing_stats':
        await cmd_indexing_stats(client, message)
    elif command == 'reset_stats':
        await cmd_reset_stats(client, message)
    elif command == 'update_db':
        await cmd_update_db(client, message)
    elif command == 'manual_deletion':
        await cmd_manual_deletion(client, message)
    elif command == 'premium':
        await cmd_premium(client, message)
    elif command == 'broadcast':
        await cmd_broadcast(client, message)
    elif command == 'stat':
        await cmd_stat(client, message)
    elif command == 'quickstat':
        await cmd_quickstat(client, message)
    elif command == 'random':
        await cmd_random(client, message)
    elif command == 'genres':
        await cmd_genres(client, message)
    elif command == 'watch':
        await cmd_watch(client, message)
    elif command == 'unwatch':
        await cmd_unwatch(client, message)
    elif command == 'watchlist':
        await cmd_watchlist(client, message)
    elif command == 'logs':
        await cmd_logs(client, message)
    elif command == 'enrich':
        await cmd_enrich(client, message)
    elif command == 'enrich_status':
        await cmd_enrich_status(client, message)
    else:
        # Unknown command
        await message.reply_text("❓ Unknown command. Use /help to see available commands.")

# -------------------------
# Command Implementations
# -------------------------
USER_HELP = """
╔══════════════════════╗
║   🎬 Movie Bot Help   ║
╚══════════════════════╝

╭─ 🔎 Search
│ /f <title>             Quick search
│ /search <title>        Smart search (exact + fuzzy)
│ /search -e <title>     Exact title only
╰─────────────────────

╭─ 📌 Discover
│ /recent                Newly added
│ /trending              Trending now
│ /random                Surprise me
│ /genres                Browse by genre
│ /request               Request missing title
╰─────────────────────

╭─ 👤 Me
│ /my_history            Your searches
│ /my_stat               Usage + premium info
│ /watch <title>         Watchlist (get notified)
│ /watchlist             Your watched titles
│ /help                  This menu
╰─────────────────────

💡 Tips: /f = fastest • -e = perfect match
📝 Requests: max 3 pending • 1 per day
"""

ADMIN_HELP = """
═══════════════════════
👑 Admin Zone

╭─ 📊 Stats
│ /stat                  Full dashboard
│ /quickstat             Quick key numbers
╰─────────────────────

╭─ 📢 Broadcast & Requests
│ /broadcast [message]   Message users
│ /request_list          Manage requests
╰─────────────────────

╭─ ⭐ Premium
│ /premium               Manage premium + features
╰─────────────────────

╭─ 📡 Channels
│ /mc                    Unified channel manager
│ /add_channel <id>      Add channel
│ /remove_channel <id>   Remove channel
│ /index_channel         Index (interactive)
│ /toggle_indexing       Auto-index on/off
│ /reset_channel         Clear channel index (confirm)
╰─────────────────────

╭─ 👥 Users
│ /promote <user_id>     Make admin
│ /demote <user_id>      Remove admin
│ /ban_user <user_id>    Ban
│ /unban_user <user_id>  Unban
╰─────────────────────

╭─ 🗄️ Database
│ /update_db             Cleanup duplicates/orphans
│ /manual_deletion <t>   Delete by title
│ /indexing_stats        Diagnose indexing skips
│ /reset_stats           Reset counters
│ /logs [n]              Recent audit log entries
│ /enrich [n]            Backfill TMDb metadata
│ /enrich_status         TMDb backfill progress
│ /reset                 WIPE all indexed data (confirm)
╰─────────────────────

✨ Highlights
• /mc unified management • interactive + cancellable indexing
• Better errors + supports all video types • diagnostics for indexing
• Safe resets + cleanup tools • premium feature access control

⚠️ Add the bot as admin in channels to index/monitor files
"""

async def cmd_start(client, message: Message):
    # Check if user is banned first
    if await check_banned(message):
        return

    uid = message.from_user.id
    user_name = message.from_user.first_name or "User"

    # Update last seen
    await users_col.update_one(
        {"user_id": uid},
        {"$set": {"last_seen": datetime.now(timezone.utc)}},
        upsert=True
    )

    # Check if user has already accepted terms
    if await has_accepted_terms(uid):
        # User has already accepted terms - show welcome message
        bg_image = await get_random_background_image()
        
        # Create buttons
        buttons = [
            [
                InlineKeyboardButton("Support", url=SUPPORT_LINK),
                InlineKeyboardButton("Tutorial", callback_data="help")
            ]
        ]
        keyboard = InlineKeyboardMarkup(buttons)

        if bg_image:
            try:
                await message.reply_photo(
                    photo=bg_image,
                    caption=START_MESSAGE,
                    reply_markup=keyboard,
                    parse_mode=ParseMode.MARKDOWN
                )
            except Exception as e:
                # Fallback if image fails
                print(f"Failed to send image: {e}")
                await message.reply_text(
                    START_MESSAGE,
                    reply_markup=keyboard,
                    parse_mode=ParseMode.MARKDOWN
                )
        else:
            await message.reply_text(
                START_MESSAGE,
                reply_markup=keyboard,
                parse_mode=ParseMode.MARKDOWN
            )
        return

    # User hasn't accepted terms - show terms and privacy policy
    terms_content = await load_terms_and_privacy()

    if not terms_content:
        # Fallback if terms file can't be loaded
        await message.reply_text(
            "❌ **Error Loading Terms**\n\n"
            "Unable to load Terms of Use and Privacy Policy.\n"
            "Please contact the administrator.",
            parse_mode=ParseMode.MARKDOWN
        )
        return

    # Split content into chunks (Telegram has a 4096 character limit)
    # We'll send full terms in one message if possible, or split if needed
    max_length = 4000  # Leave some room for formatting

    if len(terms_content) <= max_length:
        # Send in one message
        keyboard = InlineKeyboardMarkup([
            [InlineKeyboardButton("✅ Yes, I Agree", callback_data="terms#accept")],
            [InlineKeyboardButton("❌ Decline", callback_data="terms#decline")]
        ])

        await message.reply_text(
            terms_content,
            reply_markup=keyboard,
            link_preview_options=LinkPreviewOptions(is_disabled=True),
            parse_mode=ParseMode.MARKDOWN
        )
    else:
        # Split into multiple messages
        # Send first part
        first_part = terms_content[:max_length]
        await message.reply_text(
            first_part,
            link_preview_options=LinkPreviewOptions(is_disabled=True),
            parse_mode=ParseMode.MARKDOWN
        )

        # Send remaining parts
        remaining = terms_content[max_length:]
        while len(remaining) > max_length:
            chunk = remaining[:max_length]
            await message.reply_text(
                chunk,
                link_preview_options=LinkPreviewOptions(is_disabled=True),
                parse_mode=ParseMode.MARKDOWN
            )
            remaining = remaining[max_length:]

        # Send final part with buttons
        keyboard = InlineKeyboardMarkup([
            [InlineKeyboardButton("✅ Yes, I Agree", callback_data="terms#accept")],
            [InlineKeyboardButton("❌ Decline", callback_data="terms#decline")]
        ])

        await message.reply_text(
            remaining,
            reply_markup=keyboard,
            link_preview_options=LinkPreviewOptions(is_disabled=True),
            parse_mode=ParseMode.MARKDOWN
        )

async def cmd_help(client, message: Message, user_id=None):
    uid = user_id or message.from_user.id
    text = USER_HELP
    if await is_admin(uid):
        text += "\n" + ADMIN_HELP
    await message.reply_text(text)

async def cmd_search(client, message: Message):
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

    if exact_search:
        # Exact search mode - only look for exact title matches
        exact_pattern = f"^{re.escape(query)}$"
        exact = await movies_col.find({"title": {"$regex": exact_pattern, "$options": "i"}}).to_list(length=None)

        if not exact:
            # No exact matches found - suggest normal search
            await message.reply_text(
                f"⚠️ No exact matches found for \"{query}\"\n\n"
                f"💡 **Try normal search:** /search {query}\n"
                f"🔍 Normal search finds partial and similar titles"
            )
            return

        all_results = exact
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
                if score >= FUZZY_THRESHOLD:
                    candidates.append((score, r))

            candidates = sorted(candidates, key=lambda x: x[0], reverse=True)
            all_results.extend([c[1] for c in candidates])

        if not all_results:
            return await message.reply_text("⚠️ No results found for your search.")

    # Create flashy, neat search results
    # Pass client explicitly to avoid relative import issues inside search module
    await send_search_results(client, message, all_results, query)



async def cmd_my_history(client, message: Message):
    """Display user's search history with clickable command links"""
    uid = message.from_user.id
    doc = await users_col.find_one({"user_id": uid})
    history = doc.get("search_history", []) if doc else []

    if not history:
        return await message.reply_text(
            "No search history found.\n\n"
            "Use /search or /f to start searching."
        )

    # Get statistics
    total_searches = len(history)
    recent_history = history[-20:]  # Last 20 searches
    unique_queries = len(set(h['q'].lower() for h in history))

    # Get first and last search dates
    first_search = history[0]['ts']
    last_search = history[-1]['ts']

    # Build compact header with statistics
    text = "<b>SEARCH HISTORY</b>\n"
    text += f"Total: {total_searches} | Unique: {unique_queries}\n"
    text += f"Period: {first_search.strftime('%b %d, %Y')} - {last_search.strftime('%b %d, %Y')}\n\n"

    # Group searches by date
    from collections import defaultdict
    grouped = defaultdict(list)

    for h in reversed(recent_history):
        date_key = h['ts'].strftime('%d %b, %Y')
        grouped[date_key].append(h)

    # Display grouped searches
    for date_key, searches in grouped.items():
        text += f"<b>{date_key}</b>\n"

        for h in searches:
            query = h['q']
            timestamp = h['ts']

            # Format time only
            time_str = timestamp.strftime('%I:%M%p')

            # Create clickable commands
            normal_cmd = f"/f {query}"
            exact_cmd = f"/f -e {query}"

            # Add entry with time and commands
            text += f"  {time_str} | <code>{normal_cmd}</code> | <code>{exact_cmd}</code>\n"

        text += "\n"

    text += f"<i>Click any command to copy and search</i>"

    # Send message with HTML formatting (no buttons)
    await message.reply_text(
        text,
        parse_mode=ParseMode.HTML,
        link_preview_options=LinkPreviewOptions(is_disabled=True)
    )



async def cmd_my_stat(client, message: Message):
    """Display comprehensive user statistics"""
    uid = message.from_user.id
    
    # Send "loading" message
    status_msg = await message.reply_text("📊 Collecting your statistics...")
    
    try:
        # Collect user statistics
        stats = await collect_user_stats(uid)
        
        if not stats:
            await status_msg.edit_text(
                "❌ **Unable to retrieve statistics**\n\n"
                "Your user profile might not be fully initialized yet.\n"
                "Try using the bot for a while and check back later!"
            )
            return
        
        # Format and send statistics
        output = format_user_stats_output(stats)
        await status_msg.edit_text(output, parse_mode=ParseMode.HTML)
        
        # Log the action
        await log_action("my_stat_viewed", by=uid)
        
    except Exception as e:
        print(f"❌ Error in cmd_my_stat: {e}")
        import traceback
        traceback.print_exc()
        
        await status_msg.edit_text(
            "❌ **Error retrieving statistics**\n\n"
            "An error occurred while collecting your statistics.\n"
            "Please try again later or contact an admin if the issue persists."
        )

async def cmd_recent(client, message: Message):
    """Handle /recent command to display last batch update content"""

    # Check if user is banned
    if await check_banned(message):
        return

    # Check if feature is premium-only
    uid = message.from_user.id
    if await is_feature_premium_only("recent"):
        # Check if user is premium or admin
        if not await is_admin(uid) and not await is_premium_user(uid):
            return await message.reply_text(
                "⭐ <b>Premium Feature</b>\n\n"
                "The /recent command is a premium-only feature.\n\n"
                "Contact an admin to get premium access.",
                parse_mode=ParseMode.HTML
            )

    try:
        # First, get the most recent indexed_at timestamp
        latest_doc = await movies_col.find_one(
            {"indexed_at": {"$exists": True}},
            {"indexed_at": 1},
            sort=[("indexed_at", -1)]
        )

        if not latest_doc or not latest_doc.get('indexed_at'):
            await message.reply_text(
                "📭 <b>No Content Found</b>\n\n"
                "The database doesn't contain any indexed content yet.\n\n"
                "💡 Add channels and enable indexing to see recent content here.",
                parse_mode=ParseMode.HTML
            )
            return

        # Get the latest indexed_at timestamp
        latest_indexed_at = latest_doc['indexed_at']

        # Define batch window: files indexed within 10 minutes of the most recent
        batch_window_start = latest_indexed_at - timedelta(minutes=10)

        # Query for files in the last batch
        cursor = movies_col.find(
            {"indexed_at": {"$gte": batch_window_start}},
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
        ).sort("indexed_at", -1)

        raw_results = await cursor.to_list(length=None)

        # Handle empty results
        if not raw_results:
            await message.reply_text(
                "📭 <b>No Content Found</b>\n\n"
                "No recent batch updates found.",
                parse_mode=ParseMode.HTML
            )
            return

        # Calculate statistics
        total_files = len(raw_results)
        total_movies = len([r for r in raw_results if r.get('type', 'Movie').lower() not in ['series', 'tv', 'show']])
        total_series = len([r for r in raw_results if r.get('type', 'Movie').lower() in ['series', 'tv', 'show']])

        # Get last updated time from most recent item
        last_updated = latest_indexed_at.strftime('%Y-%m-%d %H:%M UTC')

        # Process and format results
        grouped_results = group_recent_content(raw_results)
        formatted_output = format_recent_output(grouped_results, total_files, total_movies, total_series, last_updated)

        # Send response with HTML parse mode
        await message.reply_text(
            formatted_output,
            parse_mode=ParseMode.HTML,
            link_preview_options=LinkPreviewOptions(is_disabled=True)
        )

        # Log successful usage
        await log_action("recent_command", by=message.from_user.id, extra={
            "results_count": len(raw_results),
            "grouped_count": len(grouped_results),
            "total_files": total_files,
            "total_movies": total_movies,
            "total_series": total_series,
            "batch_window_minutes": 10
        })

    except Exception as e:
        # Comprehensive error handling
        await log_action("recent_command_error", by=message.from_user.id, extra={
            "error": str(e),
            "error_type": "general"
        })

        await message.reply_text(
            "❌ <b>Error</b>\n\n"
            "Unable to fetch recent content. Please try again later.",
            parse_mode=ParseMode.HTML
        )


async def cmd_trending(client, message: Message):
    """Handle /trending command to display trending movies, shows, and new releases"""
    from .tmdb_integration import get_trending_movies, format_trending_list

    # Fetch trending movies by default
    status_msg = await message.reply_text("Fetching trending content...")

    try:
        movies = await get_trending_movies()

        if not movies:
            await status_msg.edit_text(
                "**Trending**\n\n"
                "Unable to fetch trending data. Please try again later."
            )
            return

        # Format the list
        content = format_trending_list(movies, "movies")

        # Create category buttons (Movies is active by default)
        buttons = [
            [
                InlineKeyboardButton("🟨 Movies", callback_data="trending:movies:active"),
                InlineKeyboardButton("Shows", callback_data="trending:shows"),
                InlineKeyboardButton("New Releases", callback_data="trending:releases")
            ]
        ]

        output = f"🔥 **Trending Movies**\n\n{content}"

        await status_msg.edit_text(
            output,
            reply_markup=InlineKeyboardMarkup(buttons),
            link_preview_options=LinkPreviewOptions(is_disabled=True)
        )

    except Exception as e:
        print(f"Error in trending command: {e}")
        await status_msg.edit_text(
            "**Trending**\n\n"
            "Unable to fetch trending data. Please try again later."
        )


async def cmd_random(client, message: Message):
    """Handle /random - pick a random indexed title (poster when available)"""
    import random

    if await check_banned(message):
        return

    try:
        total = await movies_col.count_documents({})
        if not total:
            return await message.reply_text(
                "📭 <b>No Content Found</b>\n\nNo movies or series are indexed yet.",
                parse_mode=ParseMode.HTML,
            )
        skip = random.randrange(total)
        doc = await movies_col.find_one({}, skip=skip)
        if not doc:
            return await message.reply_text("📭 No content found.")

        title = doc.get("title", "Unknown")
        year = doc.get("year")
        quality = doc.get("quality")
        movie_type = doc.get("type", "Movie")
        poster = doc.get("tmdb_poster")

        meta = {}
        if doc.get("tmdb_rating"):
            meta["rating"] = doc.get("tmdb_rating")
        if doc.get("tmdb_genres"):
            meta["genres"] = doc.get("tmdb_genres")
        if doc.get("imdb_id"):
            meta["imdb_id"] = doc.get("imdb_id")
        from .tmdb_integration import format_enrichment_line
        suffix = format_enrichment_line(meta or None)

        caption = (
            f"🎲 <b>Random Pick</b>\n\n"
            f"🎬 <b>{title}</b> ({year or 'N/A'}) · {movie_type}\n"
            f"🎞️ Quality: {quality or 'N/A'}"
        )
        if suffix:
            caption += f"\n{suffix}"

        buttons = None
        if doc.get("channel_id") and doc.get("message_id"):
            buttons = InlineKeyboardMarkup([[
                InlineKeyboardButton(
                    "📥 Get File",
                    callback_data=f"get_file:{doc['channel_id']}:{doc['message_id']}",
                )
            ]])

        if poster:
            try:
                await message.reply_photo(poster, caption=caption, reply_markup=buttons)
                return
            except Exception as e:
                print(f"⚠️ /random poster send failed ({poster}): {e}")
        await message.reply_text(
            caption,
            reply_markup=buttons,
            parse_mode=ParseMode.HTML,
            link_preview_options=LinkPreviewOptions(is_disabled=True),
        )
    except Exception as e:
        print(f"Error in random command: {e}")
        await message.reply_text("❌ Unable to pick a random title. Please try again later.")


async def cmd_genres(client, message: Message):
    """Handle /genres - browse indexed titles by TMDb genre.

    /genres            -> list genres with counts
    /genres <name>     -> browse titles in that genre
    """
    if await check_banned(message):
        return

    parts = message.text.split(maxsplit=1)
    genre_query = parts[1].strip() if len(parts) > 1 else ""

    try:
        if not genre_query:
            pipeline = [
                {"$unwind": "$tmdb_genres"},
                {"$group": {"_id": "$tmdb_genres", "count": {"$sum": 1}}},
                {"$sort": {"count": -1}},
            ]
            counts = await movies_col.aggregate(pipeline).to_list(length=100)
            if not counts:
                return await message.reply_text(
                    "🎭 <b>No genre data yet</b>\n\n"
                    "Run <code>/enrich</code> (admin) to backfill TMDb genres for indexed titles.",
                    parse_mode=ParseMode.HTML,
                )
            lines = [f"{i}. {c['_id']} — {c['count']}" for i, c in enumerate(counts, 1)]
            text = "🎭 <b>Genres</b>\n\n" + "\n".join(lines)
            text += "\n\nSend <code>/genres &lt;name&gt;</code> to browse a genre."
            return await message.reply_text(text, parse_mode=ParseMode.HTML)

        # Browse a genre (case-insensitive match on stored genre names)
        entries = await movies_col.find(
            {"tmdb_genres": {"$regex": f"^{re.escape(genre_query)}$", "$options": "i"}},
            {"title": 1, "year": 1, "quality": 1, "channel_id": 1, "message_id": 1, "type": 1, "tmdb_rating": 1},
        ).limit(12).to_list(length=12)

        if not entries:
            return await message.reply_text(f"🎭 No indexed titles found in genre <b>{genre_query}</b>.", parse_mode=ParseMode.HTML)

        lines = []
        buttons = []
        for i, e in enumerate(entries, 1):
            rating = f" ⭐{e.get('tmdb_rating')}" if e.get("tmdb_rating") else ""
            lines.append(f"{i}. <b>{e.get('title')}</b> ({e.get('year') or 'N/A'}) [{e.get('quality') or 'N/A'}]{rating}")
            if e.get("channel_id") and e.get("message_id"):
                buttons.append(InlineKeyboardButton(
                    f"Get [{i}]", callback_data=f"get_file:{e['channel_id']}:{e['message_id']}"
                ))
        text = f"🎭 <b>{genre_query}</b> ({len(entries)} titles)\n\n" + "\n".join(lines)
        reply_markup = InlineKeyboardMarkup([buttons[i:i+4] for i in range(0, len(buttons), 4)]) if buttons else None
        await message.reply_text(
            text,
            reply_markup=reply_markup,
            parse_mode=ParseMode.HTML,
            link_preview_options=LinkPreviewOptions(is_disabled=True),
        )
    except Exception as e:
        print(f"Error in genres command: {e}")
        await message.reply_text("❌ Unable to browse genres. Please try again later.")


async def cmd_watch(client, message: Message):
    """Handle /watch <title> - add a title to your watchlist."""
    from .user_management import add_to_watchlist

    parts = message.text.split(maxsplit=1)
    if len(parts) < 2:
        return await message.reply_text(
            "👁️ <b>Watchlist</b>\n\nUsage: <code>/watch &lt;title&gt;</code>\n"
            "You'll be notified when a new copy of the title is indexed.",
            parse_mode=ParseMode.HTML,
        )
    title = parts[1].strip()
    added = await add_to_watchlist(message.from_user.id, title)
    if added:
        await message.reply_text(f"👁️ <b>{title}</b> added to your watchlist.\n\nYou'll be notified when it's available.", parse_mode=ParseMode.HTML)
    else:
        await message.reply_text(f"👁️ <b>{title}</b> is already on your watchlist.", parse_mode=ParseMode.HTML)


async def cmd_unwatch(client, message: Message):
    """Handle /unwatch <title> - remove a title from your watchlist."""
    from .user_management import remove_from_watchlist

    parts = message.text.split(maxsplit=1)
    if len(parts) < 2:
        return await message.reply_text("👁️ Usage: <code>/unwatch &lt;title&gt;</code>", parse_mode=ParseMode.HTML)
    removed = await remove_from_watchlist(message.from_user.id, parts[1].strip())
    if removed:
        await message.reply_text(f"✅ <b>{parts[1].strip()}</b> removed from your watchlist.", parse_mode=ParseMode.HTML)
    else:
        await message.reply_text(f"👁️ <b>{parts[1].strip()}</b> is not on your watchlist.", parse_mode=ParseMode.HTML)


async def cmd_watchlist(client, message: Message):
    """Handle /watchlist - show your watched titles."""
    from .user_management import get_watchlist

    entries = await get_watchlist(message.from_user.id)
    if not entries:
        return await message.reply_text(
            "👁️ <b>Your watchlist is empty</b>\n\n"
            "Use <code>/watch &lt;title&gt;</code> to get notified when a title is indexed.",
            parse_mode=ParseMode.HTML,
        )
    lines = [f"{i}. <b>{e.get('title')}</b> ({e.get('type') or 'Movie'})" for i, e in enumerate(entries, 1)]
    text = "👁️ <b>Your Watchlist</b>\n\n" + "\n".join(lines)
    text += "\n\nRemove with <code>/unwatch &lt;title&gt;</code>"
    await message.reply_text(text, parse_mode=ParseMode.HTML)


async def cmd_logs(client, message: Message):
    """Admin: view the most recent audit-log entries from the database."""
    uid = message.from_user.id
    if not await is_admin(uid):
        return await message.reply_text("🚫 Admins only.")

    parts = message.text.split()
    limit = 10
    if len(parts) > 1 and parts[1].isdigit():
        limit = min(int(parts[1]), 50)

    try:
        docs = await logs_col.find({}).sort("ts", -1).limit(limit).to_list(length=limit)
        if not docs:
            return await message.reply_text("📋 No log entries yet.")

        lines = []
        for d in docs:
            ts = d.get("ts")
            ts_str = ts.strftime("%m-%d %H:%M") if hasattr(ts, "strftime") else str(ts)[:16]
            by = d.get("by")
            target = d.get("target")
            extra = d.get("extra") or {}
            detail = ", ".join(f"{k}: {v}" for k, v in list(extra.items())[:3])
            line = f"<code>{ts_str}</code> <b>{d.get('action')}</b>"
            if by:
                line += f" by {by}"
            if target:
                line += f" → {target}"
            if detail:
                line += f" | {detail}"
            lines.append(line)

        text = f"📋 <b>Recent Logs</b> (last {len(docs)})\n\n" + "\n".join(lines)
        await message.reply_text(text, parse_mode=ParseMode.HTML, link_preview_options=LinkPreviewOptions(is_disabled=True))
    except Exception as e:
        print(f"Error in logs command: {e}")
        await message.reply_text("❌ Unable to fetch logs.")


async def cmd_enrich(client, message: Message):
    """Admin: backfill TMDb metadata (poster/genres/rating/imdb) for indexed entries."""
    uid = message.from_user.id
    if not await is_admin(uid):
        return await message.reply_text("🚫 Admins only.")

    from .tmdb_integration import enrich_title, TMDB_ENRICH_INDEX
    if not TMDB_ENRICH_INDEX:
        return await message.reply_text("ℹ️ TMDb enrichment is disabled (set TMDB_ENRICH_INDEX=true in .env).")

    parts = message.text.split()
    limit = 30
    if len(parts) > 1 and parts[1].isdigit():
        limit = min(int(parts[1]), 200)

    status = await message.reply_text("🔍 Enriching entries with TMDb metadata...")
    try:
        docs = await movies_col.find(
            {"tmdb_genres": {"$exists": False}},
            {"title": 1, "year": 1, "type": 1, "_id": 1, "imdb": 1},
        ).limit(limit).to_list(length=limit)

        enriched = 0
        for doc in docs:
            meta = await enrich_title(doc.get("title"), doc.get("year"), doc.get("type", "Movie"))
            if meta:
                set_fields = {
                    "tmdb_poster": meta.get("poster_url"),
                    "tmdb_rating": meta.get("rating"),
                    "tmdb_genres": meta.get("genres"),
                    "tmdb_overview": meta.get("overview"),
                    "imdb_id": meta.get("imdb_id") or doc.get("imdb"),
                }
                await movies_col.update_one({"_id": doc["_id"]}, {"$set": set_fields})
                enriched += 1
            await asyncio.sleep(0.2)  # gentle pace toward TMDb rate limits

        await status.edit_text(f"✅ Enriched <b>{enriched}/{len(docs)}</b> entries with TMDb metadata.", parse_mode=ParseMode.HTML)
    except Exception as e:
        print(f"Error in enrich command: {e}")
        await status.edit_text("❌ Enrichment failed. Please try again later.")


async def cmd_enrich_status(client, message: Message):
    """Admin: show how many indexed titles still lack TMDb metadata."""
    uid = message.from_user.id
    if not await is_admin(uid):
        return await message.reply_text("🚫 Admins only.")

    try:
        total = await movies_col.count_documents({})
        pending = await movies_col.count_documents({"tmdb_genres": {"$exists": False}})
        no_match = await movies_col.count_documents({"tmdb_genres": []})
        enriched = total - pending - no_match

        done_pct = (enriched / total * 100) if total else 100.0
        filled = int(done_pct / 5)
        bar = "█" * filled + "░" * (20 - filled)

        text = (
            "📊 <b>TMDb Enrichment Status</b>\n\n"
            f"🎬 Total indexed: <b>{total}</b>\n"
            f"✅ Enriched: <b>{enriched}</b> ({done_pct:.1f}%)\n"
            f"⏳ Pending: <b>{pending}</b>\n"
            f"🚫 No TMDb match: <b>{no_match}</b>\n\n"
            f"<code>{bar}</code>\n\n"
            f"💡 Run <code>/enrich</code> or <code>scripts/backfill_enrichment.py</code> to backfill pending titles."
        )
        await message.reply_text(text, parse_mode=ParseMode.HTML)
    except Exception as e:
        print(f"Error in enrich_status command: {e}")
        await message.reply_text("❌ Unable to fetch enrichment status.")


# -------------------------
# Admin Commands (simplified implementations)
# -------------------------
async def cmd_add_channel(client, message: Message):
    uid = message.from_user.id
    if not await is_admin(uid):
        return await message.reply_text("🚫 Admins only.")
    parts = message.text.split()
    if len(parts) < 2:
        return await message.reply_text("Usage: /add_channel <link|id|@username>")
    target = parts[1]
    try:
        chat = await resolve_chat_ref(target, client)
        doc = {"channel_id": chat.id, "channel_title": getattr(chat, "title", None), "added_by": uid, "added_at": datetime.now(timezone.utc), "enabled": True}
        await channels_col.update_one({"channel_id": chat.id}, {"$set": doc}, upsert=True)
        await log_action("add_channel", by=uid, target=chat.id, extra={"title": doc["channel_title"]})
        await message.reply_text(f"✅ Channel added: {doc['channel_title']} ({chat.id})")
    except Exception as e:
        await message.reply_text(f"❌ Could not resolve channel: {e}")

async def cmd_remove_channel(client, message: Message):
    uid = message.from_user.id
    if not await is_admin(uid):
        return await message.reply_text("🚫 Admins only.")
    parts = message.text.split()
    if len(parts) < 2:
        return await message.reply_text("Usage: /remove_channel <link|id|@username>")
    target = parts[1]
    try:
        chat = await resolve_chat_ref(target, client)
        await channels_col.delete_one({"channel_id": chat.id})
        await log_action("remove_channel", by=uid, target=chat.id)
        await message.reply_text(f"✅ Channel removed: {getattr(chat,'title', chat.id)} ({chat.id})")
    except Exception as e:
        await message.reply_text(f"❌ Could not remove channel: {e}")

async def cmd_index_channel(client, message: Message):
    """Enhanced indexing command using iter_messages"""
    uid = message.from_user.id
    if not await is_admin(uid):
        return await message.reply_text("🚫 Admins only.")

    if indexing_lock.locked():
        return await message.reply_text("⏳ Another indexing process is already running. Please wait.")

    i = await message.reply_text("📝 Send me channel username, channel ID, or a message link from the channel you want to index.")

    try:
        # Wait for user response using our custom input system
        response = await wait_for_user_input(message.chat.id, message.from_user.id, timeout=60)
        await i.delete()

        # Parse response
        if response.text and response.text.startswith("https://t.me"):
            # Handle message link
            try:
                msg_link = response.text.split("/")
                last_msg_id = int(msg_link[-1])
                chat_id = msg_link[-2]
                if chat_id.isnumeric():
                    chat_id = int(("-100" + chat_id))
            except:
                return await message.reply_text('❌ Invalid message link!')
        elif getattr(response, "forward_origin", None) and getattr(response.forward_origin, "chat", None) and response.forward_origin.chat.type == ChatType.CHANNEL:
            # Handle forwarded message (forward_origin replaces the deprecated
            # forward_from_chat / forward_from_message_id properties)
            last_msg_id = response.forward_origin.message_id
            chat_id = response.forward_origin.chat.username or response.forward_origin.chat.id
        else:
            return await message.reply_text('❌ This is not a forwarded message or valid link.')

        # Get chat information
        try:
            chat = await client.get_chat(chat_id)
        except Exception as e:
            return await message.reply_text(f'❌ Error accessing chat: {e}')

        if chat.type != ChatType.CHANNEL:
            return await message.reply_text("❌ I can only index channels.")

        # Ask for skip number
        s = await message.reply_text("🔢 Send number of messages to skip (0 to start from beginning):")
        skip_response = await wait_for_user_input(message.chat.id, message.from_user.id, timeout=30)
        await s.delete()

        try:
            skip = int(skip_response.text)
        except:
            return await message.reply_text("❌ Invalid number.")

        # Confirmation
        buttons = [
            [InlineKeyboardButton('✅ YES', callback_data=f'index#yes#{chat_id}#{last_msg_id}#{skip}')],
            [InlineKeyboardButton('❌ CANCEL', callback_data='index#cancel')]
        ]
        reply_markup = InlineKeyboardMarkup(buttons)

        await message.reply_text(
            f'🎬 **Index Channel Confirmation**\n\n'
            f'📺 **Channel:** {chat.title}\n'
            f'🆔 **ID:** `{chat_id}`\n'
            f'📊 **Total Messages:** `{last_msg_id}`\n'
            f'⏭️ **Skip:** `{skip}` messages\n'
            f'📁 **Will Process:** `{last_msg_id - skip}` messages\n\n'
            f'⚠️ **Note:** Only video files will be indexed\n'
            f'🤖 **Bot must be admin** in channel\n\n'
            f'Do you want to proceed?',
            reply_markup=reply_markup
        )

    except asyncio.TimeoutError:
        await i.delete()
        await message.reply_text("⏰ Timeout! Please try again.")
    except Exception as e:
        await message.reply_text(f"❌ Error: {e}")


async def cmd_manage_channel(client, message: Message):
    """Unified channel management command - displays channels with stats and action buttons"""
    uid = message.from_user.id
    if not await is_admin(uid):
        return await message.reply_text("🚫 Admins only.")

    # Get auto-indexing status for the Monitoring button
    auto_index_doc = await settings_col.find_one({"k": "auto_indexing"})
    auto_indexing_enabled = auto_index_doc["v"] if auto_index_doc else AUTO_INDEX_DEFAULT
    monitoring_icon = "🟢" if auto_indexing_enabled else "🔴"

    # Get all channels
    channels = await channels_col.find({}).to_list(length=100)

    if not channels:
        # No channels configured
        output = "CHANNEL MANAGEMENT\n\n"
        output += "No channels configured yet.\n\n"
        output += "QUICK ACTIONS\n"
        output += "Use the buttons below to manage channels.\n\n"
        output += "COMMAND GUIDE\n"
        output += "Add - Add a new channel to monitor\n"
        output += "Remove - Remove an existing channel\n"
        output += "Scan - Scan messages from a channel\n"
        output += "Update - Sync DB with channel (detect new/deleted files)\n"
        output += "Reset - Clear indexed data from a channel\n"
        output += "Indexing - Toggle auto-indexing on/off"
    else:
        # Build aggregation pipeline to get indexed counts per channel
        pipeline = [
            {"$group": {"_id": "$channel_id", "count": {"$sum": 1}}},
            {"$sort": {"count": -1}}
        ]
        indexed_counts = await movies_col.aggregate(pipeline).to_list(length=100)

        # Create a map of channel_id to count
        count_map = {item["_id"]: item["count"] for item in indexed_counts}

        # Build output
        output = "CHANNEL MANAGEMENT\n\n"
        output += "REGISTERED CHANNELS\n\n"

        for idx, ch in enumerate(channels, 1):
            channel_id = ch.get("channel_id")
            channel_title = ch.get("channel_title", "Unknown")
            enabled = ch.get("enabled", True)
            added_at = ch.get("added_at")
            indexed_count = count_map.get(channel_id, 0)

            # Format date
            date_str = "N/A"
            if added_at:
                date_str = added_at.strftime("%Y-%m-%d")

            # Build channel info with click-to-copy ID
            output += f"{idx}. {channel_title}\n"
            output += f"   ID: <code>{channel_id}</code>\n"
            output += f"   Indexed: {indexed_count} files\n"
            output += f"   Status: {'Enabled' if enabled else 'Disabled'}\n"
            output += f"   Added: {date_str}\n\n"

        output += "QUICK ACTIONS\n"
        output += "Use the buttons below to manage channels.\n\n"
        output += "COMMAND GUIDE\n"
        output += "Add - Add a new channel to monitor\n"
        output += "Remove - Remove an existing channel\n"
        output += "Scan - Scan messages from a channel\n"
        output += "Update - Sync DB with channel (detect new/deleted files)\n"
        output += "Reset - Clear indexed data from a channel\n"
        output += "Indexing - Toggle auto-indexing on/off"

    # Create action buttons
    buttons = [
        [
            InlineKeyboardButton("Add", callback_data="mc#add"),
            InlineKeyboardButton("Remove", callback_data="mc#remove"),
            InlineKeyboardButton("Scan", callback_data="mc#index")
        ],
        [
            InlineKeyboardButton("Update", callback_data="mc#update"),
            InlineKeyboardButton("Reset", callback_data="mc#reset"),
            InlineKeyboardButton(f"{monitoring_icon} Indexing", callback_data="mc#monitoring")
        ]
    ]

    reply_markup = InlineKeyboardMarkup(buttons)
    await message.reply_text(output, reply_markup=reply_markup)

async def cmd_toggle_indexing(client, message: Message):
    uid = message.from_user.id
    if not await is_admin(uid):
        return await message.reply_text("🚫 Admins only.")
    doc = await settings_col.find_one({"k": "auto_indexing"})
    current = doc["v"] if doc else AUTO_INDEX_DEFAULT
    new = not current
    await settings_col.update_one({"k": "auto_indexing"}, {"$set": {"v": new}}, upsert=True)
    await message.reply_text(f"Auto-indexing set to {new}")
    await log_action("toggle_indexing", by=uid, extra={"new": new})

async def cmd_promote(client, message: Message):
    uid = message.from_user.id
    if not await is_admin(uid):
        return await message.reply_text("🚫 Admins only.")
    parts = message.text.split()
    if len(parts) < 2:
        return await message.reply_text("Usage: /promote <user_id>")
    try:
        target = int(parts[1])
        await users_col.update_one({"user_id": target}, {"$set": {"role": "admin"}}, upsert=True)
        await message.reply_text(f"✅ {target} promoted to admin.")
        await log_action("promote", by=uid, target=target)
    except Exception:
        await message.reply_text("Invalid user id.")

async def cmd_demote(client, message: Message):
    uid = message.from_user.id
    if not await is_admin(uid):
        return await message.reply_text("🚫 Admins only.")
    parts = message.text.split()
    if len(parts) < 2:
        return await message.reply_text("Usage: /demote <user_id>")
    try:
        target = int(parts[1])
        await users_col.update_one({"user_id": target}, {"$set": {"role": "user"}}, upsert=True)
        await message.reply_text(f"✅ {target} demoted to user.")
        await log_action("demote", by=uid, target=target)
    except Exception:
        await message.reply_text("Invalid user id.")

async def cmd_ban_user(client, message: Message):
    uid = message.from_user.id
    if not await is_admin(uid):
        return await message.reply_text("🚫 Admins only.")
    parts = message.text.split()
    if len(parts) < 2:
        return await message.reply_text("Usage: /ban_user <user_id>")
    try:
        target = int(parts[1])
        await users_col.update_one({"user_id": target}, {"$set": {"role": "banned"}}, upsert=True)
        await message.reply_text(f"🚫 {target} has been banned.")
        await log_action("ban_user", by=uid, target=target)
    except Exception:
        await message.reply_text("Invalid user id.")

async def cmd_unban_user(client, message: Message):
    uid = message.from_user.id
    if not await is_admin(uid):
        return await message.reply_text("🚫 Admins only.")
    parts = message.text.split()
    if len(parts) < 2:
        return await message.reply_text("Usage: /unban_user <user_id>")
    try:
        target = int(parts[1])
        await users_col.update_one({"user_id": target}, {"$set": {"role": "user"}}, upsert=True)
        await message.reply_text(f"✅ {target} has been unbanned.")
        await log_action("unban_user", by=uid, target=target)
    except Exception:
        await message.reply_text("Invalid user id.")

async def cmd_reset(client, message: Message):
    """Reset command - clears all indexed data with confirmation"""
    uid = message.from_user.id
    if not await is_admin(uid):
        return await message.reply_text("🚫 Admins only.")

    # Send confirmation prompt
    confirmation_msg = await message.reply_text(
        "⚠️ **Database Reset Confirmation**\n\n"
        "🗑️ This will **PERMANENTLY DELETE** all indexed movie data from the database!\n\n"
        "📊 **What will be deleted:**\n"
        "• All movie entries in the database\n"
        "• All search history will remain\n"
        "• All user accounts will remain\n"
        "• Channel configurations will remain\n\n"
        "🔄 **After reset:**\n"
        "• Fresh indexing will be required\n"
        "• All previous movie files will need to be re-indexed\n\n"
        "**To confirm, type:** `CONFIRM`\n"
        "**To cancel, type anything else or wait 30 seconds**\n\n"
        "⏰ This prompt will timeout in 30 seconds."
    )

    try:
        # Wait for user response with 30-second timeout
        response = await wait_for_user_input(message.chat.id, message.from_user.id, timeout=30)

        if response and response.text and response.text.upper().strip() == "CONFIRM":
            # User confirmed - proceed with reset
            await confirmation_msg.edit_text(
                "🔄 **Resetting Database...**\n\n"
                "🗑️ Clearing all indexed movie data..."
            )

            try:
                # Clear movies collection (this contains all indexed movie data)
                result = await movies_col.delete_many({})
                deleted_count = result.deleted_count

                # Log reset action
                await log_action("reset_database", by=uid, extra={
                    "deleted_count": deleted_count,
                    "success": True
                })

                # Update confirmation message with success
                await confirmation_msg.edit_text(
                    f"✅ **Database Reset Complete!**\n\n"
                    f"🗑️ **Deleted:** {deleted_count} movie entries\n"
                    f"👤 **By:** {uid}\n"
                    f"🕒 **Time:** {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S UTC')}\n\n"
                    f"🔄 **The database is now clean and ready for fresh indexing.**\n"
                    f"💡 Use `/index_channel` to add new movie files to the database."
                )

                print(f"🗑️ Database reset completed by user {uid}. Deleted {deleted_count} movie entries.")

            except Exception as e:
                # Handle database error
                await log_action("reset_database", by=uid, extra={
                    "success": False,
                    "error": str(e)
                })

                await confirmation_msg.edit_text(
                    f"❌ **Database Reset Failed!**\n\n"
                    f"**Error:** {str(e)}\n\n"
                    f"🔄 The database was not modified. Please try again later."
                )

                print(f"❌ Database reset failed for user {uid}: {e}")

        else:
            # User cancelled or typed something else
            await confirmation_msg.edit_text(
                "❌ **Database Reset Cancelled**\n\n"
                "🛡️ No changes were made to the database.\n"
                "💡 All your indexed movie data is safe."
            )

    except asyncio.TimeoutError:
        # Timeout - auto cancel
        await confirmation_msg.edit_text(
            "⏰ **Database Reset Timeout**\n\n"
            "🛡️ The reset operation was cancelled due to timeout.\n"
            "💡 All your indexed movie data is safe.\n"
            "🔄 You can try again later if needed."
        )

    except Exception as e:
        # Unexpected error
        await log_action("reset_error", by=uid, extra={"error": str(e)})
        await confirmation_msg.edit_text(
            f"❌ **Unexpected Error**\n\n"
            f"**Error:** {str(e)}\n\n"
            f"🛡️ The database was not modified."
        )

async def cmd_reset_channel(client, message: Message):
    """Reset command - clears indexed data from a specific channel with confirmation"""
    uid = message.from_user.id
    if not await is_admin(uid):
        return await message.reply_text("🚫 Admins only.")

    # Step 1: Get list of registered channels
    try:
        channels_cursor = channels_col.find({})
        channels = []
        async for channel_doc in channels_cursor:
            channels.append({
                'channel_id': channel_doc.get('channel_id'),
                'channel_title': channel_doc.get('channel_title', 'Unknown Channel'),
                'enabled': channel_doc.get('enabled', True)
            })

        if not channels:
            return await message.reply_text("📺 No registered channels found. Use /add_channel to add channels first.")

        # Step 2: Display numbered list of channels
        channel_list_text = "📺 **Select a channel to reset:**\n\n"
        for i, channel in enumerate(channels, 1):
            status = "✅ Enabled" if channel['enabled'] else "❌ Disabled"
            channel_list_text += f"{i}. **{channel['channel_title']}**\n"
            channel_list_text += f"   📊 ID: `{channel['channel_id']}` | {status}\n\n"

        channel_list_text += "🔢 **Send number** of the channel you want to reset\n"
        channel_list_text += "⏰ **Timeout:** 30 seconds\n"
        channel_list_text += "🛑 **To cancel:** Send 'CANCEL'"

        selection_msg = await message.reply_text(channel_list_text)

        # Step 3: Wait for channel selection
        try:
            response = await wait_for_user_input(message.chat.id, message.from_user.id, timeout=30)

            # Handle cancellation
            if not response or (response.text and response.text.upper().strip() == "CANCEL"):
                await selection_msg.edit_text("❌ **Channel Reset Cancelled**\n\n🛡️ No changes were made to the database.")
                return

            # Parse channel selection
            try:
                selection = int(response.text.strip())
                if selection < 1 or selection > len(channels):
                    raise ValueError("Invalid selection")
                selected_channel = channels[selection - 1]
            except (ValueError, IndexError):
                await selection_msg.edit_text("❌ **Invalid Selection**\n\nPlease send a valid channel number or 'CANCEL' to abort.")
                return

            # Step 4: Show confirmation with channel details
            channel_id = selected_channel['channel_id']
            channel_title = selected_channel['channel_title']

            # Count documents to be deleted
            docs_to_delete = await movies_col.count_documents({"channel_id": channel_id})

            confirmation_text = f"🗑️ **Channel Reset Confirmation**\n\n"
            confirmation_text += f"📺 **Channel:** {channel_title}\n"
            confirmation_text += f"🆔 **ID:** `{channel_id}`\n"
            confirmation_text += f"📊 **Files to delete:** {docs_to_delete} movie entries\n\n"
            confirmation_text += f"⚠️ **This will permanently delete ALL indexed movie data from this channel!**\n\n"
            confirmation_text += f"**What will be deleted:**\n"
            confirmation_text += f"• All movie entries from {channel_title}\n"
            confirmation_text += f"• All metadata associated with this channel\n"
            confirmation_text += f"• Search results will be affected\n\n"
            confirmation_text += f"**What will remain:**\n"
            confirmation_text += f"• Channel configuration\n"
            confirmation_text += f"• Data from other channels\n"
            confirmation_text += f"• User accounts and settings\n\n"
            confirmation_text += f"**To confirm, type:** `CONFIRM`\n"
            confirmation_text += f"**To cancel, type:** `CANCEL`\n\n"
            confirmation_text += f"⏰ **This prompt will timeout in 30 seconds.**"

            confirmation_msg = await message.reply_text(confirmation_text)

            # Step 5: Wait for final confirmation
            try:
                final_response = await wait_for_user_input(message.chat.id, message.from_user.id, timeout=30)

                # Handle final cancellation
                if not final_response or (final_response.text and final_response.text.upper().strip() != "CONFIRM"):
                    await confirmation_msg.edit_text(
                        f"❌ **Channel Reset Cancelled**\n\n"
                        f"🛡️ No changes were made to the database.\n"
                        f"📁 All movie data from {channel_title} remains safe."
                    )
                    return

                # Step 6: Proceed with channel reset
                await confirmation_msg.edit_text(
                    f"🔄 **Resetting Channel Data...**\n\n"
                    f"📺 Channel: {channel_title}\n"
                    f"🗑️ Clearing indexed movie data..."
                )

                try:
                    # Delete documents from movies collection for this channel
                    result = await movies_col.delete_many({"channel_id": channel_id})
                    deleted_count = result.deleted_count

                    # Log reset action with comprehensive details
                    await log_action("reset_channel", by=uid, target=channel_id, extra={
                        "channel_name": channel_title,
                        "deleted_count": deleted_count,
                        "success": True
                    })

                    # Update confirmation message with success
                    await confirmation_msg.edit_text(
                        f"✅ **Channel Reset Complete!**\n\n"
                        f"📺 **Channel:** {channel_title}\n"
                        f"🆔 **ID:** `{channel_id}`\n"
                        f"🗑️ **Deleted:** {deleted_count} movie entries\n"
                        f"👤 **By:** {uid}\n"
                        f"🕒 **Time:** {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S UTC')}\n\n"
                        f"🔄 **The channel data has been cleared.**\n"
                        f"💡 Use `/index_channel` to re-index movie files for this channel."
                    )

                    print(f"🗑️ Channel reset completed by user {uid}. Deleted {deleted_count} movie entries from channel {channel_id} ({channel_title}).")

                except Exception as e:
                    # Handle database error
                    await log_action("reset_channel", by=uid, target=channel_id, extra={
                        "channel_name": channel_title,
                        "success": False,
                        "error": str(e)
                    })

                    await confirmation_msg.edit_text(
                        f"❌ **Channel Reset Failed!**\n\n"
                        f"📺 **Channel:** {channel_title}\n"
                        f"**Error:** {str(e)}\n\n"
                        f"🔄 The database was not modified. Please try again later."
                    )

                    print(f"❌ Channel reset failed for user {uid}, channel {channel_id}: {e}")

            except asyncio.TimeoutError:
                # Final timeout - auto cancel
                await confirmation_msg.edit_text(
                    f"⏰ **Channel Reset Timeout**\n\n"
                    f"🛡️ The reset operation was cancelled due to timeout.\n"
                    f"📁 All movie data from {channel_title} remains safe.\n"
                    f"🔄 You can try again later if needed."
                )

        except asyncio.TimeoutError:
            # Selection timeout
            await selection_msg.edit_text(
                f"⏰ **Channel Selection Timeout**\n\n"
                f"🛡️ The reset operation was cancelled due to timeout.\n"
                f"🔄 You can try again later with /reset_channel."
            )

    except Exception as e:
        # Unexpected error during channel listing
        await log_action("reset_channel_error", by=uid, extra={"error": str(e)})
        await message.reply_text(
            f"❌ **Unexpected Error**\n\n"
            f"**Error:** {str(e)}\n\n"
            f"🛡️ No changes were made to the database."
        )

async def cmd_indexing_stats(client, message: Message):
    """Display indexing statistics to diagnose file skipping issues"""

    # Check if user is admin
    if not await is_admin(message.from_user.id):
        await message.reply_text("🚫 Admins only.")
        return

    # Create comprehensive statistics report
    stats_text = f"```\n"
    stats_text += f"📊 **INDEXING DIAGNOSTIC STATISTICS**\n\n"

    # Basic statistics
    stats_text += f"🔢 Total indexing attempts: {indexing_stats['total_attempts']}\n"
    stats_text += f"✅ Successful insertions: {indexing_stats['successful_inserts']}\n"
    stats_text += f"🔄 Duplicate errors: {indexing_stats['duplicate_errors']}\n"
    stats_text += f"❌ Other errors: {indexing_stats['other_errors']}\n"
    stats_text += f"📈 Peak concurrent operations: {indexing_stats['concurrent_peak']}\n\n"

    # Calculate success rate
    if indexing_stats['total_attempts'] > 0:
        success_rate = (indexing_stats['successful_inserts'] / indexing_stats['total_attempts']) * 100
        stats_text += f"📈 Success rate: {success_rate:.1f}%\n\n"
    else:
        stats_text += f"📈 Success rate: N/A (no attempts)\n\n"

    # Error analysis
    if indexing_stats['duplicate_errors'] > 0:
        stats_text += f"⚠️ **RACE CONDITION DETECTED**: {indexing_stats['duplicate_errors']} duplicate key errors\n"
        stats_text += f"💡 This indicates concurrent indexing attempts on the same message\n\n"

    if indexing_stats['other_errors'] > 0:
        stats_text += f"⚠️ **OTHER ERRORS**: {indexing_stats['other_errors']} database/processing errors\n"
        stats_text += f"💡 Check logs for specific error details\n\n"

    # Concurrency analysis
    if indexing_stats['concurrent_peak'] > 1:
        stats_text += f"🔄 **CONCURRENCY ISSUES**: Peak of {indexing_stats['concurrent_peak']} simultaneous operations\n"
        stats_text += f"💡 Auto-indexing lacks proper synchronization\n"
        stats_text += f"🔧 Recommendation: Implement message queuing for better handling\n\n"
    else:
        stats_text += f"✅ **CONCURRENCY**: No significant concurrent activity detected\n\n"

    # Queue status
    stats_text += f"📦 **QUEUE STATUS**: {len(message_queue)} messages pending\n\n"

    # Recommendations
    stats_text += f"🛠️ **TROUBLESHOOTING RECOMMENDATIONS**:\n\n"
    stats_text += f"1. Use /indexing_stats to monitor real-time statistics\n"
    stats_text += f"2. Check [DIAGNOSTIC] logs in console for race conditions\n"
    stats_text += f"3. Monitor 'Duplicate key error' messages for concurrent indexing\n"
    stats_text += f"4. Consider implementing message queue for high-volume channels\n\n"

    stats_text += f"🔄 **RESET STATISTICS**: Use /reset_stats to clear counters\n"
    stats_text += f"```"

    await message.reply_text(stats_text, link_preview_options=LinkPreviewOptions(is_disabled=True))

    # Log statistics viewing
    await log_action("indexing_stats_viewed", by=message.from_user.id, extra=indexing_stats)

async def cmd_reset_stats(client, message: Message):
    """Reset indexing statistics counters"""

    # Check if user is admin
    if not await is_admin(message.from_user.id):
        await message.reply_text("🚫 Admins only.")
        return

    # Reset statistics counters. The dict is shared via statistics_store.py
    # (imported through indexing), so mutate it in place - rebinding the name
    # would only reset this module's local reference and leave the counters
    # that indexing.py keeps incrementing untouched.
    old_stats = indexing_stats.copy()

    indexing_stats.update({
        'total_attempts': 0,
        'successful_inserts': 0,
        'duplicate_errors': 0,
        'other_errors': 0,
        'concurrent_peak': 0
    })

    await message.reply_text(
        f"✅ **Indexing Statistics Reset**\n\n"
        f"📊 Previous stats:\n"
        f"• Total attempts: {old_stats['total_attempts']}\n"
        f"• Successful: {old_stats['successful_inserts']}\n"
        f"• Duplicate errors: {old_stats['duplicate_errors']}\n"
        f"• Other errors: {old_stats['other_errors']}\n"
        f"• Peak concurrent: {old_stats['concurrent_peak']}\n\n"
        f"🔄 Counters reset to zero. Monitoring will continue.\n"
    )

    await log_action("indexing_stats_reset", by=message.from_user.id, extra=old_stats)

async def cmd_update_db(client, message: Message):
    """
    Admin command to update database by scanning a specific message range:
    - Compares messages in the specified range with indexed entries
    - Removes orphaned entries (deleted files from channel)
    - Indexes new/missed files in the range

    Usage: /update_db
    Interactive flow: Select channel → Provide message range (IDs or links)
    """
    if not await is_admin(message.from_user.id):
        await message.reply_text("🚫 Admins only.")
        return

    uid = message.from_user.id

    # Check if another indexing process is running
    from .config import indexing_lock
    if indexing_lock.locked():
        return await message.reply_text("⏳ Another indexing process is already running. Please wait.")

    # Step 1: Get all registered channels
    channels = await channels_col.find({}).to_list(length=100)

    if not channels:
        return await message.reply_text("❌ No channels registered yet. Use /add_channel first.")

    # Step 2: Display channel selection with indexed counts
    pipeline = [
        {"$group": {"_id": "$channel_id", "count": {"$sum": 1}}},
        {"$sort": {"count": -1}}
    ]
    indexed_counts = await movies_col.aggregate(pipeline).to_list(length=100)
    count_map = {item["_id"]: item["count"] for item in indexed_counts}

    channel_list = "🔄 **Database Update - Select Channel**\n\n"
    for idx, ch in enumerate(channels, 1):
        channel_title = ch.get("channel_title", "Unknown")
        channel_id = ch.get("channel_id")
        status = "✅" if ch.get("enabled", True) else "❌"
        indexed = count_map.get(channel_id, 0)
        channel_list += f"{idx}. {status} **{channel_title}**\n"
        channel_list += f"   📊 Indexed: `{indexed}` | ID: `{channel_id}`\n\n"

    channel_list += "🔢 Send the **number** of the channel to update\n"
    channel_list += "⏰ Timeout: 60 seconds | Send **CANCEL** to abort"

    selection_msg = await message.reply_text(channel_list)

    try:
        # Wait for channel selection
        response = await wait_for_user_input(message.chat.id, uid, timeout=60)

        if not response or (response.text and response.text.upper().strip() == "CANCEL"):
            await selection_msg.delete()
            return await message.reply_text("❌ **Database Update Cancelled**")

        # Validate selection
        try:
            selection = int(response.text.strip())
            if selection < 1 or selection > len(channels):
                await selection_msg.delete()
                return await message.reply_text(f"❌ Invalid selection. Please choose a number between 1 and {len(channels)}.")
        except ValueError:
            await selection_msg.delete()
            return await message.reply_text("❌ Invalid input. Please send a number.")

        selected_channel = channels[selection - 1]
        channel_id = selected_channel.get("channel_id")
        channel_title = selected_channel.get("channel_title", "Unknown")
        await selection_msg.delete()

        # Step 3: Ask for message range
        range_msg = await message.reply_text(
            f"📺 **Channel Selected:** {channel_title}\n\n"
            f"📍 **Provide Message Range**\n\n"
            f"Send the **start** and **end** message IDs or links.\n"
            f"Format options:\n"
            f"• `13617 13638` (space-separated IDs)\n"
            f"• `13617-13638` (hyphen-separated IDs)\n"
            f"• Paste two Telegram message links (one per line):\n"
            f"  `https://t.me/c/2465144431/13617`\n"
            f"  `https://t.me/c/2465144431/13638`\n\n"
            f"⏰ Timeout: 120 seconds | Send **CANCEL** to abort"
        )

        # Wait for range input
        range_response = await wait_for_user_input(message.chat.id, uid, timeout=120)

        if not range_response or (range_response.text and range_response.text.upper().strip() == "CANCEL"):
            await range_msg.delete()
            return await message.reply_text("❌ **Database Update Cancelled**")

        await range_msg.delete()
        range_text = range_response.text.strip()

        # Parse the range input
        start_id, end_id = None, None

        # Try parsing as links (check for t.me URLs)
        import re
        link_pattern = r'https?://t\.me/c/\d+/(\d+)'
        links = re.findall(link_pattern, range_text)

        if len(links) >= 2:
            start_id = int(links[0])
            end_id = int(links[1])
        elif len(links) == 1:
            # Only one link provided, try to parse second as ID
            remaining = re.sub(link_pattern, '', range_text).strip()
            if remaining:
                try:
                    second_id = int(remaining.replace('-', ' ').split()[0])
                    start_id = int(links[0])
                    end_id = second_id
                except ValueError:
                    pass
        else:
            # Try parsing as IDs (space or hyphen separated)
            # Handle formats: "13617 13638", "13617-13638", "13617 - 13638"
            range_text = range_text.replace('-', ' ').replace(',', ' ')
            parts = range_text.split()

            if len(parts) >= 2:
                try:
                    start_id = int(parts[0])
                    end_id = int(parts[-1])
                except ValueError:
                    pass

        if start_id is None or end_id is None:
            return await message.reply_text(
                "❌ **Invalid Range Format**\n\n"
                "Please provide a valid range using:\n"
                "• Space-separated IDs: `13617 13638`\n"
                "• Hyphen-separated IDs: `13617-13638`\n"
                "• Telegram links (one per line)"
            )

        # Ensure start_id <= end_id
        if start_id > end_id:
            start_id, end_id = end_id, start_id

        total_range = end_id - start_id + 1

        # Confirmation before starting
        confirm_msg = await message.reply_text(
            f"🔄 **Database Update Confirmation**\n\n"
            f"📺 **Channel:** {channel_title}\n"
            f"🆔 **Channel ID:** `{channel_id}`\n\n"
            f"📍 **Message Range:**\n"
            f"   Start: `{start_id}`\n"
            f"   End: `{end_id}`\n"
            f"   Total: `{total_range}` messages\n\n"
            f"This will:\n"
            f"• 🔍 Check each message in the range\n"
            f"• 🗑️ Remove orphaned entries (deleted files)\n"
            f"• ➕ Index new/missed files\n\n"
            f"Send **CONFIRM** to proceed or **CANCEL** to abort\n"
            f"⏰ Timeout: 30 seconds"
        )

        # Wait for confirmation
        confirm_response = await wait_for_user_input(message.chat.id, uid, timeout=30)

        if not confirm_response or confirm_response.text.upper().strip() != "CONFIRM":
            await confirm_msg.delete()
            return await message.reply_text("❌ **Database Update Cancelled**")

        await confirm_msg.delete()

        # Step 4: Start the update process
        start_time = datetime.now(timezone.utc)

        status_msg = await message.reply_text(
            f"🔄 **Database Update Started**\n\n"
            f"📺 Channel: {channel_title}\n"
            f"📍 Range: `{start_id}` → `{end_id}` ({total_range} messages)\n\n"
            f"⏳ Initializing scan...\n"
            f"━━━━━━━━━━━━━━━━━━━━\n"
            f"🔍 Scanned: 0/{total_range}\n"
            f"🗑️ Orphans Removed: 0\n"
            f"➕ New Files Indexed: 0\n"
            f"⚠️ Errors: 0"
        )

        print(f"\n{'='*60}")
        print(f"[UPDATE_DB] Starting database update for {channel_title}")
        print(f"[UPDATE_DB] Channel ID: {channel_id}")
        print(f"[UPDATE_DB] Range: {start_id} → {end_id} ({total_range} messages)")
        print(f"[UPDATE_DB] Initiated by: User {uid}")
        print(f"{'='*60}\n")

        # Statistics
        scanned = 0
        orphans_removed = 0
        new_indexed = 0
        errors = 0
        skipped_no_media = 0
        already_indexed = 0
        paused = False  # Set when the scan is interrupted (e.g. FloodWait)

        # The scan loop lives in scan_message_range() - a standalone helper so
        # it can be unit-tested in isolation. This closure re-renders the
        # Telegram progress message from the helper's state dict.
        async def _render_progress(state):
            try:
                await status_msg.edit_text(
                    f"🔄 **Database Update In Progress**\n\n"
                    f"📺 Channel: {channel_title}\n"
                    f"📍 Range: `{start_id}` → `{end_id}`\n\n"
                    f"`[{state['bar']}]` {state['progress_pct']:.1f}%\n"
                    f"⏳ ETA: {state['eta_str']}\n"
                    f"━━━━━━━━━━━━━━━━━━━━\n"
                    f"🔍 Scanned: {state['scanned']}/{state['total_range']}\n"
                    f"🗑️ Orphans Removed: {state['orphans_removed']}\n"
                    f"➕ New Files Indexed: {state['new_indexed']}\n"
                    f"📁 Already Indexed: {state['already_indexed']}\n"
                    f"📭 No Media: {state['skipped_no_media']}\n"
                    f"⚠️ Errors: {state['errors']}"
                )
            except Exception:
                pass  # Ignore edit errors (rate limit, etc.)

        async with indexing_lock:
            try:
                # movies_col is passed EXPLICITLY: scan_message_range lives in
                # database_scan.py with its own module-global default, and the
                # end-to-end tests patch commands.movies_col - relying on the
                # helper's default would bypass that patch.
                result = await scan_message_range(
                    client,
                    channel_id,
                    start_id,
                    end_id,
                    movies_col_ref=movies_col,
                    progress_cb=_render_progress,
                )
                scanned = result["scanned"]
                orphans_removed = result["orphans_removed"]
                new_indexed = result["new_indexed"]
                already_indexed = result["already_indexed"]
                skipped_no_media = result["skipped_no_media"]
                errors = result["errors"]
                paused = result["paused"]

                end_time = datetime.now(timezone.utc)
                duration = (end_time - start_time).total_seconds()

                # Log the update action
                await log_action("update_db", by=uid, extra={
                    "channel_id": channel_id,
                    "channel_title": channel_title,
                    "range_start": start_id,
                    "range_end": end_id,
                    "total_range": total_range,
                    "scanned": scanned,
                    "orphans_removed": orphans_removed,
                    "new_indexed": new_indexed,
                    "already_indexed": already_indexed,
                    "skipped_no_media": skipped_no_media,
                    "errors": errors,
                    "paused": paused,
                    "duration_seconds": duration,
                    "start_time": start_time.isoformat(),
                    "end_time": end_time.isoformat()
                })

                # Calculate scan rate
                scan_rate = scanned / duration if duration > 0 else 0

                # Final status with completed progress bar (honest about pauses)
                final_pct = (scanned / total_range) * 100 if total_range else 100
                filled = int(final_pct / 5)
                bar = "█" * filled + "░" * (20 - filled)
                if paused:
                    header = "⚠️ **Database Update Paused (FloodWait)**"
                    pause_note = "🔄 Rate limited mid-scan - entries were kept safe. Re-run /update_db to finish.\n\n"
                else:
                    header = "✅ **Database Update Complete**"
                    pause_note = ""
                await status_msg.edit_text(
                    f"{header}\n\n"
                    f"📺 **Channel:** {channel_title}\n"
                    f"📍 **Range:** `{start_id}` → `{end_id}`\n\n"
                    f"`[{bar}]` {final_pct:.1f}%\n\n"
                    f"{pause_note}"
                    f"**📊 Results:**\n"
                    f"━━━━━━━━━━━━━━━━━━━━\n"
                    f"🔍 Messages Scanned: `{scanned}`\n"
                    f"🗑️ Orphans Removed: `{orphans_removed}`\n"
                    f"➕ New Files Indexed: `{new_indexed}`\n"
                    f"📁 Already Indexed: `{already_indexed}`\n"
                    f"📭 No Media (Skipped): `{skipped_no_media}`\n"
                    f"⚠️ Errors: `{errors}`\n\n"
                    f"⏱️ **Duration:** {duration:.1f}s ({scan_rate:.1f} msg/s)\n"
                    f"👤 **By:** `{uid}`\n"
                    f"📅 **Completed:** {end_time.strftime('%Y-%m-%d %H:%M:%S UTC')}"
                )

                print(f"\n{'='*60}")
                print(f"[UPDATE_DB] ✅ Database update completed!")
                print(f"[UPDATE_DB] Summary:")
                print(f"  - Scanned: {scanned} messages")
                print(f"  - Orphans removed: {orphans_removed}")
                print(f"  - New files indexed: {new_indexed}")
                print(f"  - Already indexed: {already_indexed}")
                print(f"  - No media: {skipped_no_media}")
                print(f"  - Errors: {errors}")
                print(f"  - Duration: {duration:.1f}s ({scan_rate:.1f} messages/second)")
                print(f"{'='*60}\n")

            except Exception as e:
                print(f"[UPDATE_DB] ❌ Critical error: {e}")
                import traceback
                traceback.print_exc()

                await status_msg.edit_text(
                    f"❌ **Database Update Failed**\n\n"
                    f"**Error:** {str(e)}\n\n"
                    f"📊 **Partial Results:**\n"
                    f"🔍 Scanned: {scanned}/{total_range}\n"
                    f"🗑️ Orphans Removed: {orphans_removed}\n"
                    f"➕ New Indexed: {new_indexed}\n"
                    f"⚠️ Errors: {errors + 1}\n\n"
                    f"Check logs for more details."
                )

    except asyncio.TimeoutError:
        try:
            await selection_msg.delete()
        except Exception:
            pass
        await message.reply_text("⏰ **Timeout!** Please try again with /update_db")
    except Exception as e:
        print(f"[UPDATE_DB] Error: {e}")
        import traceback
        traceback.print_exc()
        await message.reply_text(f"❌ **Error:** {e}")


async def cmd_manual_deletion(client, message: Message):
    """
    Admin command to manually delete indexed entries by searching for title.

    Workflow:
    1. Get title from command argument or ask user
    2. Search database for matching entries
    3. Display results with selection buttons
    4. Allow user to select one or more entries to delete
    5. Confirm and delete selected entries

    Usage: /manual_deletion [title]
    Example: /manual_deletion Spider-Man
    """
    if not await is_admin(message.from_user.id):
        await message.reply_text("🚫 Admins only.")
        return

    uid = message.from_user.id

    # Step 1: Get title from command argument or ask user
    parts = message.text.split(maxsplit=1)

    if len(parts) > 1:
        # Title provided as command argument
        search_title = parts[1].strip()
    else:
        # Ask for title
        prompt_msg = await message.reply_text(
            "**Manual Deletion**\n\n"
            "Please send the title (or part of the title) to search for.\n"
            "Tip: You can send partial titles for broader search.\n"
            "Timeout: 60 seconds"
        )

        try:
            # Wait for user input
            response = await wait_for_user_input(message.chat.id, message.from_user.id, timeout=60)

            if not response or not response.text:
                await prompt_msg.edit_text("**Cancelled**\n\nNo title provided.")
                return

            search_title = response.text.strip()

            # Delete the prompt message
            await prompt_msg.delete()
        except asyncio.TimeoutError:
            await prompt_msg.edit_text(
                "**Timeout**\n\n"
                "You took too long to respond. Please try again with /manual_deletion or /manual_deletion <title>."
            )
            return

    # Step 2: Search database for matching entries
    try:
        search_msg = await message.reply_text(
            f"**Searching for:** {search_title}\n"
            f"Please wait..."
        )

        # Search using regex for partial matching (case-insensitive)
        cursor = movies_col.find(
            {"title": {"$regex": search_title, "$options": "i"}},
            {"_id": 1, "title": 1, "channel_id": 1, "message_id": 1, "indexed_at": 1}
        ).limit(50)  # Limit to 50 results to avoid overwhelming

        results = await cursor.to_list(length=50)

        if not results:
            await search_msg.edit_text(
                f"**No Results Found**\n\n"
                f"Search: {search_title}\n"
                f"Tip: Try a different search term or check spelling."
            )
            return

        # Step 3: Display results with selection buttons
        # Store results in a temporary dict for callback handling
        deletion_session_id = str(uuid.uuid4())[:8]
        temp_data_key = f"manual_deletion_{deletion_session_id}"

        # Store in temp_data (we'll use a dict attribute)
        if not hasattr(temp_data, 'deletion_sessions'):
            temp_data.deletion_sessions = {}

        temp_data.deletion_sessions[temp_data_key] = {
            'results': results,
            'selected': set(),
            'user_id': uid,
            'search_title': search_title
        }

        # Build message with results
        results_text = f"**Found {len(results)} matching entries**\n"
        results_text += f"Search: {search_title}\n\n"

        for idx, doc in enumerate(results, 1):
            title = doc.get('title', 'Unknown')
            channel_id = doc.get('channel_id', 'N/A')
            message_id = doc.get('message_id', 'N/A')
            indexed_at = doc.get('indexed_at')

            # Format indexed date
            if indexed_at:
                try:
                    date_str = indexed_at.strftime('%Y-%m-%d')
                except:
                    date_str = 'Unknown'
            else:
                date_str = 'Unknown'

            results_text += f"{idx}. {title} | Ch: {channel_id} | Msg: {message_id} | {date_str}\n"

        results_text += f"\nSelect entries to delete using the buttons below."

        # Create inline keyboard with selection buttons
        # Show up to 10 results per page for now (simplified version)
        buttons = []

        # Add selection buttons (max 10 per row, 2 columns)
        for idx in range(min(len(results), 20)):  # Limit to first 20 for button space
            button_text = f"[ ] {idx + 1}"
            callback_data = f"mdel#{deletion_session_id}#toggle#{idx}"

            if idx % 2 == 0:
                buttons.append([InlineKeyboardButton(button_text, callback_data=callback_data)])
            else:
                buttons[-1].append(InlineKeyboardButton(button_text, callback_data=callback_data))

        # Add action buttons
        buttons.append([
            InlineKeyboardButton("Delete Selected", callback_data=f"mdel#{deletion_session_id}#confirm"),
            InlineKeyboardButton("Cancel", callback_data=f"mdel#{deletion_session_id}#cancel")
        ])

        if len(results) > 20:
            results_text += f"\n\nNote: Showing first 20 results. Use more specific search for fewer results."

        await search_msg.edit_text(
            results_text,
            reply_markup=InlineKeyboardMarkup(buttons)
        )

        # Log the action
        await log_action("manual_deletion_search", by=uid, extra={
            "search_title": search_title,
            "results_count": len(results),
            "session_id": deletion_session_id
        })

    except Exception as e:
        await log_action("manual_deletion_error", by=uid, extra={
            "error": str(e),
            "error_type": type(e).__name__
        })

        await message.reply_text(
            f"❌ **Error**\n\n"
            f"An error occurred: {str(e)}\n\n"
            f"Please try again later."
        )

        print(f"❌ Manual deletion error for user {uid}: {e}")


async def cmd_request(client, message: Message):
    """Handle /request command for movie/series requests"""
    uid = message.from_user.id
    username = message.from_user.username or message.from_user.first_name or str(uid)

    try:
        # Check if user is admin (admins bypass rate limits for testing)
        user_is_admin = await is_admin(uid)

        # Check if feature is premium-only
        if await is_feature_premium_only("request"):
            # Check if user is premium or admin
            if not user_is_admin and not await is_premium_user(uid):
                return await message.reply_text(
                    "⭐ **Premium Feature**\n\n"
                    "The /request command is a premium-only feature.\n\n"
                    "Contact an admin to get premium access."
                )

        # Check rate limits (skip for admins)
        if not user_is_admin:
            can_request, error_msg = await check_rate_limits(uid)
            if not can_request:
                await message.reply_text(error_msg)
                return

        # Start interactive request flow with warning
        await message.reply_text(
            "📝 **Movie/Series Request**\n\n"
            "⚠️ **IMPORTANT WARNING:**\n"
            "Before requesting, please search the database using /search to ensure the content is not already available.\n"
            "Requesting content that already exists may result in a ban from the bot.\n\n"
            "Let's gather the information for your request.\n"
            "You can type **CANCEL** at any step to abort.\n\n"
            "**Step 1/3:** What type of content are you requesting?\n"
            "Reply with: **Movie** or **Series**"
        )

        # Wait for content type
        try:
            type_msg = await wait_for_user_input(message.chat.id, uid, timeout=120)
        except asyncio.TimeoutError:
            await message.reply_text("⏰ Request timeout. Please start over with /request")
            return

        if not type_msg or not type_msg.text:
            await message.reply_text("❌ Invalid input. Please start over with /request")
            return

        content_type_input = type_msg.text.strip().upper()

        if content_type_input == "CANCEL":
            await message.reply_text("❌ Request cancelled.")
            return

        if content_type_input not in ["MOVIE", "SERIES"]:
            await message.reply_text("❌ Invalid type. Please use 'Movie' or 'Series'. Start over with /request")
            return

        content_type = "Movie" if content_type_input == "MOVIE" else "Series"

        # Step 2: Get title
        await message.reply_text(
            f"✅ Type: **{content_type}**\n\n"
            f"**Step 2/3:** What is the title/name?\n"
            f"Reply with the {content_type.lower()} title."
        )

        try:
            title_msg = await wait_for_user_input(message.chat.id, uid, timeout=120)
        except asyncio.TimeoutError:
            await message.reply_text("⏰ Request timeout. Please start over with /request")
            return

        if not title_msg or not title_msg.text:
            await message.reply_text("❌ Invalid input. Please start over with /request")
            return

        title = title_msg.text.strip()

        if title.upper() == "CANCEL":
            await message.reply_text("❌ Request cancelled.")
            return

        if len(title) < 2:
            await message.reply_text("❌ Title too short. Please start over with /request")
            return

        # Step 3: Get year
        await message.reply_text(
            f"✅ Title: **{title}**\n\n"
            f"**Step 3/3:** What is the release year?\n"
            f"Reply with a 4-digit year (e.g., 2024)."
        )

        try:
            year_msg = await wait_for_user_input(message.chat.id, uid, timeout=120)
        except asyncio.TimeoutError:
            await message.reply_text("⏰ Request timeout. Please start over with /request")
            return

        if not year_msg or not year_msg.text:
            await message.reply_text("❌ Invalid input. Please start over with /request")
            return

        year_input = year_msg.text.strip()

        if year_input.upper() == "CANCEL":
            await message.reply_text("❌ Request cancelled.")
            return

        # Validate year
        if not year_input.isdigit() or len(year_input) != 4:
            await message.reply_text("❌ Invalid year format. Please use a 4-digit year. Start over with /request")
            return

        year = year_input
        current_year = datetime.now(timezone.utc).year
        if int(year) < 1900 or int(year) > current_year + 2:
            await message.reply_text(f"❌ Year must be between 1900 and {current_year + 2}. Start over with /request")
            return

        # Search TMDb for matches
        search_msg = await message.reply_text(
            f"🔍 Searching TMDb for **{title}** ({year})...\n"
            f"Please wait..."
        )

        tmdb_results = await search_tmdb(title, year, content_type)

        imdb_link = None

        if tmdb_results:
            # Display results
            results_text = f"✅ Found {len(tmdb_results)} result(s) on TMDb:\n\n"

            for idx, result in enumerate(tmdb_results, 1):
                result_title = result.get("title", "Unknown")
                result_year = result.get("year", "N/A")
                result_imdb = result.get("imdb_id", "N/A")

                # Format: 1. Title (Year) - IMDB: tt1234567
                results_text += f"{idx}. {result_title} ({result_year})"
                if result_imdb and result_imdb != "N/A":
                    results_text += f" - IMDB: {result_imdb}"
                results_text += "\n"

            results_text += (
                f"\n**Select a result** by replying with the number (1-{len(tmdb_results)})\n"
                f"Or type **SKIP** to continue without IMDB link\n"
                f"Or type **CANCEL** to abort"
            )

            await search_msg.edit_text(results_text)

            # Wait for selection
            try:
                selection_msg = await wait_for_user_input(message.chat.id, uid, timeout=120)
            except asyncio.TimeoutError:
                await message.reply_text("⏰ Request timeout. Please start over with /request")
                return

            if not selection_msg or not selection_msg.text:
                await message.reply_text("❌ Invalid input. Please start over with /request")
                return

            selection_input = selection_msg.text.strip().upper()

            if selection_input == "CANCEL":
                await message.reply_text("❌ Request cancelled.")
                return

            if selection_input != "SKIP":
                # Validate selection
                if not selection_input.isdigit():
                    await message.reply_text("❌ Invalid selection. Please start over with /request")
                    return

                selection_idx = int(selection_input) - 1

                if selection_idx < 0 or selection_idx >= len(tmdb_results):
                    await message.reply_text(f"❌ Invalid selection. Please choose 1-{len(tmdb_results)}. Start over with /request")
                    return

                # Get IMDB link from selected result
                selected_result = tmdb_results[selection_idx]
                imdb_id = selected_result.get("imdb_id")

                if imdb_id:
                    imdb_link = f"https://www.imdb.com/title/{imdb_id}/"
                    await message.reply_text(f"✅ Selected: {selected_result.get('title')} ({selected_result.get('year')})")
                else:
                    await message.reply_text("⚠️ IMDB ID not available for this selection. Proceeding without IMDB link.")
        else:
            # No TMDb results found, allow manual entry or skip
            await search_msg.edit_text(
                f"❌ No results found on TMDb for **{title}** ({year}).\n\n"
                f"You can continue without an IMDB link.\n"
                f"Type **CONTINUE** to proceed or **CANCEL** to abort."
            )

            try:
                continue_msg = await wait_for_user_input(message.chat.id, uid, timeout=60)
            except asyncio.TimeoutError:
                await message.reply_text("⏰ Request timeout. Please start over with /request")
                return

            if not continue_msg or not continue_msg.text:
                await message.reply_text("❌ Invalid input. Please start over with /request")
                return

            if continue_msg.text.strip().upper() == "CANCEL":
                await message.reply_text("❌ Request cancelled.")
                return

            if continue_msg.text.strip().upper() != "CONTINUE":
                await message.reply_text("❌ Invalid input. Please start over with /request")
                return

        # Check for duplicate requests
        is_duplicate, similar_req = await check_duplicate_request(title, year, uid)
        if is_duplicate:
            await message.reply_text(
                f"⚠️ **Similar Request Found**\n\n"
                f"You already have a similar pending request:\n"
                f"**Title:** {similar_req.get('title')}\n"
                f"**Year:** {similar_req.get('year')}\n"
                f"**Type:** {similar_req.get('content_type')}\n\n"
                f"Do you want to proceed anyway?\n"
                f"Reply with **YES** to proceed or **NO** to cancel."
            )

            try:
                confirm_msg = await wait_for_user_input(message.chat.id, uid, timeout=60)
            except asyncio.TimeoutError:
                await message.reply_text("⏰ Request timeout. Request cancelled.")
                return

            if not confirm_msg or not confirm_msg.text or confirm_msg.text.strip().upper() != "YES":
                await message.reply_text("❌ Request cancelled.")
                return

        # Create request document
        now = datetime.now(timezone.utc)
        request_doc = {
            "user_id": uid,
            "username": username,
            "content_type": content_type,
            "title": title,
            "year": year,
            "imdb_link": imdb_link,
            "request_date": now,
            "status": "pending"
        }

        # Insert into database
        result = await requests_col.insert_one(request_doc)

        # Update user limits (skip for admins)
        if not user_is_admin:
            await update_user_limits(uid)

        # Get queue position
        queue_position = await get_queue_position(uid)

        # Get remaining quota
        pending_count = await requests_col.count_documents({
            "user_id": uid,
            "status": "pending"
        })

        # Send confirmation
        confirmation_text = (
            f"✅ **Request Submitted Successfully!**\n\n"
            f"**Type:** {content_type}\n"
            f"**Title:** {title}\n"
            f"**Year:** {year}\n"
        )

        if imdb_link:
            confirmation_text += f"**IMDB:** {imdb_link}\n"

        confirmation_text += f"\n📊 **Queue Position:** #{queue_position}\n"

        if user_is_admin:
            confirmation_text += f"📝 **Your Pending Requests:** {pending_count} (Admin - No Limits)\n\n"
        else:
            confirmation_text += f"📝 **Your Pending Requests:** {pending_count}/{MAX_PENDING_REQUESTS_PER_USER}\n\n"

        confirmation_text += "You will be notified when your request is fulfilled."

        await message.reply_text(confirmation_text)

        # Log the request
        await log_action("request_submitted", by=uid, extra={
            "title": title,
            "year": year,
            "content_type": content_type,
            "queue_position": queue_position
        })

    except Exception as e:
        await log_action("request_error", by=uid, extra={"error": str(e)})
        await message.reply_text(
            f"❌ **Error**\n\n"
            f"An error occurred while processing your request.\n"
            f"Please try again later."
        )
        print(f"❌ Request error for user {uid}: {e}")


async def cmd_request_list(client, message: Message):
    """Handle /request_list command for admins to view and manage requests"""
    uid = message.from_user.id

    # Check if user is admin
    if not await is_admin(uid):
        await message.reply_text("🚫 Admins only.")
        return

    try:
        # Get all pending requests sorted by request date
        pending_requests = await requests_col.find(
            {"status": "pending"}
        ).sort("request_date", 1).to_list(length=1000)

        if not pending_requests:
            await message.reply_text(
                "📝 **Request List**\n\n"
                "No pending requests at the moment."
            )
            return

        # Pagination settings
        REQUESTS_PER_PAGE = 9
        total_requests = len(pending_requests)
        total_pages = (total_requests + REQUESTS_PER_PAGE - 1) // REQUESTS_PER_PAGE

        # Store request list data for pagination
        request_list_id = str(uuid.uuid4())[:8]
        bulk_downloads[request_list_id] = {
            'requests': pending_requests,
            'created_at': datetime.now(timezone.utc),
            'user_id': uid,
            'type': 'request_list'
        }

        # Send first page
        await send_request_list_page(client, message, pending_requests, request_list_id, page=1)

        # Log the action
        await log_action("request_list_viewed", by=uid, extra={
            "total_requests": total_requests
        })

    except Exception as e:
        await log_action("request_list_error", by=uid, extra={"error": str(e)})
        await message.reply_text(
            f"❌ **Error**\n\n"
            f"An error occurred while fetching the request list.\n"
            f"Please try again later."
        )
        print(f"❌ Request list error for admin {uid}: {e}")


async def send_request_list_page(client, message, all_requests, request_list_id, page=1, edit=False):
    """Send a paginated request list

    Args:
        client: The bot client
        message: The message object to reply to or edit
        all_requests: List of all requests
        request_list_id: Unique ID for this request list session
        page: Page number to display
        edit: Whether to edit the message (True) or send new message (False)
    """
    REQUESTS_PER_PAGE = 9
    total_requests = len(all_requests)
    total_pages = (total_requests + REQUESTS_PER_PAGE - 1) // REQUESTS_PER_PAGE

    # Ensure page is within valid range
    page = max(1, min(page, total_pages))

    # Calculate start and end indices for current page
    start_idx = (page - 1) * REQUESTS_PER_PAGE
    end_idx = min(start_idx + REQUESTS_PER_PAGE, total_requests)
    page_requests = all_requests[start_idx:end_idx]

    # Build request list text
    list_text = "```\n"
    list_text += f"Request List - Page {page}/{total_pages}\n"
    list_text += f"Total Pending: {total_requests}\n"
    list_text += "=" * 50 + "\n\n"

    for idx, req in enumerate(page_requests, start=start_idx + 1):
        req_type = "[M]" if req.get("content_type") == "Movie" else "[S]"
        title = req.get("title", "Unknown")
        year = req.get("year", "N/A")
        username = req.get("username", "Unknown")
        user_id = req.get("user_id", "N/A")
        req_date = req.get("request_date")
        date_str = req_date.strftime("%Y-%m-%d %H:%M") if req_date else "N/A"

        list_text += f"#{idx} {req_type} {title} ({year})\n"
        list_text += f"    User: {username} (ID: {user_id})\n"
        list_text += f"    Date: {date_str}\n"

        if req.get("imdb_link"):
            list_text += f"    IMDB: {req.get('imdb_link')}\n"

        list_text += "\n"

    list_text += "```"

    # Create buttons
    buttons = []

    # Individual Mark Done buttons (3 per row)
    current_row = []
    for idx, req in enumerate(page_requests, start=start_idx + 1):
        req_id = str(req.get("_id"))
        current_row.append(
            InlineKeyboardButton(
                f"Done [{idx}]",
                callback_data=f"req_done:{req_id}"
            )
        )

        if len(current_row) == 3 or idx == end_idx:
            buttons.append(current_row)
            current_row = []

    # Navigation row
    nav_row = []

    # Previous button
    if page > 1:
        nav_row.append(
            InlineKeyboardButton(
                "← Prev",
                callback_data=f"req_page:{request_list_id}:{page-1}"
            )
        )

    # Mark All Done button
    nav_row.append(
        InlineKeyboardButton(
            "Mark All Done",
            callback_data=f"req_all_done:{request_list_id}"
        )
    )

    # Next button
    if page < total_pages:
        nav_row.append(
            InlineKeyboardButton(
                "Next →",
                callback_data=f"req_page:{request_list_id}:{page+1}"
            )
        )

    if nav_row:
        buttons.append(nav_row)

    # Create keyboard
    keyboard = InlineKeyboardMarkup(buttons) if buttons else None

    # Send or edit message based on the edit parameter
    if edit:
        await message.edit_text(list_text, reply_markup=keyboard)
    else:
        await message.reply_text(list_text, reply_markup=keyboard)


# -------------------------
# Statistics Commands
# -------------------------
async def cmd_stat(client, message: Message):
    """Display comprehensive bot statistics dashboard"""
    uid = message.from_user.id
    
    # Admin check
    if not await is_admin(uid):
        return await message.reply_text("🚫 Admins only.")
    
    try:
        # Show loading message
        loading_msg = await message.reply_text(
            "📊 **Generating Statistics Dashboard...**\n\n"
            "⏳ Collecting data from database...\n"
            "Please wait, this may take a moment."
        )
        
        # Set timeout for data collection (30 seconds)
        try:
            stats = await asyncio.wait_for(collect_comprehensive_stats(admin_id=uid), timeout=30.0)
        except asyncio.TimeoutError:
            await loading_msg.edit_text(
                "⏰ **Timeout**\n\n"
                "Statistics collection took too long.\n"
                "Try using /quickstat for a faster summary."
            )
            return
        
        if not stats:
            await loading_msg.edit_text(
                "❌ **Error**\n\n"
                "Failed to collect statistics.\n"
                "Please try again later."
            )
            return
        
        # Format and send statistics
        output = format_stats_output(stats)
        
        # Store stats for export
        stats_id = str(uuid.uuid4())[:8]
        bulk_downloads[stats_id] = {
            'type': 'stats_export',
            'stats': stats,
            'created_at': datetime.now(timezone.utc),
            'user_id': uid
        }
        
        # Create export buttons
        buttons = [
            [
                InlineKeyboardButton("📥 Export JSON", callback_data=f"stats_export:json:{stats_id}"),
                InlineKeyboardButton("📥 Export CSV", callback_data=f"stats_export:csv:{stats_id}")
            ]
        ]
        keyboard = InlineKeyboardMarkup(buttons)
        
        # Send statistics
        await loading_msg.edit_text(output, reply_markup=keyboard, link_preview_options=LinkPreviewOptions(is_disabled=True), parse_mode=ParseMode.HTML)
        
        # Log action
        await log_action("stat_command", by=uid, extra={
            "stats_id": stats_id,
            "total_users": stats.get('total_users', 0),
            "total_content": stats.get('total_content', 0)
        })
        
    except Exception as e:
        await log_action("stat_command_error", by=uid, extra={"error": str(e)})
        await message.reply_text(
            "❌ **Error**\n\n"
            "An error occurred while generating statistics.\n"
            "Please try again later."
        )
        print(f"❌ Statistics error for user {uid}: {e}")


async def cmd_quickstat(client, message: Message):
    """Display quick statistics summary"""
    uid = message.from_user.id
    
    # Admin check
    if not await is_admin(uid):
        return await message.reply_text("🚫 Admins only.")
    
    try:
        # Show loading message
        loading_msg = await message.reply_text("📊 **Generating Quick Stats...**")
        
        # Collect quick stats with timeout
        try:
            stats = await asyncio.wait_for(collect_quick_stats(), timeout=10.0)
        except asyncio.TimeoutError:
            await loading_msg.edit_text(
                "⏰ **Timeout**\n\n"
                "Statistics collection took too long.\n"
                "Please try again later."
            )
            return
        
        if not stats:
            await loading_msg.edit_text(
                "❌ **Error**\n\n"
                "Failed to collect statistics.\n"
                "Please try again later."
            )
            return
        
        # Format and send quick stats
        output = format_quick_stats_output(stats)
        
        await loading_msg.edit_text(output, link_preview_options=LinkPreviewOptions(is_disabled=True))
        
        # Log action
        await log_action("quickstat_command", by=uid, extra={
            "total_users": stats.get('total_users', 0),
            "total_content": stats.get('total_content', 0)
        })
        
    except Exception as e:
        await log_action("quickstat_command_error", by=uid, extra={"error": str(e)})
        await message.reply_text(
            "❌ **Error**\n\n"
            "An error occurred while generating statistics.\n"
            "Please try again later."
        )
        print(f"❌ Quick statistics error for user {uid}: {e}")


# -------------------------
# Premium Management Commands
# -------------------------
async def cmd_premium(client, message: Message):
    """Handle /premium command - Premium management interface"""
    uid = message.from_user.id

    # Check if user is admin
    if not await is_admin(uid):
        return await message.reply_text("🚫 Admins only.")

    # Create button interface
    buttons = [
        [InlineKeyboardButton("Add Users", callback_data="premium:add_users")],
        [InlineKeyboardButton("Edit Users", callback_data="premium:edit_users")],
        [InlineKeyboardButton("Remove Users", callback_data="premium:remove_users")],
        [InlineKeyboardButton("Manage Features", callback_data="premium:manage_features")]
    ]

    keyboard = InlineKeyboardMarkup(buttons)

    help_text = (
        "**Premium Management System**\n\n"
        "**Add Users:** Add users to premium with specified duration\n"
        "**Edit Users:** Modify premium duration for existing users\n"
        "**Remove Users:** Remove users from premium\n"
        "**Manage Features:** Control which features are premium-only\n\n"
        "Select an option below:"
    )

    await message.reply_text(help_text, reply_markup=keyboard)
