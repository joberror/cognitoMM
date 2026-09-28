"""
User Management and Access Control Module

This module handles user authentication, authorization, and access control
for the MovieBot. It includes functions for checking user roles,
banning/unbanning users, and verifying terms acceptance.
"""

import time
from datetime import datetime, timezone
from pyrogram.types import Message
from pyrogram.enums import ChatType

from .config import ADMINS, WATCHLIST_FREE_LIMIT, WATCHLIST_PREMIUM_LIMIT, \
    WATCHLIST_NOTIFY_COOLDOWN_SECONDS
from .database import users_col, logs_col, channels_col
from .tmdb_integration import normalize_content_type


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


async def _resolve_tmdb_id(title: str, year=None, type_=None):
    """Best-effort TMDb ID lookup (cached; None without API key/failure)."""
    try:
        from .tmdb_integration import enrich_title
        meta = await enrich_title(title, year, type_ or "Movie")
    except Exception:
        return None
    return (meta or {}).get("tmdb_id")


async def add_to_watchlist(user_id: int, title: str, year=None, type_=None,
                           tmdb_id=None, imdb_id=None, status=None,
                           poster_url=None, seasons=None, episodes=None) -> bool:
    """Add a title to a user's watchlist (idempotent). Returns True if added.

    The entry carries the TMDb ID (resolved via the cached enrichment when
    not passed) so notifications match remakes/transliterations exactly;
    the normalized title stays as fallback for titles TMDb doesn't know.

    Callers that already resolved a candidate through the /watch picker pass
    the full detail set (``imdb_id``, ``status``, ``poster_url``, and for
    series ``seasons``/``episodes``) so the stored entry renders the
    type/year/status line in /watchlist without another API call.
    """
    if not title or not str(title).strip():
        return False
    key = _watch_key(title)
    if tmdb_id is None:
        tmdb_id = await _resolve_tmdb_id(str(title).strip(), year, type_)
    entry = {
        "title": str(title).strip(),
        "title_key": key,
        "year": year,
        "type": normalize_content_type(type_),
        "tmdb_id": tmdb_id,
        "added_at": datetime.now(timezone.utc),
    }
    # Only store the optional detail fields when we actually have them, so a
    # TMDb-less entry stays clean instead of carrying null placeholders.
    for field, value in (("imdb_id", imdb_id), ("status", status),
                         ("poster_url", poster_url), ("seasons", seasons),
                         ("episodes", episodes)):
        if value is not None:
            entry[field] = value
    if entry.get("status"):
        entry["status_checked_at"] = entry["added_at"]

    try:
        # Ensure the user document exists FIRST (upsert on user_id alone). A
        # $ne-filtered upsert would insert a SECOND user document whenever the
        # title is already watched (filter matches nothing -> upsert inserts).
        await users_col.update_one(
            {"user_id": user_id},
            {"$setOnInsert": {"user_id": user_id, "watchlist": []}},
            upsert=True,
        )
        # Idempotent on EITHER identity: skip the push when an entry with the
        # same TMDb ID or the same normalized title already exists.
        filt = {"user_id": user_id,
                "watchlist.title_key": {"$ne": key}}
        if tmdb_id is not None:
            filt["watchlist.tmdb_id"] = {"$ne": tmdb_id}
        result = await users_col.update_one(filt, {"$push": {"watchlist": entry}})
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


async def watchlist_capacity(user_id: int) -> tuple:
    """Return ``(limit, is_premium)`` for a user's watchlist cap.

    Free users track WATCHLIST_FREE_LIMIT titles, premium users
    WATCHLIST_PREMIUM_LIMIT. Admins get the premium cap without holding a
    premium record (same bypass the /request rate limits use).
    """
    if await is_admin(user_id):
        return WATCHLIST_PREMIUM_LIMIT, True
    # Imported lazily: premium_management imports log_action from this module,
    # so a top-level import here would be circular.
    from .premium_management import is_premium_user
    try:
        premium = await is_premium_user(user_id)
    except Exception as e:
        print(f"⚠️ watchlist_capacity premium check failed for {user_id}: {e}")
        premium = False
    return (WATCHLIST_PREMIUM_LIMIT if premium else WATCHLIST_FREE_LIMIT), premium


