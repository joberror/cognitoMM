"""
Request Commands Module

Handles the user /request flow (TMDb-verified requests, rate limits, upvotes)
and the admin /request_list queue. Extracted from commands.py so the request
surface is a self-contained domain module; commands.py re-imports the handlers
for its router.
"""

import asyncio
import uuid
from datetime import datetime, timezone

from pyrogram.types import Message, InlineKeyboardMarkup, InlineKeyboardButton

from .config import bulk_downloads
from .database import requests_col
from .utils import wait_for_user_input
from .user_management import is_admin, log_action
from .premium_management import is_premium_user, is_feature_premium_only
from .request_management import (
    check_rate_limits,
    update_user_limits,
    check_duplicate_request,
    get_queue_position,
    find_global_match,
    upvote_request,
    request_priority_key,
    MAX_PENDING_REQUESTS_PER_USER,
)
from .tmdb_integration import search_tmdb


async def cmd_request(client, message: Message):
    """Handle /request command for movie/series requests"""
    uid = message.from_user.id
    username = message.from_user.username or message.from_user.first_name or str(uid)

    try:
        # Check if user is admin (admins bypass rate limits for testing)
        user_is_admin = await is_admin(uid)

        # Check if feature is premium-only
        if await is_feature_premium_only("request"):
            # Check if user is premium or admin
            if not user_is_admin and not await is_premium_user(uid):
                return await message.reply_text(
                    "⭐ **Premium Feature**\n\n"
                    "The /request command is a premium-only feature.\n\n"
                    "Contact an admin to get premium access."
                )

        # Check rate limits (skip for admins)
        if not user_is_admin:
            can_request, error_msg = await check_rate_limits(uid)
            if not can_request:
                await message.reply_text(error_msg)
                return

        # Start interactive request flow with warning
        await message.reply_text(
            "📝 **Movie/Series Request**\n\n"
            "⚠️ **IMPORTANT WARNING:**\n"
            "Before requesting, please search the database using /search to ensure the content is not already available.\n"
            "Requesting content that already exists may result in a ban from the bot.\n\n"
            "Let's gather the information for your request.\n"
            "You can type **CANCEL** at any step to abort.\n\n"
            "**Step 1/3:** What type of content are you requesting?\n"
            "Reply with: **Movie** or **Series**"
        )

        # Wait for content type
        try:
            type_msg = await wait_for_user_input(message.chat.id, uid, timeout=120)
        except asyncio.TimeoutError:
            await message.reply_text("⏰ Request timeout. Please start over with /request")
            return

        if not type_msg or not type_msg.text:
            await message.reply_text("❌ Invalid input. Please start over with /request")
            return

        content_type_input = type_msg.text.strip().upper()

        if content_type_input == "CANCEL":
            await message.reply_text("❌ Request cancelled.")
            return

        if content_type_input not in ["MOVIE", "SERIES"]:
            await message.reply_text("❌ Invalid type. Please use 'Movie' or 'Series'. Start over with /request")
            return

        content_type = "Movie" if content_type_input == "MOVIE" else "Series"

        # Step 2: Get title
        await message.reply_text(
            f"✅ Type: **{content_type}**\n\n"
            f"**Step 2/3:** What is the title/name?\n"
            f"Reply with the {content_type.lower()} title."
        )

        try:
            title_msg = await wait_for_user_input(message.chat.id, uid, timeout=120)
        except asyncio.TimeoutError:
            await message.reply_text("⏰ Request timeout. Please start over with /request")
            return

        if not title_msg or not title_msg.text:
            await message.reply_text("❌ Invalid input. Please start over with /request")
            return

        title = title_msg.text.strip()

        if title.upper() == "CANCEL":
            await message.reply_text("❌ Request cancelled.")
            return

        if len(title) < 2:
            await message.reply_text("❌ Title too short. Please start over with /request")
            return

        # Step 3: Get year
        await message.reply_text(
            f"✅ Title: **{title}**\n\n"
            f"**Step 3/3:** What is the release year?\n"
            f"Reply with a 4-digit year (e.g., 2024)."
        )

        try:
            year_msg = await wait_for_user_input(message.chat.id, uid, timeout=120)
        except asyncio.TimeoutError:
            await message.reply_text("⏰ Request timeout. Please start over with /request")
            return

        if not year_msg or not year_msg.text:
            await message.reply_text("❌ Invalid input. Please start over with /request")
            return

        year_input = year_msg.text.strip()

        if year_input.upper() == "CANCEL":
            await message.reply_text("❌ Request cancelled.")
            return

        # Validate year
        if not year_input.isdigit() or len(year_input) != 4:
            await message.reply_text("❌ Invalid year format. Please use a 4-digit year. Start over with /request")
            return

        year = year_input
        current_year = datetime.now(timezone.utc).year
        if int(year) < 1900 or int(year) > current_year + 2:
            await message.reply_text(f"❌ Year must be between 1900 and {current_year + 2}. Start over with /request")
            return

        # Search TMDb for matches
        search_msg = await message.reply_text(
            f"🔍 Searching TMDb for **{title}** ({year})...\n"
            f"Please wait..."
        )

        tmdb_results = await search_tmdb(title, year, content_type)

        imdb_link = None
        selected_tmdb_id = None

        if tmdb_results:
            # Display results
            results_text = f"✅ Found {len(tmdb_results)} result(s) on TMDb:\n\n"

            for idx, result in enumerate(tmdb_results, 1):
                result_title = result.get("title", "Unknown")
                result_year = result.get("year", "N/A")
                result_imdb = result.get("imdb_id", "N/A")

                # Format: 1. Title (Year) - IMDB: tt1234567
                results_text += f"{idx}. {result_title} ({result_year})"
                if result_imdb and result_imdb != "N/A":
                    results_text += f" - IMDB: {result_imdb}"
                results_text += "\n"

            results_text += (
                f"\n**Select a result** by replying with the number (1-{len(tmdb_results)})\n"
                f"Or type **SKIP** to continue without IMDB link\n"
                f"Or type **CANCEL** to abort"
            )

            await search_msg.edit_text(results_text)

            # Wait for selection
            try:
                selection_msg = await wait_for_user_input(message.chat.id, uid, timeout=120)
            except asyncio.TimeoutError:
                await message.reply_text("⏰ Request timeout. Please start over with /request")
                return

            if not selection_msg or not selection_msg.text:
                await message.reply_text("❌ Invalid input. Please start over with /request")
                return

            selection_input = selection_msg.text.strip().upper()

            if selection_input == "CANCEL":
                await message.reply_text("❌ Request cancelled.")
                return

            if selection_input != "SKIP":
                # Validate selection
                if not selection_input.isdigit():
                    await message.reply_text("❌ Invalid selection. Please start over with /request")
                    return

                selection_idx = int(selection_input) - 1

                if selection_idx < 0 or selection_idx >= len(tmdb_results):
                    await message.reply_text(f"❌ Invalid selection. Please choose 1-{len(tmdb_results)}. Start over with /request")
                    return

                # Get IMDB link from selected result
                selected_result = tmdb_results[selection_idx]
                imdb_id = selected_result.get("imdb_id")
                selected_tmdb_id = selected_result.get("tmdb_id")

                if imdb_id:
                    imdb_link = f"https://www.imdb.com/title/{imdb_id}/"
                    await message.reply_text(f"✅ Selected: {selected_result.get('title')} ({selected_result.get('year')})")
                else:
                    await message.reply_text("⚠️ IMDB ID not available for this selection. Proceeding without IMDB link.")
        else:
            # No TMDb results found, allow manual entry or skip
            await search_msg.edit_text(
                f"❌ No results found on TMDb for **{title}** ({year}).\n\n"
                f"You can continue without an IMDB link.\n"
                f"Type **CONTINUE** to proceed or **CANCEL** to abort."
            )

            try:
                continue_msg = await wait_for_user_input(message.chat.id, uid, timeout=60)
            except asyncio.TimeoutError:
                await message.reply_text("⏰ Request timeout. Please start over with /request")
                return

            if not continue_msg or not continue_msg.text:
                await message.reply_text("❌ Invalid input. Please start over with /request")
                return

            if continue_msg.text.strip().upper() == "CANCEL":
                await message.reply_text("❌ Request cancelled.")
                return

            if continue_msg.text.strip().upper() != "CONTINUE":
                await message.reply_text("❌ Invalid input. Please start over with /request")
                return

        # Check for duplicate requests (TMDb ID match is exact even across
        # spellings; falls back to fuzzy title + year)
        is_duplicate, similar_req = await check_duplicate_request(
            title, year, uid, tmdb_id=selected_tmdb_id)
        if is_duplicate:
            await message.reply_text(
                f"⚠️ **Similar Request Found**\n\n"
                f"You already have a similar pending request:\n"
                f"**Title:** {similar_req.get('title')}\n"
                f"**Year:** {similar_req.get('year')}\n"
                f"**Type:** {similar_req.get('content_type')}\n\n"
                f"Do you want to proceed anyway?\n"
                f"Reply with **YES** to proceed or **NO** to cancel."
            )

            try:
                confirm_msg = await wait_for_user_input(message.chat.id, uid, timeout=60)
            except asyncio.TimeoutError:
                await message.reply_text("⏰ Request timeout. Request cancelled.")
                return

            if not confirm_msg or not confirm_msg.text or confirm_msg.text.strip().upper() != "YES":
                await message.reply_text("❌ Request cancelled.")
                return

        # Another user may already have requested this title - offer an
        # upvote (free, no quota consumed) instead of a duplicate request.
        global_match = await find_global_match(
            title, year, selected_tmdb_id, exclude_user_id=uid)
        if global_match is not None:
            match_votes = int(global_match.get("votes") or 0)
            await message.reply_text(
                f"👍 **Someone already requested this!**\n\n"
                f"**Title:** {global_match.get('title')}\n"
                f"**Year:** {global_match.get('year')}\n"
                f"**Type:** {global_match.get('content_type')}\n"
                f"**Votes:** {match_votes}\n\n"
                f"Reply with **YES** to upvote it (you'll be notified when "
                f"it's fulfilled, and votes push it up the admin queue).\n"
                f"Reply with **NO** to file your own separate request."
            )
            try:
                vote_msg = await wait_for_user_input(message.chat.id, uid, timeout=60)
            except asyncio.TimeoutError:
                await message.reply_text("⏰ Request timeout. Request cancelled.")
                return
            vote_choice = (vote_msg.text.strip().upper()
                           if vote_msg and vote_msg.text else "")
            if vote_choice == "YES":
                ok, votes = await upvote_request(global_match.get("_id"), uid)
                if ok:
                    await log_action("request_upvoted", by=uid, extra={
                        "title": global_match.get("title"),
                        "year": global_match.get("year"),
                        "votes": votes,
                    })
                    await message.reply_text(
                        f"👍 **Upvoted!**\n\n"
                        f"**{global_match.get('title')}** ({global_match.get('year')}) "
                        f"now has **{votes}** vote(s).\n\n"
                        f"You'll be notified when it's fulfilled."
                    )
                else:
                    await message.reply_text(
                        "⚠️ That request was just fulfilled or removed - "
                        "please file a fresh request with /request."
                    )
                return
            elif vote_choice != "NO":
                await message.reply_text("❌ Request cancelled.")
                return

        # Create request document
        now = datetime.now(timezone.utc)
        request_doc = {
            "user_id": uid,
            "username": username,
            "content_type": content_type,
            "title": title,
            "year": year,
            "imdb_link": imdb_link,
            "tmdb_id": selected_tmdb_id,
            "votes": 0,
            "voters": [],
            "request_date": now,
            "status": "pending"
        }

        # Insert into database
        result = await requests_col.insert_one(request_doc)

        # Update user limits (skip for admins)
        if not user_is_admin:
            await update_user_limits(uid)

        # Get queue position
        queue_position = await get_queue_position(uid)

        # Get remaining quota
        pending_count = await requests_col.count_documents({
            "user_id": uid,
            "status": "pending"
        })

        # Send confirmation
        confirmation_text = (
            f"✅ **Request Submitted Successfully!**\n\n"
            f"**Type:** {content_type}\n"
            f"**Title:** {title}\n"
            f"**Year:** {year}\n"
        )

        if imdb_link:
            confirmation_text += f"**IMDB:** {imdb_link}\n"

        confirmation_text += f"\n📊 **Queue Position:** #{queue_position}\n"

        if user_is_admin:
            confirmation_text += f"📝 **Your Pending Requests:** {pending_count} (Admin - No Limits)\n\n"
        else:
            confirmation_text += f"📝 **Your Pending Requests:** {pending_count}/{MAX_PENDING_REQUESTS_PER_USER}\n\n"

        confirmation_text += "You will be notified when your request is fulfilled."

        await message.reply_text(confirmation_text)

        # Log the request
        await log_action("request_submitted", by=uid, extra={
            "title": title,
            "year": year,
            "content_type": content_type,
            "queue_position": queue_position
        })

    except Exception as e:
        await log_action("request_error", by=uid, extra={"error": str(e)})
        await message.reply_text(
            "❌ **Error**\n\n"
            "An error occurred while processing your request.\n"
            "Please try again later."
        )
        print(f"❌ Request error for user {uid}: {e}")


