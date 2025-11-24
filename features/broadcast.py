"""
Broadcast System Module

This module handles admin broadcast messaging functionality for the MovieBot.
It allows administrators to send messages to all eligible users with proper
rate limiting, error handling, and progress tracking.
"""

import asyncio
from datetime import datetime, timezone
from collections import defaultdict
from hydrogram import Client
from hydrogram.types import Message
from hydrogram.errors import (
    UserIsBlocked,
    PeerIdInvalid,
    FloodWait,
    InputUserDeactivated,
    UserDeactivated
)

from .config import (
    BROADCAST_RATE_LIMIT,
    BROADCAST_PROGRESS_INTERVAL,
    BROADCAST_TEST_MODE,
    BROADCAST_TEST_USERS
)
from .database import users_col, broadcasts_col
from .user_management import is_admin, log_action
from .utils import wait_for_user_input, get_readable_time


# -------------------------
# Helper Functions
# -------------------------

async def get_broadcast_recipients(filters: dict = None) -> list[int]:
    """
    Query database for eligible broadcast recipients
    
    Args:
        filters: Optional additional filters
    
    Returns:
        list: User IDs eligible for broadcast
    """
    # Base query for eligible users
    query = {
        "terms_accepted": True,
        "role": {"$ne": "banned"}
    }
    
    # Add optional filters
    if filters:
        query.update(filters)
    
    # Test mode override
    if BROADCAST_TEST_MODE and BROADCAST_TEST_USERS:
        print(f"[BROADCAST] Test mode enabled - using test users: {BROADCAST_TEST_USERS}")
        return BROADCAST_TEST_USERS
    
    # Query database
    cursor = users_col.find(query, {"user_id": 1, "_id": 0})
    users = await cursor.to_list(length=None)
    
    return [user["user_id"] for user in users]


async def send_broadcast_message(
    client: Client,
    user_id: int,
    message_text: str,
    parse_mode: str = None
) -> dict:
    """
    Send message to single user with comprehensive error handling
    
    Args:
        client: Hydrogram client instance
        user_id: Target user ID
        message_text: Message content
        parse_mode: Optional parse mode (Markdown/HTML)
    
    Returns:
        dict: Result with success status and error info
    """
    try:
        await client.send_message(user_id, message_text, parse_mode=parse_mode)
        return {"success": True, "user_id": user_id}
    
    except (UserIsBlocked, InputUserDeactivated, UserDeactivated):
        # User blocked the bot or deleted account - silent fail
        return {"success": False, "user_id": user_id, "error": "blocked"}
    
    except PeerIdInvalid:
        # Invalid user ID
        return {"success": False, "user_id": user_id, "error": "invalid"}
    
    except FloodWait as e:
        # Rate limit exceeded - wait and retry
        print(f"[BROADCAST] FloodWait: {e.value}s for user {user_id}")
        await asyncio.sleep(e.value)
        # Retry once
        try:
            await client.send_message(user_id, message_text, parse_mode=parse_mode)
            return {"success": True, "user_id": user_id, "retry": True}
        except Exception as retry_error:
            return {"success": False, "user_id": user_id, "error": f"flood_retry_failed: {str(retry_error)}"}
    
    except Exception as e:
        # Other errors - log and continue
        error_msg = str(e)
        print(f"[BROADCAST] Error sending to {user_id}: {error_msg}")
        return {"success": False, "user_id": user_id, "error": error_msg}


def format_progress_message(metrics: dict, elapsed: float, remaining: float) -> str:
    """Format progress message for status updates"""
    total = metrics["total"]
    sent = metrics["sent"]
    failed = metrics["failed"]
    processed = sent + failed
    
    # Calculate percentages
    sent_pct = (sent / total * 100) if total > 0 else 0
    failed_pct = (failed / total * 100) if total > 0 else 0
    progress_pct = (processed / total * 100) if total > 0 else 0
    
    # Format times
    elapsed_str = get_readable_time(elapsed)
    remaining_str = get_readable_time(remaining) if remaining > 0 else "calculating..."
    
    lines = [
        "📢 **BROADCAST IN PROGRESS**",
        "",
        f"📊 **Status:** Sending...",
        f"👥 **Total Users:** {total:,}",
        f"✅ **Sent:** {sent:,} ({sent_pct:.1f}%)",
        f"❌ **Failed:** {failed:,} ({failed_pct:.1f}%)",
        f"📈 **Progress:** {processed:,}/{total:,} ({progress_pct:.1f}%)",
        f"⏱️ **Elapsed:** {elapsed_str}",
        f"⏳ **Remaining:** {remaining_str}",
        "",
        "🔄 Processing..."
    ]
    return "\n".join(lines)


