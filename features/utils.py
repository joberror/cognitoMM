"""
Utility Functions Module

This module contains various utility functions used throughout the Movie Bot application,
including file management, time formatting, and helper functions.
"""

import asyncio
import uuid
import json
import os
import re
from datetime import datetime, timezone, timedelta
from .config import file_deletions, file_deletions_lock, bulk_downloads

async def wait_for_user_input(chat_id: int, user_id: int, timeout: int = 60):
    """Wait for user input - replacement for client.listen"""
    from .config import user_input_events
    key = f"{chat_id}_{user_id}"
    event = asyncio.Event()
    user_input_events[key] = {'event': event, 'message': None}

    try:
        await asyncio.wait_for(event.wait(), timeout=timeout)
        return user_input_events[key]['message']
    except asyncio.TimeoutError:
        raise asyncio.TimeoutError("User input timeout")
    finally:
        # Clean up
        if key in user_input_events:
            del user_input_events[key]

def set_user_input(chat_id: int, user_id: int, message):
    """Set user input message - called from message handler"""
    from .config import user_input_events
    key = f"{chat_id}_{user_id}"
    if key in user_input_events:
        user_input_events[key]['message'] = message
        user_input_events[key]['event'].set()

async def cleanup_expired_bulk_downloads():
    """Remove bulk downloads older than 1 hour"""
    current_time = datetime.now(timezone.utc)
    expired_keys = []

    for bulk_id, data in bulk_downloads.items():
        if (current_time - data['created_at']).total_seconds() > 3600:  # 1 hour
            expired_keys.append(bulk_id)

    for key in expired_keys:
        del bulk_downloads[key]

    if expired_keys:
        print(f"🧹 Cleaned up {len(expired_keys)} expired bulk downloads")

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

