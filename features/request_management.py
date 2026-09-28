"""
Request Management Module

This module handles movie/series request functionality including:
- Rate limiting (per user and global)
- Request validation and duplicate detection
- Database operations for requests
- User notifications
"""

import re
from datetime import datetime, timezone, timedelta
from fuzzywuzzy import fuzz
from .database import requests_col, user_request_limits_col


# Rate limiting constants
MAX_PENDING_REQUESTS_PER_USER = 3
MAX_REQUESTS_PER_DAY_PER_USER = 1
MAX_GLOBAL_REQUESTS_PER_DAY = 20


async def check_rate_limits(user_id: int):
    """
    Check if user can submit a new request based on rate limits.
    
    Returns:
        tuple: (can_request: bool, error_message: str or None)
    """
    # Get user's current limits
    limits_doc = await user_request_limits_col.find_one({"user_id": user_id})
    
    # Check pending requests count
    pending_count = await requests_col.count_documents({
        "user_id": user_id,
        "status": "pending"
    })
    
    if pending_count >= MAX_PENDING_REQUESTS_PER_USER:
        return False, (
            f"❌ **Request Limit Reached**\n\n"
            f"You have {pending_count} pending requests (maximum: {MAX_PENDING_REQUESTS_PER_USER}).\n"
            f"Please wait for your current requests to be fulfilled before submitting new ones."
        )
    
    # Check daily user limit
    now = datetime.now(timezone.utc)
    today_start = now.replace(hour=0, minute=0, second=0, microsecond=0)

    if limits_doc:
        last_request = limits_doc.get("last_request_date")
        if last_request:
            # Ensure last_request is timezone-aware for comparison
            if last_request.tzinfo is None:
                last_request = last_request.replace(tzinfo=timezone.utc)

            if last_request >= today_start:
                # User already made a request today
                next_request_time = (last_request + timedelta(days=1)).strftime("%Y-%m-%d %H:%M UTC")
                return False, (
                    f"❌ **Daily Limit Reached**\n\n"
                    f"You can only submit {MAX_REQUESTS_PER_DAY_PER_USER} request per day.\n"
                    f"You can submit your next request after: {next_request_time}"
                )
    
    # Check global daily limit
    global_today_count = await requests_col.count_documents({
        "request_date": {"$gte": today_start}
    })
    
    if global_today_count >= MAX_GLOBAL_REQUESTS_PER_DAY:
        return False, (
            f"❌ **Global Daily Limit Reached**\n\n"
            f"The bot has reached its maximum of {MAX_GLOBAL_REQUESTS_PER_DAY} requests per day.\n"
            f"Please try again tomorrow."
        )
    
    return True, None


async def update_user_limits(user_id: int):
    """Update user's request limits after successful request submission."""
    now = datetime.now(timezone.utc)
    
    await user_request_limits_col.update_one(
        {"user_id": user_id},
        {
            "$set": {
                "last_request_date": now,
                "user_id": user_id
            }
        },
        upsert=True
    )


async def check_duplicate_request(title: str, year: str, user_id: int = None,
                                  tmdb_id=None):
    """
    Check for duplicate or similar requests using fuzzy matching.

    Args:
        title: Movie/series title
        year: Release year
        user_id: Optional user ID to check user's own requests
        tmdb_id: Optional TMDb ID - an exact TMDb match is always a
            duplicate, even when the spellings differ (remakes,
            transliterations).

    Returns:
        tuple: (is_duplicate: bool, similar_request: dict or None)
    """
    # Search for similar pending requests
    query = {"status": "pending"}
    if user_id:
        query["user_id"] = user_id

    pending_requests = await requests_col.find(query).to_list(length=100)

    # TMDb identity match first (exact, spelling-independent).
    if tmdb_id is not None:
        for req in pending_requests:
            if req.get("tmdb_id") is not None and req.get("tmdb_id") == tmdb_id:
                return True, req

    for req in pending_requests:
        # Check year match
        if str(req.get("year")) == str(year):
            # Check title similarity
            similarity = fuzz.ratio(title.lower(), req.get("title", "").lower())
            if similarity >= 85:  # 85% similarity threshold
                return True, req

    return False, None


async def validate_imdb_link(link: str):
    """
    Validate IMDB link format.
    
    Returns:
        bool: True if valid or empty, False otherwise
    """
    if not link or link.strip() == "":
        return True
    
    # IMDB link patterns
    patterns = [
        r'^https?://(?:www\.)?imdb\.com/title/tt\d+/?',
        r'^https?://(?:m\.)?imdb\.com/title/tt\d+/?',
        r'^imdb\.com/title/tt\d+/?',
        r'^tt\d+$'
    ]
    
    for pattern in patterns:
        if re.match(pattern, link.strip(), re.IGNORECASE):
            return True
    
    return False


async def get_queue_position(user_id: int):
    """Get the queue position for a user's most recent request."""
    # Count all pending requests before this user's latest request
    user_latest = await requests_col.find_one(
        {"user_id": user_id, "status": "pending"},
        sort=[("request_date", -1)]
    )

    if not user_latest:
        return None

    position = await requests_col.count_documents({
        "status": "pending",
        "request_date": {"$lt": user_latest["request_date"]}
    }) + 1

    return position