def format_summary_message(results: dict) -> str:
    """Format final summary message"""
    total = results["total"]
    sent = results["sent"]
    failed = results["failed"]
    errors = results["errors"]
    duration = results["duration"]
    admin_id = results["admin_id"]
    completed_at = results["completed_at"]
    
    # Calculate percentages
    sent_pct = (sent / total * 100) if total > 0 else 0
    failed_pct = (failed / total * 100) if total > 0 else 0
    
    lines = [
        "✅ **BROADCAST COMPLETED**",
        "",
        "📊 **Final Statistics:**",
        f"👥 **Total Users:** {total:,}",
        f"✅ **Successfully Sent:** {sent:,} ({sent_pct:.1f}%)",
        f"❌ **Failed:** {failed:,} ({failed_pct:.1f}%)",
        ""
    ]
    
    # Error breakdown
    if errors:
        lines.append("📉 **Error Breakdown:**")
        for error_type, count in sorted(errors.items(), key=lambda x: x[1], reverse=True):
            error_pct = (count / failed * 100) if failed > 0 else 0
            lines.append(f"• {error_type}: {count} ({error_pct:.1f}%)")
        lines.append("")
    
    lines.extend([
        f"⏱️ **Total Time:** {get_readable_time(duration)}",
        f"📅 **Completed:** {completed_at.strftime('%Y-%m-%d %H:%M:%S UTC')}",
        f"👤 **By:** Admin (ID: {admin_id})"
    ])
    
    return "\n".join(lines)


async def execute_broadcast(
    client: Client,
    admin_message: Message,
    user_ids: list[int],
    message_text: str,
    parse_mode: str = None
) -> dict:
    """Execute broadcast to all users with progress tracking"""
    # Initialize metrics
    metrics = {
        "total": len(user_ids),
        "sent": 0,
        "failed": 0,
        "errors": defaultdict(int),
        "start_time": datetime.now(timezone.utc)
    }
    
    # Send initial status
    status_msg = await admin_message.reply_text(
        format_progress_message(metrics, 0, 0)
    )
    
    # Calculate delay for rate limiting
    delay = 1.0 / BROADCAST_RATE_LIMIT
    
    # Broadcast loop
    for idx, user_id in enumerate(user_ids, 1):
        # Send message
        result = await send_broadcast_message(client, user_id, message_text, parse_mode)
        
        # Update metrics
        if result["success"]:
            metrics["sent"] += 1
        else:
            metrics["failed"] += 1
            error_type = result.get("error", "unknown")
            metrics["errors"][error_type] += 1
        
        # Rate limiting delay
        await asyncio.sleep(delay)
        
        # Progress update
        if idx % BROADCAST_PROGRESS_INTERVAL == 0 or idx == len(user_ids):
            elapsed = (datetime.now(timezone.utc) - metrics["start_time"]).total_seconds()
            rate = idx / elapsed if elapsed > 0 else 0
            remaining = (metrics["total"] - idx) / rate if rate > 0 else 0
            
            try:
                await status_msg.edit_text(
                    format_progress_message(metrics, elapsed, remaining)
                )
            except Exception as e:
                # Ignore edit errors (message might be too old)
                print(f"[BROADCAST] Progress update error: {e}")
    
    # Calculate final metrics
    end_time = datetime.now(timezone.utc)
    duration = (end_time - metrics["start_time"]).total_seconds()
    
    results = {
        "total": metrics["total"],
        "sent": metrics["sent"],
        "failed": metrics["failed"],
        "errors": dict(metrics["errors"]),
        "duration": duration,
        "admin_id": admin_message.from_user.id,
        "completed_at": end_time,
        "started_at": metrics["start_time"]
    }
    
    # Send final summary
    try:
        await status_msg.edit_text(format_summary_message(results))
    except Exception as e:
        # If edit fails, send new message
        await admin_message.reply_text(format_summary_message(results))
    
    return results


async def log_broadcast(
    admin_id: int,
    admin_username: str,
    message_text: str,
    results: dict,
    parse_mode: str = None
):
    """Log broadcast to database for history and analytics"""
    # Generate broadcast ID
    broadcast_id = f"bc_{results['started_at'].strftime('%Y%m%d_%H%M%S')}"
    
    # Create document
    doc = {
        "broadcast_id": broadcast_id,
        "admin_id": admin_id,
        "admin_username": admin_username,
        "message_text": message_text,
        "message_type": "text",
        "parse_mode": parse_mode,
        
        # Targeting
        "target_query": {
            "terms_accepted": True,
            "role": {"$ne": "banned"}
        },
        "total_users": results["total"],
        
        # Results
        "sent_count": results["sent"],
        "failed_count": results["failed"],
        "error_breakdown": results["errors"],
        
        # Timing
        "started_at": results["started_at"],
        "completed_at": results["completed_at"],
        "duration_seconds": results["duration"],
        
        # Status
        "status": "completed",
        
        # Metadata
        "created_at": datetime.now(timezone.utc)
    }
    
    try:
        await broadcasts_col.insert_one(doc)
        print(f"[BROADCAST] Logged broadcast {broadcast_id} to database")
    except Exception as e:
        print(f"[BROADCAST] Error logging to database: {e}")
    
    # Also log action
    await log_action("broadcast", by=admin_id, extra={
        "broadcast_id": broadcast_id,
        "total_users": results["total"],
        "sent": results["sent"],
        "failed": results["failed"]
    })


