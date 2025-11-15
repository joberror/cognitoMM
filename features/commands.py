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
from hydrogram import Client, filters
from hydrogram.types import Message, InlineQuery, InlineQueryResultArticle, InputTextMessageContent, InlineKeyboardMarkup, InlineKeyboardButton, CallbackQuery
from hydrogram.enums import ParseMode, ChatType

# Import from our modules
from .config import API_ID, API_HASH, BOT_TOKEN, BOT_ID, MONGO_URI, MONGO_DB, ADMINS, LOG_CHANNEL, FUZZY_THRESHOLD, AUTO_INDEX_DEFAULT, temp_data, user_input_events, bulk_downloads
from .database import mongo, db, movies_col, users_col, channels_col, settings_col, logs_col, ensure_indexes
from .utils import get_readable_time, wait_for_user_input, set_user_input, cleanup_expired_bulk_downloads
from .metadata_parser import parse_metadata
from .user_management import get_user_doc, is_admin, is_banned, has_accepted_terms, load_terms_and_privacy, log_action, check_banned, check_terms_acceptance, should_process_command, require_not_banned
from .file_deletion import track_file_for_deletion
from .indexing import INDEX_EXTENSIONS, indexing_lock, start_indexing_process, save_file_to_db, index_message, message_queue, process_message_queue, indexing_stats, prune_orphaned_index_entries
from .search import format_file_size, group_recent_content, format_recent_output, send_search_results

# -------------------------
# Command Handler
# -------------------------
async def handle_command(client, message: Message):
    """Handle bot commands"""
    if not message.text:
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
    elif command == 'metadata':
        await cmd_metadata(client, message)
    elif command == 'my_history':
        await cmd_my_history(client, message)
    elif command == 'my_prefs':
        await cmd_my_prefs(client, message)
    # Admin commands
    elif command == 'add_channel':
        await cmd_add_channel(client, message)
    elif command == 'remove_channel':
        await cmd_remove_channel(client, message)
    elif command == 'list_channels':
        await cmd_list_channels(client, message)
    elif command == 'channel_stats':
        await cmd_channel_stats(client, message)
    elif command == 'index_channel' or command == 'index':
        await cmd_index_channel(client, message)
    elif command == 'rescan_channel':
        await cmd_rescan_channel(client, message)
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
    elif command == 'indexing_stats':
        await cmd_indexing_stats(client, message)
    elif command == 'reset_stats':
        await cmd_reset_stats(client, message)
    elif command == 'prune_orphans':
        await cmd_prune_orphans(client, message)
    elif command == 'update_db':
        await cmd_update_db(client, message)
    else:
        # Unknown command
        await message.reply_text("❓ Unknown command. Use /help to see available commands.")

# -------------------------
# Command Implementations
# -------------------------
USER_HELP = """
🤖 Movie Bot Commands (Bot Session)
/search <title>           - Search (exact + fuzzy)
/f <title>             - Shortcut for search command
/search -e <title>      - Exact search (match full title)
/metadata <title>         - Show rich metadata
/recent                   - Show recently added content
/my_history               - Show your search history
/my_prefs                 - Show or set preferences
/help                     - Show this message

💡 Search Tips:
• Use /f for quick searches
• Use -e for exact title matches
• Normal search combines exact + fuzzy results
• Exact search finds perfect title matches only
"""

