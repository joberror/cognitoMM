"""
Premium Command Handlers Module

This module contains handlers for premium user input flows.
It processes user inputs during interactive premium management operations.
"""

import asyncio
from datetime import datetime, timezone
from hydrogram.types import Message
from .database import premium_users_col, premium_features_col, users_col
from .user_management import is_admin, log_action
from .premium_management import add_premium_user, edit_premium_user, remove_premium_user, get_premium_user, get_days_remaining, add_premium_feature
from .utils import wait_for_user_input


async def handle_premium_user_input(client, message: Message, input_type: str):
    """
    Handle premium management user input flows
    
    Args:
        client: Telegram client
        message: User message
        input_type: Type of input being handled
    """
    uid = message.from_user.id
    
    # Check if user is admin
    if not await is_admin(uid):
        return await message.reply_text("🚫 Admins only.")
    
    if input_type == "premium_add_user_id":
        await handle_add_premium_user(client, message)
    elif input_type == "premium_edit_user_id":
        await handle_edit_premium_user(client, message)
    elif input_type == "premium_remove_user_id":
        await handle_remove_premium_user(client, message)
    elif input_type == "premium_add_feature_name":
        await handle_add_premium_feature(client, message)


async def handle_add_premium_user(client, message: Message):
    """Handle adding a premium user"""
    uid = message.from_user.id
    
    # Get user ID input
    user_input = message.text.strip()
    
    if user_input.upper() == "CANCEL":
        return await message.reply_text("❌ Operation cancelled.")
    
    # Try to parse user ID
    try:
        target_user_id = int(user_input)
    except ValueError:
        return await message.reply_text(
            "❌ Invalid User ID. Please provide a numeric User ID.\n\n"
            "Use /premium to start over."
        )
    
    # Ask for number of days
    await message.reply_text(
        f"**Add Premium User**\n\n"
        f"User ID: {target_user_id}\n\n"
        f"How many days should this user have premium access?\n"
        f"Reply with a number (e.g., 30 for 30 days).\n\n"
        f"You can type **CANCEL** to abort."
    )
    
    # Wait for days input
    try:
        days_msg = await wait_for_user_input(message.chat.id, uid, timeout=120)
    except asyncio.TimeoutError:
        return await message.reply_text("⏰ Timeout. Use /premium to start over.")
    
    if not days_msg or not days_msg.text:
        return await message.reply_text("❌ Invalid input. Use /premium to start over.")
    
    days_input = days_msg.text.strip()
    
    if days_input.upper() == "CANCEL":
        return await message.reply_text("❌ Operation cancelled.")
    
    # Try to parse days
    try:
        days = int(days_input)
        if days <= 0:
            return await message.reply_text("❌ Days must be a positive number. Use /premium to start over.")
    except ValueError:
        return await message.reply_text("❌ Invalid number. Use /premium to start over.")
    
    # Try to get username (optional)
    try:
        user_info = await client.get_users(target_user_id)
        username = user_info.username or user_info.first_name or str(target_user_id)
    except Exception:
        username = str(target_user_id)
    
    # Add premium user
    success, result_message = await add_premium_user(target_user_id, days, uid, username)
    
    if success:
        await message.reply_text(f"✅ {result_message}")
    else:
        await message.reply_text(f"❌ {result_message}")


async def handle_edit_premium_user(client, message: Message):
    """Handle editing a premium user"""
    uid = message.from_user.id
    
    # Get user ID input
    user_input = message.text.strip()
    
    if user_input.upper() == "CANCEL":
        return await message.reply_text("❌ Operation cancelled.")
    
    # Try to parse user ID
    try:
        target_user_id = int(user_input)
    except ValueError:
        return await message.reply_text(
            "❌ Invalid User ID. Please provide a numeric User ID.\n\n"
            "Use /premium to start over."
        )
    
    # Check if user exists in premium
    premium_doc = await get_premium_user(target_user_id)
    
    if not premium_doc:
        return await message.reply_text(
            f"❌ User {target_user_id} is not a premium user.\n\n"
            f"Use /premium to start over."
        )
    
    # Get days remaining
    days_left = await get_days_remaining(target_user_id)
    expiry_date = premium_doc.get("expiry_date")
    added_by = premium_doc.get("added_by")
    added_date = premium_doc.get("added_date")
    
    # Format details
    details_text = (
        f"**Premium User Details**\n\n"
        f"User ID: {target_user_id}\n"
        f"Days Left: {days_left}\n"
        f"Expiry Date: {expiry_date.strftime('%Y-%m-%d %H:%M UTC') if expiry_date else 'N/A'}\n"
        f"Added By: {added_by}\n"
        f"Added Date: {added_date.strftime('%Y-%m-%d %H:%M UTC') if added_date else 'N/A'}\n\n"
        f"How many days do you want to add or remove?\n"
        f"Reply with a positive number to add days (e.g., 30)\n"
        f"Reply with a negative number to remove days (e.g., -10)\n\n"
        f"You can type **CANCEL** to abort."
    )
    
    await message.reply_text(details_text)

    # Wait for days delta input
    try:
        days_msg = await wait_for_user_input(message.chat.id, uid, timeout=120)
    except asyncio.TimeoutError:
        return await message.reply_text("⏰ Timeout. Use /premium to start over.")

    if not days_msg or not days_msg.text:
        return await message.reply_text("❌ Invalid input. Use /premium to start over.")

    days_input = days_msg.text.strip()

    if days_input.upper() == "CANCEL":
        return await message.reply_text("❌ Operation cancelled.")

    # Try to parse days delta
    try:
        days_delta = int(days_input)
        if days_delta == 0:
            return await message.reply_text("❌ Days delta cannot be zero. Use /premium to start over.")
    except ValueError:
        return await message.reply_text("❌ Invalid number. Use /premium to start over.")

    # Edit premium user
    success, result_message = await edit_premium_user(target_user_id, days_delta, uid)

    if success:
        await message.reply_text(f"✅ {result_message}")
    else:
        await message.reply_text(f"❌ {result_message}")


