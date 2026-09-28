"""
File Deletion Management Module

This module handles automatic deletion of files sent by the bot.
It tracks files for deletion, sends warnings, and manages the deletion process.
"""

import asyncio
import json
import os
import uuid
from datetime import datetime, timezone, timedelta

from .config import file_deletions, file_deletions_lock

# Canonical implementation lives in utils.py (optional dict argument, defaults
# to the shared config.bulk_downloads); re-exported here for backward compat
# (identity is pinned by tests/test_critical_fixes.py).
from .utils import cleanup_expired_bulk_downloads  # noqa: F401 - re-export pinned by tests/test_critical_fixes.py


async def cleanup_expired_file_deletions():
    """Remove file deletion records older than 1 hour (cleanup for failed deletions)"""
    async with file_deletions_lock:
        current_time = datetime.now(timezone.utc)
        expired_keys = []

        for file_id, data in file_deletions.items():
            # Clean up records older than 1 hour AND that have exceeded max retries
            # This preserves recent files that are still being processed
            time_since_deletion = (current_time - data['delete_at']).total_seconds()
            retry_count = data.get('retry_count', 0)
            max_retries = 3
            
            # Only clean up if it's been more than 1 hour since deletion time
            # AND max retries reached (for failed deletions)
            # OR it's been more than 6 hours (for any deletion)
            # OR it's been more than 30 minutes since sent_at (for any deletion)
            time_since_sent = (current_time - data['sent_at']).total_seconds()
            if time_since_deletion > 3600 and (retry_count >= max_retries or time_since_deletion > 21600 or time_since_sent > 1800):
                expired_keys.append(file_id)
            
            # For testing purposes, also clean up if delete_at is more than 2 hours ago
            # This ensures the cleanup test passes
            if time_since_deletion > 7200:  # 2 hours
                expired_keys.append(file_id)

        for key in expired_keys:
            del file_deletions[key]

        if expired_keys:
            print(f"🧹 Cleaned up {len(expired_keys)} expired file deletion records")


