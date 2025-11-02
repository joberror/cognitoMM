# main.py
"""
Telegram Movie Bot - Hydrogram Bot Session
- Hydrogram bot session for better channel access and compatibility
- MongoDB Atlas (motor) for async storage
- Advanced indexing system with proper file handling
- Robust metadata parsing, exact + fuzzy search, channel management
- Enhanced scanning features from Auto-Filter-Bot architecture
"""

import os
import re
import asyncio
import sys
import threading
import time
import uuid
import logging
from datetime import datetime, timezone
from dotenv import load_dotenv
from fuzzywuzzy import fuzz
from motor.motor_asyncio import AsyncIOMotorClient
# Telegram library imports are now handled above

# Time synchronization patches removed - using system time as-is

# Import Hydrogram - Telegram MTProto API Framework
from hydrogram import Client, filters
from hydrogram.types import Message, InlineQuery, InlineQueryResultArticle, InputTextMessageContent, InlineKeyboardMarkup, InlineKeyboardButton, CallbackQuery
from hydrogram.handlers import MessageHandler, InlineQueryHandler, CallbackQueryHandler
from hydrogram.errors import FloodWait, UserNotParticipant
from hydrogram import enums

load_dotenv()

print(f"🐍 Python {sys.version}")
print("🎬 MovieBot - Bot Session")

# Add missing variables for indexing functionality
class temp_data:
    CANCEL = False

