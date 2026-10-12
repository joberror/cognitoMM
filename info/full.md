```python
"""
🎬 Hybrid Telegram Movie Bot
-----------------------------------
- User session (Kurigram): monitors channels, extracts metadata
- Bot session (Pyrogram): handles user commands (/search, /help, etc.)
- MongoDB Atlas for storage
- .env for configuration
"""

import os
import asyncio
from datetime import datetime
from dotenv import load_dotenv
from kurigram import Client as UserClient
from pyrogram import Client as BotClient, filters
from pymongo import MongoClient, ASCENDING

# Load .env
load_dotenv()

# ------------------ ENV CONFIG ------------------
API_ID = int(os.getenv("API_ID"))
API_HASH = os.getenv("API_HASH")
SESSION_STRING = os.getenv("SESSION_STRING")

BOT_TOKEN = os.getenv("BOT_TOKEN")
BOT_ID = int(os.getenv("BOT_ID", 0))

MONGO_URI = os.getenv("MONGO_URI")
MONGO_DB = os.getenv("MONGO_DB", "moviebot")

ADMINS = [int(x) for x in os.getenv("ADMINS", "").split(",") if x]

# ------------------ DB CONFIG ------------------
mongo = MongoClient(MONGO_URI)
db = mongo[MONGO_DB]
movies_col = db["movies"]
users_col = db["users"]
channels_col = db["channels"]

# Index for faster searches
movies_col.create_index([("title", ASCENDING)])
movies_col.create_index([("year", ASCENDING)])
movies_col.create_index([("quality", ASCENDING)])
movies_col.create_index([("type", ASCENDING)])

# ------------------ TELEGRAM CLIENTS ------------------
user = UserClient(
    name="user_session",
    api_id=API_ID,
    api_hash=API_HASH,
    session_string=SESSION_STRING,
)

bot = BotClient(
    "bot_session",
    bot_token=BOT_TOKEN,
)

# ------------------ USER COMMANDS ------------------
USER_HELP = """
🎬 **Movie Bot Commands**

🔍 **Search**
/search <title>          - Search movies by title
/search_type <movie|series> - Filter by type
/search_episode <SxxExx> - Search by season & episode

📁 **File Info**
/metadata <title>        - Show stored metadata

👤 **Account**
/my_history              - Show your search history
/my_prefs                - Manage your preferences
/help                    - Show this menu
"""

ADMIN_HELP = """
👑 **Admin Commands**

📡 **Channel Management**
/add_channel <link>      - Add a channel to monitor
/remove_channel <link>   - Remove a channel
/list_channels           - Show monitored channels
/channel_stats           - Stats per channel

🛠️ **Indexing & Metadata**
/reparse <msg_id>        - Re-extract metadata
/toggle_indexing         - Toggle auto-indexing
/rescan_channel <link>   - Re-scan a channel

🗄️ **Database**
/stats_db                - Show database stats
/clear_db                - Delete all entries

👥 **Users**
/user                    - Unified user manager (filters, batch actions)
/ban_user <id>           - Ban a user (hidden alias of /user)
/unban_user <id>         - Unban a user (hidden alias)
/promote <id>            - Promote to admin (hidden alias, Super Admin only)
/demote <id>             - Demote from admin (hidden alias, Super Admin only)
"""

@bot.on_message(filters.command("help"))
async def help_command(client, message):
    uid = message.from_user.id
    base_text = USER_HELP
    if uid in ADMINS or users_col.find_one({"_id": uid, "role": "admin"}):
        base_text += "\n\n" + ADMIN_HELP
    await message.reply_text(base_text, disable_web_page_preview=True)

@bot.on_message(filters.command("start"))
async def start(client, message):
    await message.reply_text("👋 Welcome to MovieBot! Use /help to see commands.")

# ------------------ SEARCH COMMANDS ------------------
@bot.on_message(filters.command("search"))
async def search_title(client, message):
    query = " ".join(message.command[1:])
    if not query:
        return await message.reply_text("❌ Usage: /search <title>")
    results = movies_col.find({"title": {"$regex": query, "$options": "i"}}).limit(10)
    text = "\n\n".join([f"🎬 {r['title']} ({r.get('upload_date').strftime('%Y') if r.get('upload_date') else ''})\n📂 File size: {r.get('file_size')} bytes\n🔗 Channel: {r.get('channel_title')}" for r in results])
    await message.reply_text(text or "No results found.")

# REMOVED COMMANDS: search_year, search_quality
# These commands were deemed unoptimized and unnecessary
# @bot.on_message(filters.command("search_year"))
# async def search_year(client, message):
#     if len(message.command) < 2:
#         return await message.reply_text("❌ Usage: /search_year <year>")
#     year = int(message.command[1])
#     results = movies_col.find({"year": year}).limit(10)
#     text = "\n\n".join([f"🎬 {r['title']} ({year})" for r in results])
#     await message.reply_text(text or "No results found.")

# @bot.on_message(filters.command("search_quality"))
# async def search_quality(client, message):
#     if len(message.command) < 2:
#         return await message.reply_text("❌ Usage: /search_quality <quality>")
#     quality = message.command[1]
#     results = movies_col.find({"quality": {"$regex": quality, "$options": "i"}}).limit(10)
#     text = "\n\n".join([f"🎬 {r['title']} [{quality}]" for r in results])
#     await message.reply_text(text or "No results found.")

@bot.on_message(filters.command("search_type"))
async def search_type(client, message):
    if len(message.command) < 2:
        return await message.reply_text("❌ Usage: /search_type <movie|series>")
    type_filter = message.command[1].capitalize()
    results = movies_col.find({"type": type_filter}).limit(10)
    text = "\n\n".join([f"🎬 {r['title']} ({type_filter})" for r in results])
    await message.reply_text(text or "No results found.")

# ------------------ USER SESSION MONITORING ------------------
@user.on_message()
async def monitor_channels(client, message):
    """Monitors channels for new movie uploads"""
    if message.chat.type != "channel":
        return

    if not message.video and not message.document:
        return

    file_size = None
    if message.video:
        file_size = message.video.file_size
    elif message.document and "video" in message.document.mime_type:
        file_size = message.document.file_size

    entry = {
        "title": message.caption or "Unknown",
        "file_size": file_size,
        "upload_date": datetime.utcfromtimestamp(message.date.timestamp()),
        "year": message.date.year,
        "channel_id": message.chat.id,
        "channel_title": message.chat.title,
        "message_id": message.id,
        "caption": message.caption,
        "quality": "Unknown",
        "type": "Movie",
    }

    # Avoid duplicates
    if not movies_col.find_one({"message_id": message.id, "channel_id": message.chat.id}):
        movies_col.insert_one(entry)
        print(f"[INDEXED] {entry['title']} from {entry['channel_title']}")
    else:
        print(f"[SKIPPED DUPLICATE] {entry['title']}")

# ------------------ RUN BOTH CLIENTS ------------------
async def main():
    await user.start()
    await bot.start()
    print("✅ MovieBot is running (Hybrid Mode).")
    await asyncio.Event().wait()  # Keep alive

if __name__ == "__main__":
    asyncio.run(main())
```
```python
# ... [imports + config stay the same as in your previous block] ...

# ------------------ EXTRA FILE INFO COMMANDS ------------------
# REMOVED COMMAND: file_info
# This command was deemed unoptimized and unnecessary
# @bot.on_message(filters.command("file_info"))
# async def file_info(client, message):
#     """
#     Usage: /file_info <message_id>
#     Returns details of a specific indexed movie file
#     """
#     if len(message.command) < 2:
#         return await message.reply_text("❌ Usage: /file_info <message_id>")
#     try:
#         msg_id = int(message.command[1])
#     except ValueError:
#         return await message.reply_text("❌ Message ID must be a number")
#
#     entry = movies_col.find_one({"message_id": msg_id})
#     if not entry:
#         return await message.reply_text("⚠️ No file found with that ID.")
#
#     text = f"""
# 🎬 **{entry.get('title', 'Unknown')}**
# 📅 Year: {entry.get('upload_date').strftime('%Y') if entry.get('upload_date') else 'N/A'}
# 📂 File Size: {entry.get('file_size', 'N/A')} bytes
# 🎚️ Quality: {entry.get('quality', 'Unknown')}
# 📁 Type: {entry.get('type', 'Unknown')}
# 🔗 Channel: {entry.get('channel_title', 'Unknown')}
# 🆔 Message ID: {entry.get('message_id')}
# 📝 Caption: {entry.get('caption', '')}
# """
#     await message.reply_text(text, disable_web_page_preview=True)


@bot.on_message(filters.command("metadata"))
async def metadata(client, message):
    """
    Usage: /metadata <title>
    Search movie by title and return stored metadata
    """
    query = " ".join(message.command[1:])
    if not query:
        return await message.reply_text("❌ Usage: /metadata <title>")

    entry = movies_col.find_one({"title": {"$regex": query, "$options": "i"}})
    if not entry:
        return await message.reply_text("⚠️ No metadata found for that title.")

    text = f"""
🎬 **{entry.get('title')}**
📅 Year: {entry.get('year', 'Unknown')}
🧵 Rip: {entry.get('rip', 'N/A')}
🌐 Source: {entry.get('source', 'N/A')}
🎚️ Quality: {entry.get('quality', 'N/A')}
📁 Extension: {entry.get('extension', 'N/A')}
🖥️ Resolution: {entry.get('resolution', 'N/A')}
🔊 Audio: {entry.get('audio', 'N/A')}
📺 Type: {entry.get('type', 'N/A')}
📺 Season: {entry.get('season', 'N/A')}
📺 Episode: {entry.get('episode', 'N/A')}
📂 File Size: {entry.get('file_size', 'N/A')} bytes
📅 Uploaded: {entry.get('upload_date', 'N/A')}
🔗 Channel: {entry.get('channel_title', 'N/A')}
🆔 Message ID: {entry.get('message_id')}
📝 Caption: {entry.get('caption', '')}
"""
    await message.reply_text(text, disable_web_page_preview=True)

# ------------------ NOTE ------------------
"""
👉 /metadata is useful when searching by title (user-friendly).
"""

# ... [monitor_channels + main() same as before] ...
```
```python
# ... [imports + config remain unchanged] ...

import re
from fuzzywuzzy import fuzz

# ------------------ HELPER: METADATA PARSER ------------------
def parse_metadata(caption: str) -> dict:
    """
    Parse basic movie metadata from caption text using regex patterns.
    """
    if not caption:
        return {}

    metadata = {}
    title_match = re.search(r"^(.*?)(?:19\d{2}|20\d{2}|WEBRip|BluRay|HDRip|DVDRip|HDTS|CAM)", caption, re.IGNORECASE)
    if title_match:
        metadata["title"] = title_match.group(1).strip()

    year_match = re.search(r"(19\d{2}|20\d{2})", caption)
    if year_match:
        metadata["year"] = int(year_match.group(1))

    rip_match = re.search(r"(WEBRip|BluRay|HDRip|DVDRip|HDTS|CAM)", caption, re.IGNORECASE)
    if rip_match:
        metadata["rip"] = rip_match.group(1)

    source_match = re.search(r"(Netflix|Amazon|Disney\+|HBO|Hulu|Apple TV\+)", caption, re.IGNORECASE)
    if source_match:
        metadata["source"] = source_match.group(1)

    quality_match = re.search(r"(480p|720p|1080p|2160p|4K)", caption, re.IGNORECASE)
    if quality_match:
        metadata["quality"] = quality_match.group(1)

    ext_match = re.search(r"\.(mkv|mp4|avi|mov)", caption, re.IGNORECASE)
    if ext_match:
        metadata["extension"] = "." + ext_match.group(1)

    res_match = re.search(r"(\d{3,4}x\d{3,4})", caption)
    if res_match:
        metadata["resolution"] = res_match.group(1)

    audio_match = re.search(r"(AAC|MP3|DTS|AC3|FLAC|Dolby Digital)", caption, re.IGNORECASE)
    if audio_match:
        metadata["audio"] = audio_match.group(1)

    if re.search(r"S\d{1,2}E\d{1,2}", caption, re.IGNORECASE):
        metadata["type"] = "Series"
        season_match = re.search(r"S(\d{1,2})", caption, re.IGNORECASE)
        episode_match = re.search(r"E(\d{1,2})", caption, re.IGNORECASE)
        if season_match:
            metadata["season"] = int(season_match.group(1))
        if episode_match:
            metadata["episode"] = int(episode_match.group(1))
    else:
        metadata["type"] = "Movie"

    return metadata

# ------------------ USER SESSION MONITORING ------------------
@user.on_message()
async def monitor_channels(client, message):
    """Monitors channels for new movie uploads with metadata parsing"""
    if message.chat.type != "channel":
        return
    if not message.video and not message.document:
        return

    file_size = None
    if message.video:
        file_size = message.video.file_size
    elif message.document and "video" in message.document.mime_type:
        file_size = message.document.file_size

    caption = message.caption or ""
    parsed = parse_metadata(caption)

    entry = {
        "title": parsed.get("title", caption or "Unknown"),
        "year": parsed.get("year"),
        "rip": parsed.get("rip"),
        "source": parsed.get("source"),
        "quality": parsed.get("quality"),
        "extension": parsed.get("extension"),
        "resolution": parsed.get("resolution"),
        "audio": parsed.get("audio"),
        "type": parsed.get("type", "Movie"),
        "season": parsed.get("season"),
        "episode": parsed.get("episode"),
        "file_size": file_size,
        "upload_date": datetime.utcfromtimestamp(message.date.timestamp()),
        "channel_id": message.chat.id,
        "channel_title": message.chat.title,
        "message_id": message.id,
        "caption": caption,
    }

    if not movies_col.find_one({"message_id": message.id, "channel_id": message.chat.id}):
        movies_col.insert_one(entry)
        print(f"[INDEXED] {entry['title']} ({entry.get('quality', 'N/A')}) from {entry['channel_title']}")
    else:
        print(f"[SKIPPED DUPLICATE] {entry['title']}")

# ------------------ HYBRID SEARCH ------------------
@bot.on_message(filters.command("search"))
async def search_hybrid(client, message):
    """
    Usage: /search <title>
    Hybrid approach:
      1. Show exact/regex matches first (if any).
      2. Then show fuzzy matches ranked by similarity.
    """
    query = " ".join(message.command[1:])
    if not query:
        return await message.reply_text("❌ Usage: /search <title>")

    response_parts = []

    # -------- Exact/Regex Match --------
    exact_results = list(
        movies_col.find({"title": {"$regex": query, "$options": "i"}}).limit(10)
    )
    if exact_results:
        exact_text = "**🔍 Exact Matches:**\n\n"
        exact_text += "\n\n".join(
            [f"🎬 {r.get('title')} ({r.get('year', 'N/A')}) [{r.get('quality', 'N/A')}]"
             for r in exact_results]
        )
        response_parts.append(exact_text)

    # -------- Fuzzy Match --------
    candidates = []
    for movie in movies_col.find({}, {"title": 1, "year": 1, "quality": 1}).limit(300):
        title = movie.get("title", "")
        score = fuzz.partial_ratio(query.lower(), title.lower())
        if score >= 70:
            candidates.append((score, movie))

    candidates = sorted(candidates, key=lambda x: x[0], reverse=True)[:10]
    if candidates:
        fuzzy_text = "**🤔 Similar (Fuzzy Matches):**\n\n"
        fuzzy_text += "\n\n".join(
            [f"🎬 {r[1].get('title')} ({r[1].get('year', 'N/A')}) [{r[1].get('quality', 'N/A')}] - {r[0]}%"
             for r in candidates]
        )
        response_parts.append(fuzzy_text)

    if not response_parts:
        return await message.reply_text("⚠️ No results found (exact or fuzzy).")

    # Combine both exact + fuzzy in one response
    final_text = "\n\n".join(response_parts)
    await message.reply_text(final_text, disable_web_page_preview=True)
```
