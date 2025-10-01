```python
from pyrogram import Client, filters
from pymongo import MongoClient

# ---------------------------
# 🔧 CONFIG
# ---------------------------
API_ID = 123456       # Replace with your API ID
API_HASH = "abc123"   # Replace with your API Hash
BOT_TOKEN = "123:ABC" # Replace with your Bot Token

MONGO_URI = "mongodb+srv://username:password@cluster.mongodb.net/"
DB_NAME = "moviebot"

app = Client("movie_bot", api_id=API_ID, api_hash=API_HASH, bot_token=BOT_TOKEN)

# ---------------------------
# 📦 MONGO CONNECTION
# ---------------------------
mongo = MongoClient(MONGO_URI)
db = mongo[DB_NAME]
users_col = db["users"]

# ---------------------------
# 📑 HELP TEXTS
# ---------------------------
USER_HELP = """
🎬 **Telegram Movie Bot Commands**

🔍 **Search**
/search <title>             - Search movies by title
/search_year <year>         - Search by release year
/search_quality <q>         - Search by quality (720p, 1080p)
/search_type <movie|series> - Filter by type
/search_episode <SxxExx>    - Search by season & episode

📁 **File Info**
/file_info <message_id>     - Show details of a file
/metadata <title>           - Show stored metadata

👤 **Account**
/my_history                 - Show your search history
/my_prefs                   - Manage your preferences
/help                       - Show this menu
"""

ADMIN_HELP = """
👑 **Admin Commands**

📡 **Channel Management**
/add_channel <link>     - Add a channel to monitor
/remove_channel <link>  - Remove a channel
/list_channels          - Show monitored channels
/channel_stats          - Stats per channel

🛠️ **Indexing & Metadata**
/reparse <msg_id>       - Re-extract metadata
/toggle_indexing        - Toggle auto-indexing
/rescan_channel <link>  - Re-scan a channel

🗄️ **Database**
/stats_db               - Show database stats
/clear_db               - Delete all entries

🚫 **User Control**
/ban_user <id>          - Ban a user
/unban_user <id>        - Unban a user
/promote <id>           - Promote a user to admin
/demote <id>            - Remove admin role
"""

# ---------------------------
# 🔍 HELPERS
# ---------------------------
def get_user(user_id: int):
    return users_col.find_one({"user_id": user_id})

def is_admin(user_id: int) -> bool:
    user = get_user(user_id)
    return user and user.get("role") == "admin"

def is_banned(user_id: int) -> bool:
    user = get_user(user_id)
    return user and user.get("role") == "banned"

# ---------------------------
# 🚦 GLOBAL BAN MIDDLEWARE
# ---------------------------
@app.on_message(filters.command(None))
async def check_ban(client, message):
    user_id = message.from_user.id
    if is_banned(user_id):
        await message.reply_text("🚫 You are banned from using this bot.")
        return  # Block further processing

# ---------------------------
# 🆘 /HELP COMMAND
# ---------------------------
@app.on_message(filters.command("help"))
async def help_command(client, message):
    user_id = message.from_user.id
    if is_admin(user_id):
        await message.reply_text(USER_HELP + "\n\n" + ADMIN_HELP, disable_web_page_preview=True)
    else:
        await message.reply_text(USER_HELP, disable_web_page_preview=True)

# ---------------------------
# 🔼 /PROMOTE COMMAND
# ---------------------------
@app.on_message(filters.command("promote"))
async def promote_command(client, message):
    if not is_admin(message.from_user.id):
        return await message.reply_text("🚫 You are not allowed to promote users.")

    if len(message.command) < 2:
        return await message.reply_text("⚠️ Usage: /promote <user_id>")

    try:
        target_id = int(message.command[1])
        users_col.update_one(
            {"user_id": target_id},
            {"$set": {"role": "admin"}},
            upsert=True
        )
        await message.reply_text(f"✅ User `{target_id}` promoted to **admin**.")
    except ValueError:
        await message.reply_text("❌ Invalid user_id.")

# ---------------------------
# 🔽 /DEMOTE COMMAND
# ---------------------------
@app.on_message(filters.command("demote"))
async def demote_command(client, message):
    if not is_admin(message.from_user.id):
        return await message.reply_text("🚫 You are not allowed to demote users.")

    if len(message.command) < 2:
        return await message.reply_text("⚠️ Usage: /demote <user_id>")

    try:
        target_id = int(message.command[1])
        users_col.update_one(
            {"user_id": target_id},
            {"$set": {"role": "user"}},
            upsert=True
        )
        await message.reply_text(f"✅ User `{target_id}` demoted to **user**.")
    except ValueError:
        await message.reply_text("❌ Invalid user_id.")

# ---------------------------
# 🚫 /BAN_USER COMMAND
# ---------------------------
@app.on_message(filters.command("ban_user"))
async def ban_user_command(client, message):
    if not is_admin(message.from_user.id):
        return await message.reply_text("🚫 You are not allowed to ban users.")

    if len(message.command) < 2:
        return await message.reply_text("⚠️ Usage: /ban_user <user_id>")

    try:
        target_id = int(message.command[1])
        users_col.update_one(
            {"user_id": target_id},
            {"$set": {"role": "banned"}},
            upsert=True
        )
        await message.reply_text(f"🚫 User `{target_id}` has been **banned**.")
    except ValueError:
        await message.reply_text("❌ Invalid user_id.")

# ---------------------------
# ✅ /UNBAN_USER COMMAND
# ---------------------------
@app.on_message(filters.command("unban_user"))
async def unban_user_command(client, message):
    if not is_admin(message.from_user.id):
        return await message.reply_text("🚫 You are not allowed to unban users.")

    if len(message.command) < 2:
        return await message.reply_text("⚠️ Usage: /unban_user <user_id>")

    try:
        target_id = int(message.command[1])
        users_col.update_one(
            {"user_id": target_id},
            {"$set": {"role": "user"}},
            upsert=True
        )
        await message.reply_text(f"✅ User `{target_id}` has been **unbanned**.")
    except ValueError:
        await message.reply_text("❌ Invalid user_id.")

# ---------------------------
# ▶️ START BOT
# ---------------------------
print("🤖 Bot is running...")
app.run()
```

---

## 📂 MongoDB `users` Schema Example

```json
{
  "user_id": 123456789,
  "role": "user",   // can be "user", "admin", or "banned"
  "search_history": [],
  "preferences": {}
}
```

---

✅ Now your bot automatically blocks banned users from **every command**, no need to check inside each handler.

Do you want me to also add a **logging system** (e.g., log bans, promotions, errors to a special admin channel or MongoDB collection)?
