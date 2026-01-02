"""
Indexing System Module

This module handles the indexing of media files from channels.
It includes functions for processing messages, extracting metadata,
and storing file information in the database.
"""

import os
import re
import asyncio
import sys
import threading
import time
import uuid
from datetime import datetime, timezone
from collections import deque

from hydrogram import enums
from hydrogram.types import Message
from hydrogram.errors import FloodWait

from .config import AUTO_INDEX_DEFAULT, INDEX_EXTENSIONS, indexing_lock, active_indexing_threads, indexing_stats, message_queue, queue_processor_task, temp_data
from .database import movies_col, channels_col, settings_col
from .metadata_parser import parse_metadata
from .utils import get_readable_time


async def start_indexing_process(client, msg, chat_id, last_msg_id, skip):
    """Enhanced indexing process using Hydrogram's get_chat_history"""
    start_time = time.time()
    total_files = 0
    duplicate = 0
    errors = 0
    deleted = 0
    no_media = 0
    unsupported = 0
    current = skip

    async with indexing_lock:
        try:
            # Get chat info
            chat = await client.get_chat(chat_id)

            # Update initial message
            await msg.edit_text("🚀 **Starting Indexing Process**\n\n📺 **Channel:** {}\n🔄 **Status:** Initializing...".format(chat.title))

            # Try to use iter_messages as in Auto-Filter-Bot
            print(f"🔍 Attempting to use iter_messages for chat {chat_id}, last_msg_id: {last_msg_id}, skip: {skip}")

            try:
                # Test if iter_messages exists and works
                async for message in client.iter_messages(chat_id, last_msg_id, skip):
                    current += 1
                    time_taken = get_readable_time(time.time() - start_time)

                    # Check for cancellation
                    if temp_data.CANCEL:
                        temp_data.CANCEL = False
                        await msg.edit_text(
                            f"❌ **Indexing Cancelled!**\n\n"
                            f"📺 **Channel:** {chat.title}\n"
                            f"⏱️ **Time Taken:** {time_taken}\n"
                            f"📊 **Progress:** {current}/{last_msg_id}\n\n"
                            f"✅ **Saved:** {total_files} files\n"
                            f"🔄 **Duplicates:** {duplicate}\n"
                            f"🗑️ **Deleted:** {deleted}\n"
                            f"📄 **No Media:** {no_media}\n"
                            f"❌ **Errors:** {errors}"
                        )
                        return

                    # Update progress every 30 messages
                    if current % 30 == 0:
                        try:
                            from hydrogram.types import InlineKeyboardMarkup, InlineKeyboardButton
                            btn = [[InlineKeyboardButton('🛑 CANCEL', callback_data='index#cancel')]]
                            await msg.edit_text(
                                f"🔄 **Indexing In Progress**\n\n"
                                f"📺 **Channel:** {chat.title}\n"
                                f"⏱️ **Time:** {time_taken}\n"
                                f"📊 **Progress:** {current}/{last_msg_id}\n\n"
                                f"✅ **Saved:** {total_files} files\n"
                                f"🔄 **Duplicates:** {duplicate}\n"
                                f"🗑️ **Deleted:** {deleted}\n"
                                f"📄 **No Media:** {no_media}\n"
                                f"⚠️ **Unsupported:** {unsupported}\n"
                                f"❌ **Errors:** {errors}",
                                reply_markup=InlineKeyboardMarkup(btn)
                            )
                        except FloodWait as e:
                            await asyncio.sleep(e.value)
                        except Exception:
                            pass  # Continue if update fails

                    # Process message
                    if message.empty:
                        deleted += 1
                        continue
                    elif not message.media:
                        no_media += 1
                        continue
                    elif message.media not in [enums.MessageMediaType.VIDEO, enums.MessageMediaType.DOCUMENT]:
                        unsupported += 1
                        continue

                    # Get media object
                    media = getattr(message, message.media.value, None)
                    if not media:
                        unsupported += 1
                        continue

                    # Check file extension for documents
                    if message.media == enums.MessageMediaType.DOCUMENT:
                        if not hasattr(media, 'file_name') or not media.file_name:
                            unsupported += 1
                            continue

                        file_ext = os.path.splitext(media.file_name.lower())[1]
                        if file_ext not in INDEX_EXTENSIONS:
                            unsupported += 1
                            continue

                    # Save file
                    try:
                        result = await save_file_to_db(media, message)
                        if result == 'suc':
                            total_files += 1
                        elif result == 'dup':
                            duplicate += 1
                        elif result == 'err':
                            errors += 1
                    except Exception as e:
                        errors += 1
                        print(f"❌ Error processing message {message.id}: {e}")

                # Final success message
                time_taken = get_readable_time(time.time() - start_time)
                await msg.edit_text(
                    f"✅ **Indexing Complete!**\n\n"
                    f"📺 **Channel:** {chat.title}\n"
                    f"⏱️ **Time Taken:** {time_taken}\n"
                    f"📊 **Total Processed:** {current}/{last_msg_id}\n\n"
                    f"✅ **Successfully Saved:** {total_files} files\n"
                    f"🔄 **Duplicates Skipped:** {duplicate}\n"
                    f"🗑️ **Deleted Messages:** {deleted}\n"
                    f"📄 **Non-Media Messages:** {no_media}\n"
                    f"⚠️ **Unsupported Media:** {unsupported}\n"
                    f"❌ **Errors:** {errors}\n\n"
                    f"🎉 **Indexing completed successfully!**"
                )

            except AttributeError as e:
                print(f"❌ iter_messages not available: {e}")
                await msg.edit_text(
                    f"❌ **Method Not Available**\n\n"
                    f"The `iter_messages` method is not available in this version of Hydrogram.\n\n"
                    f"**Error:** {e}\n\n"
                    f"**Available alternatives:**\n"
                    f"• Use real-time auto-indexing instead\n"
                    f"• Forward messages manually for indexing\n"
                    f"• Check Hydrogram version compatibility"
                )
                return
            except Exception as e:
                print(f"❌ iter_messages error: {e}")
                await msg.edit_text(
                    f"❌ **Indexing Error**\n\n"
                    f"An error occurred while trying to index messages.\n\n"
                    f"**Error:** {e}\n\n"
                    f"This might be due to:\n"
                    f"• Bot API limitations\n"
                    f"• Insufficient permissions\n"
                    f"• Network issues"
                )
                return

        except Exception as e:
            await msg.edit_text(f"❌ **Error:** {e}")
            print(f"❌ Indexing error: {e}")