# ------------------------------------------------------------------ #
# Request voting + auto-fulfillment (TMDb-identity based)              #
# ------------------------------------------------------------------ #
# Requests carry an optional ``tmdb_id`` (captured from the TMDb picker
# in /request). It is the canonical identity: remakes and transliterated
# titles share spellings but never a TMDb ID. Every matcher below tries
# the TMDb ID first and falls back to normalized title + year so requests
# filed without a TMDb match (API down, SKIP) still work.

def _request_matches(req: dict, title: str, year, tmdb_id) -> bool:
    """True when a pending request doc refers to the same title."""
    if tmdb_id is not None and req.get("tmdb_id") is not None:
        return req.get("tmdb_id") == tmdb_id
    return (str(req.get("title") or "").strip().lower()
            == str(title or "").strip().lower()
            and str(req.get("year")) == str(year))


def request_priority_key(req: dict):
    """Sort key for the admin queue: most-voted first, then oldest first.

    Missing ``request_date`` sorts last so legacy docs never crash the sort.
    """
    votes = req.get("votes") or 0
    ts = req.get("request_date")
    try:
        stamp = ts.timestamp() if hasattr(ts, "timestamp") else 0
    except Exception:
        stamp = 0
    return (-votes, stamp)


async def find_global_match(title: str, year, tmdb_id, exclude_user_id: int = None):
    """Best pending request from ANOTHER user for the same title (or None).

    Used by /request to offer an upvote instead of filing a duplicate.
    """
    pending = await requests_col.find({"status": "pending"}).to_list(length=1000)
    best = None
    for req in pending:
        if exclude_user_id is not None and req.get("user_id") == exclude_user_id:
            continue
        if _request_matches(req, title, year, tmdb_id):
            if best is None or request_priority_key(req) < request_priority_key(best):
                best = req
    return best


async def upvote_request(request_id, user_id: int):
    """Add an upvote to a pending request (idempotent per user).

    Returns ``(ok: bool, votes: int)`` - ok is False when the request is
    missing or no longer pending.
    """
    try:
        req = await requests_col.find_one({"_id": request_id, "status": "pending"})
    except Exception:
        return False, 0
    if not req:
        return False, 0
    voters = list(req.get("voters") or [])
    if user_id in voters:
        return True, int(req.get("votes") or 0)
    voters.append(user_id)
    try:
        await requests_col.update_one(
            {"_id": request_id},
            {"$set": {"voters": voters, "votes": int(req.get("votes") or 0) + 1}},
        )
    except Exception:
        return False, 0
    return True, int(req.get("votes") or 0) + 1


async def fulfill_matching_requests(entry: dict, completed_by="auto_index"):
    """Auto-complete pending requests fulfilled by a newly indexed copy.

    Matches on TMDb ID first, title + year fallback. Marks each match
    completed and DMs the requester plus all voters with a Get button for
    the fresh copy. Returns the number of requests fulfilled.
    """
    from datetime import datetime as _dt, timezone as _tz

    title = (entry.get("title") or "").strip()
    if not title:
        return 0
    tmdb_id = entry.get("tmdb_id")
    year = entry.get("year")

    try:
        pending = await requests_col.find({"status": "pending"}).to_list(length=1000)
    except Exception as e:
        print(f"⚠️ fulfill_matching_requests query failed: {e}")
        return 0

    matches = [r for r in pending if _request_matches(r, title, year, tmdb_id)]
    if not matches:
        return 0

    # Resolve the client lazily (None at import time, set in bot.main()).
    try:
        from .config import client as _client
    except Exception:
        _client = None

    fulfilled = 0
    for req in matches:
        try:
            await requests_col.update_one(
                {"_id": req.get("_id"), "status": "pending"},
                {"$set": {
                    "status": "completed",
                    "completed_at": _dt.now(_tz.utc),
                    "completed_by": completed_by,
                }},
            )
        except Exception as e:
            print(f"⚠️ fulfill_matching_requests update failed: {e}")
            continue
        fulfilled += 1

        recipients = []
        for uid in [req.get("user_id")] + list(req.get("voters") or []):
            if uid is not None and uid not in recipients:
                recipients.append(uid)
        if _client is not None:
            for uid in recipients:
                try:
                    text = (
                        f"✅ **Request Fulfilled!**\n\n"
                        f"**{req.get('title')}** ({req.get('year')}) "
                        f"is now available - grab it below."
                    )
                    reply_markup = None
                    channel_id = entry.get("channel_id")
                    message_id = entry.get("message_id")
                    if channel_id and message_id:
                        from pyrogram.types import InlineKeyboardMarkup, InlineKeyboardButton
                        reply_markup = InlineKeyboardMarkup([[
                            InlineKeyboardButton(
                                "📥 Get File",
                                callback_data=f"get_file:{channel_id}:{message_id}",
                            )
                        ]])
                    await _client.send_message(uid, text, reply_markup=reply_markup)
                except Exception as e:
                    print(f"⚠️ fulfill notify failed for {uid}: {e}")
    return fulfilled

