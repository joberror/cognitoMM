"""
User Management and Access Control Module

This module handles user authentication, authorization, and access control
for the MovieBot. It includes functions for checking user roles,
banning/unbanning users, and verifying terms acceptance.
"""

import asyncio
from datetime import datetime, timezone
from pyrogram.types import Message
from pyrogram.enums import ChatType

from .config import ADMINS
from .database import users_col, logs_col, channels_col


async def get_user_doc(user_id: int):
    """Get user document from database"""
    return await users_col.find_one({"user_id": user_id})


async def is_admin(user_id: int):
    """Check if user is an admin"""
    if user_id in ADMINS:
        return True
    doc = await get_user_doc(user_id)
    return bool(doc and doc.get("role") == "admin")


async def is_banned(user_id: int):
    """Check if user is banned"""
    doc = await get_user_doc(user_id)
    return bool(doc and doc.get("role") == "banned")


async def has_accepted_terms(user_id: int):
    """Check if user has accepted terms and privacy policy"""
    doc = await get_user_doc(user_id)
    return bool(doc and doc.get("terms_accepted", False))


async def load_terms_and_privacy():
    """Load terms and privacy policy from markdown file"""
    try:
        with open('TERMS_AND_PRIVACY.md', 'r', encoding='utf-8') as f:
            content = f.read()
        return content
    except Exception as e:
        print(f"❌ Failed to load terms and privacy: {e}")
        return None


async def log_action(action: str, by: int = None, target: int = None, extra: dict = None):
    """Log actions to database and optionally to log channel"""
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
    
    # Import client and LOG_CHANNEL here to avoid circular imports
    from .config import client, LOG_CHANNEL
    if client and LOG_CHANNEL:
        try:
            msg = f"Log: {action}\nBy: {by}\nTarget: {target}\nExtra: {extra or {}}"
            await client.send_message(int(LOG_CHANNEL), msg)
        except Exception:
            pass


# ------------------------------------------------------------------ #
#  Watchlist (notify users when a watched title gets indexed)          #
# ------------------------------------------------------------------ #


def _watch_key(title: str) -> str:
    """Normalized lowercase key used for watchlist matching."""
    return (title or "").strip().lower()


async def add_to_watchlist(user_id: int, title: str, year=None, type_=None) -> bool:
    """Add a title to a user's watchlist (idempotent). Returns True if added."""
    if not title or not str(title).strip():
        return False
    key = _watch_key(title)
    entry = {
        "title": str(title).strip(),
        "title_key": key,
        "year": year,
        "type": type_ or "Movie",
        "added_at": datetime.now(timezone.utc),
    }
    try:
        # Ensure the user document exists FIRST (upsert on user_id alone). A
        # $ne-filtered upsert would insert a SECOND user document whenever the
        # title is already watched (filter matches nothing -> upsert inserts).
        await users_col.update_one(
            {"user_id": user_id},
            {"$setOnInsert": {"user_id": user_id, "watchlist": []}},
            upsert=True,
        )
        result = await users_col.update_one(
            {"user_id": user_id, "watchlist.title_key": {"$ne": key}},
            {"$push": {"watchlist": entry}},
        )
        return bool(result.modified_count)
    except Exception as e:
        print(f"⚠️ add_to_watchlist failed for {user_id}: {e}")
        return False


async def remove_from_watchlist(user_id: int, title: str) -> bool:
    """Remove a title from a user's watchlist. Returns True if removed."""
    key = _watch_key(title)
    try:
        result = await users_col.update_one(
            {"user_id": user_id},
            {"$pull": {"watchlist": {"title_key": key}}},
        )
        return bool(result.modified_count)
    except Exception as e:
        print(f"⚠️ remove_from_watchlist failed for {user_id}: {e}")
        return False


async def get_watchlist(user_id: int):
    """Return the user's watchlist (list of entries) or []."""
    try:
        doc = await users_col.find_one({"user_id": user_id}, {"watchlist": 1})
    except Exception as e:
        print(f"⚠️ get_watchlist failed for {user_id}: {e}")
        return []
    return (doc or {}).get("watchlist") or []


async def notify_watchlist(entry: dict) -> int:
    """DM every user watching a title when a new copy is indexed.

    Matching is by normalized title (exact, case-insensitive) so a new season
    or episode of a watched series notifies too. The DM carries a Get button
    for the freshly indexed copy. Returns the number of users notified.
    """
    from .config import client
    from pyrogram.types import InlineKeyboardMarkup, InlineKeyboardButton

    title = (entry.get("title") or "").strip()
    if not title or client is None:
        return 0
    key = _watch_key(title)

    try:
        docs = await users_col.find({"watchlist.title_key": key}).to_list(length=200)
    except Exception as e:
        print(f"⚠️ notify_watchlist query failed: {e}")
        return 0

    notified = 0
    channel_id = entry.get("channel_id")
    message_id = entry.get("message_id")
    for doc in docs:
        uid = doc.get("user_id")
        try:
            text = (
                f"🎬 **{title}** is now available!\n\n"
                f"You're watching this title - grab it below."
            )
            reply_markup = None
            if channel_id and message_id:
                reply_markup = InlineKeyboardMarkup([[
                    InlineKeyboardButton(
                        "📥 Get File",
                        callback_data=f"get_file:{channel_id}:{message_id}",
                    )
                ]])
            await client.send_message(uid, text, reply_markup=reply_markup)
            notified += 1
        except Exception as e:
            print(f"⚠️ notify_watchlist DM failed for {uid}: {e}")
    return notified


async def check_banned(message: Message) -> bool:
    """Check if user is banned and send message if they are"""
    uid = message.from_user.id
    if await is_banned(uid):
        await message.reply_text("🚫 You are banned from using this bot.")
        return True
    return False


async def check_terms_acceptance(message: Message) -> bool:
    """Check if user has accepted terms and send prompt if they haven't"""
    uid = message.from_user.id

    # Admins bypass terms acceptance check
    if await is_admin(uid):
        return True

    if not await has_accepted_terms(uid):
        await message.reply_text(
            "⚠️ **Terms Acceptance Required**\n\n"
            "You must accept our Terms of Use and Privacy Policy before using this bot.\n\n"
            "Please use /start to view and accept the terms."
        )
        return False
    return True


async def should_process_command(message: Message) -> bool:
    """
    Determine if a command should be processed based on access control rules.

    Commands are processed if:
    1. Message is from a private chat (direct message to bot)
    2. Message is from a monitored channel/group (registered in channels_col
       and enabled)
    3. User is an admin (in ADMINS list or has admin role in database)

    This prevents the bot from responding to commands in random groups.

    Note: chat.type is a pyrogram ChatType enum (not a plain string), so it
    is compared against the enum values directly.
    """
    # Always process private messages (direct messages to bot)
    if message.chat.type == ChatType.PRIVATE:
        return True

    # Check if user is an admin - admins can use commands anywhere
    user_id = message.from_user.id
    if await is_admin(user_id):
        return True

    # For groups/supergroups/channels, only process commands if the chat is a
    # registered, enabled monitored channel
    if message.chat.type in (ChatType.GROUP, ChatType.SUPERGROUP, ChatType.CHANNEL):
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