async def save_file_to_db(media, message):
    """Enhanced file saving function compatible with Hydrogram"""
    try:
        # Extract file information
        if hasattr(media, 'file_name') and media.file_name:
            file_name = media.file_name
        else:
            file_name = f"file_{message.id}"

        # Clean filename for better searching
        clean_name = re.sub(r"@\w+|(_|\-|\.|\+)", " ", str(file_name))

        # Get file caption
        file_caption = ""
        if hasattr(media, 'caption') and media.caption:
            file_caption = re.sub(r"@\w+|(_|\-|\.|\+)", " ", str(media.caption))
        elif message.caption:
            file_caption = re.sub(r"@\w+|(_|\-|\.|\+)", " ", str(message.caption))

        # Create document for database
        document = {
            '_id': f"{message.chat.id}_{message.id}",  # Unique identifier
            'file_name': clean_name,
            'original_file_name': file_name,
            'file_size': getattr(media, 'file_size', 0),
            'caption': file_caption,
            'channel_id': message.chat.id,
            'message_id': message.id,
            'date': message.date,
            'indexed_at': datetime.now(timezone.utc),
            'file_type': 'video' if hasattr(media, 'duration') else 'document',
            'duration': getattr(media, 'duration', 0),
            'mime_type': getattr(media, 'mime_type', ''),
        }

        # Parse additional metadata
        metadata = parse_metadata(file_caption, file_name)
        document.update(metadata)

        try:
            # Insert into database
            await movies_col.insert_one(document)
            return 'suc'
        except Exception as e:
            if 'duplicate key' in str(e).lower():
                return 'dup'
            else:
                print(f"❌ Database error: {e}")
                return 'err'

    except Exception as e:
        print(f"❌ Error saving file: {e}")
        return 'err'


