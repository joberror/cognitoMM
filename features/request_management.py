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
        if last_request and last_request >= today_start:
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


async def check_duplicate_request(title: str, year: str, user_id: int = None):
    """
    Check for duplicate or similar requests using fuzzy matching.
    
    Args:
        title: Movie/series title
        year: Release year
        user_id: Optional user ID to check user's own requests
        
    Returns:
        tuple: (is_duplicate: bool, similar_request: dict or None)
    """
    # Search for similar pending requests
    query = {"status": "pending"}
    if user_id:
        query["user_id"] = user_id
    
    pending_requests = await requests_col.find(query).to_list(length=100)
    
    for req in pending_requests:
        # Check year match
        if req.get("year") == year:
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

