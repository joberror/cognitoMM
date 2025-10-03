# main.py
"""
Telegram Movie Bot - User Session Only
- Single user session (Kurigram) handles both monitoring and bot commands
- MongoDB Atlas (motor) for async storage
- Robust metadata parsing, exact + fuzzy search, channel management
- Simplified architecture without hybrid session conflicts
"""

import os
import re
import asyncio
import sys
import threading
from datetime import datetime, timezone
from dotenv import load_dotenv
from fuzzywuzzy import fuzz
from motor.motor_asyncio import AsyncIOMotorClient

# Import Kurigram (maintained Pyrogram fork) - uses pyrogram import name
from pyrogram import Client, filters
from pyrogram.types import Message, InlineQuery, InlineQueryResultArticle, InputTextMessageContent
from pyrogram.handlers import MessageHandler, InlineQueryHandler

load_dotenv()

print(f"🐍 Python {sys.version}")
print("🎬 MovieBot - User Session Only")

# -------------------------
# CONFIG / ENV
# -------------------------
API_ID = int(os.getenv("API_ID", "0"))
API_HASH = os.getenv("API_HASH", "")
SESSION_STRING = os.getenv("SESSION_STRING", "")   # User session string
BOT_TOKEN = os.getenv("BOT_TOKEN", "")             # Bot token (for bot-like features)
BOT_ID = int(os.getenv("BOT_ID", "0"))             # Bot ID
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
    Determine if a command should be processed based on access control rules.

    Commands are processed if:
    1. Message is from a private chat (direct message)
    2. Message is from a monitored channel (in channels_col database)
    3. User is an admin (in ADMINS list or has admin role in database)

    This prevents the user account from responding to commands in random groups.
    """
    # Always process private messages
    if message.chat.type == "private":
        return True

    # Check if user is an admin - admins can use commands anywhere
    user_id = message.from_user.id
    if await is_admin(user_id):
        return True

    # Check if this is a monitored channel
    if message.chat.type == "channel":
        channel_doc = await channels_col.find_one({"channel_id": message.chat.id})
        if channel_doc and channel_doc.get("enabled", True):
            return True

    # Check if this is a monitored group/supergroup
    if message.chat.type in ["group", "supergroup"]:
        # Only process if the group is explicitly added as a monitored channel
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
🎬 Movie Bot Commands
/search <title>           - Search (exact + fuzzy)
/search_year <year>       - Search by year
/search_quality <quality> - Search by quality
/file_info <message_id>   - Show stored file info
/metadata <title>         - Show rich metadata
/my_history               - Show your search history
/my_prefs                 - Show or set preferences
/help                     - Show this message
"""

ADMIN_HELP = """
👑 Admin Commands
/add_channel <link|id>     - Add a channel
/remove_channel <link|id>  - Remove a channel
/list_channels             - List channels
/channel_stats             - Counts per channel
/rescan_channel <link|id> [limit] - Rescan channel history (limit default 200)
/toggle_indexing           - Toggle auto-indexing on/off
/promote <user_id>         - Promote to admin
/demote <user_id>          - Demote admin
/ban_user <user_id>        - Ban a user
/unban_user <user_id>      - Unban a user
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

    parts = []

    exact = await movies_col.find({"title": {"$regex": query, "$options": "i"}}).to_list(length=10)
    if exact:
        parts.append("**🔍 Exact Matches:**\n\n" + "\n\n".join(
            [f"🎬 {r.get('title')} ({r.get('year','N/A')}) [{r.get('quality','N/A')}] — `{r.get('channel_title')}` (msg {r.get('message_id')})" for r in exact]
        ))

    # fuzzy
    candidates = []
    cursor = movies_col.find({}, {"title": 1, "year": 1, "quality": 1, "channel_title": 1, "message_id": 1}).limit(800)
    async for r in cursor:
        title = r.get("title", "")
        score = fuzz.partial_ratio(query.lower(), title.lower())
        if score >= FUZZY_THRESHOLD:
            candidates.append((score, r))
    candidates = sorted(candidates, key=lambda x: x[0], reverse=True)[:10]
    if candidates:
        parts.append("**🤔 Similar (Fuzzy Matches):**\n\n" + "\n\n".join(
            [f"🎬 {r[1].get('title')} ({r[1].get('year','N/A')}) [{r[1].get('quality','N/A')}] — {r[0]}% — `{r[1].get('channel_title')}` (msg {r[1].get('message_id')})" for r in candidates]
        ))

    if not parts:
        return await message.reply_text("⚠️ No results found (exact or fuzzy).")
    await message.reply_text("\n\n".join(parts), disable_web_page_preview=True)

async def cmd_search_year(client, message: Message):
    parts = message.text.split()
    if len(parts) < 2:
        return await message.reply_text("Usage: /search_year <year>")

    try:
        year = int(parts[1])
    except ValueError:
        return await message.reply_text("Year must be a number")

    results = await movies_col.find({"year": year}).to_list(length=20)
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
    results = await movies_col.find({"quality": {"$regex": quality, "$options": "i"}}).to_list(length=20)
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

async def cmd_rescan_channel(client, message: Message):
    uid = message.from_user.id
    if not await is_admin(uid):
        return await message.reply_text("🚫 Admins only.")
    parts = message.text.split()
    if len(parts) < 2:
        return await message.reply_text("Usage: /rescan_channel <link|id|@username> [limit]")
    target = parts[1]
    limit = int(parts[2]) if len(parts) >= 3 else 50  # Reduced default limit

    try:
        chat = await resolve_chat_ref(target)
        await message.reply_text(f"🔄 Starting rescan of {getattr(chat,'title',chat.id)} (limit: {limit})...")

        count = 0
        indexed = 0

        # Process in smaller batches with timeout handling
        try:
            async for m in client.get_chat_history(chat.id, limit=limit):
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
    exact = await movies_col.find({"title": {"$regex": q, "$options": "i"}}).to_list(length=20)
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

        if not SESSION_STRING:
            print("❌ SESSION_STRING is required for user session")
            sys.exit(1)

        print("🔄 Starting user session with proper async context...")

        # Use async with Client() pattern as recommended by Kurigram docs
        async with Client(
            name="movie_bot_session",
            api_id=API_ID,
            api_hash=API_HASH,
            session_string=SESSION_STRING,
            workdir=".",
            sleep_threshold=60,  # Sleep threshold for flood wait
        ) as app:
            # Set global client reference for handlers
            global client
            client = app

            # Register handlers manually since decorators can't be used with async context
            app.add_handler(MessageHandler(on_message))
            app.add_handler(InlineQueryHandler(inline_handler))

            print("✅ User session started successfully")
            print("✅ MovieBot running with single user session!")
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
        raise e

if __name__ == "__main__":
    # Check Python version and warn about compatibility
    if sys.version_info >= (3, 13):
        print("⚠️  WARNING: Python 3.13+ detected!")
        print("⚠️  This version may have compatibility issues with Pyrogram.")
        print("⚠️  Recommended: Use Python 3.12.x for best compatibility.")
        print("⚠️  Attempting to run with compatibility patches...")

    run_bot()
