"""
Callback Handling Module

This module contains all callback handlers for inline buttons and user interactions.
It handles file requests, pagination, bulk downloads, and other button interactions.
"""

import asyncio
import uuid
from datetime import datetime, timezone
from bson import ObjectId
from hydrogram import Client, filters
from hydrogram.types import Message, InlineQuery, InlineQueryResultArticle, InputTextMessageContent, InlineKeyboardMarkup, InlineKeyboardButton, CallbackQuery
from hydrogram.enums import ParseMode

# Import from our modules
from .config import LOG_CHANNEL, client
from .database import users_col, movies_col, requests_col, premium_users_col, premium_features_col
from .config import bulk_downloads, temp_data, user_input_events
from .utils import cleanup_expired_bulk_downloads, wait_for_user_input, set_user_input, construct_final_caption
from .file_deletion import track_file_for_deletion
from .search import format_file_size, send_search_results
from .user_management import should_process_command_for_user, has_accepted_terms, is_admin, log_action
from .premium_management import is_premium_user, get_premium_user, add_premium_user, edit_premium_user, remove_premium_user, get_days_remaining, is_feature_premium_only, toggle_feature, add_premium_feature, get_all_premium_features, get_all_premium_users

async def callback_handler(client, callback_query: CallbackQuery):
    """Handle inline button callbacks"""
    try:
        data = callback_query.data
        user_id = callback_query.from_user.id

        print(f"🔧 DEBUG: Callback received - Data: {data}, User: {user_id}")

        # Handle terms acceptance (bypass access control for this)
        if data.startswith("terms#"):
            action = data.split("#")[1]

            if action == "accept":
                # User accepted terms
                await users_col.update_one(
                    {"user_id": user_id},
                    {
                        "$set": {
                            "terms_accepted": True,
                            "terms_accepted_at": datetime.now(timezone.utc),
                            "last_seen": datetime.now(timezone.utc)
                        }
                    },
                    upsert=True
                )

                # Log acceptance
                await log_action("terms_accepted", by=user_id)

                # Update message to show acceptance
                await callback_query.message.edit_text(
                    "✅ **Terms Accepted**\n\n"
                    "Thank you for accepting our Terms of Use and Privacy Policy!\n\n"
                    "You can now use all features of MovieBot.\n\n"
                    "Use /help to see available commands.",
                    parse_mode=ParseMode.MARKDOWN
                )

                await callback_query.answer("✅ Terms accepted! Welcome to MovieBot!", show_alert=True)

            elif action == "decline":
                # User declined terms
                await callback_query.message.edit_text(
                    "❌ **Terms Declined**\n\n"
                    "You have declined Terms of Use and Privacy Policy.\n\n"
                    "Unfortunately, you cannot use this bot without accepting terms.\n\n"
                    "If you change your mind, use /start to view terms again.",
                    parse_mode=ParseMode.MARKDOWN
                )

                await callback_query.answer("You must accept terms to use this bot.", show_alert=True)

            return

        # Check access control for all other callbacks
        if not await should_process_command_for_user(user_id):
            await callback_query.answer("🚫 Access denied.", show_alert=True)
            return

        # Check terms acceptance for all other callbacks
        if not await has_accepted_terms(user_id) and not await is_admin(user_id):
            await callback_query.answer(
                "⚠️ You must accept Terms of Use first. Use /start to accept.",
                show_alert=True
            )
            return

        if data.startswith("get_file:"):
            # Handle single file request
            _, channel_id, message_id = data.split(":")
            channel_id = int(channel_id)
            message_id = int(message_id)

            await callback_query.answer("📥 Fetching file...")
            
            # Track download
            try:
                await users_col.update_one(
                    {"user_id": user_id},
                    {
                        "$inc": {"download_count": 1},
                        "$push": {"download_history": {
                            "channel_id": channel_id,
                            "message_id": message_id,
                            "ts": datetime.now(timezone.utc)
                        }}
                    },
                    upsert=True
                )
            except Exception as e:
                print(f"⚠️ Failed to track download for user {user_id}: {e}")

            try:
                # Get the message from the channel to extract media
                msg = await client.get_messages(channel_id, message_id)

                if not msg:
                    raise Exception("Message not found")

                # Parse custom caption from database
                db_item = await movies_col.find_one({"channel_id": channel_id, "message_id": message_id})
                final_caption = construct_final_caption(db_item) or msg.caption or ""

                # Extract media and send using send_cached_media (no forward header)
                sent_message = None
                if msg.video:
                    sent_message = await client.send_cached_media(
                        chat_id=callback_query.from_user.id,
                        file_id=msg.video.file_id,
                        caption=final_caption
                    )
                elif msg.document:
                    sent_message = await client.send_cached_media(
                        chat_id=callback_query.from_user.id,
                        file_id=msg.document.file_id,
                        caption=final_caption
                    )
                else:
                    raise Exception("Message does not contain video or document")

                # Track sent file for auto-deletion
                if sent_message:
                    await track_file_for_deletion(
                        user_id=callback_query.from_user.id,
                        message_id=sent_message.id
                    )
                    
                    # Send immediate notification about auto-deletion
                    try:
                        await client.send_message(
                            callback_query.from_user.id,
                            "⏰ **Auto-Delete Notice**\n\n"
                            "This file will be **automatically deleted in 5 minutes**.\n"
                            "You'll receive a 2-minute warning before deletion.\n\n"
                            "💡 Please save the file if you want to keep it!"
                        )
                    except Exception as notify_error:
                        print(f"❌ Failed to send auto-delete notification: {notify_error}")

                # Show success notification without editing the message
                await callback_query.answer("✅ File sent successfully!", show_alert=True)

            except Exception as e:
                # If forwarding fails, show error notification
                await callback_query.answer(f"❌ Failed to fetch file: {str(e)}", show_alert=True)

        elif data.startswith("page:"):
            # Handle pagination callback
            _, search_id, page_str = data.split(":")
            page = int(page_str)

            # Retrieve search data
            if search_id not in bulk_downloads:
                await callback_query.answer("❌ Search expired or not found", show_alert=True)
                return

            search_data = bulk_downloads[search_id]

            # Verify user permission
            if search_data['user_id'] != callback_query.from_user.id:
                await callback_query.answer("❌ You can only navigate your own searches", show_alert=True)
                return

            results = search_data['results']
            query = search_data['query']

            await callback_query.answer(f"📄 Page {page}")

            # Update message with new page
            # Create header
            RESULTS_PER_PAGE = 9
            total_results = len(results)
            total_pages = (total_results + RESULTS_PER_PAGE - 1) // RESULTS_PER_PAGE

            # Calculate start and end indices for current page
            start_idx = (page - 1) * RESULTS_PER_PAGE
            end_idx = min(start_idx + RESULTS_PER_PAGE, total_results)
            page_results = results[start_idx:end_idx]

            # Create search text
            search_text = f"```\n"
            search_text += f"Search: \"{query}\"\n"
            search_text += f"Total Results: {total_results} | Page {page}/{total_pages}\n\n"

            # Format each result on current page
            button_data = []
            for i, result in enumerate(page_results, start=start_idx + 1):
                title = result.get('title', 'Unknown Title')
                year = result.get('year')
                quality = result.get('quality')
                rip = result.get('rip')
                movie_type = result.get('type', 'Movie')
                season = result.get('season')
                episode = result.get('episode')
                file_size = result.get('file_size')
                channel_id = result.get('channel_id')
                message_id = result.get('message_id')

                # Format file size
                size_str = format_file_size(file_size)
                quality_str = quality if quality else ""

                # Format season/episode info for series
                series_info = ""
                if movie_type.lower() in ['series', 'tv', 'show'] and (season or episode):
                    if season and episode:
                        series_info = f"S{season:02d}E{episode:02d}"
                    elif season:
                        series_info = f"S{season:02d}"
                    elif episode:
                        series_info = f"E{episode:02d}"

                year_str = str(year) if year else ""

                # Format rip type
                rip_str = ""
                if rip and rip.lower() in ['bluray', 'blu-ray', 'bdrip', 'bd']:
                    rip_str = "Blu"
                elif rip and 'web' in rip.lower():
                    rip_str = "Web"
                elif rip and 'hd' in rip.lower():
                    rip_str = "HD"

                # Build info string
                info_parts = []
                if size_str != "N/A":
                    info_parts.append(size_str)
                if quality_str:
                    info_parts.append(quality_str)
                if series_info:
                    info_parts.append(series_info)
                if year_str:
                    info_parts.append(year_str)
                if rip_str:
                    info_parts.append(rip_str)

                info_string = ".".join(info_parts) if info_parts else "N/A"
                search_text += f"{i}. {title} [{info_string}]\n"

                if channel_id and message_id:
                    button_data.append({
                        'number': i,
                        'channel_id': channel_id,
                        'message_id': message_id
                    })

            search_text += f"```"

            # Create buttons
            buttons = []
            if button_data:
                # Create individual file buttons in rows of 3
                current_row = []
                for btn in button_data:
                    current_row.append(
                        InlineKeyboardButton(
                            f"Get [{btn['number']}]",
                            callback_data=f"get_file:{btn['channel_id']}:{btn['message_id']}"
                        )
                    )
                    if len(current_row) == 3 or btn == button_data[-1]:
                        buttons.append(current_row)
                        current_row = []

                # Create navigation row
                nav_row = []

                # Previous button
                if page > 1:
                    nav_row.append(
                        InlineKeyboardButton(
                            "← Prev",
                            callback_data=f"page:{search_id}:{page-1}"
                        )
                    )

                # Get All button
                if total_results > 1:
                    # Check if Get All is premium-only
                    show_get_all = True
                    if await is_feature_premium_only("get_all"):
                        # Only show if user is premium or admin
                        uid = callback_query.from_user.id
                        if not await is_admin(uid) and not await is_premium_user(uid):
                            show_get_all = False

                    if show_get_all:
                        bulk_id = str(uuid.uuid4())[:8]
                        bulk_downloads[bulk_id] = {
                            'files': [{'channel_id': r.get('channel_id'), 'message_id': r.get('message_id')}
                                     for r in results if r.get('channel_id') and r.get('message_id')][:10],
                            'created_at': datetime.now(timezone.utc),
                            'user_id': callback_query.from_user.id
                        }
                        nav_row.append(
                            InlineKeyboardButton(
                                f"Get All ({total_results})",
                                callback_data=f"bulk:{bulk_id}"
                            )
                        )

                # Next button
                if page < total_pages:
                    nav_row.append(
                        InlineKeyboardButton(
                            "Next →",
                            callback_data=f"page:{search_id}:{page+1}"
                        )
                    )

                if nav_row:
                    buttons.append(nav_row)

            keyboard = InlineKeyboardMarkup(buttons) if buttons else None

            # Edit the message
            await callback_query.edit_message_text(
                search_text,
                reply_markup=keyboard,
                disable_web_page_preview=True
            )

        elif data.startswith("index#"):
            # Handle indexing callback
            parts = data.split("#")
            action = parts[1]

            if action == "yes":
                # Start indexing process
                from .indexing import start_indexing_process
                from .config import temp_data
                chat_id = int(parts[2]) if parts[2].lstrip('-').isdigit() else parts[2]
                last_msg_id = int(parts[3])
                skip = int(parts[4])

                await callback_query.answer("🚀 Starting indexing process...")
                await start_indexing_process(client, callback_query.message, chat_id, last_msg_id, skip)

            elif action == "cancel":
                from .config import temp_data
                temp_data.CANCEL = True
                await callback_query.answer("🛑 Cancelling indexing...")
                await callback_query.message.edit_text("❌ **Indexing Cancelled**\n\nThe indexing process has been cancelled by user request.")

        elif data.startswith("mc#"):
            # Handle manage_channel button callbacks - execute commands directly
            from .commands import (
                cmd_add_channel,
                cmd_remove_channel,
                cmd_index_channel,
                cmd_update_db,
                cmd_reset_channel,
                cmd_toggle_indexing,
                cmd_manage_channel
            )

            parts = data.split("#")
            action = parts[1]

            # Check if user is admin
            if not await is_admin(user_id):
                await callback_query.answer("🚫 Admins only.", show_alert=True)
                return

            # Answer the callback to remove loading state
            await callback_query.answer()

            # Create a pseudo-message object that mimics a command message
            # We need to set from_user to the callback query user
            class PseudoMessage:
                def __init__(self, original_message, user, command_text):
                    self.chat = original_message.chat
                    self.from_user = user
                    self.text = command_text
                    self._original = original_message

                async def reply_text(self, *args, **kwargs):
                    return await self._original.reply_text(*args, **kwargs)

            # Map actions to command text
            command_map = {
                "add": "/add_channel",
                "remove": "/remove_channel",
                "index": "/index_channel",
                "update": "/update_db",
                "reset": "/reset_channel",
                "monitoring": "/toggle_indexing"
            }

            # Create pseudo message with proper from_user and command text
            pseudo_msg = PseudoMessage(
                callback_query.message,
                callback_query.from_user,
                command_map.get(action, "")
            )

            if action == "add":
                await cmd_add_channel(client, pseudo_msg)

            elif action == "remove":
                await cmd_remove_channel(client, pseudo_msg)

            elif action == "index":
                await cmd_index_channel(client, pseudo_msg)

            elif action == "update":
                await cmd_update_db(client, pseudo_msg)

            elif action == "reset":
                await cmd_reset_channel(client, pseudo_msg)

            elif action == "monitoring":
                # Toggle the auto-indexing setting
                from .database import settings_col, channels_col
                from .config import AUTO_INDEX_DEFAULT

                uid = callback_query.from_user.id
                doc = await settings_col.find_one({"k": "auto_indexing"})
                current = doc["v"] if doc else AUTO_INDEX_DEFAULT
                new = not current
                await settings_col.update_one({"k": "auto_indexing"}, {"$set": {"v": new}}, upsert=True)
                await log_action("toggle_indexing", by=uid, extra={"new": new})

                # Show confirmation
                status = "enabled" if new else "disabled"
                await callback_query.answer(f"Auto-indexing {status}", show_alert=False)

                # Refresh the manage_channel display to show updated icon
                # Get updated auto-indexing status
                monitoring_icon = "🟢" if new else "🔴"

                # Get all channels
                channels = await channels_col.find({}).to_list(length=100)

                if not channels:
                    output = "CHANNEL MANAGEMENT\n\n"
                    output += "No channels configured yet.\n\n"
                    output += "QUICK ACTIONS\n"
                    output += "Use the buttons below to manage channels.\n\n"
                    output += "COMMAND GUIDE\n"
                    output += "Add - Add a new channel to monitor\n"
                    output += "Remove - Remove an existing channel\n"
                    output += "Scan - Scan messages from a channel\n"
                    output += "Update - Sync DB with channel (detect new/deleted files)\n"
                    output += "Reset - Clear indexed data from a channel\n"
                    output += "Indexing - Toggle auto-indexing on/off"
                else:
                    # Build aggregation pipeline to get indexed counts per channel
                    pipeline = [
                        {"$group": {"_id": "$channel_id", "count": {"$sum": 1}}},
                        {"$sort": {"count": -1}}
                    ]
                    indexed_counts = await movies_col.aggregate(pipeline).to_list(length=100)

                    # Create a map of channel_id to count
                    count_map = {item["_id"]: item["count"] for item in indexed_counts}

                    # Build output
                    output = "CHANNEL MANAGEMENT\n\n"
                    output += "REGISTERED CHANNELS\n\n"

                    for idx, ch in enumerate(channels, 1):
                        channel_id = ch.get("channel_id")
                        channel_title = ch.get("channel_title", "Unknown")
                        enabled = ch.get("enabled", True)
                        added_at = ch.get("added_at")
                        indexed_count = count_map.get(channel_id, 0)

                        # Format date
                        date_str = "N/A"
                        if added_at:
                            date_str = added_at.strftime("%Y-%m-%d")

                        # Build channel info with click-to-copy ID
                        output += f"{idx}. {channel_title}\n"
                        output += f"   ID: <code>{channel_id}</code>\n"
                        output += f"   Indexed: {indexed_count} files\n"
                        output += f"   Status: {'Enabled' if enabled else 'Disabled'}\n"
                        output += f"   Added: {date_str}\n\n"

                    output += "QUICK ACTIONS\n"
                    output += "Use the buttons below to manage channels.\n\n"
                    output += "COMMAND GUIDE\n"
                    output += "Add - Add a new channel to monitor\n"
                    output += "Remove - Remove an existing channel\n"
                    output += "Scan - Scan messages from a channel\n"
                    output += "Update - Sync DB with channel (detect new/deleted files)\n"
                    output += "Reset - Clear indexed data from a channel\n"
                    output += "Indexing - Toggle auto-indexing on/off"

                # Create updated buttons with new icon
                buttons = [
                    [
                        InlineKeyboardButton("Add", callback_data="mc#add"),
                        InlineKeyboardButton("Remove", callback_data="mc#remove"),
                        InlineKeyboardButton("Scan", callback_data="mc#index")
                    ],
                    [
                        InlineKeyboardButton("Update", callback_data="mc#update"),
                        InlineKeyboardButton("Reset", callback_data="mc#reset"),
                        InlineKeyboardButton(f"{monitoring_icon} Indexing", callback_data="mc#monitoring")
                    ]
                ]

                reply_markup = InlineKeyboardMarkup(buttons)

                # Edit the message to update the display
                await callback_query.edit_message_text(
                    output,
                    reply_markup=reply_markup
                )

        elif data.startswith("bulk:"):
            # Handle bulk download request using stored data
            _, bulk_id = data.split(":", 1)

            # Retrieve bulk download data
            if bulk_id not in bulk_downloads:
                await callback_query.answer("❌ Bulk download expired or not found", show_alert=True)
                return

            bulk_data = bulk_downloads[bulk_id]

            # Verify user permission (only the user who initiated can download)
            if bulk_data['user_id'] != callback_query.from_user.id:
                await callback_query.answer("❌ You can only download your own searches", show_alert=True)
                return

            files = bulk_data['files']
            await callback_query.answer(f"📦 Fetching {len(files)} files...")
            
            # Track bulk download
            try:
                await users_col.update_one(
                    {"user_id": user_id},
                    {
                        "$inc": {"download_count": len(files)},
                        "$push": {"download_history": {
                            "bulk": True,
                            "file_count": len(files),
                            "ts": datetime.now(timezone.utc)
                        }}
                    },
                    upsert=True
                )
            except Exception as e:
                print(f"⚠️ Failed to track bulk download for user {user_id}: {e}")

            success_count = 0
            failed_files = []
            sent_messages = []  # Track sent messages for auto-deletion

            for file_info in files:
                try:
                    channel_id = int(file_info['channel_id'])
                    message_id = int(file_info['message_id'])

                    # Get the message from the channel to extract media
                    msg = await client.get_messages(channel_id, message_id)

                    if not msg:
                        raise Exception("Message not found")

                    # Parse custom caption from database
                    db_item = await movies_col.find_one({"channel_id": channel_id, "message_id": message_id})
                    final_caption = construct_final_caption(db_item) or msg.caption or ""

                    # Extract media and send using send_cached_media (no forward header)
                    sent_message = None
                    if msg.video:
                        sent_message = await client.send_cached_media(
                            chat_id=callback_query.from_user.id,
                            file_id=msg.video.file_id,
                            caption=final_caption
                        )
                    elif msg.document:
                        sent_message = await client.send_cached_media(
                            chat_id=callback_query.from_user.id,
                            file_id=msg.document.file_id,
                            caption=final_caption
                        )
                    else:
                        raise Exception("Message does not contain video or document")

                    if sent_message:
                        sent_messages.append(sent_message.id)
                    success_count += 1

                except Exception as e:
                    print(f"❌ Failed to send {channel_id}:{message_id}: {e}")
                    failed_files.append(f"{channel_id}:{message_id}")
                    continue

            # Track all sent files for auto-deletion
            for msg_id in sent_messages:
                await track_file_for_deletion(
                    user_id=callback_query.from_user.id,
                    message_id=msg_id
                )

            # Send notification about auto-deletion for bulk files
            if sent_messages:
                try:
                    await client.send_message(
                        callback_query.from_user.id,
                        f"⏰ **Auto-Delete Notice**\n\n"
                        f"All {len(sent_messages)} files will be **automatically deleted in 15 minutes**.\n"
                        "You'll receive a 5-minute warning before deletion.\n\n"
                        "💡 Please save files if you want to keep them!"
                    )
                except Exception as notify_error:
                    print(f"❌ Failed to send bulk auto-delete notification: {notify_error}")

            # Clean up temporary data after use
            del bulk_downloads[bulk_id]

            # Update the message with results
            result_text = f"✅ Successfully sent {success_count}/{len(files)} files!"

            if failed_files:
                result_text += f"\n❌ Failed: {len(failed_files)} files"
                result_text += f"\n💡 Add bot as admin to channels for direct file access"

            await callback_query.edit_message_text(
                f"{result_text}\n\n{callback_query.message.text}",
                reply_markup=callback_query.message.reply_markup
            )

        elif data.startswith("hsearch#") or data.startswith("hsearch_exact#"):
            # Handle history search callback
            is_exact = data.startswith("hsearch_exact#")
            query = data.split("#", 1)[1]

            await callback_query.answer(f"🔍 Searching for: {query}")

            # Import search functionality
            from .search import perform_search
            from .config import FUZZY_THRESHOLD

            # Perform the search
            results = await perform_search(query, exact_search=is_exact, fuzzy_threshold=FUZZY_THRESHOLD)

            # Check if results exist
            if not results:
                if is_exact:
                    await callback_query.message.reply_text(
                        f"⚠️ No exact matches found for \"{query}\"\n\n"
                        f"💡 **Try normal search:** /search {query}\n"
                        f"🔍 Normal search finds partial and similar titles"
                    )
                else:
                    await callback_query.message.reply_text("⚠️ No results found for your search.")
                return

            # Send search results as a new message
            await send_search_results(
                client=client,
                message=callback_query.message,
                results=results,
                query=query
            )

            # Record search history
            await users_col.update_one(
                {"user_id": callback_query.from_user.id},
                {"$push": {"search_history": {"q": query, "ts": datetime.now(timezone.utc)}}},
                upsert=True
            )

        elif data.startswith("mdel#"):
            # Handle manual deletion callbacks
            from .config import temp_data

            parts = data.split("#")
            session_id = parts[1]
            action = parts[2]

            temp_data_key = f"manual_deletion_{session_id}"

            # Check if session exists
            if not hasattr(temp_data, 'deletion_sessions') or temp_data_key not in temp_data.deletion_sessions:
                await callback_query.answer("Session expired. Please start a new search with /manual_deletion", show_alert=True)
                return

            session = temp_data.deletion_sessions[temp_data_key]

            # Verify user
            if session['user_id'] != user_id:
                await callback_query.answer("This is not your deletion session.", show_alert=True)
                return

            if action == "toggle":
                # Toggle selection
                idx = int(parts[3])

                if idx in session['selected']:
                    session['selected'].remove(idx)
                else:
                    session['selected'].add(idx)

                # Update buttons to reflect selection
                results = session['results']
                buttons = []

                for i in range(min(len(results), 20)):
                    if i in session['selected']:
                        button_text = f"[X] {i + 1}"
                    else:
                        button_text = f"[ ] {i + 1}"

                    callback_data = f"mdel#{session_id}#toggle#{i}"

                    if i % 2 == 0:
                        buttons.append([InlineKeyboardButton(button_text, callback_data=callback_data)])
                    else:
                        buttons[-1].append(InlineKeyboardButton(button_text, callback_data=callback_data))

                # Add action buttons
                buttons.append([
                    InlineKeyboardButton("Delete Selected", callback_data=f"mdel#{session_id}#confirm"),
                    InlineKeyboardButton("Cancel", callback_data=f"mdel#{session_id}#cancel")
                ])

                # Update message
                try:
                    await callback_query.message.edit_reply_markup(reply_markup=InlineKeyboardMarkup(buttons))
                    await callback_query.answer(f"{'Selected' if idx in session['selected'] else 'Deselected'} entry #{idx + 1}")
                except Exception as e:
                    await callback_query.answer("Error updating selection.", show_alert=True)

            elif action == "confirm":
                # Confirm and delete selected entries
                if not session['selected']:
                    await callback_query.answer("No entries selected. Please select at least one entry to delete.", show_alert=True)
                    return

                await callback_query.answer("Deleting selected entries...")

                # Get selected entries
                results = session['results']
                selected_indices = sorted(session['selected'])
                deleted_count = 0
                errors = 0

                deleted_titles = []

                for idx in selected_indices:
                    if idx < len(results):
                        doc = results[idx]
                        try:
                            # DIAGNOSTIC LOG: Check movies_col before deletion
                            print(f"🔍 DEBUG: About to delete entry {doc['_id']}")
                            print(f"🔍 DEBUG: movies_col available: {movies_col is not None}")
                            
                            result = await movies_col.delete_one({"_id": doc['_id']})
                            if result.deleted_count > 0:
                                deleted_count += 1
                                deleted_titles.append(doc.get('title', 'Unknown'))
                        except Exception as e:
                            errors += 1
                            print(f"Error deleting entry {doc['_id']}: {e}")
                            # DIAGNOSTIC LOG: Check if this is the specific error
                            if "cannot access local variable 'movies_col'" in str(e):
                                print(f"🔍 CRITICAL: This is the movies_col scoping error!")
                                print(f"🔍 DEBUG: movies_col type in exception: {type(movies_col) if 'movies_col' in locals() else 'NOT IN LOCALS'}")

                # Log the action
                await log_action("manual_deletion_confirmed", by=user_id, extra={
                    "session_id": session_id,
                    "search_title": session['search_title'],
                    "selected_count": len(selected_indices),
                    "deleted_count": deleted_count,
                    "errors": errors,
                    "deleted_titles": deleted_titles
                })

                # Update message with results
                result_text = f"**Deletion Complete**\n\n"
                result_text += f"Deleted: {deleted_count} entries\n"
                if errors > 0:
                    result_text += f"Errors: {errors}\n"
                result_text += f"\n**Deleted Entries:**\n"

                for title in deleted_titles[:10]:  # Show first 10
                    result_text += f"{title}\n"

                if len(deleted_titles) > 10:
                    result_text += f"... and {len(deleted_titles) - 10} more\n"

                await callback_query.message.edit_text(result_text)

                # Clean up session
                del temp_data.deletion_sessions[temp_data_key]

                print(f"Manual deletion completed by user {user_id}. Deleted {deleted_count} entries.")

            elif action == "cancel":
                # Cancel deletion
                await callback_query.answer("Deletion cancelled.")

                await callback_query.message.edit_text(
                    "**Deletion Cancelled**\n\n"
                    "No entries were deleted."
                )

                # Clean up session
                del temp_data.deletion_sessions[temp_data_key]

                # Log cancellation
                await log_action("manual_deletion_cancelled", by=user_id, extra={
                    "session_id": session_id,
                    "search_title": session['search_title']
                })

        elif data.startswith("req_done:"):
            # Handle marking a single request as done
            if not await is_admin(user_id):
                await callback_query.answer("🚫 Admins only.", show_alert=True)
                return

            _, req_id_str = data.split(":", 1)

            # Convert string ID to ObjectId
            try:
                req_id = ObjectId(req_id_str)
            except Exception as e:
                await callback_query.answer("❌ Invalid request ID.", show_alert=True)
                print(f"Error converting request ID: {e}")
                return

            # Get request details before deletion
            request = await requests_col.find_one({"_id": req_id})

            if not request:
                await callback_query.answer("❌ Request not found.", show_alert=True)
                return

            # Update request status to completed
            await requests_col.update_one(
                {"_id": req_id},
                {"$set": {"status": "completed", "completed_at": datetime.now(timezone.utc), "completed_by": user_id}}
            )

            # Notify the user
            try:
                notification_text = (
                    f"✅ **Request Fulfilled!**\n\n"
                    f"Your request for **{request.get('title')}** ({request.get('year')}) has been fulfilled.\n\n"
                    f"Thank you for using our service!"
                )
                await client.send_message(request.get("user_id"), notification_text)
            except Exception as e:
                print(f"Failed to notify user {request.get('user_id')}: {e}")

            await callback_query.answer(f"✅ Request marked as done!")

            # Log the action
            await log_action("request_completed", by=user_id, target=request.get("user_id"), extra={
                "title": request.get("title"),
                "year": request.get("year"),
                "request_id": req_id
            })

            # Refresh the request list
            # Get the request_list_id from bulk_downloads to refresh the page
            # For simplicity, just update the message text
            await callback_query.message.edit_text(
                f"✅ Request marked as done!\n\n"
                f"Use /request_list to view updated list."
            )

        elif data.startswith("req_page:"):
            # Handle request list pagination
            if not await is_admin(user_id):
                await callback_query.answer("🚫 Admins only.", show_alert=True)
                return

            _, request_list_id, page_str = data.split(":")
            page = int(page_str)

            # Retrieve request list data
            if request_list_id not in bulk_downloads:
                await callback_query.answer("❌ Request list expired. Use /request_list again.", show_alert=True)
                return

            list_data = bulk_downloads[request_list_id]

            # Verify it's a request list
            if list_data.get('type') != 'request_list':
                await callback_query.answer("❌ Invalid data.", show_alert=True)
                return

            requests_list = list_data['requests']

            await callback_query.answer(f"📄 Page {page}")

            # Import send_request_list_page from commands
            from .commands import send_request_list_page

            # Update message with new page (edit=True for pagination)
            await send_request_list_page(client, callback_query.message, requests_list, request_list_id, page, edit=True)

        elif data.startswith("req_all_done:"):
            # Handle marking all requests as done
            if not await is_admin(user_id):
                await callback_query.answer("🚫 Admins only.", show_alert=True)
                return

            _, request_list_id = data.split(":", 1)

            # Retrieve request list data
            if request_list_id not in bulk_downloads:
                await callback_query.answer("❌ Request list expired. Use /request_list again.", show_alert=True)
                return

            list_data = bulk_downloads[request_list_id]

            # Verify it's a request list
            if list_data.get('type') != 'request_list':
                await callback_query.answer("❌ Invalid data.", show_alert=True)
                return

            requests_list = list_data['requests']

            # Confirm action
            await callback_query.answer("⚠️ Marking all requests as done...", show_alert=True)

            # Mark all as completed
            completed_count = 0
            notified_count = 0

            for request in requests_list:
                # Update status
                await requests_col.update_one(
                    {"_id": request.get("_id")},
                    {"$set": {"status": "completed", "completed_at": datetime.now(timezone.utc), "completed_by": user_id}}
                )
                completed_count += 1

                # Notify user
                try:
                    notification_text = (
                        f"✅ **Request Fulfilled!**\n\n"
                        f"Your request for **{request.get('title')}** ({request.get('year')}) has been fulfilled.\n\n"
                        f"Thank you for using our service!"
                    )
                    await client.send_message(request.get("user_id"), notification_text)
                    notified_count += 1
                except Exception as e:
                    print(f"Failed to notify user {request.get('user_id')}: {e}")

            # Log the action
            await log_action("request_all_completed", by=user_id, extra={
                "completed_count": completed_count,
                "notified_count": notified_count
            })

            # Update message
            await callback_query.message.edit_text(
                f"✅ **All Requests Marked as Done!**\n\n"
                f"**Completed:** {completed_count} requests\n"
                f"**Notified:** {notified_count} users\n\n"
                f"Use /request_list to view updated list."
            )

            # Clean up bulk_downloads
            del bulk_downloads[request_list_id]

        # -------------------------
        # Premium Management Callbacks
        # -------------------------
        elif data.startswith("premium:"):
            # Check if user is admin
            if not await is_admin(user_id):
                await callback_query.answer("🚫 Admins only.", show_alert=True)
                return

            action = data.split(":")[1]

            if action == "add_users":
                await callback_query.answer()
                await callback_query.message.edit_text(
                    "**Add Premium User**\n\n"
                    "Please send the User ID or Username of the user you want to add to premium.\n\n"
                    "You can type **CANCEL** to abort."
                )

                # Set user input event with input_type
                from .config import user_input_events
                key = f"{callback_query.message.chat.id}_{user_id}"
                user_input_events[key] = {'input_type': 'premium_add_user_id', 'event': None, 'message': None}

            elif action == "edit_users":
                await callback_query.answer()
                await callback_query.message.edit_text(
                    "**Edit Premium User**\n\n"
                    "Please send the User ID or Username of the premium user you want to edit.\n\n"
                    "You can type **CANCEL** to abort."
                )

                # Set user input event with input_type
                from .config import user_input_events
                key = f"{callback_query.message.chat.id}_{user_id}"
                user_input_events[key] = {'input_type': 'premium_edit_user_id', 'event': None, 'message': None}

            elif action == "remove_users":
                await callback_query.answer()
                await callback_query.message.edit_text(
                    "**Remove Premium User**\n\n"
                    "Please send the User ID or Username of the premium user you want to remove.\n\n"
                    "You can type **CANCEL** to abort."
                )

                # Set user input event with input_type
                from .config import user_input_events
                key = f"{callback_query.message.chat.id}_{user_id}"
                user_input_events[key] = {'input_type': 'premium_remove_user_id', 'event': None, 'message': None}

            elif action == "manage_features":
                await callback_query.answer()

                # Get all premium features
                features = await get_all_premium_features()

                if not features:
                    await callback_query.message.edit_text(
                        "❌ No premium features found.\n\n"
                        "Use /premium to go back."
                    )
                    return

                # Create feature list with buttons
                feature_text = "**Premium Features Management**\n\n"
                feature_text += "Features marked as ON are premium-only.\n"
                feature_text += "Features marked as OFF are available to all users.\n\n"

                buttons = []
                for feature in features:
                    feature_name = feature.get("feature_name")
                    description = feature.get("description", feature_name)
                    enabled = feature.get("enabled", False)
                    status = "ON" if enabled else "OFF"

                    feature_text += f"**{description}:** {status}\n"

                    button_text = f"[{status}] {description}"
                    buttons.append([
                        InlineKeyboardButton(
                            button_text,
                            callback_data=f"premium_toggle:{feature_name}"
                        )
                    ])

                # Add "Add Feature" button
                buttons.append([
                    InlineKeyboardButton(
                        "Add New Feature",
                        callback_data="premium:add_feature"
                    )
                ])

                # Add back button
                buttons.append([
                    InlineKeyboardButton(
                        "← Back",
                        callback_data="premium:back"
                    )
                ])

                keyboard = InlineKeyboardMarkup(buttons)
                await callback_query.message.edit_text(feature_text, reply_markup=keyboard)

            elif action == "add_feature":
                await callback_query.answer()
                await callback_query.message.edit_text(
                    "**Add New Premium Feature**\n\n"
                    "Please send the feature name (e.g., 'bulk_download', 'advanced_search').\n\n"
                    "You can type **CANCEL** to abort."
                )

                # Set user input event with input_type
                from .config import user_input_events
                key = f"{callback_query.message.chat.id}_{user_id}"
                user_input_events[key] = {'input_type': 'premium_add_feature_name', 'event': None, 'message': None}

            elif action == "back":
                await callback_query.answer()
                # Recreate the main premium menu
                buttons = [
                    [InlineKeyboardButton("Add Users", callback_data="premium:add_users")],
                    [InlineKeyboardButton("Edit Users", callback_data="premium:edit_users")],
                    [InlineKeyboardButton("Remove Users", callback_data="premium:remove_users")],
                    [InlineKeyboardButton("Manage Features", callback_data="premium:manage_features")]
                ]

                keyboard = InlineKeyboardMarkup(buttons)

                help_text = (
                    "**Premium Management System**\n\n"
                    "**Add Users:** Add users to premium with specified duration\n"
                    "**Edit Users:** Modify premium duration for existing users\n"
                    "**Remove Users:** Remove users from premium\n"
                    "**Manage Features:** Control which features are premium-only\n\n"
                    "Select an option below:"
                )

                await callback_query.message.edit_text(help_text, reply_markup=keyboard)

        elif data.startswith("stats_export:"):
            # Handle statistics export callbacks
            if not await is_admin(user_id):
                await callback_query.answer("🚫 Admins only.", show_alert=True)
                return
            
            parts = data.split(":")
            export_format = parts[1]  # json or csv
            stats_id = parts[2]
            
            # Retrieve stats data
            if stats_id not in bulk_downloads:
                await callback_query.answer("❌ Statistics expired. Use /stat again.", show_alert=True)
                return
            
            stats_data = bulk_downloads[stats_id]
            
            # Verify it's a stats export
            if stats_data.get('type') != 'stats_export':
                await callback_query.answer("❌ Invalid data.", show_alert=True)
                return
            
            stats = stats_data['stats']
            
            await callback_query.answer(f"📥 Generating {export_format.upper()} export...")
            
            try:
                if export_format == 'json':
                    from .statistics import export_stats_json
                    export_data = await export_stats_json(stats)
                    
                    if export_data:
                        # Create filename
                        timestamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
                        filename = f"bot_stats_{timestamp}.json"
                        
                        # Send as document
                        await client.send_document(
                            chat_id=callback_query.from_user.id,
                            document=export_data.encode('utf-8'),
                            file_name=filename,
                            caption=f"📊 **Bot Statistics Export**\n\nFormat: JSON\nGenerated: {timestamp}"
                        )
                        
                        await callback_query.message.reply_text("✅ JSON export sent successfully!")
                    else:
                        await callback_query.answer("❌ Failed to generate JSON export.", show_alert=True)
                
                elif export_format == 'csv':
                    from .statistics import export_stats_csv
                    export_data = await export_stats_csv(stats)
                    
                    if export_data:
                        # Create filename
                        timestamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
                        filename = f"bot_stats_{timestamp}.csv"
                        
                        # Send as document
                        await client.send_document(
                            chat_id=callback_query.from_user.id,
                            document=export_data.encode('utf-8'),
                            file_name=filename,
                            caption=f"📊 **Bot Statistics Export**\n\nFormat: CSV\nGenerated: {timestamp}"
                        )
                        
                        await callback_query.message.reply_text("✅ CSV export sent successfully!")
                    else:
                        await callback_query.answer("❌ Failed to generate CSV export.", show_alert=True)
                
                # Log export action
                await log_action("stats_exported", by=user_id, extra={
                    "format": export_format,
                    "stats_id": stats_id
                })
                
            except Exception as e:
                print(f"❌ Export error: {e}")
                await callback_query.answer("❌ Export failed. Please try again.", show_alert=True)
        
        elif data.startswith("premium_toggle:"):
            # Check if user is admin
            if not await is_admin(user_id):
                await callback_query.answer("🚫 Admins only.", show_alert=True)
                return

            feature_name = data.split(":")[1]

            # Toggle the feature
            success, message, new_state = await toggle_feature(feature_name, user_id)

            if success:
                await callback_query.answer(f"✅ {message}")

                # Refresh the feature list
                features = await get_all_premium_features()

                feature_text = "**Premium Features Management**\n\n"
                feature_text += "Features marked as ON are premium-only.\n"
                feature_text += "Features marked as OFF are available to all users.\n\n"

                buttons = []
                for feature in features:
                    fname = feature.get("feature_name")
                    description = feature.get("description", fname)
                    enabled = feature.get("enabled", False)
                    status = "ON" if enabled else "OFF"

                    feature_text += f"**{description}:** {status}\n"

                    button_text = f"[{status}] {description}"
                    buttons.append([
                        InlineKeyboardButton(
                            button_text,
                            callback_data=f"premium_toggle:{fname}"
                        )
                    ])

                # Add "Add Feature" button
                buttons.append([
                    InlineKeyboardButton(
                        "Add New Feature",
                        callback_data="premium:add_feature"
                    )
                ])

                # Add back button
                buttons.append([
                    InlineKeyboardButton(
                        "← Back",
                        callback_data="premium:back"
                    )
                ])

                keyboard = InlineKeyboardMarkup(buttons)
                await callback_query.message.edit_text(feature_text, reply_markup=keyboard)
            else:
                await callback_query.answer(f"❌ {message}", show_alert=True)

        elif data.startswith("trending:"):
            # Handle trending category callbacks
            from .tmdb_integration import get_trending_movies, get_trending_shows, get_new_releases, format_trending_list

            parts = data.split(":")
            category = parts[1]

            # Check if already active (ignore click)
            if len(parts) > 2 and parts[2] == "active":
                await callback_query.answer("Already viewing this category")
                return

            await callback_query.answer(f"Loading {category}...")

            try:
                if category == "movies":
                    items = await get_trending_movies()
                    content = format_trending_list(items, "movies")
                    header = "🔥 **Trending Movies**"
                    buttons = [
                        [
                            InlineKeyboardButton("🟨 Movies", callback_data="trending:movies:active"),
                            InlineKeyboardButton("Shows", callback_data="trending:shows"),
                            InlineKeyboardButton("New Releases", callback_data="trending:releases")
                        ]
                    ]
                elif category == "shows":
                    items = await get_trending_shows()
                    content = format_trending_list(items, "shows")
                    header = "🔥 **Trending Shows**"
                    buttons = [
                        [
                            InlineKeyboardButton("Movies", callback_data="trending:movies"),
                            InlineKeyboardButton("🟩 Shows", callback_data="trending:shows:active"),
                            InlineKeyboardButton("New Releases", callback_data="trending:releases")
                        ]
                    ]
                elif category == "releases":
                    items = await get_new_releases()
                    content = format_trending_list(items, "releases")
                    header = "🔥 **New Releases**"
                    buttons = [
                        [
                            InlineKeyboardButton("Movies", callback_data="trending:movies"),
                            InlineKeyboardButton("Shows", callback_data="trending:shows"),
                            InlineKeyboardButton("🟦 New Releases", callback_data="trending:releases:active")
                        ]
                    ]
                else:
                    await callback_query.answer("Invalid category", show_alert=True)
                    return

                if not items:
                    content = "No data available."

                output = f"{header}\n\n{content}"

                await callback_query.message.edit_text(
                    output,
                    reply_markup=InlineKeyboardMarkup(buttons),
                    disable_web_page_preview=True
                )

            except Exception as e:
                print(f"Error in trending callback: {e}")
                await callback_query.answer("Failed to fetch data", show_alert=True)

        else:
            await callback_query.answer("❌ Unknown action.", show_alert=True)

    except Exception as e:
        print(f"❌ Callback error: {e}")
        await callback_query.answer("❌ An error occurred.", show_alert=True)
