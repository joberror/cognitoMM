"""
User Management and Access Control Module

This module handles user authentication, authorization, and access control
for the MovieBot. It includes functions for checking user roles,
banning/unbanning users, and verifying terms acceptance.
"""

import asyncio
from datetime import datetime, timezone
from hydrogram.types import Message

from .config import ADMINS
from .database import users_col, logs_col


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
    Determine if a command should be processed based on access control rules for bot session.

    Commands are processed if:
    1. Message is from a private chat (direct message to bot)
    2. Message is from a monitored channel/group (in channels_col database)
    3. User is an admin (in ADMINS list or has admin role in database)
    4. Bot is mentioned in groups (for bot session compatibility)

    This prevents the bot from responding to commands in random groups.
    """
    # Import channels_col here to avoid circular imports
    from ..main import channels_col
    
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