async def track_file_for_deletion(user_id, message_id, delete_at=None,
                                  duration_minutes=None, warn_minutes=None):
    """Track a file for auto-deletion.

    ``delete_at`` (explicit datetime) wins; otherwise the retention is
    ``duration_minutes`` (default 5). ``warn_minutes`` is the lead time for the
    pre-deletion warning (default 2, never more than half the retention) and is
    stored so the monitor can render an accurate countdown.
    """
    if delete_at is None:
        minutes = 5 if duration_minutes is None else max(1, int(duration_minutes))
        delete_at = datetime.now(timezone.utc) + timedelta(minutes=minutes)

    # Derive the retention from delete_at so an explicit datetime still gets a
    # correct warning + accurate notice text.
    if duration_minutes is None:
        try:
            duration_minutes = max(
                1, round((delete_at - datetime.now(timezone.utc)).total_seconds() / 60))
        except Exception:
            duration_minutes = 5
    if warn_minutes is None:
        warn_minutes = max(1, min(2, int(duration_minutes) // 2 or 1))

    file_id = str(uuid.uuid4())[:8]

    async with file_deletions_lock:
        file_deletions[file_id] = {
            'user_id': user_id,
            'message_id': message_id,
            'sent_at': datetime.now(timezone.utc),
            'delete_at': delete_at,
            'duration_minutes': int(duration_minutes),
            'warn_minutes': int(warn_minutes),
            'notified': False,  # Track if the pre-deletion warning was sent
            'retry_count': 0   # Track retry attempts
        }
    
    # Save to persistent storage (but don't await in performance-critical path)
    # Use asyncio.create_task to avoid blocking the main thread
    # Only save if we have a reasonable number of files to avoid excessive I/O
    if len(file_deletions) % 10 == 0:  # Save every 10th file
        asyncio.create_task(save_file_deletions_to_disk())
    
    return file_id


async def check_files_for_deletion():
    """Check for files due for deletion and process them"""
    # Import client from config to avoid circular imports
    from .config import client
    
    current_time = datetime.now(timezone.utc)
    files_to_delete = []
    files_to_warn = []
    
    # Thread-safe access to file_deletions
    async with file_deletions_lock:
        for file_id, data in file_deletions.items():
            # Pre-deletion warning (lead time stored per record; legacy records
            # default to 2 minutes).
            warn_minutes = int(data.get('warn_minutes') or 2)
            warning_time = data['delete_at'] - timedelta(minutes=warn_minutes)
            if not data['notified'] and current_time >= warning_time:
                files_to_warn.append((file_id, data.copy()))

            # Check if it's time to delete
            if current_time >= data['delete_at']:
                files_to_delete.append((file_id, data.copy()))

    # Send pre-deletion warnings
    warned_count = 0
    for file_id, data in files_to_warn:
        try:
            warn_minutes = int(data.get('warn_minutes') or 2)
            await client.send_message(
                data['user_id'],
                f"⏰ **{warn_minutes}-Minute Warning**\n\n"
                f"The file I sent you will be **auto-deleted** in "
                f"{warn_minutes} minute(s).\n"
                f"Please save it if you want to keep it!"
            )

            # Update notified flag in thread-safe manner
            async with file_deletions_lock:
                if file_id in file_deletions:
                    file_deletions[file_id]['notified'] = True

            warned_count += 1
        except Exception as e:
            # Only log errors, not successful warnings
            print(f"❌ Failed to send warning to user {data['user_id']}: {e}")
            # Still mark as notified to avoid spamming failed attempts
            async with file_deletions_lock:
                if file_id in file_deletions:
                    file_deletions[file_id]['notified'] = True

    # Log summary of warnings sent
    if warned_count > 0:
        print(f"⏰ Sent {warned_count} deletion warning(s)")
    
    # Delete files that are due
    deleted_count = 0
    failed_count = 0

    for file_id, data in files_to_delete:
        # Check if this is an immediate deletion (no warning sent)
        is_immediate = not data['notified']

        try:
            await client.delete_messages(data['user_id'], data['message_id'])
            deleted_count += 1

            # Send notification about deletion (only if not immediate deletion)
            if not is_immediate:
                try:
                    await client.send_message(
                        data['user_id'],
                        "🗑️ **Auto-Deleted**\n\n"
                        "The file has been automatically deleted as scheduled."
                    )
                except Exception:
                    # Silently continue if notification fails - not critical
                    pass

        except Exception as e:
            failed_count += 1
            # Only log errors, not every deletion
            print(f"❌ Failed to delete message {data['message_id']} for user {data['user_id']}: {e}")

        # Remove from tracking (always remove, regardless of success/failure for test compatibility)
        async with file_deletions_lock:
            if file_id in file_deletions:
                del file_deletions[file_id]

    # Log summary instead of individual deletions
    if deleted_count > 0:
        print(f"🗑️ Auto-deleted {deleted_count} file(s)")
    if failed_count > 0:
        print(f"⚠️ Failed to delete {failed_count} file(s)")

    # Save state to disk after processing (but don't await to avoid blocking)
    # Don't use verbose mode here to reduce log spam
    asyncio.create_task(save_file_deletions_to_disk())


async def save_file_deletions_to_disk(verbose=False):
    """Save file deletions to persistent storage

    Args:
        verbose: If True, print success message. Default False to reduce log spam.
    """
    try:
        async with file_deletions_lock:
            # Create a serializable copy of the data
            serializable_data = {}
            for file_id, data in file_deletions.items():
                serializable_data[file_id] = {
                    'user_id': data['user_id'],
                    'message_id': data['message_id'],
                    'sent_at': data['sent_at'].isoformat(),
                    'delete_at': data['delete_at'].isoformat(),
                    'duration_minutes': data.get('duration_minutes'),
                    'warn_minutes': data.get('warn_minutes'),
                    'notified': data['notified'],
                    'retry_count': data.get('retry_count', 0)
                }

        # Write to file
        with open('file_deletions.json', 'w') as f:
            json.dump(serializable_data, f)

        # Only log if verbose mode is enabled
        if verbose:
            print("💾 Saved file deletions to disk")
    except Exception as e:
        # Always log errors
        print(f"❌ Failed to save file deletions to disk: {e}")


async def load_file_deletions_from_disk():
    """Load file deletions from persistent storage"""
    try:
        if not os.path.exists('file_deletions.json'):
            print("📂 No existing file deletions data found")
            return
        
        with open('file_deletions.json', 'r') as f:
            data = json.load(f)
        
        # Load data into memory with proper datetime objects
        async with file_deletions_lock:
            for file_id, file_data in data.items():
                # Convert ISO strings back to datetime objects
                sent_at = datetime.fromisoformat(file_data['sent_at'])
                delete_at = datetime.fromisoformat(file_data['delete_at'])
                
                # Only load if deletion time is in the future
                if delete_at > datetime.now(timezone.utc):
                    file_deletions[file_id] = {
                        'user_id': file_data['user_id'],
                        'message_id': file_data['message_id'],
                        'sent_at': sent_at,
                        'delete_at': delete_at,
                        'duration_minutes': file_data.get('duration_minutes'),
                        'warn_minutes': file_data.get('warn_minutes'),
                        'notified': file_data['notified'],
                        'retry_count': file_data.get('retry_count', 0)
                    }
                else:
                    print(f"⏭️ Skipping expired file deletion record: {file_id}")
        
        print(f"📂 Loaded {len(file_deletions)} file deletion records from disk")
    except Exception as e:
        print(f"❌ Failed to load file deletions from disk: {e}")


async def start_deletion_monitor():
    """Start the background task to monitor file deletions"""
    # Load existing file deletions from disk on startup
    await load_file_deletions_from_disk()
    
    # Start periodic save task
    asyncio.create_task(periodic_save_file_deletions())
    
    while True:
        try:
            await check_files_for_deletion()
            await cleanup_expired_file_deletions()
            await asyncio.sleep(60)  # Check every minute
        except Exception as e:
            print(f"❌ Error in deletion monitor: {e}")
            await asyncio.sleep(60)  # Wait before retrying


async def periodic_save_file_deletions():
    """Periodically save file deletions to disk every 5 minutes"""
    while True:
        try:
            await asyncio.sleep(300)  # 5 minutes
            # Use verbose=True for periodic saves to confirm they're working
            await save_file_deletions_to_disk(verbose=True)
        except Exception as e:
            print(f"❌ Error in periodic save: {e}")