async def index_message(msg):
    """Index a single message from a channel"""
    try:
        # Debug logging (remove this in production)
        # print(f"🔍 Index attempt: Chat={getattr(msg.chat, 'type', 'None')} ID={getattr(msg.chat, 'id', 'None')} HasVideo={getattr(msg, 'video', None) is not None} HasDoc={getattr(msg, 'document', None) is not None}")

        # DIAGNOSTIC LOG: Track indexing attempts
        import threading
        current_thread = threading.current_thread().ident
        timestamp = datetime.now(timezone.utc).isoformat()
        print(f"[DIAGNOSTIC] {timestamp} - index_message() called for msg {msg.id} on thread {current_thread}")

        # must be channel, supergroup, or forum post
        if getattr(msg, "chat", None) is None:
            print(f"[DIAGNOSTIC] {timestamp} - Message {msg.id} skipped: No chat object")
            return

        chat_type = getattr(msg.chat, "type", None)
        # Handle both string and enum values
        chat_type_str = str(chat_type).lower() if chat_type else ""
        if not any(supported in chat_type_str for supported in ["channel", "supergroup", "forum"]):
            print(f"[DIAGNOSTIC] {timestamp} - Message {msg.id} skipped: Unsupported chat type {chat_type}")
            return

        # Only index channels that exist in channels_col and enabled True
        chdoc = await channels_col.find_one({"channel_id": msg.chat.id})
        if not chdoc or not chdoc.get("enabled", True):
            print(f"[DIAGNOSTIC] {timestamp} - Message {msg.id} skipped: Channel {msg.chat.id} not registered or disabled")
            return

        # Only process video or documents with video mime
        has_video = getattr(msg, "video", None) is not None
        has_doc = getattr(msg, "document", None) is not None and getattr(msg.document, "mime_type", "").startswith("video")
        if not (has_video or has_doc):
            print(f"[DIAGNOSTIC] {timestamp} - Message {msg.id} skipped: No video content")
            return

        # DIAGNOSTIC LOG: Track duplicate check race condition
        print(f"[DIAGNOSTIC] {timestamp} - Checking for duplicate of message {msg.id} in channel {msg.chat.id}")
        
        # Avoid duplicates
        existing = await movies_col.find_one({"channel_id": msg.chat.id, "message_id": msg.id})
        if existing:
            print(f"[DIAGNOSTIC] {timestamp} - Message {msg.id} skipped: Already exists in database")
            return
        
        print(f"[DIAGNOSTIC] {timestamp} - Message {msg.id} passed duplicate check, proceeding with database insertion")

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
            "upload_date": datetime.utcfromtimestamp(msg.date.timestamp()) if getattr(msg, "date", None) else datetime.now(timezone.utc),
            "channel_id": msg.chat.id,
            "channel_title": getattr(msg.chat, "title", None),
            "message_id": msg.id,
            "caption": caption,
            "indexed_at": datetime.now(timezone.utc)
        }

        # DIAGNOSTIC LOG: Track database insertion
        timestamp = datetime.now(timezone.utc).isoformat()
        print(f"[DIAGNOSTIC] {timestamp} - Attempting to insert message {msg.id} into database")
        
        try:
            await movies_col.insert_one(entry)
            print(f"[DIAGNOSTIC] {timestamp} - Successfully inserted message {msg.id} into database")
            indexing_stats['successful_inserts'] += 1
            from .user_management import log_action
            await log_action("indexed_message", extra={"title": entry["title"], "channel_id": entry["channel_id"], "message_id": entry["message_id"]})
            print(f"[INDEXED] {entry['title']} from {entry['channel_title']}")
        except Exception as db_error:
            print(f"[DIAGNOSTIC] {timestamp} - Database insertion failed for message {msg.id}: {str(db_error)}")
            # Check if it's a duplicate key error
            if 'duplicate key' in str(db_error).lower():
                print(f"[DIAGNOSTIC] {timestamp} - Duplicate key error detected for message {msg.id} - RACE CONDITION CONFIRMED")
                indexing_stats['duplicate_errors'] += 1
            else:
                print(f"[DIAGNOSTIC] {timestamp} - Other database error for message {msg.id}: {str(db_error)}")
                indexing_stats['other_errors'] += 1
            from .user_management import log_action
            await log_action("index_error", extra={"error": str(db_error)})
            print("Index error:", db_error)
    except Exception as e:
        from .user_management import log_action
        await log_action("index_error", extra={"error": str(e)})
        print("Index error:", e)