async def update_watchlist_status(user_id: int, title_key: str, fields: dict) -> bool:
    """Patch the status/detail fields of one watchlist entry. True if changed.

    Called by the /watchlist UPDATE button. Only the fields present in
    ``fields`` are written, so a partial TMDb response (e.g. a failed status
    derivation) never blanks data we already had.
    """
    allowed = {"status", "status_checked_at", "seasons", "episodes", "year"}
    patch = {k: v for k, v in (fields or {}).items() if k in allowed and v is not None}
    if not patch:
        return False
    try:
        result = await users_col.update_one(
            {"user_id": user_id, "watchlist.title_key": title_key},
            {"$set": {f"watchlist.$.{k}": v for k, v in patch.items()}},
        )
        return bool(result.modified_count)
    except Exception as e:
        print(f"⚠️ update_watchlist_status failed for {user_id}/{title_key}: {e}")
        return False


# Per-(user, title) floodgate: (uid, identity) -> (sent_at, extra_count).
# A series batch (S01E01..E10) or a multi-file drop indexes in one burst and
# each file would otherwise DM the watcher. Only the first copy inside the
# window notifies; the rest are suppressed. Keyed per title so two different
# titles landing together each get their own single message.
_notify_cooldowns: dict = {}


def _notify_identity(title: str, tmdb_id) -> str:
    """Cooldown key for one title: TMDb ID when known, else normalized title."""
    if tmdb_id is not None:
        return f"tmdb:{tmdb_id}"
    return f"title:{_watch_key(title)}"


def _cooldown_active(key: tuple) -> bool:
    """True when this (user, title) was already notified inside the window."""
    record = _notify_cooldowns.get(key)
    if not record:
        return False
    sent_at, count = record
    if (time.monotonic() - sent_at) > WATCHLIST_NOTIFY_COOLDOWN_SECONDS:
        _notify_cooldowns.pop(key, None)
        return False
    # Already DMed in this window: absorb the extra copy into the count
    # instead of sending a second message.
    _notify_cooldowns[key] = (sent_at, count + 1)
    return True


def reset_notify_cooldowns() -> None:
    """Clear the watchlist floodgate state (tests / manual recovery)."""
    _notify_cooldowns.clear()


async def notify_watchlist(entry: dict) -> int:
    """DM every user watching a title when a new copy is indexed.

    Matching is by TMDb ID first (exact across remakes/transliterations),
    falling back to normalized title (exact, case-insensitive) so a new
    season or episode of a watched series notifies too. The DM carries a
    Get button for the freshly indexed copy. Returns users notified.

    Floodgate: a burst of copies for the same title (a full season dropping
    at once, or several quality variants) sends each watcher ONE message —
    the rest are absorbed by the per-(user, title) cooldown above.
    """
    from .config import client
    from pyrogram.types import InlineKeyboardMarkup, InlineKeyboardButton

    title = (entry.get("title") or "").strip()
    if not title or client is None:
        return 0
    key = _watch_key(title)
    tmdb_id = entry.get("tmdb_id")

    query = {"watchlist.title_key": key}
    if tmdb_id is not None:
        query = {"$or": [{"watchlist.tmdb_id": tmdb_id},
                         {"watchlist.title_key": key}]}

    try:
        docs = await users_col.find(query).to_list(length=200)
    except Exception as e:
        print(f"⚠️ notify_watchlist query failed: {e}")
        return 0

    notified = 0
    channel_id = entry.get("channel_id")
    message_id = entry.get("message_id")
    identity = _notify_identity(title, tmdb_id)
    for doc in docs:
        uid = doc.get("user_id")
        if uid is None:
            continue
        if _cooldown_active((uid, identity)):
            continue
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
            # Record only after a successful send, so a failed DM does not
            # burn the user's window.
            _notify_cooldowns[(uid, identity)] = (time.monotonic(), 0)
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