# -------------------------
# Main Command Handler
# -------------------------

async def cmd_broadcast(client: Client, message: Message):
    """Handle /broadcast command for admin message broadcasting"""
    uid = message.from_user.id
    username = message.from_user.username or message.from_user.first_name or str(uid)
    
    # Check admin permission
    if not await is_admin(uid):
        return await message.reply_text("🚫 Admins only.")
    
    # Get message text
    parts = message.text.split(maxsplit=1)
    parse_mode = None  # Can be extended to support Markdown/HTML
    
    if len(parts) < 2:
        # Interactive mode - ask for message
        prompt_text = "\n".join([
            "📝 **Broadcast Message**",
            "",
            "Send the message you want to broadcast to all users.",
            "",
            "⏰ **Timeout:** 60 seconds",
            "🛑 **To cancel:** Send 'CANCEL'"
        ])
        prompt = await message.reply_text(prompt_text)
        
        try:
            response = await wait_for_user_input(message.chat.id, uid, timeout=60)
            
            if not response or not response.text:
                return await prompt.edit_text("❌ Invalid input. Broadcast cancelled.")
            
            if response.text.upper().strip() == "CANCEL":
                return await prompt.edit_text("❌ Broadcast cancelled.")
            
            message_text = response.text
            await prompt.delete()
            
        except asyncio.TimeoutError:
            return await prompt.edit_text("⏰ Timeout. Broadcast cancelled.")
    else:
        message_text = parts[1]
    
    # Validate message
    MAX_MESSAGE_LENGTH = 4096
    if len(message_text) > MAX_MESSAGE_LENGTH:
        error_text = "\n".join([
            "❌ **Message Too Long**",
            "",
            f"Maximum length: {MAX_MESSAGE_LENGTH} characters",
            f"Your message: {len(message_text)} characters"
        ])
        return await message.reply_text(error_text)
    
    # Get recipients
    loading = await message.reply_text("🔍 Querying eligible users...")
    
    try:
        user_ids = await get_broadcast_recipients()
    except Exception as e:
        error_text = "\n".join([
            "❌ **Error Querying Users**",
            "",
            f"Error: {str(e)}",
            "",
            "Please try again later."
        ])
        return await loading.edit_text(error_text)
    
    if not user_ids:
        error_text = "\n".join([
            "⚠️ **No Eligible Users**",
            "",
            "No users found matching broadcast criteria.",
            "Users must have accepted terms and not be banned."
        ])
        return await loading.edit_text(error_text)
    
    await loading.delete()
    
    # Show confirmation
    preview = message_text[:200] + "..." if len(message_text) > 200 else message_text
    
    confirm_lines = [
        "📢 **Broadcast Confirmation**",
        "",
        f"👥 **Recipients:** {len(user_ids):,} users",
        f"📝 **Message Preview:**",
        preview,
        "",
        "⚠️ **This will send the message to all eligible users.**",
        "",
        "Reply **YES** to confirm or **NO** to cancel.",
        "⏰ **Timeout:** 30 seconds"
    ]
    confirm_text = "\n".join(confirm_lines)
    
    confirm_msg = await message.reply_text(confirm_text)
    
    try:
        response = await wait_for_user_input(message.chat.id, uid, timeout=30)
        
        if not response or not response.text or response.text.upper().strip() != "YES":
            return await confirm_msg.edit_text("❌ Broadcast cancelled.")
        
        await confirm_msg.delete()
        
    except asyncio.TimeoutError:
        return await confirm_msg.edit_text("⏰ Timeout. Broadcast cancelled.")
    
    # Execute broadcast
    await message.reply_text("🚀 Starting broadcast...")
    
    try:
        results = await execute_broadcast(
            client,
            message,
            user_ids,
            message_text,
            parse_mode
        )
        
        # Log to database
        await log_broadcast(uid, username, message_text, results, parse_mode)
        
    except Exception as e:
        error_lines = [
            "❌ **Broadcast Error**",
            "",
            f"An error occurred during broadcast:",
            str(e),
            "",
            "Some messages may have been sent."
        ]
        await message.reply_text("\n".join(error_lines))
        
        # Log error
        await log_action("broadcast_error", by=uid, extra={"error": str(e)})