async def process_message_queue():
    """Process messages from queue sequentially to avoid race conditions"""
    print("[DIAGNOSTIC] Message queue processor started")
    
    # Batch statistics
    batch_stats = {
        'processed': 0,
        'success': 0,
        'error': 0,
        'skipped': 0
    }
    
    from .logger import logger
    
    while True:
        try:
            # Check if queue is empty to finalize batch
            if not message_queue:
                # If we have processed messages in this batch, log the summary
                if batch_stats['processed'] > 0:
                     summary = (
                        f"INDEX - Index completed - "
                        f"Processed {batch_stats['processed']} - "
                        f"{batch_stats['success']} satisfied - "
                        f"{batch_stats['skipped']} skipped - "
                        f"{batch_stats['error']} errors"
                     )
                     logger.log(summary)
                     
                     # Reset stats
                     batch_stats = {
                        'processed': 0,
                        'success': 0,
                        'error': 0,
                        'skipped': 0
                     }
                
                await asyncio.sleep(1)  # Wait for new messages
                continue
                
            message = message_queue.popleft()
            if not message:
                await asyncio.sleep(1)  # Wait for new messages
                continue
                
            # Process message sequentially
            current_thread = threading.current_thread().ident
            timestamp = datetime.now(timezone.utc).isoformat()
            
            # Count as processed
            batch_stats['processed'] += 1
            
            print(f"[DIAGNOSTIC] {timestamp} - Processing queued message {message.id} on thread {current_thread}")
            
            # Check if this message has media before attempting to index
            has_video = getattr(message, "video", None) is not None
            has_doc = getattr(message, "document", None) is not None and getattr(message.document, "mime_type", "").startswith("video")
            
            if has_video or has_doc:
                print(f"[DIAGNOSTIC] {timestamp} - Media detected in queued message {message.id}, attempting to index...")
                
                try:
                    await index_message(message)
                    indexing_stats['successful_inserts'] += 1
                    batch_stats['success'] += 1
                    print(f"[DIAGNOSTIC] {timestamp} - Successfully indexed queued message {message.id}")
                except Exception as e:
                    indexing_stats['other_errors'] += 1
                    batch_stats['error'] += 1
                    print(f"[DIAGNOSTIC] {timestamp} - ERROR indexing queued message {message.id}: {str(e)}")
            else:
                batch_stats['skipped'] += 1
                print(f"[DIAGNOSTIC] {timestamp} - Queued message {message.id} skipped: No media content")
                
        except Exception as e:
            print(f"[DIAGNOSTIC] Message queue processor error: {e}")
            await asyncio.sleep(5)  # Brief pause before retrying


async def on_message(client, message):
    """Handle incoming messages for auto-indexing and user input"""
    # Check for user input waiting (replacement for client.listen)
    if message.chat and message.from_user:
        from .utils import set_user_input
        from .config import user_input_events

        # Check if this is a premium management input
        key = f"{message.chat.id}_{message.from_user.id}"
        if key in user_input_events:
            input_data = user_input_events[key]
            # Check if there's a pending premium input type
            if 'input_type' in input_data and input_data['input_type'].startswith('premium_'):
                from .premium_commands import handle_premium_user_input
                await handle_premium_user_input(client, message, input_data['input_type'])
                # Clean up the event
                del user_input_events[key]
                return

        set_user_input(message.chat.id, message.from_user.id, message)

    # DIAGNOSTIC: Check if this is a command message
    if message.text and message.text.startswith('/'):
        timestamp = datetime.now(timezone.utc).isoformat()
        print(f"[DIAGNOSTIC] {timestamp} - COMMAND DETECTED: {message.text} - This should be handled by command handler, not indexing!")
        # Don't process commands in indexing - let them fall through to command handler
        return
    # Auto-indexing for channel messages
    s = await settings_col.find_one({"k": "auto_indexing"})
    auto_index = s["v"] if s and "v" in s else AUTO_INDEX_DEFAULT

    if auto_index:
        import threading
        current_thread = threading.current_thread().ident
        timestamp = datetime.now(timezone.utc).isoformat()
        
        # Add message to queue for sequential processing
        message_queue.append(message)
        
        # Start queue processor if not already running
        global queue_processor_task
        if queue_processor_task is None:
            queue_processor_task = asyncio.create_task(process_message_queue())
            print(f"[DIAGNOSTIC] {timestamp} - Started message queue processor task")
        
        # Update global indexing statistics
        indexing_stats['total_attempts'] += 1
        
        # Log message arrival for analysis
        print(f"[DIAGNOSTIC] {timestamp} - Message {message.id} queued for sequential processing")
        print(f"[DIAGNOSTIC] {timestamp} - Queue size: {len(message_queue)}")


