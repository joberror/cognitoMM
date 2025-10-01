# main.py
"""
Hybrid Telegram Movie Bot (full)
- User session (Kurigram) monitors channels and indexes uploads
- Bot session (Pyrogram) provides user commands, admin management, inline
- MongoDB Atlas (motor) for async storage
- Robust metadata parsing, exact + fuzzy search, channel management
"""

import os
import re
import asyncio
from datetime import datetime
from dotenv import load_dotenv
from fuzzywuzzy import fuzz
from motor.motor_asyncio import AsyncIOMotorClient
from pyrogram import Client as UserClient
from pyrogram import Client as BotClient, filters
from pyrogram.types import Message, InlineQuery, InlineQueryResultArticle, InputTextMessageContent

load_dotenv()

# -------------------------
# CONFIG / ENV
# -------------------------
API_ID = int(os.getenv("API_ID", "0"))
API_HASH = os.getenv("API_HASH", "")
SESSION_STRING = os.getenv("SESSION_STRING", "")   # Kurigram user session string
BOT_TOKEN = os.getenv("BOT_TOKEN", "")             # Bot token (recommended)
BOT_ID = int(os.getenv("BOT_ID", "0"))             # optional
MONGO_URI = os.getenv("MONGO_URI", "")
MONGO_DB = os.getenv("MONGO_DB", "moviebot")
ADMINS = [int(x) for x in os.getenv("ADMINS", "").split(",") if x.strip()]
LOG_CHANNEL = os.getenv("LOG_CHANNEL")             # optional - e.g. -1001234567890
FUZZY_THRESHOLD = int(os.getenv("FUZZY_THRESHOLD", "68"))
AUTO_INDEX_DEFAULT = os.getenv("AUTO_INDEXING", "True").lower() in ("1", "true", "yes")

# -------------------------
# DB (motor async)
# -------------------------
mongo = AsyncIOMotorClient(MONGO_URI)
db = mongo[MONGO_DB]
movies_col = db["movies"]
users_col = db["users"]
channels_col = db["channels"]
settings_col = db["settings"]
logs_col = db["logs"]

async def ensure_indexes():
    # Called at startup
    await movies_col.create_index([("title", 1)])
    await movies_col.create_index([("year", 1)])
    await movies_col.create_index([("quality", 1)])
    await movies_col.create_index([("type", 1)])
    await movies_col.create_index([("channel_id", 1), ("message_id", 1)], unique=False)
    await users_col.create_index([("user_id", 1)], unique=True)
    await channels_col.create_index([("channel_id", 1)], unique=True)

# -------------------------
# Clients
# -------------------------
user = None
bot = None

if SESSION_STRING:
    user = UserClient(name="user_session", api_id=API_ID, api_hash=API_HASH, session_string=SESSION_STRING)

if BOT_TOKEN:
    bot = BotClient("bot_session", api_id=API_ID, api_hash=API_HASH, bot_token=BOT_TOKEN)

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
        "ts": datetime.utcnow()
    }
    try:
        await logs_col.insert_one(doc)
    except Exception:
        pass
    if bot and LOG_CHANNEL:
        try:
            msg = f"Log: {action}\nBy: {by}\nTarget: {target}\nExtra: {extra or {}}"
            await bot.send_message(int(LOG_CHANNEL), msg)
        except Exception:
            pass

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
        # must be channel post
        if getattr(msg, "chat", None) is None:
            return
        if getattr(msg.chat, "type", None) != "channel":
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
            "upload_date": datetime.utcfromtimestamp(msg.date.timestamp()) if getattr(msg, "date", None) else datetime.utcnow(),
            "channel_id": msg.chat.id,
            "channel_title": getattr(msg.chat, "title", None),
            "message_id": msg.id,
            "caption": caption,
            "indexed_at": datetime.utcnow()
        }

        await movies_col.insert_one(entry)
        await log_action("indexed_message", extra={"title": entry["title"], "channel_id": entry["channel_id"], "message_id": entry["message_id"]})
        print(f"[INDEXED] {entry['title']} from {entry['channel_title']}")
    except Exception as e:
        await log_action("index_error", extra={"error": str(e)})
        print("Index error:", e)

# -------------------------
# user session monitoring
# -------------------------
if user:
    @user.on_message()
    async def _on_user_msg(client, message):
        # auto-indexing controlled via settings_col
        s = await settings_col.find_one({"k": "auto_indexing"})
        auto_index = s["v"] if s and "v" in s else AUTO_INDEX_DEFAULT
        if not auto_index:
            return
        await index_message(message)

# -------------------------
# Bot middleware: block banned users
# -------------------------
if bot:
    @bot.on_message(filters.command("start"))
    async def _block_banned(client, message: Message):
        uid = message.from_user.id
        if await is_banned(uid):
            await message.reply_text("🚫 You are banned from using this bot.")
            return