async def handle_remove_premium_user(client, message: Message):
    """Handle removing a premium user"""
    uid = message.from_user.id

    # Get user ID input
    user_input = message.text.strip()

    if user_input.upper() == "CANCEL":
        return await message.reply_text("❌ Operation cancelled.")

    # Try to parse user ID
    try:
        target_user_id = int(user_input)
    except ValueError:
        return await message.reply_text(
            "❌ Invalid User ID. Please provide a numeric User ID.\n\n"
            "Use /premium to start over."
        )

    # Check if user exists in premium
    premium_doc = await get_premium_user(target_user_id)

    if not premium_doc:
        return await message.reply_text(
            f"❌ User {target_user_id} is not a premium user.\n\n"
            f"Use /premium to start over."
        )

    # Get user details
    days_left = await get_days_remaining(target_user_id)
    expiry_date = premium_doc.get("expiry_date")

    # Show details and ask for confirmation
    details_text = (
        f"**Premium User Details**\n\n"
        f"User ID: {target_user_id}\n"
        f"Days Left: {days_left}\n"
        f"Expiry Date: {expiry_date.strftime('%Y-%m-%d %H:%M UTC') if expiry_date else 'N/A'}\n\n"
        f"Are you sure you want to remove this user from premium?\n"
        f"Reply with **YES** to confirm or **CANCEL** to abort."
    )

    await message.reply_text(details_text)

    # Wait for confirmation
    try:
        confirm_msg = await wait_for_user_input(message.chat.id, uid, timeout=120)
    except asyncio.TimeoutError:
        return await message.reply_text("⏰ Timeout. Use /premium to start over.")

    if not confirm_msg or not confirm_msg.text:
        return await message.reply_text("❌ Invalid input. Use /premium to start over.")

    confirm_input = confirm_msg.text.strip().upper()

    if confirm_input != "YES":
        return await message.reply_text("❌ Operation cancelled.")

    # Remove premium user
    from .premium_management import remove_premium_user
    success, result_message = await remove_premium_user(target_user_id, uid)

    if success:
        await message.reply_text(f"✅ {result_message}")
    else:
        await message.reply_text(f"❌ {result_message}")


async def handle_add_premium_feature(client, message: Message):
    """Handle adding a new premium feature"""
    uid = message.from_user.id

    # Get feature name input
    feature_name = message.text.strip()

    if feature_name.upper() == "CANCEL":
        return await message.reply_text("❌ Operation cancelled.")

    # Validate feature name (alphanumeric and underscores only)
    if not feature_name.replace("_", "").isalnum():
        return await message.reply_text(
            "❌ Invalid feature name. Use only letters, numbers, and underscores.\n\n"
            "Use /premium to start over."
        )

    # Ask for description
    await message.reply_text(
        f"**Add Premium Feature**\n\n"
        f"Feature Name: {feature_name}\n\n"
        f"Please provide a description for this feature.\n"
        f"Reply with a short description (e.g., 'Advanced search filters').\n\n"
        f"You can type **CANCEL** to abort."
    )

    # Wait for description input
    try:
        desc_msg = await wait_for_user_input(message.chat.id, uid, timeout=120)
    except asyncio.TimeoutError:
        return await message.reply_text("⏰ Timeout. Use /premium to start over.")

    if not desc_msg or not desc_msg.text:
        return await message.reply_text("❌ Invalid input. Use /premium to start over.")

    description = desc_msg.text.strip()

    if description.upper() == "CANCEL":
        return await message.reply_text("❌ Operation cancelled.")

    # Add premium feature
    success, result_message = await add_premium_feature(feature_name, description, uid)

    if success:
        await message.reply_text(
            f"✅ {result_message}\n\n"
            f"The feature is now enabled (premium-only) by default.\n"
            f"Use /premium → Manage Features to toggle it."
        )
    else:
        await message.reply_text(f"❌ {result_message}")