async def cmd_request_list(client, message: Message):
    """Handle /request_list command for admins to view and manage requests"""
    uid = message.from_user.id

    # Check if user is admin
    if not await is_admin(uid):
        await message.reply_text("🚫 Admins only.")
        return

    try:
        # Get all pending requests sorted by request date, then prioritize by
        # votes (most-voted first) so popular requests surface at the top.
        pending_requests = await requests_col.find(
            {"status": "pending"}
        ).sort("request_date", 1).to_list(length=1000)
        pending_requests.sort(key=request_priority_key)

        if not pending_requests:
            await message.reply_text(
                "📝 **Request List**\n\n"
                "No pending requests at the moment."
            )
            return

        # Store request list data for pagination
        total_requests = len(pending_requests)
        request_list_id = str(uuid.uuid4())[:8]
        bulk_downloads[request_list_id] = {
            'requests': pending_requests,
            'created_at': datetime.now(timezone.utc),
            'user_id': uid,
            'type': 'request_list'
        }

        # Send first page
        await send_request_list_page(client, message, pending_requests, request_list_id, page=1)

        # Log the action
        await log_action("request_list_viewed", by=uid, extra={
            "total_requests": total_requests
        })

    except Exception as e:
        await log_action("request_list_error", by=uid, extra={"error": str(e)})
        await message.reply_text(
            "❌ **Error**\n\n"
            "An error occurred while fetching the request list.\n"
            "Please try again later."
        )
        print(f"❌ Request list error for admin {uid}: {e}")