# -------------------------
# Bot commands
# -------------------------
if bot:
    # help/start
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
/add_channel <link|id>     - Add a channel (user session must have access)
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

    @bot.on_message(filters.command("help"))
    async def help_cmd(client, message: Message):
        uid = message.from_user.id
        text = USER_HELP
        if await is_admin(uid):
            text += "\n" + ADMIN_HELP
        await message.reply_text(text)

    @bot.on_message(filters.command("start"))
    async def start_cmd(client, message: Message):
        await users_col.update_one({"user_id": message.from_user.id}, {"$set": {"last_seen": datetime.utcnow()}}, upsert=True)
        await message.reply_text("👋 Welcome! Use /help to see commands.")

    # add_channel / remove / list
    async def resolve_chat_ref(ref: str):
        """Use user client to resolve a channel reference (id, t.me/slug, @username)."""
        if not user:
            raise RuntimeError("User session required to resolve channels")
        r = ref.strip()
        if r.startswith("t.me/"):
            r = r.split("t.me/")[-1]
        # try numeric
        try:
            cid = int(r)
            return await user.get_chat(cid)
        except Exception:
            pass
        # try username or slug
        return await user.get_chat(r)

    @bot.on_message(filters.command("add_channel"))
    async def add_channel_cmd(client, message: Message):
        uid = message.from_user.id
        if not await is_admin(uid):
            return await message.reply_text("🚫 Admins only.")
        if len(message.command) < 2:
            return await message.reply_text("Usage: /add_channel <link|id|@username>")
        target = message.command[1]
        try:
            chat = await resolve_chat_ref(target)
            doc = {"channel_id": chat.id, "channel_title": getattr(chat, "title", None), "added_by": uid, "added_at": datetime.utcnow(), "enabled": True}
            await channels_col.update_one({"channel_id": chat.id}, {"$set": doc}, upsert=True)
            await log_action("add_channel", by=uid, target=chat.id, extra={"title": doc["channel_title"]})
            await message.reply_text(f"✅ Channel added: {doc['channel_title']} ({chat.id})")
        except Exception as e:
            await message.reply_text(f"❌ Could not resolve channel: {e}")

    @bot.on_message(filters.command("remove_channel"))
    async def remove_channel_cmd(client, message: Message):
        uid = message.from_user.id
        if not await is_admin(uid):
            return await message.reply_text("🚫 Admins only.")
        if len(message.command) < 2:
            return await message.reply_text("Usage: /remove_channel <link|id|@username>")
        target = message.command[1]
        try:
            chat = await resolve_chat_ref(target)
            await channels_col.delete_one({"channel_id": chat.id})
            await log_action("remove_channel", by=uid, target=chat.id)
            await message.reply_text(f"✅ Channel removed: {getattr(chat,'title', chat.id)} ({chat.id})")
        except Exception as e:
            await message.reply_text(f"❌ Could not remove channel: {e}")

    @bot.on_message(filters.command("list_channels"))
    async def list_channels_cmd(client, message: Message):
        uid = message.from_user.id
        if not await is_admin(uid):
            return await message.reply_text("🚫 Admins only.")
        docs = channels_col.find({})
        items = []
        async for d in docs:
            items.append(f"{d.get('channel_title','?')} — `{d.get('channel_id')}` — enabled={d.get('enabled', True)}")
        await message.reply_text("\n".join(items) or "No channels configured.")

    @bot.on_message(filters.command("channel_stats"))
    async def channel_stats_cmd(client, message: Message):
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

    @bot.on_message(filters.command("rescan_channel"))
    async def rescan_channel_cmd(client, message: Message):
        uid = message.from_user.id
        if not await is_admin(uid):
            return await message.reply_text("🚫 Admins only.")
        if not user:
            return await message.reply_text("User session required for rescanning.")
        if len(message.command) < 2:
            return await message.reply_text("Usage: /rescan_channel <link|id|@username> [limit]")
        target = message.command[1]
        limit = int(message.command[2]) if len(message.command) >= 3 else 200
        try:
            chat = await resolve_chat_ref(target)
            count = 0
            async for m in user.iter_history(chat.id, limit=limit):
                await index_message(m)
                count += 1
            await message.reply_text(f"✅ Rescan complete. Scanned {count} messages from {getattr(chat,'title',chat.id)}")
            await log_action("rescan_channel", by=uid, target=chat.id, extra={"scanned": count})
        except Exception as e:
            await message.reply_text(f"❌ Rescan failed: {e}")

    @bot.on_message(filters.command("toggle_indexing"))
    async def toggle_indexing_cmd(client, message: Message):
        uid = message.from_user.id
        if not await is_admin(uid):
            return await message.reply_text("🚫 Admins only.")
        doc = await settings_col.find_one({"k": "auto_indexing"})
        current = doc["v"] if doc else AUTO_INDEX_DEFAULT
        new = not current
        await settings_col.update_one({"k": "auto_indexing"}, {"$set": {"v": new}}, upsert=True)
        await message.reply_text(f"Auto-indexing set to {new}")
        await log_action("toggle_indexing", by=uid, extra={"new": new})

    # promote/demote/ban/unban
    @bot.on_message(filters.command("promote"))
    async def promote_cmd(client, message: Message):
        uid = message.from_user.id
        if not await is_admin(uid):
            return await message.reply_text("🚫 Admins only.")
        if len(message.command) < 2:
            return await message.reply_text("Usage: /promote <user_id>")
        try:
            target = int(message.command[1])
            await users_col.update_one({"user_id": target}, {"$set": {"role": "admin"}}, upsert=True)
            await message.reply_text(f"✅ {target} promoted to admin.")
            await log_action("promote", by=uid, target=target)
        except Exception:
            await message.reply_text("Invalid user id.")

    @bot.on_message(filters.command("demote"))
    async def demote_cmd(client, message: Message):
        uid = message.from_user.id
        if not await is_admin(uid):
            return await message.reply_text("🚫 Admins only.")
        if len(message.command) < 2:
            return await message.reply_text("Usage: /demote <user_id>")
        try:
            target = int(message.command[1])
            await users_col.update_one({"user_id": target}, {"$set": {"role": "user"}}, upsert=True)
            await message.reply_text(f"✅ {target} demoted to user.")
            await log_action("demote", by=uid, target=target)
        except Exception:
            await message.reply_text("Invalid user id.")

    @bot.on_message(filters.command("ban_user"))
    async def ban_cmd(client, message: Message):
        uid = message.from_user.id
        if not await is_admin(uid):
            return await message.reply_text("🚫 Admins only.")
        if len(message.command) < 2:
            return await message.reply_text("Usage: /ban_user <user_id>")
        try:
            target = int(message.command[1])
            await users_col.update_one({"user_id": target}, {"$set": {"role": "banned"}}, upsert=True)
            await message.reply_text(f"🚫 {target} has been banned.")
            await log_action("ban_user", by=uid, target=target)
        except Exception:
            await message.reply_text("Invalid user id.")

    @bot.on_message(filters.command("unban_user"))
    async def unban_cmd(client, message: Message):
        uid = message.from_user.id
        if not await is_admin(uid):
            return await message.reply_text("🚫 Admins only.")
        if len(message.command) < 2:
            return await message.reply_text("Usage: /unban_user <user_id>")
        try:
            target = int(message.command[1])
            await users_col.update_one({"user_id": target}, {"$set": {"role": "user"}}, upsert=True)
            await message.reply_text(f"✅ {target} has been unbanned.")
            await log_action("unban_user", by=uid, target=target)
        except Exception:
            await message.reply_text("Invalid user id.")

    # search hybrid (exact + fuzzy)
    @bot.on_message(filters.command("search"))
    async def search_hybrid_cmd(client, message: Message):
        uid = message.from_user.id
        query = " ".join(message.command[1:]).strip()
        if not query:
            return await message.reply_text("Usage: /search <title>")

        # record search history
        await users_col.update_one({"user_id": uid}, {"$push": {"search_history": {"q": query, "ts": datetime.utcnow()}}}, upsert=True)

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

    # file_info & metadata
    @bot.on_message(filters.command("file_info"))
    async def file_info_cmd(client, message: Message):
        if len(message.command) < 2:
            return await message.reply_text("Usage: /file_info <message_id>")
        try:
            msg_id = int(message.command[1])
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

    @bot.on_message(filters.command("metadata"))
    async def metadata_cmd(client, message: Message):
        query = " ".join(message.command[1:]).strip()
        if not query:
            return await message.reply_text("Usage: /metadata <title>")
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

    # my_history & prefs
    @bot.on_message(filters.command("my_history"))
    async def my_history_cmd(client, message: Message):
        uid = message.from_user.id
        doc = await users_col.find_one({"user_id": uid})
        history = doc.get("search_history", []) if doc else []
        if not history:
            return await message.reply_text("You have no search history.")
        text = "\n".join([f"{h['ts'].isoformat()} — {h['q']}" for h in history[-20:]])
        await message.reply_text(text)

    @bot.on_message(filters.command("my_prefs"))
    async def my_prefs_cmd(client, message: Message):
        uid = message.from_user.id
        if len(message.command) == 1:
            doc = await users_col.find_one({"user_id": uid})
            prefs = doc.get("preferences", {}) if doc else {}
            await message.reply_text(f"Your preferences: {prefs}")
        else:
            if len(message.command) < 3:
                return await message.reply_text("Usage: /my_prefs <key> <value>")
            key = message.command[1]
            value = " ".join(message.command[2:])
            await users_col.update_one({"user_id": uid}, {"$set": {f"preferences.{key}": value}}, upsert=True)
            await message.reply_text(f"Set preference `{key}` = `{value}`")

    # inline query support
    @bot.on_inline_query()
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
# Startup
# -------------------------
async def main():
    await ensure_indexes()
    started = []
    if user:
        await user.start()
        print("User session started.")
        started.append(user)
    if bot:
        await bot.start()
        print("Bot session started.")
        started.append(bot)
    print("✅ MovieBot hybrid running.")
    try:
        await asyncio.Event().wait()
    finally:
        for c in started:
            await c.stop()

if __name__ == "__main__":
    asyncio.run(main())