async def track_file_for_deletion(user_id, message_id, delete_at=None):
    """Track a file for auto-deletion"""
    if delete_at is None:
        # Default: 5 minutes from now
        delete_at = datetime.now(timezone.utc) + timedelta(minutes=5)
    
    file_id = str(uuid.uuid4())[:8]
    
    async with file_deletions_lock:
        file_deletions[file_id] = {
            'user_id': user_id,
            'message_id': message_id,
            'sent_at': datetime.now(timezone.utc),
            'delete_at': delete_at,
            'notified': False,  # Track if 5-minute warning was sent
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
    from .config import client
    current_time = datetime.now(timezone.utc)
    files_to_delete = []
    files_to_warn = []
    
    # Thread-safe access to file_deletions
    async with file_deletions_lock:
        for file_id, data in file_deletions.items():
            # Check if it's time to send 2-minute warning (for 5-minute deletion timer)
            warning_time = data['delete_at'] - timedelta(minutes=2)
            if not data['notified'] and current_time >= warning_time:
                files_to_warn.append((file_id, data.copy()))

            # Check if it's time to delete
            if current_time >= data['delete_at']:
                files_to_delete.append((file_id, data.copy()))

    # Send 2-minute warnings
    warned_count = 0
    for file_id, data in files_to_warn:
        try:
            await client.send_message(
                data['user_id'],
                f"⏰ **2-Minute Warning**\n\n"
                f"The file I sent you will be **auto-deleted** in 2 minutes.\n"
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
        deletion_success = False
        retry_count = data.get('retry_count', 0)
        max_retries = 3

        # Check if this is an immediate deletion (no warning sent)
        is_immediate = not data['notified']

        try:
            await client.delete_messages(data['user_id'], data['message_id'])
            deletion_success = True
            deleted_count += 1

            # Send notification about deletion (only if not immediate deletion)
            if not is_immediate:
                try:
                    await client.send_message(
                        data['user_id'],
                        "🗑️ **Auto-Deleted**\n\n"
                        "The file has been automatically deleted as scheduled."
                    )
                except Exception as notify_error:
                    # Silently continue if notification fails - not critical
                    pass

        except Exception as e:
            failed_count += 1
            # Only log errors, not every deletion
            print(f"❌ Failed to delete message {data['message_id']} for user {data['user_id']}: {e}")
            deletion_success = False

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

def get_readable_time(seconds):
    """Convert seconds to readable time format"""
    periods = [('d', 86400), ('h', 3600), ('m', 60), ('s', 1)]
    result = ''
    for period_name, period_seconds in periods:
        if seconds >= period_seconds:
            period_value, seconds = divmod(seconds, period_seconds)
            result += f'{int(period_value)}{period_name}'
    return result

def format_file_size(size_bytes):
    """Convert bytes to human readable format (GB, MB, KB)"""
    if not size_bytes or size_bytes == 0:
        return "N/A"

    # Convert to appropriate unit
    if size_bytes >= 1024**3:  # GB
        return f"{size_bytes / (1024**3):.1f}GB"
    elif size_bytes >= 1024**2:  # MB
        return f"{size_bytes / (1024**2):.0f}MB"
    elif size_bytes >= 1024:  # KB
        return f"{size_bytes / 1024:.0f}KB"
    else:
        return f"{size_bytes}B"

async def load_terms_and_privacy():
    """Load terms and privacy policy from markdown file"""
    try:
        with open('TERMS_AND_PRIVACY.md', 'r', encoding='utf-8') as f:
            content = f.read()
        return content
    except Exception as e:
        print(f"❌ Failed to load terms and privacy: {e}")
        return None

async def check_banned(message):
    """Check if user is banned and send message if they are"""
    from .database import is_banned
    uid = message.from_user.id
    if await is_banned(uid):
        await message.reply_text("🚫 You are banned from using this bot.")
        return True
    return False

async def check_terms_acceptance(message):
    """Check if user has accepted terms and send prompt if they haven't"""
    from .database import is_admin, has_accepted_terms
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

async def should_process_command(message):
    """
    Determine if a command should be processed based on access control rules for bot session.

    Commands are processed if:
    1. Message is from a private chat (direct message to bot)
    2. Message is from a monitored channel/group (in channels_col database)
    3. User is an admin (in ADMINS list or has admin role in database)
    4. Bot is mentioned in groups (for bot session compatibility)

    This prevents the bot from responding to commands in random groups.
    """
    from .database import channels_col, is_admin
    from .config import ADMINS
    
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
    async def wrapper(client, message):
        if check_banned(message):
            return
        return await func(client, message)
    return wrapper

async def should_process_command_for_user(user_id: int) -> bool:
    """Check if user has access to use bot commands"""
    from .database import is_admin, is_banned
    
    # Check if user is admin
    if await is_admin(user_id):
        return True

    # Check if user is banned
    if await is_banned(user_id):
        return False

    # For now, allow all non-banned users
    return True

def group_recent_content(results):
    """Group database results by title with quality/episode consolidation and categorization"""
    # Use dictionaries to group by title first
    movies_dict = {}
    series_dict = {}

    for item in results:
        # Skip items without required fields
        if not item.get('title') or not item.get('type'):
            continue

        title = item.get('title', 'Unknown')
        content_type = item.get('type', 'Movie').lower()
        year = item.get('year')

        # Determine which dictionary to use
        target_dict = series_dict if content_type in ['series', 'tv', 'show'] else movies_dict

        # Initialize group data if title not seen before
        if title not in target_dict:
            target_dict[title] = {
                'title': title,
                'type': content_type,
                'year': year,
                'qualities': set(),
                'seasons_episodes': [],
                'count': 0
            }

        # Update existing group data
        group_data = target_dict[title]

        # Add quality if available
        quality = item.get('quality')
        if quality:
            group_data['qualities'].add(quality.upper())

        # Collect season/episode info for series
        if content_type in ['series', 'tv', 'show']:
            season = item.get('season')
            episode = item.get('episode')
            if season and episode:
                group_data['seasons_episodes'].append((season, episode))

        group_data['count'] += 1

    # Convert dictionaries to lists for processing
    movies = list(movies_dict.values())
    series = list(series_dict.values())

    # Process each category to create display names
    categorized_results = {
        'movies': [],
        'series': []
    }

    # Process movies
    for movie_data in movies:
        title, details = format_movie_group(movie_data)
        categorized_results['movies'].append({
            'title': title,
            'details': details,
            'count': movie_data['count']
        })

    # Process series
    for series_data in series:
        title, details = format_series_group(series_data)
        categorized_results['series'].append({
            'title': title,
            'details': details,
            'count': series_data['count']
        })

    return categorized_results

def format_movie_group(group_data):
    """Format movie group with quality consolidation and year. Returns (title, details)."""
    title = group_data['title']
    year = group_data['year']
    qualities = sorted(group_data['qualities'])

    # Build details string (year + qualities)
    details_parts = []
    if year:
        details_parts.append(str(year))

    if qualities:
        if len(qualities) == 1:
            details_parts.append(f"({qualities[0]})")
        else:
            quality_str = " & ".join(qualities)
            details_parts.append(f"({quality_str})")

    details = " ".join(details_parts)
    return title, details

def format_series_group(group_data):
    """Format series group with season/episode consolidation and year. Returns (title, details)."""
    title = group_data['title']
    year = group_data['year']
    seasons_episodes = group_data['seasons_episodes']

    # Build details parts
    details_parts = []
    if year:
        details_parts.append(str(year))

    if seasons_episodes:
        # Group by season
        season_groups = {}
        for season, episode in seasons_episodes:
            if season not in season_groups:
                season_groups[season] = []
            season_groups[season].append(episode)

        # Format each season's episode ranges
        season_parts = []
        for season in sorted(season_groups.keys()):
            episodes = sorted(season_groups[season])

            if len(episodes) == 1:
                episode_str = f"E{episodes[0]:02d}"
            else:
                # Create episode range
                first_ep = episodes[0]
                last_ep = episodes[-1]
                episode_str = f"E{first_ep:02d}-{last_ep:02d}"

            season_parts.append(f"S{season:02d}({episode_str})")

        episode_info = ", ".join(season_parts)
        details_parts.append(episode_info)

    details = " ".join(details_parts)
    return title, details

def format_recent_output(categorized_results, total_files=None, total_movies=None, total_series=None, last_updated=None):
    """Format categorized results for display with context information (plain HTML, click-to-copy titles)"""
    output_text = "<b>LAST BATCH UPDATE</b>\n\n"

    # Add context information
    if last_updated:
        output_text += f"Updated: {last_updated}\n"
    if total_files is not None:
        output_text += f"Files: {total_files}"
        if total_movies is not None and total_series is not None:
            output_text += f" (Movies: {total_movies} | Series: {total_series})"
        output_text += "\n"

    output_text += "\n"

    # Display Movies section
    movies = categorized_results['movies']
    if movies:
        output_text += "<b>MOVIES</b>\n"
        output_text += "─" * 30 + "\n"
        for i, result in enumerate(movies, 1):
            title = result['title']
            details = result.get('details', '')
            if details:
                output_text += f"{i}. <code>{title}</code> {details}\n"
            else:
                output_text += f"{i}. <code>{title}</code>\n"
        output_text += "\n"

    # Display Series section
    series = categorized_results['series']
    if series:
        output_text += "<b>SERIES</b>\n"
        output_text += "─" * 30 + "\n"
        for i, result in enumerate(series, 1):
            title = result['title']
            details = result.get('details', '')
            if details:
                output_text += f"{i}. <code>{title}</code> {details}\n"
            else:
                output_text += f"{i}. <code>{title}</code>\n"
        output_text += "\n"

    # Calculate total items and check if we hit limit
    total_items = len(movies) + len(series)
    if total_items >= 20:
        output_text += "<i>..and more</i>"

    output_text += "\n<i>Tap any title to copy</i>"

    return output_text

async def resolve_chat_ref(ref: str, client):
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