async def send_request_list_page(client, message, all_requests, request_list_id, page=1, edit=False):
    """Send a paginated request list

    Args:
        client: The bot client
        message: The message object to reply to or edit
        all_requests: List of all requests
        request_list_id: Unique ID for this request list session
        page: Page number to display
        edit: Whether to edit the message (True) or send new message (False)
    """
    REQUESTS_PER_PAGE = 9
    total_requests = len(all_requests)
    total_pages = (total_requests + REQUESTS_PER_PAGE - 1) // REQUESTS_PER_PAGE

    # Ensure page is within valid range
    page = max(1, min(page, total_pages))

    # Calculate start and end indices for current page
    start_idx = (page - 1) * REQUESTS_PER_PAGE
    end_idx = min(start_idx + REQUESTS_PER_PAGE, total_requests)
    page_requests = all_requests[start_idx:end_idx]

    # Build request list text
    list_text = "```\n"
    list_text += f"Request List - Page {page}/{total_pages}\n"
    list_text += f"Total Pending: {total_requests}\n"
    list_text += "=" * 50 + "\n\n"

    for idx, req in enumerate(page_requests, start=start_idx + 1):
        req_type = "[M]" if req.get("content_type") == "Movie" else "[S]"
        title = req.get("title", "Unknown")
        year = req.get("year", "N/A")
        username = req.get("username", "Unknown")
        user_id = req.get("user_id", "N/A")
        req_date = req.get("request_date")
        date_str = req_date.strftime("%Y-%m-%d %H:%M") if req_date else "N/A"
        votes = int(req.get("votes") or 0)

        list_text += f"#{idx} {req_type} {title} ({year})"
        if votes:
            list_text += f" ▲{votes}"
        list_text += "\n"
        list_text += f"    User: {username} (ID: {user_id})\n"
        list_text += f"    Date: {date_str}\n"

        if req.get("imdb_link"):
            list_text += f"    IMDB: {req.get('imdb_link')}\n"

        list_text += "\n"

    list_text += "```"

    # Create buttons
    buttons = []

    # Individual Mark Done buttons (3 per row)
    current_row = []
    for idx, req in enumerate(page_requests, start=start_idx + 1):
        req_id = str(req.get("_id"))
        current_row.append(
            InlineKeyboardButton(
                f"Done [{idx}]",
                callback_data=f"req_done:{req_id}"
            )
        )

        if len(current_row) == 3 or idx == end_idx:
            buttons.append(current_row)
            current_row = []

    # Navigation row
    nav_row = []

    # Previous button
    if page > 1:
        nav_row.append(
            InlineKeyboardButton(
                "← Prev",
                callback_data=f"req_page:{request_list_id}:{page-1}"
            )
        )

    # Mark All Done button
    nav_row.append(
        InlineKeyboardButton(
            "Mark All Done",
            callback_data=f"req_all_done:{request_list_id}"
        )
    )

    # Next button
    if page < total_pages:
        nav_row.append(
            InlineKeyboardButton(
                "Next →",
                callback_data=f"req_page:{request_list_id}:{page+1}"
            )
        )

    if nav_row:
        buttons.append(nav_row)

    # Create keyboard
    keyboard = InlineKeyboardMarkup(buttons) if buttons else None

    # Send or edit message based on the edit parameter
    if edit:
        await message.edit_text(list_text, reply_markup=keyboard)
    else:
        await message.reply_text(list_text, reply_markup=keyboard)


