"""
Callback Handling Module

This module contains all callback handlers for inline buttons and user interactions.
It handles file requests, pagination, bulk downloads, and other button interactions.
"""

import asyncio
import uuid
from datetime import datetime, timezone
from hydrogram import Client, filters
from hydrogram.types import Message, InlineQuery, InlineQueryResultArticle, InputTextMessageContent, InlineKeyboardMarkup, InlineKeyboardButton, CallbackQuery
from hydrogram.enums import ParseMode

# Import from our modules
from .config import LOG_CHANNEL
from .database import users_col, movies_col
from .config import bulk_downloads
from .utils import cleanup_expired_bulk_downloads
from .file_deletion import track_file_for_deletion
from .search import format_file_size, send_search_results
from .user_management import should_process_command_for_user, has_accepted_terms, is_admin, log_action

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

            try:
                # Get the message from the channel to extract media
                msg = await client.get_messages(channel_id, message_id)

                if not msg:
                    raise Exception("Message not found")

                # Extract media and send using send_cached_media (no forward header)
                sent_message = None
                if msg.video:
                    sent_message = await client.send_cached_media(
                        chat_id=callback_query.from_user.id,
                        file_id=msg.video.file_id,
                        caption=msg.caption or ""
                    )
                elif msg.document:
                    sent_message = await client.send_cached_media(
                        chat_id=callback_query.from_user.id,
                        file_id=msg.document.file_id,
                        caption=msg.caption or ""
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

                    # Extract media and send using send_cached_media (no forward header)
                    sent_message = None
                    if msg.video:
                        sent_message = await client.send_cached_media(
                            chat_id=callback_query.from_user.id,
                            file_id=msg.video.file_id,
                            caption=msg.caption or ""
                        )
                    elif msg.document:
                        sent_message = await client.send_cached_media(
                            chat_id=callback_query.from_user.id,
                            file_id=msg.document.file_id,
                            caption=msg.caption or ""
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
                            result = await movies_col.delete_one({"_id": doc['_id']})
                            if result.deleted_count > 0:
                                deleted_count += 1
                                deleted_titles.append(doc.get('title', 'Unknown'))
                        except Exception as e:
                            errors += 1
                            print(f"Error deleting entry {doc['_id']}: {e}")

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

        else:
            await callback_query.answer("❌ Unknown action.", show_alert=True)

    except Exception as e:
        print(f"❌ Callback error: {e}")
        await callback_query.answer("❌ An error occurred.", show_alert=True)