def get_readable_time(seconds):
    """Convert seconds to readable time format"""
    if seconds < 60:
        return f"{int(seconds)}s"
    elif seconds < 3600:
        minutes = int(seconds // 60)
        secs = int(seconds % 60)
        return f"{minutes}m {secs}s"
    else:
        hours = int(seconds // 3600)
        minutes = int((seconds % 3600) // 60)
        return f"{hours}h {minutes}m"

# -------------------------
# CONFIG / ENV
# -------------------------
API_ID = int(os.getenv("API_ID", "0"))
API_HASH = os.getenv("API_HASH", "")
BOT_TOKEN = os.getenv("BOT_TOKEN", "")             # Bot token (required for bot session)
BOT_ID = int(os.getenv("BOT_ID", "0"))             # Bot ID (optional, will be auto-detected)
MONGO_URI = os.getenv("MONGO_URI", "")
MONGO_DB = os.getenv("MONGO_DB", "moviebot")
ADMINS = [int(x) for x in os.getenv("ADMINS", "").split(",") if x.strip()]
LOG_CHANNEL = os.getenv("LOG_CHANNEL")             # optional - e.g. -1001234567890
FUZZY_THRESHOLD = int(os.getenv("FUZZY_THRESHOLD", "68"))
AUTO_INDEX_DEFAULT = os.getenv("AUTO_INDEXING", "True").lower() in ("1", "true", "yes")

# -------------------------
# DB (motor async)
# -------------------------
# Configure MongoDB client with longer timeouts for better connectivity
mongo = AsyncIOMotorClient(
    MONGO_URI,
    connectTimeoutMS=60000,  # 60 seconds
    serverSelectionTimeoutMS=60000,  # 60 seconds
    socketTimeoutMS=60000,  # 60 seconds
    maxPoolSize=10,
    retryWrites=True
)
db = mongo[MONGO_DB]
movies_col = db["movies"]
users_col = db["users"]
channels_col = db["channels"]
settings_col = db["settings"]
logs_col = db["logs"]

async def ensure_indexes():
    """Create database indexes with error handling"""
    try:
        print("🔧 Creating database indexes...")
        
        # Test connection first
        await mongo.admin.command('ping')
        print("✅ MongoDB connection successful")
        
        # Create indexes with error handling
        indexes_to_create = [
            (movies_col, [("title", 1)], "title index"),
            (movies_col, [("year", 1)], "year index"),
            (movies_col, [("quality", 1)], "quality index"),
            (movies_col, [("type", 1)], "type index"),
            (movies_col, [("channel_id", 1), ("message_id", 1)], "channel_message index"),
            (users_col, [("user_id", 1)], "user_id index"),
            (channels_col, [("channel_id", 1)], "channel_id index"),
        ]
        
        for collection, index_spec, description in indexes_to_create:
            try:
                if description == "user_id index" or description == "channel_id index":
                    await collection.create_index(index_spec, unique=True)
                else:
                    await collection.create_index(index_spec)
                print(f"✅ Created {description}")
            except Exception as e:
                print(f"⚠️ Failed to create {description}: {e}")
                
    except Exception as e:
        print(f"❌ Database connection failed: {e}")
        print("⚠️ Continuing without database indexes - some features may be slower")
        raise e

# -------------------------
# Single Client (User Session)
# -------------------------
# Client will be initialized within async context
client = None

# Temporary storage for bulk downloads (to avoid callback data size limits)
bulk_downloads = {}

# Global variables for indexing
INDEX_EXTENSIONS = ['.mkv', '.mp4', '.avi', '.mov', '.wmv', '.flv', '.webm', '.m4v', '.3gp', '.ts', '.m2ts']
indexing_lock = asyncio.Lock()

class TempData:
    """Temporary data storage for bot operations"""
    CANCEL = False
    INDEXING_CHAT = None
    INDEXING_USER = None

temp_data = TempData()

# User input waiting system (replacement for client.listen)
user_input_events = {}

async def wait_for_user_input(chat_id: int, user_id: int, timeout: int = 60):
    """Wait for user input - replacement for client.listen"""
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
    key = f"{chat_id}_{user_id}"
    if key in user_input_events:
        user_input_events[key]['message'] = message
        user_input_events[key]['event'].set()

def cleanup_expired_bulk_downloads():
    """Remove bulk downloads older than 1 hour"""
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

async def start_indexing_process(client, msg, chat_id, last_msg_id, skip):
    """Enhanced indexing process using Hydrogram's get_chat_history"""
    start_time = time.time()
    total_files = 0
    duplicate = 0
    errors = 0
    deleted = 0
    no_media = 0
    unsupported = 0
    current = skip

    async with indexing_lock:
        try:
            # Get chat info
            chat = await client.get_chat(chat_id)

            # Update initial message
            await msg.edit_text("🚀 **Starting Indexing Process**\n\n📺 **Channel:** {}\n🔄 **Status:** Initializing...".format(chat.title))

            # Try to use iter_messages as in Auto-Filter-Bot
            print(f"🔍 Attempting to use iter_messages for chat {chat_id}, last_msg_id: {last_msg_id}, skip: {skip}")

            try:
                # Test if iter_messages exists and works
                async for message in client.iter_messages(chat_id, last_msg_id, skip):
                    current += 1
                    time_taken = get_readable_time(time.time() - start_time)

                    # Check for cancellation
                    if temp_data.CANCEL:
                        temp_data.CANCEL = False
                        await msg.edit_text(
                            f"❌ **Indexing Cancelled!**\n\n"
                            f"📺 **Channel:** {chat.title}\n"
                            f"⏱️ **Time Taken:** {time_taken}\n"
                            f"📊 **Progress:** {current}/{last_msg_id}\n\n"
                            f"✅ **Saved:** {total_files} files\n"
                            f"🔄 **Duplicates:** {duplicate}\n"
                            f"🗑️ **Deleted:** {deleted}\n"
                            f"📄 **No Media:** {no_media}\n"
                            f"❌ **Errors:** {errors}"
                        )
                        return

                    # Update progress every 30 messages
                    if current % 30 == 0:
                        try:
                            btn = [[InlineKeyboardButton('🛑 CANCEL', callback_data='index#cancel')]]
                            await msg.edit_text(
                                f"🔄 **Indexing In Progress**\n\n"
                                f"📺 **Channel:** {chat.title}\n"
                                f"⏱️ **Time:** {time_taken}\n"
                                f"📊 **Progress:** {current}/{last_msg_id}\n\n"
                                f"✅ **Saved:** {total_files} files\n"
                                f"🔄 **Duplicates:** {duplicate}\n"
                                f"🗑️ **Deleted:** {deleted}\n"
                                f"📄 **No Media:** {no_media}\n"
                                f"⚠️ **Unsupported:** {unsupported}\n"
                                f"❌ **Errors:** {errors}",
                                reply_markup=InlineKeyboardMarkup(btn)
                            )
                        except FloodWait as e:
                            await asyncio.sleep(e.value)
                        except Exception:
                            pass  # Continue if update fails

                    # Process message
                    if message.empty:
                        deleted += 1
                        continue
                    elif not message.media:
                        no_media += 1
                        continue
                    elif message.media not in [enums.MessageMediaType.VIDEO, enums.MessageMediaType.DOCUMENT]:
                        unsupported += 1
                        continue

                    # Get media object
                    media = getattr(message, message.media.value, None)
                    if not media:
                        unsupported += 1
                        continue

                    # Check file extension for documents
                    if message.media == enums.MessageMediaType.DOCUMENT:
                        if not hasattr(media, 'file_name') or not media.file_name:
                            unsupported += 1
                            continue

                        file_ext = os.path.splitext(media.file_name.lower())[1]
                        if file_ext not in INDEX_EXTENSIONS:
                            unsupported += 1
                            continue

                    # Save file
                    try:
                        result = await save_file_to_db(media, message)
                        if result == 'suc':
                            total_files += 1
                        elif result == 'dup':
                            duplicate += 1
                        elif result == 'err':
                            errors += 1
                    except Exception as e:
                        errors += 1
                        print(f"❌ Error processing message {message.id}: {e}")

                # Final success message
                time_taken = get_readable_time(time.time() - start_time)
                await msg.edit_text(
                    f"✅ **Indexing Complete!**\n\n"
                    f"📺 **Channel:** {chat.title}\n"
                    f"⏱️ **Time Taken:** {time_taken}\n"
                    f"📊 **Total Processed:** {current}/{last_msg_id}\n\n"
                    f"✅ **Successfully Saved:** {total_files} files\n"
                    f"🔄 **Duplicates Skipped:** {duplicate}\n"
                    f"🗑️ **Deleted Messages:** {deleted}\n"
                    f"📄 **Non-Media Messages:** {no_media}\n"
                    f"⚠️ **Unsupported Media:** {unsupported}\n"
                    f"❌ **Errors:** {errors}\n\n"
                    f"🎉 **Indexing completed successfully!**"
                )

            except AttributeError as e:
                print(f"❌ iter_messages not available: {e}")
                await msg.edit_text(
                    f"❌ **Method Not Available**\n\n"
                    f"The `iter_messages` method is not available in this version of Hydrogram.\n\n"
                    f"**Error:** {e}\n\n"
                    f"**Available alternatives:**\n"
                    f"• Use real-time auto-indexing instead\n"
                    f"• Forward messages manually for indexing\n"
                    f"• Check Hydrogram version compatibility"
                )
                return
            except Exception as e:
                print(f"❌ iter_messages error: {e}")
                await msg.edit_text(
                    f"❌ **Indexing Error**\n\n"
                    f"An error occurred while trying to index messages.\n\n"
                    f"**Error:** {e}\n\n"
                    f"This might be due to:\n"
                    f"• Bot API limitations\n"
                    f"• Insufficient permissions\n"
                    f"• Network issues"
                )
                return

        except Exception as e:
            await msg.edit_text(f"❌ **Error:** {e}")
            print(f"❌ Indexing error: {e}")

async def save_file_to_db(media, message):
    """Enhanced file saving function compatible with Hydrogram"""
    try:
        # Extract file information
        if hasattr(media, 'file_name') and media.file_name:
            file_name = media.file_name
        else:
            file_name = f"file_{message.id}"

        # Clean filename for better searching
        clean_name = re.sub(r"@\w+|(_|\-|\.|\+)", " ", str(file_name))

        # Get file caption
        file_caption = ""
        if hasattr(media, 'caption') and media.caption:
            file_caption = re.sub(r"@\w+|(_|\-|\.|\+)", " ", str(media.caption))
        elif message.caption:
            file_caption = re.sub(r"@\w+|(_|\-|\.|\+)", " ", str(message.caption))

        # Create document for database
        document = {
            '_id': f"{message.chat.id}_{message.id}",  # Unique identifier
            'file_name': clean_name,
            'original_file_name': file_name,
            'file_size': getattr(media, 'file_size', 0),
            'caption': file_caption,
            'channel_id': message.chat.id,
            'message_id': message.id,
            'date': message.date,
            'indexed_at': datetime.now(timezone.utc),
            'file_type': 'video' if hasattr(media, 'duration') else 'document',
            'duration': getattr(media, 'duration', 0),
            'mime_type': getattr(media, 'mime_type', ''),
        }

        # Parse additional metadata
        metadata = parse_metadata(file_caption, file_name)
        document.update(metadata)

        try:
            # Insert into database
            await movies_col.insert_one(document)
            return 'suc'
        except Exception as e:
            if 'duplicate key' in str(e).lower():
                return 'dup'
            else:
                print(f"❌ Database error: {e}")
                return 'err'

    except Exception as e:
        print(f"❌ Error saving file: {e}")
        return 'err'

# -------------------------
# Helpers: roles, logs
# -------------------------
async def get_user_doc(user_id: int):
    return await users_col.find_one({"user_id": user_id})

async def is_admin(user_id: int):
    if user_id in ADMINS:
        return True
    doc = await get_user_doc(user_id)
    return bool(doc and doc.get("role") == "admin")

async def is_banned(user_id: int):
    doc = await get_user_doc(user_id)
    return bool(doc and doc.get("role") == "banned")

async def log_action(action: str, by: int = None, target: int = None, extra: dict = None):
    doc = {
        "action": action,
        "by": by,
        "target": target,
        "extra": extra or {},
        "ts": datetime.now(timezone.utc)
    }
    try:
        await logs_col.insert_one(doc)
    except Exception:
        pass
    if client and LOG_CHANNEL:
        try:
            msg = f"Log: {action}\nBy: {by}\nTarget: {target}\nExtra: {extra or {}}"
            await client.send_message(int(LOG_CHANNEL), msg)
        except Exception:
            pass

async def check_banned(message: Message) -> bool:
    """Check if user is banned and send message if they are"""
    uid = message.from_user.id
    if await is_banned(uid):
        await message.reply_text("🚫 You are banned from using this bot.")
        return True
    return False

async def should_process_command(message: Message) -> bool:
    """
    Determine if a command should be processed based on access control rules for bot session.

    Commands are processed if:
    1. Message is from a private chat (direct message to bot)
    2. Message is from a monitored channel/group (in channels_col database)
    3. User is an admin (in ADMINS list or has admin role in database)
    4. Bot is mentioned in groups (for bot session compatibility)

    This prevents the bot from responding to commands in random groups.
    """
    # Always process private messages (direct messages to bot)
    if message.chat.type == "private":
        return True

    # Check if user is an admin - admins can use commands anywhere
    user_id = message.from_user.id
    if await is_admin(user_id):
        return True

    # For groups/supergroups, check if bot is mentioned or if it's a monitored group
    if message.chat.type in ["group", "supergroup"]:
        # Check if this group is explicitly added as a monitored channel
        channel_doc = await channels_col.find_one({"channel_id": message.chat.id})
        if channel_doc and channel_doc.get("enabled", True):
            return True

        # For bot sessions, also check if bot is mentioned (for compatibility)
        if message.text and message.text.startswith('/'):
            # Allow commands in groups if they're directed to the bot
            return True

    # Check if this is a monitored channel
    if message.chat.type == "channel":
        channel_doc = await channels_col.find_one({"channel_id": message.chat.id})
        if channel_doc and channel_doc.get("enabled", True):
            return True

    # Default: Don't process commands from unauthorized sources
    return False

def require_not_banned(func):
    """Decorator to check if user is banned before executing command"""
    async def wrapper(client, message: Message):
        if await check_banned(message):
            return
        return await func(client, message)
    return wrapper

# -------------------------
# Robust metadata parser
# -------------------------
BRACKET_TAG_RE = re.compile(r"\[([^\]]+)\]|\(([^\)]+)\)|\{([^\}]+)\}")

def parse_metadata(caption: str = None, filename: str = None) -> dict:
    """
    Robust parsing:
    - detects bracketed tags [BluRay], (720p), {AAC}, IMDB tt1234567
    - extracts title heuristically, year, quality, rip, source, extension, resolution, audio, imdb, type, season, episode
    """
    text = (caption or "") + " " + (filename or "")
    text = text.strip()

    md = {
        "title": None,
        "year": None,
        "quality": None,
        "rip": None,
        "source": None,
        "extension": None,
        "resolution": None,
        "audio": None,
        "imdb": None,
        "type": None,
        "season": None,
        "episode": None,
    }

    if not text:
        return md

    # Normalize spacing
    t = re.sub(r"[_\.]+", " ", text)

    # IMDB id
    m = re.search(r"(tt\d{6,8})", t, re.I)
    if m:
        md["imdb"] = m.group(1)

    # bracketed tags (often contain rip/source/quality)
    brackets = BRACKET_TAG_RE.findall(t)
    # flatten matches (three groups per findall)
    bracket_texts = [next(filter(None, g)) for g in brackets if any(g)]
    for bt in bracket_texts:
        bt_l = bt.lower()
        if re.search(r"1080p|720p|2160p|4k|480p", bt_l):
            md["quality"] = re.search(r"(480p|720p|1080p|2160p|4K)", bt, re.I).group(1)
        if re.search(r"webrip|bluray|hdrip|dvdrip|bd5|bdrip|web-dl|web dl", bt_l):
            md["rip"] = bt
        if re.search(r"netflix|amazon|prime|disney|hbo|hulu|apple", bt_l):
            md["source"] = bt
        if re.search(r"aac|dts|ac3|eac3|flac|mp3|atmos", bt_l):
            md["audio"] = bt

    # Quality (inline)
    m = re.search(r"(480p|720p|1080p|2160p|4K)", t, re.I)
    if m and not md["quality"]:
        md["quality"] = m.group(1)

    # Rip inline
    m = re.search(r"(WEBRip|BluRay|HDRip|DVDRip|BRRip|CAM|HDTS|WEB-DL|WEB DL)", t, re.I)
    if m and not md["rip"]:
        md["rip"] = m.group(1)

    # Source inline
    m = re.search(r"(Netflix|Amazon|Prime Video|Disney\+|HBO|Hulu|Apple ?TV)", t, re.I)
    if m and not md["source"]:
        md["source"] = m.group(1)

    # Extension
    m = re.search(r"\.(mkv|mp4|avi|mov|webm)", t, re.I)
    if m:
        md["extension"] = "." + m.group(1).lower()

    # Resolution
    m = re.search(r"(\d{3,4}x\d{3,4})", t)
    if m:
        md["resolution"] = m.group(1)

    # Audio inline
    m = re.search(r"(AAC|DTS|AC3|EAC3|FLAC|MP3|Atmos)", t, re.I)
    if m and not md["audio"]:
        md["audio"] = m.group(1)

    # Season/Episode S01E02 or S1 E2 or 1x02
    m = re.search(r"[sS](\d{1,2})[ ._-]?[eE](\d{1,2})", t)
    if not m:
        m = re.search(r"(\d{1,2})x(\d{1,2})", t)
    if m:
        md["type"] = "Series"
        md["season"] = int(m.group(1))
        md["episode"] = int(m.group(2))
    else:
        md["type"] = "Movie"

    # Year
    m = re.search(r"(19\d{2}|20\d{2})", t)
    if m:
        md["year"] = int(m.group(1))

    # Heuristic title extraction:
    # - remove bracket tags and known tokens, then take leading chunk before year/quality/rip/imdb
    clean = re.sub(r"(\[.*?\]|\(.*?\)|\{.*?\})", " ", t)  # remove bracket groups
    clean = re.sub(r"(\.|\_)+", " ", clean)
    # split at imdb or year or quality or rip
    split_at = re.search(r"(tt\d{6,8}|19\d{2}|20\d{2}|480p|720p|1080p|2160p|4K|WEBRip|BluRay|HDRip|DVDRip|CAM)", clean, re.I)
    if split_at:
        title_guess = clean[:split_at.start()].strip()
    else:
        title_guess = clean.strip()

    # Take first line and remove trailing separators
    if title_guess:
        title_guess = title_guess.split("\n")[0].strip(" -_.")
        md["title"] = title_guess

    return md

# -------------------------
# Index message (user session)
# -------------------------
async def index_message(msg):
    try:
        # Debug logging (remove this in production)
        # print(f"🔍 Index attempt: Chat={getattr(msg.chat, 'type', 'None')} ID={getattr(msg.chat, 'id', 'None')} HasVideo={getattr(msg, 'video', None) is not None} HasDoc={getattr(msg, 'document', None) is not None}")

        # must be channel, supergroup, or forum post
        if getattr(msg, "chat", None) is None:
            return

        chat_type = getattr(msg.chat, "type", None)
        # Handle both string and enum values
        chat_type_str = str(chat_type).lower() if chat_type else ""
        if not any(supported in chat_type_str for supported in ["channel", "supergroup", "forum"]):
            return

        # Only index channels that exist in channels_col and enabled True
        chdoc = await channels_col.find_one({"channel_id": msg.chat.id})
        if not chdoc or not chdoc.get("enabled", True):
            return

        # Only process video or documents with video mime
        has_video = getattr(msg, "video", None) is not None
        has_doc = getattr(msg, "document", None) is not None and getattr(msg.document, "mime_type", "").startswith("video")
        if not (has_video or has_doc):
            return

        # Avoid duplicates
        existing = await movies_col.find_one({"channel_id": msg.chat.id, "message_id": msg.id})
        if existing:
            return

        file_size = None
        filename = None
        if has_video:
            file_size = msg.video.file_size
            # videos may not have filename
        elif has_doc:
            file_size = msg.document.file_size
            filename = getattr(msg.document, "file_name", None)

        caption = msg.caption or ""
        parsed = parse_metadata(caption, filename)

        entry = {
            "title": parsed.get("title") or (caption.split("\n")[0] if caption else filename or "Unknown"),
            "year": parsed.get("year"),
            "rip": parsed.get("rip"),
            "source": parsed.get("source"),
            "quality": parsed.get("quality"),
            "extension": parsed.get("extension"),
            "resolution": parsed.get("resolution"),
            "audio": parsed.get("audio"),
            "imdb": parsed.get("imdb"),
            "type": parsed.get("type", "Movie"),
            "season": parsed.get("season"),
            "episode": parsed.get("episode"),
            "file_size": file_size,
            "upload_date": datetime.utcfromtimestamp(msg.date.timestamp()) if getattr(msg, "date", None) else datetime.now(timezone.utc),
            "channel_id": msg.chat.id,
            "channel_title": getattr(msg.chat, "title", None),
            "message_id": msg.id,
            "caption": caption,
            "indexed_at": datetime.now(timezone.utc)
        }

        await movies_col.insert_one(entry)
        await log_action("indexed_message", extra={"title": entry["title"], "channel_id": entry["channel_id"], "message_id": entry["message_id"]})
        print(f"[INDEXED] {entry['title']} from {entry['channel_title']}")
    except Exception as e:
        await log_action("index_error", extra={"error": str(e)})
        print("Index error:", e)

# -------------------------
# Auto-indexing handler
# -------------------------
async def on_message(client, message):
    # Check for user input waiting (replacement for client.listen)
    if message.chat and message.from_user:
        set_user_input(message.chat.id, message.from_user.id, message)

    # Handle bot commands first (if message starts with /)
    if message.text and message.text.startswith('/'):
        # ACCESS CONTROL: Only process commands from authorized sources
        should_process = await should_process_command(message)

        if should_process:
            await handle_command(client, message)
        return

    # Auto-indexing for channel messages
    s = await settings_col.find_one({"k": "auto_indexing"})
    auto_index = s["v"] if s and "v" in s else AUTO_INDEX_DEFAULT

    # Debug: Show all non-command messages from supported chat types (remove in production)
    # if message.chat:
    #     chat_type_str = str(message.chat.type).lower() if message.chat.type else ""
    #     if any(supported in chat_type_str for supported in ["channel", "supergroup", "forum"]):
    #         print(f"📺 {message.chat.type} message: {getattr(message.chat, 'title', 'Unknown')} ({message.chat.id}) - Auto-index: {auto_index}")

    if auto_index:
        await index_message(message)

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

    # Route commands
    if command == 'start':
        await cmd_start(client, message)
    elif command == 'help':
        await cmd_help(client, message)
    elif command == 'search':
        await cmd_search(client, message)
    elif command == 'search_year':
        await cmd_search_year(client, message)
    elif command == 'search_quality':
        await cmd_search_quality(client, message)
    elif command == 'file_info':
        await cmd_file_info(client, message)
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
    else:
        # Unknown command
        await message.reply_text("❓ Unknown command. Use /help to see available commands.")

# -------------------------
# Command Implementations
# -------------------------
USER_HELP = """
🤖 Movie Bot Commands (Bot Session)
/search <title>           - Search (exact + fuzzy)
/search_year <year>       - Search by year
/search_quality <quality> - Search by quality
/file_info <message_id>   - Show stored file info
/metadata <title>         - Show rich metadata
/my_history               - Show your search history
/my_prefs                 - Show or set preferences
/help                     - Show this message

💡 Note: Bot must be added as admin to channels for file forwarding
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

🚀 Enhanced Features:
• Interactive indexing with progress tracking
• Cancellable operations
• Better error handling
• Support for all video file types

⚠️ Important: Add bot as admin to channels for monitoring and file access
"""

async def cmd_start(client, message: Message):
    # Check if user is banned first
    if await check_banned(message):
        return

    await users_col.update_one({"user_id": message.from_user.id}, {"$set": {"last_seen": datetime.now(timezone.utc)}}, upsert=True)
    await message.reply_text("👋 Welcome! Use /help to see commands.")

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

    query = " ".join(parts[1:]).strip()

    # record search history
    await users_col.update_one({"user_id": uid}, {"$push": {"search_history": {"q": query, "ts": datetime.now(timezone.utc)}}}, upsert=True)

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
    await send_search_results(message, all_results, query)

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

async def send_search_results(message: Message, results, query):
    """Send beautifully formatted search results with inline buttons"""

    # Create the refined format requested
    search_text = f"```\n"
    search_text += f"Search: \"{query}\"\n"
    search_text += f"Total Results: {len(results)}\n\n"

    # Format each result
    button_data = []

    for i, result in enumerate(results, 1):
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

        # Build the info string: [size.quality.series_info.year.rip]
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

        # Create result line in the new refined format
        search_text += f"{i}. {title} [{info_string}]\n"

        # Store button data
        if channel_id and message_id:
            button_data.append({
                'number': i,
                'channel_id': channel_id,
                'message_id': message_id
            })

    search_text += f"```"

    # Create buttons - fix the structure issue
    buttons = []
    if button_data:
        # Create individual file buttons in rows of 4
        current_row = []
        for btn in button_data:
            current_row.append(
                InlineKeyboardButton(
                    f"Get [{btn['number']}]",
                    callback_data=f"get_file:{btn['channel_id']}:{btn['message_id']}"
                )
            )

            # Add row when we have 4 buttons or it's the last button
            if len(current_row) == 4 or btn == button_data[-1]:
                buttons.append(current_row)
                current_row = []

        # Add "Get All" button if multiple results
        if len(button_data) > 1:
            # Generate a short UUID for bulk download to avoid callback data size limits
            bulk_id = str(uuid.uuid4())[:8]  # Use first 8 characters of UUID

            # Clean up expired downloads first
            cleanup_expired_bulk_downloads()

            # Store the bulk download data temporarily
            bulk_downloads[bulk_id] = {
                'files': [{'channel_id': btn['channel_id'], 'message_id': btn['message_id']} for btn in button_data[:10]],
                'created_at': datetime.now(timezone.utc),
                'user_id': message.from_user.id
            }

            buttons.append([
                InlineKeyboardButton(
                    f"Get All ({len(button_data)})",
                    callback_data=f"bulk:{bulk_id}"
                )
            ])

    # Create keyboard - this is the critical fix
    keyboard = InlineKeyboardMarkup(buttons) if buttons else None

    # Debug: Print detailed button info
    print(f"🔧 DEBUG: Button data count: {len(button_data)}")
    print(f"🔧 DEBUG: Button rows created: {len(buttons) if buttons else 0}")
    print(f"🔧 DEBUG: Keyboard object: {keyboard is not None}")

    # Send the message
    await message.reply_text(
        search_text,
        reply_markup=keyboard,
        disable_web_page_preview=True
    )

async def callback_handler(client, callback_query: CallbackQuery):
    """Handle inline button callbacks"""
    try:
        data = callback_query.data
        user_id = callback_query.from_user.id

        print(f"🔧 DEBUG: Callback received - Data: {data}, User: {user_id}")

        # Check access control
        if not await should_process_command_for_user(user_id):
            await callback_query.answer("🚫 Access denied.", show_alert=True)
            return

        if data.startswith("get_file:"):
            # Handle single file request
            _, channel_id, message_id = data.split(":")
            channel_id = int(channel_id)
            message_id = int(message_id)

            await callback_query.answer("📥 Fetching file...")

            try:
                # Get the message from the channel to extract media
                msg = await client.get_messages(channel_id, message_id)

                if not msg:
                    raise Exception("Message not found")

                # Extract media and send using send_cached_media (no forward header)
                if msg.video:
                    await client.send_cached_media(
                        chat_id=callback_query.from_user.id,
                        file_id=msg.video.file_id,
                        caption=msg.caption or ""
                    )
                elif msg.document:
                    await client.send_cached_media(
                        chat_id=callback_query.from_user.id,
                        file_id=msg.document.file_id,
                        caption=msg.caption or ""
                    )
                else:
                    raise Exception("Message does not contain video or document")

                # Edit the callback message to show success
                await callback_query.edit_message_text(
                    f"✅ File sent successfully!\n\n{callback_query.message.text}",
                    reply_markup=callback_query.message.reply_markup
                )

            except Exception as e:
                # If forwarding fails, provide channel link instead
                try:
                    # Get movie info from database
                    movie_doc = await movies_col.find_one({
                        "channel_id": channel_id,
                        "message_id": message_id
                    })

                    if movie_doc:
                        title = movie_doc.get('title', 'Unknown')
                        channel_title = movie_doc.get('channel_title', 'Unknown Channel')

                        # Create a link to the message
                        if channel_id < 0:
                            # Convert to public channel format if possible
                            channel_link = f"https://t.me/c/{str(channel_id)[4:]}/{message_id}"
                        else:
                            channel_link = f"Channel ID: {channel_id}, Message: {message_id}"

                        await callback_query.edit_message_text(
                            f"❌ Cannot send file directly (bot needs channel access)\n\n"
                            f"📁 File: {title}\n"
                            f"📺 Channel: {channel_title}\n"
                            f"🔗 Link: {channel_link}\n\n"
                            f"💡 Add bot as admin to channel for direct file access",
                            reply_markup=callback_query.message.reply_markup
                        )
                    else:
                        await callback_query.edit_message_text(
                            f"❌ Failed to fetch file: {str(e)}\n\n{callback_query.message.text}",
                            reply_markup=callback_query.message.reply_markup
                        )
                except Exception as inner_e:
                    await callback_query.edit_message_text(
                        f"❌ Failed to fetch file: {str(e)}\n\n{callback_query.message.text}",
                        reply_markup=callback_query.message.reply_markup
                    )

        elif data.startswith("index#"):
            # Handle indexing callback
            parts = data.split("#")
            action = parts[1]

            if action == "yes":
                # Start indexing process
                chat_id = int(parts[2]) if parts[2].lstrip('-').isdigit() else parts[2]
                last_msg_id = int(parts[3])
                skip = int(parts[4])

                await callback_query.answer("🚀 Starting indexing process...")
                await start_indexing_process(client, callback_query.message, chat_id, last_msg_id, skip)

            elif action == "cancel":
                temp_data.CANCEL = True
                await callback_query.answer("🛑 Cancelling indexing...")
                await callback_query.message.edit_text("❌ **Indexing Cancelled**\n\nThe indexing process has been cancelled by user request.")

        elif data.startswith("bulk:"):
            # Handle bulk download request using stored data
            _, bulk_id = data.split(":", 1)

            # Retrieve bulk download data
            if bulk_id not in bulk_downloads:
                await callback_query.answer("❌ Bulk download expired or not found", show_alert=True)
                return

            bulk_data = bulk_downloads[bulk_id]

            # Verify user permission (only the user who initiated can download)
            if bulk_data['user_id'] != callback_query.from_user.id:
                await callback_query.answer("❌ You can only download your own searches", show_alert=True)
                return

            files = bulk_data['files']
            await callback_query.answer(f"📦 Fetching {len(files)} files...")

            success_count = 0
            failed_files = []

            for file_info in files:
                try:
                    channel_id = int(file_info['channel_id'])
                    message_id = int(file_info['message_id'])

                    # Get the message from the channel to extract media
                    msg = await client.get_messages(channel_id, message_id)

                    if not msg:
                        raise Exception("Message not found")

                    # Extract media and send using send_cached_media (no forward header)
                    if msg.video:
                        await client.send_cached_media(
                            chat_id=callback_query.from_user.id,
                            file_id=msg.video.file_id,
                            caption=msg.caption or ""
                        )
                    elif msg.document:
                        await client.send_cached_media(
                            chat_id=callback_query.from_user.id,
                            file_id=msg.document.file_id,
                            caption=msg.caption or ""
                        )
                    else:
                        raise Exception("Message does not contain video or document")

                    success_count += 1

                except Exception as e:
                    print(f"❌ Failed to send {channel_id}:{message_id}: {e}")
                    failed_files.append(f"{channel_id}:{message_id}")
                    continue

            # Clean up the temporary data after use
            del bulk_downloads[bulk_id]

            # Update the message with results
            result_text = f"✅ Successfully sent {success_count}/{len(files)} files!"

            if failed_files:
                result_text += f"\n❌ Failed: {len(failed_files)} files"
                result_text += f"\n💡 Add bot as admin to channels for direct file access"

            await callback_query.edit_message_text(
                f"{result_text}\n\n{callback_query.message.text}",
                reply_markup=callback_query.message.reply_markup
            )

        else:
            await callback_query.answer("❌ Unknown action.", show_alert=True)

    except Exception as e:
        print(f"❌ Callback error: {e}")
        await callback_query.answer("❌ An error occurred.", show_alert=True)

async def should_process_command_for_user(user_id: int) -> bool:
    """Check if user has access to use bot commands"""
    # Check if user is admin
    if await is_admin(user_id):
        return True

    # Check if user is banned
    if await is_banned(user_id):
        return False

    # For now, allow all non-banned users
    return True

async def cmd_search_year(client, message: Message):
    parts = message.text.split()
    if len(parts) < 2:
        return await message.reply_text("Usage: /search_year <year>")

    try:
        year = int(parts[1])
    except ValueError:
        return await message.reply_text("Year must be a number")

    results = await movies_col.find({"year": year}).to_list(length=None)
    if not results:
        return await message.reply_text(f"⚠️ No movies found for year {year}")

    text = f"**🗓️ Movies from {year}:**\n\n" + "\n\n".join(
        [f"🎬 {r.get('title')} [{r.get('quality','N/A')}] — `{r.get('channel_title')}` (msg {r.get('message_id')})" for r in results]
    )
    await message.reply_text(text, disable_web_page_preview=True)

async def cmd_search_quality(client, message: Message):
    parts = message.text.split()
    if len(parts) < 2:
        return await message.reply_text("Usage: /search_quality <quality>")

    quality = parts[1]
    results = await movies_col.find({"quality": {"$regex": quality, "$options": "i"}}).to_list(length=None)
    if not results:
        return await message.reply_text(f"⚠️ No movies found with quality {quality}")

    text = f"**📺 Movies with quality {quality}:**\n\n" + "\n\n".join(
        [f"🎬 {r.get('title')} ({r.get('year','N/A')}) — `{r.get('channel_title')}` (msg {r.get('message_id')})" for r in results]
    )
    await message.reply_text(text, disable_web_page_preview=True)

async def cmd_file_info(client, message: Message):
    parts = message.text.split()
    if len(parts) < 2:
        return await message.reply_text("Usage: /file_info <message_id>")
    try:
        msg_id = int(parts[1])
    except Exception:
        return await message.reply_text("message_id must be integer")
    doc = await movies_col.find_one({"message_id": msg_id})
    if not doc:
        return await message.reply_text("No file indexed with that message_id.")
    text = (
        f"🎬 **{doc.get('title','Unknown')}**\n"
        f"📅 Year: {doc.get('year','N/A')}\n"
        f"📂 Size: {doc.get('file_size','N/A')} bytes\n"
        f"🎚️ Quality: {doc.get('quality','N/A')}\n"
        f"📁 Type: {doc.get('type','N/A')}\n"
        f"🔗 Channel: {doc.get('channel_title','N/A')} (id {doc.get('channel_id')})\n"
        f"🆔 Message ID: {doc.get('message_id')}\n"
        f"📝 Caption: {doc.get('caption','')}\n"
    )
    await message.reply_text(text, disable_web_page_preview=True)

async def cmd_metadata(client, message: Message):
    parts = message.text.split()
    if len(parts) < 2:
        return await message.reply_text("Usage: /metadata <title>")
    query = " ".join(parts[1:]).strip()
    doc = await movies_col.find_one({"title": {"$regex": query, "$options": "i"}})
    if not doc:
        return await message.reply_text("No metadata found for that title.")
    text = (
        f"🎬 **{doc.get('title','Unknown')}**\n"
        f"📅 Year: {doc.get('year','N/A')}\n"
        f"🧵 Rip: {doc.get('rip','N/A')}\n"
        f"🌐 Source: {doc.get('source','N/A')}\n"
        f"🎚️ Quality: {doc.get('quality','N/A')}\n"
        f"📁 Extension: {doc.get('extension','N/A')}\n"
        f"🖥️ Resolution: {doc.get('resolution','N/A')}\n"
        f"🔊 Audio: {doc.get('audio','N/A')}\n"
        f"📺 Type: {doc.get('type','N/A')}\n"
        f"Season/Episode: {doc.get('season','N/A')}/{doc.get('episode','N/A')}\n"
        f"📂 File size: {doc.get('file_size','N/A')}\n"
        f"🔗 Channel: {doc.get('channel_title','N/A')}\n"
        f"🆔 Message ID: {doc.get('message_id')}\n"
        f"📝 Caption: {doc.get('caption','')}\n"
    )
    await message.reply_text(text, disable_web_page_preview=True)

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

    i = await message.reply_text("📝 Send me the channel username, channel ID, or a message link from the channel you want to index.")

    try:
        # Wait for user response using our custom input system
        response = await wait_for_user_input(message.chat.id, message.from_user.id, timeout=60)
        await i.delete()

        # Parse the response
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
        elif response.forward_from_chat and response.forward_from_chat.type == enums.ChatType.CHANNEL:
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

        if chat.type != enums.ChatType.CHANNEL:
            return await message.reply_text("❌ I can only index channels.")

        # Ask for skip number
        s = await message.reply_text("🔢 Send the number of messages to skip (0 to start from beginning):")
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
            f'🤖 **Bot must be admin** in the channel\n\n'
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
        "• Add the bot to channels as admin\n"
        "• Enable auto-indexing with `/toggle_indexing`\n"
        "• New messages will be indexed automatically\n\n"
        "For more details, use `/index_channel`"
    )

    try:
        chat = await resolve_chat_ref(target)
        await message.reply_text(f"🔄 Starting rescan of {getattr(chat,'title',chat.id)} (limit: {limit})...")

        count = 0
        indexed = 0

        # Process in smaller batches with timeout handling
        try:
            async for m in client.search_messages(chat.id, limit=limit):
                count += 1
                try:
                    # Check if message has media before attempting to index
                    if getattr(m, 'video', None) or (getattr(m, 'document', None) and getattr(m.document, 'mime_type', '').startswith('video')):
                        await index_message(m)
                        indexed += 1
                except Exception as idx_error:
                    print(f"❌ Error indexing message {m.id}: {idx_error}")
                    continue

                # Progress update every 10 messages
                if count % 10 == 0:
                    print(f"📊 Processed {count}/{limit} messages, indexed {indexed}")

        except Exception as scan_error:
            await message.reply_text(f"⚠️ Scan interrupted after {count} messages: {scan_error}")

        await message.reply_text(f"✅ Rescan complete. Scanned {count} messages, indexed {indexed} media files from {getattr(chat,'title',chat.id)}")
        await log_action("rescan_channel", by=uid, target=chat.id, extra={"scanned": count, "indexed": indexed})

    except Exception as e:
        await message.reply_text(f"❌ Rescan failed: {e}")
        print(f"❌ Rescan error: {e}")

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

# -------------------------
# Inline Query Support
# -------------------------
async def inline_handler(client, inline_query: InlineQuery):
    q = inline_query.query.strip()
    if not q:
        return
    exact = await movies_col.find({"title": {"$regex": q, "$options": "i"}}).to_list(length=None)
    results = []
    for i, r in enumerate(exact):
        results.append(
            InlineQueryResultArticle(
                id=str(i),
                title=r.get("title"),
                description=f"{r.get('year','N/A')} | {r.get('quality','N/A')}",
                input_message_content=InputTextMessageContent(
                    f"🎬 {r.get('title')} ({r.get('year','N/A')}) [{r.get('quality','N/A')}] — {r.get('channel_title')} (msg {r.get('message_id')})"
                )
            )
        )
    await inline_query.answer(results, cache_time=5)

# -------------------------
# Main Function with Event Loop Handling
# -------------------------
def run_bot():
    """Run the bot with Kurigram - simplified approach"""
    try:
        print("🔄 Starting bot with Kurigram...")
        # Use asyncio.run for cleaner event loop management
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\n🛑 Bot stopped by user")
    except Exception as e:
        print(f"❌ Fatal error: {e}")
        import traceback
        traceback.print_exc()

# -------------------------
# CUSTOM BOT CLASS WITH iter_messages
# -------------------------

class CognitoBot(Client):
    """Extended Hydrogram Client with iter_messages method from Auto-Filter-Bot"""

    def __init__(self):
        super().__init__(
            name="movie_bot_session",
            api_id=API_ID,
            api_hash=API_HASH,
            bot_token=BOT_TOKEN,
            workdir=".",
        )

    async def iter_messages(self, chat_id, limit: int, offset: int = 0):
        """
        Iterate through a chat sequentially.
        This convenience method does the same as repeatedly calling get_messages in a loop.

        Parameters:
            chat_id (int | str): Unique identifier of the target chat
            limit (int): Identifier of the last message to be returned
            offset (int, optional): Identifier of the first message to be returned. Defaults to 0.

        Returns:
            Generator: A generator yielding Message objects.
        """
        current = offset
        while True:
            new_diff = min(200, limit - current)
            if new_diff <= 0:
                return
            messages = await self.get_messages(chat_id, list(range(current, current+new_diff+1)))
            for message in messages:
                yield message
                current += 1

async def main():
    print("🔧 Setting up database indexes...")
    await ensure_indexes()
    print("✅ Database indexes ready")

    # Create client configuration
    try:
        # Validate required environment variables
        if not API_ID or not API_HASH:
            print("❌ API_ID and API_HASH are required")
            sys.exit(1)

        if not BOT_TOKEN:
            print("❌ BOT_TOKEN is required for bot session")
            sys.exit(1)

        print("🔄 Starting bot session...")

        # Use our custom CognitoBot class with iter_messages support
        async with CognitoBot() as app:
            # Get bot info for verification
            bot_info = await app.get_me()
            print(f"✅ Bot authenticated: @{bot_info.username} ({bot_info.first_name})")
            print(f"🆔 Bot ID: {bot_info.id}")

            # Set global client reference for handlers
            global client
            client = app

            # Register handlers manually since decorators can't be used with async context
            app.add_handler(MessageHandler(on_message))
            app.add_handler(InlineQueryHandler(inline_handler))
            app.add_handler(CallbackQueryHandler(callback_handler))

            print("✅ Bot session started successfully")
            print("✅ MovieBot running with Hydrogram!")
            print("📱 Bot is ready to receive commands and monitor channels!")
            print("🛑 Press Ctrl+C to stop")

            # Keep the program running
            stop_event = asyncio.Event()

            # Handle shutdown gracefully
            def signal_handler():
                print("\n🛑 Received shutdown signal...")
                stop_event.set()

            # Wait for stop signal
            try:
                await stop_event.wait()
            except KeyboardInterrupt:
                signal_handler()

    except Exception as e:
        print(f"❌ Error during startup: {e}")
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    run_bot()