ADMIN_HELP = """
👑 Admin Commands
/add_channel <link|id>     - Add a channel (bot must be admin)
/remove_channel <link|id>  - Remove a channel
/list_channels             - List channels
/channel_stats             - Counts per channel
/index_channel             - Enhanced channel indexing (interactive)
/index                     - Alias for /index_channel
/rescan_channel            - Legacy command (redirects to /index_channel)
/toggle_indexing           - Toggle auto-indexing on/off
/promote <user_id>         - Promote to admin
/demote <user_id>          - Demote admin
/ban_user <user_id>        - Ban a user
/unban_user <user_id>      - Unban a user
/reset                     - Clear all indexed data from database (requires confirmation)
/reset_channel             - Clear indexed data from a specific registered channel (requires confirmation)
/indexing_stats            - Show indexing statistics (diagnose file skipping)
/reset_stats               - Reset indexing statistics counters
/prune_orphans             - Manually prune orphaned index entries
/update_db                 - Scan for duplicates + remove orphaned entries (maintenance)

🚀 Enhanced Features:
• Interactive indexing with progress tracking
• Cancellable operations
• Better error handling
• Support for all video file types
• Safe database & per-channel reset with confirmation
• Orphan/duplicate cleanup utilities
• Diagnostic logging for troubleshooting file indexing issues

⚠️ Important: Add bot as admin to channels for monitoring and file access
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
        await message.reply_text(
            f"👋 **Welcome back, {user_name}!**\n\n"
            f"You're all set to use MovieBot.\n\n"
            f"Use /help to see available commands.",
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
            disable_web_page_preview=True,
            parse_mode=ParseMode.MARKDOWN
        )
    else:
        # Split into multiple messages
        # Send first part
        first_part = terms_content[:max_length]
        await message.reply_text(
            first_part,
            disable_web_page_preview=True,
            parse_mode=ParseMode.MARKDOWN
        )

        # Send remaining parts
        remaining = terms_content[max_length:]
        while len(remaining) > max_length:
            chunk = remaining[:max_length]
            await message.reply_text(
                chunk,
                disable_web_page_preview=True,
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
            disable_web_page_preview=True,
            parse_mode=ParseMode.MARKDOWN
        )

async def cmd_help(client, message: Message):
    uid = message.from_user.id
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

async def cmd_metadata(client, message: Message):
    parts = message.text.split()
    if len(parts) < 2:
        return await message.reply_text("Usage: /metadata <title>")
    query = " ".join(parts[1:]).strip()
    doc = await movies_col.find_one({"title": {"$regex": query, "$options": "i"}})
    if not doc:
        return await message.reply_text("No metadata found for that title.")
    
    # Helper function to check if value is available
    def has_value(val):
        return val and val not in ['N/A', 'Unknown', '', None] and val != 0
    
    # Extract metadata fields
    title = doc.get('title', 'Unknown')
    caption = doc.get('caption')
    quality = doc.get('quality')
    rip = doc.get('rip')
    audio = doc.get('audio')
    file_size = doc.get('file_size')
    resolution = doc.get('resolution')
    movie_type = doc.get('type')
    year = doc.get('year')
    season = doc.get('season')
    episode = doc.get('episode')
    source = doc.get('source')
    extension = doc.get('extension')
    
    # Build metadata output with specific attributes
    metadata_text = f"```\n"
    metadata_text += f"Metadata: \"{query}\"\n\n"
    
    # 1. Name (always shown)
    metadata_text += f"Name: {title}\n"
    
    # 2. Quality (combine quality and rip if available)
    quality_parts = []
    if has_value(quality):
        quality_parts.append(quality)
    if has_value(rip):
        quality_parts.append(rip)
    if quality_parts:
        metadata_text += f"Quality: {' '.join(quality_parts)}\n"
    
    # 4. Audio (only if available)
    if has_value(audio):
        metadata_text += f"Audio: {audio}\n"
    
    # 5. Size (formatted, only if available)
    if has_value(file_size):
        size_str = format_file_size(file_size)
        metadata_text += f"Size: {size_str}\n"
    
    # 6. Resolution (only if available)
    if has_value(resolution):
        metadata_text += f"Resolution: {resolution}\n"
    
    # 7. Type (only if available)
    if has_value(movie_type):
        metadata_text += f"Type: {movie_type}\n"
    
    # 8. Year (only if available)
    if has_value(year):
        metadata_text += f"Year: {year}\n"
    
    # 9. Season (only if available for series)
    if has_value(season) or has_value(episode):
        season_str = ""
        if has_value(season) and has_value(episode):
            season_str = f"S{season:02d}E{episode:02d}"
        elif has_value(season):
            season_str = f"S{season:02d}"
        elif has_value(episode):
            season_str = f"E{episode:02d}"
        if season_str:
            metadata_text += f"Season: {season_str}\n"
    
    # 10. Features (combine source, extension, and other special features)
    features = []
    if has_value(source):
        features.append(source)
    if has_value(extension):
        features.append(extension.upper().replace('.', ''))
    # Check for DV, HDR, Dolby Vision in caption or filename
    if caption:
        caption_lower = caption.lower()
        if 'dolby vision' in caption_lower or 'dv' in caption_lower:
            if 'Dolby Vision' not in features:
                features.append('Dolby Vision')
        if 'hdr' in caption_lower and 'HDR' not in features:
            features.append('HDR')
    if features:
        metadata_text += f"Extras: {', '.join(features)}\n"
    
    metadata_text += f"```"
    
    await message.reply_text(metadata_text, disable_web_page_preview=True)

async def cmd_my_history(client, message: Message):
    uid = message.from_user.id
    doc = await users_col.find_one({"user_id": uid})
    history = doc.get("search_history", []) if doc else []
    if not history:
        return await message.reply_text("You have no search history.")
    text = "\n".join([f"{h['ts'].isoformat()} — {h['q']}" for h in history[-20:]])
    await message.reply_text(text)

async def cmd_my_prefs(client, message: Message):
    uid = message.from_user.id
    parts = message.text.split()
    if len(parts) == 1:
        doc = await users_col.find_one({"user_id": uid})
        prefs = doc.get("preferences", {}) if doc else {}
        await message.reply_text(f"Your preferences: {prefs}")
    else:
        if len(parts) < 3:
            return await message.reply_text("Usage: /my_prefs <key> <value>")
        key = parts[1]
        value = " ".join(parts[2:])
        await users_col.update_one({"user_id": uid}, {"$set": {f"preferences.{key}": value}}, upsert=True)
        await message.reply_text(f"Set preference `{key}` = `{value}`")

async def cmd_recent(client, message: Message):
    """Handle /recent command to display recently added content"""
    
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

# -------------------------
# Admin Commands (simplified implementations)
# -------------------------
async def resolve_chat_ref(ref: str):
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

async def cmd_add_channel(client, message: Message):
    uid = message.from_user.id
    if not await is_admin(uid):
        return await message.reply_text("🚫 Admins only.")
    parts = message.text.split()
    if len(parts) < 2:
        return await message.reply_text("Usage: /add_channel <link|id|@username>")
    target = parts[1]
    try:
        chat = await resolve_chat_ref(target)
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
        chat = await resolve_chat_ref(target)
        await channels_col.delete_one({"channel_id": chat.id})
        await log_action("remove_channel", by=uid, target=chat.id)
        await message.reply_text(f"✅ Channel removed: {getattr(chat,'title', chat.id)} ({chat.id})")
    except Exception as e:
        await message.reply_text(f"❌ Could not remove channel: {e}")

async def cmd_list_channels(client, message: Message):
    uid = message.from_user.id
    if not await is_admin(uid):
        return await message.reply_text("🚫 Admins only.")
    docs = channels_col.find({})
    items = []
    async for d in docs:
        items.append(f"{d.get('channel_title','?')} — `{d.get('channel_id')}` — enabled={d.get('enabled', True)}")
    await message.reply_text("\n".join(items) or "No channels configured.")

async def cmd_channel_stats(client, message: Message):
    uid = message.from_user.id
    if not await is_admin(uid):
        return await message.reply_text("🚫 Admins only.")
    pipeline = [{"$group": {"_id": "$channel_id", "count": {"$sum": 1}}}, {"$sort": {"count": -1}}, {"$limit": 50}]
    rows = await movies_col.aggregate(pipeline).to_list(length=50)
    parts = []
    for r in rows:
        ch = await channels_col.find_one({"channel_id": r["_id"]})
        title = ch.get("channel_title") if ch else str(r["_id"])
        parts.append(f"{title} ({r['_id']}): {r['count']}")
    await message.reply_text("\n".join(parts) or "No data.")

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
        elif response.forward_from_chat and response.forward_from_chat.type == ChatType.CHANNEL:
            # Handle forwarded message
            last_msg_id = response.forward_from_message_id
            chat_id = response.forward_from_chat.username or response.forward_from_chat.id
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

async def cmd_rescan_channel(client, message: Message):
    """Legacy rescan command - explains Bot API limitations"""
    await message.reply_text(
        "🔄 **Command Not Available**\n\n"
        "❌ **Bot API Limitation:** Telegram bots cannot access chat history or rescan past messages.\n\n"
        "✅ **Alternative:** Use real-time auto-indexing instead:\n"
        "• Add bot to channels as admin\n"
        "• Enable auto-indexing with `/toggle_indexing`\n"
        "• New messages will be indexed automatically\n\n"
        "For more details, use `/index_channel`"
    )

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
    
    await message.reply_text(stats_text, disable_web_page_preview=True)
    
    # Log statistics viewing
    await log_action("indexing_stats_viewed", by=message.from_user.id, extra=indexing_stats)

async def cmd_reset_stats(client, message: Message):
    """Reset indexing statistics counters"""
    
    # Check if user is admin
    if not await is_admin(message.from_user.id):
        await message.reply_text("🚫 Admins only.")
        return
    
    # Reset global statistics
    global indexing_stats
    old_stats = indexing_stats.copy()
    
    indexing_stats = {
        'total_attempts': 0,
        'successful_inserts': 0,
        'duplicate_errors': 0,
        'other_errors': 0,
        'concurrent_peak': 0
    }
    
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

async def cmd_prune_orphans(client, message: Message):
    """
    Admin command to trigger immediate orphaned index reconciliation.
    Usage: /prune_orphans [limit]
    limit (optional) caps number of recent entries scanned (default 500).
    """
    if not await is_admin(message.from_user.id):
        await message.reply_text("🚫 Admins only.")
        return

    parts = message.text.split()
    limit = 500
    if len(parts) >= 2:
        try:
            limit = int(parts[1])
        except ValueError:
            return await message.reply_text("❌ Invalid limit. Usage: /prune_orphans [limit]")

    start = datetime.now(timezone.utc).isoformat()
    await message.reply_text(f"🔍 Starting orphan prune (limit {limit})...")

    removed = 0
    checked = 0
    errors = 0

    # Custom inline version of prune for user feedback (reuse core function but capture prints)
    try:
        cursor = movies_col.find({}, {"channel_id": 1, "message_id": 1, "title": 1}).sort("indexed_at", -1).limit(limit)
        async for doc in cursor:
            checked += 1
            channel_id = doc.get("channel_id")
            message_id = doc.get("message_id")
            doc_id = doc.get("_id")
            if channel_id is None or message_id is None:
                try:
                    await movies_col.delete_one({"_id": doc_id})
                    removed += 1
                except Exception:
                    errors += 1
                continue
            try:
                msg = await client.get_messages(channel_id, message_id)
                if not msg or getattr(msg, "empty", False):
                    await movies_col.delete_one({"_id": doc_id})
                    removed += 1
            except Exception:
                try:
                    await movies_col.delete_one({"_id": doc_id})
                    removed += 1
                except Exception:
                    errors += 1
        end = datetime.now(timezone.utc).isoformat()
        await log_action("prune_orphans", by=message.from_user.id, extra={
            "checked": checked,
            "removed": removed,
            "errors": errors,
            "start": start,
            "end": end
        })
        await message.reply_text(
            f"✅ Orphan prune complete\n"
            f"Checked: {checked}\nRemoved: {removed}\nErrors: {errors}\n"
            f"Window: {start} → {end}"
        )
    except Exception as e:
        await log_action("prune_orphans_error", by=message.from_user.id, extra={"error": str(e)})
        await message.reply_text(f"❌ Orphan prune failed: {e}")