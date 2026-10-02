"""
Premium Management Module

This module handles premium user management and feature access control.
It includes functions for checking premium status, managing premium users,
and controlling premium features.
"""

from datetime import datetime, timezone, timedelta
from typing import Optional, Dict, List, Tuple
import asyncio
from pyrogram.types import InlineKeyboardMarkup, InlineKeyboardButton
from .config import (ADMINS, FREE_DOWNLOAD_DAILY_LIMIT, PREMIUM_DOWNLOAD_DAILY_LIMIT,
                     PREMIUM_EXPIRY_WARN_DAYS,
                     FILE_DELETION_MINUTES, PREMIUM_FILE_DELETION_MINUTES,
                     BULK_FILE_DELETION_MINUTES, PREMIUM_BULK_FILE_DELETION_MINUTES,
                     FILE_DELETION_WARN_MINUTES)
from .database import (premium_users_col, premium_features_col, users_col,
                       premium_payments_col)
from .user_management import log_action


# Default premium features
DEFAULT_PREMIUM_FEATURES = [
    {"feature_name": "recent", "enabled": True, "description": "/recent command"},
    {"feature_name": "request", "enabled": True, "description": "/request command"},
    {"feature_name": "get_all", "enabled": True, "description": "Get All button in search results"},
]


async def initialize_premium_features():
    """Initialize default premium features if they don't exist"""
    try:
        # Check if features already exist
        existing_count = await premium_features_col.count_documents({})

        if existing_count == 0:
            # Prepare features with required fields
            now = datetime.now(timezone.utc)
            features_to_insert = []

            for feature in DEFAULT_PREMIUM_FEATURES:
                features_to_insert.append({
                    "feature_name": feature["feature_name"],
                    "description": feature["description"],
                    "enabled": feature["enabled"],
                    "added_date": now,
                    "added_by": 0,  # System initialization
                    "last_updated": now,
                    "last_updated_by": 0  # System initialization
                })

            # Insert default features
            await premium_features_col.insert_many(features_to_insert)
            print("✅ Initialized default premium features")
    except Exception as e:
        print(f"⚠️ Failed to initialize premium features: {e}")


async def is_premium_user(user_id: int) -> bool:
    """
    Check if user has active premium status.

    Admin == premium: an admin always gets the premium tier (download quota,
    auto-delete retention, premium-only features) without holding a premium
    record. Two fast paths keep this cheap:

    1. Config ``ADMINS`` short-circuit with ZERO queries.
    2. Only a user with NO active premium record pays the extra ``role``
       lookup (``is_admin``) — a paying premium user still costs one read.

    ``is_admin`` is imported lazily: ``user_management`` imports this module
    from inside a function, so a top-level import would be circular.

    Args:
        user_id: User ID to check
        
    Returns:
        True if user has active premium (or is an admin), False otherwise
    """
    # (1) Super admins are premium without touching the database.
    if user_id in ADMINS:
        return True

    active = False
    try:
        premium_doc = await premium_users_col.find_one({"user_id": user_id})
        
        if premium_doc:
            # Check if premium has expired
            expiry_date = premium_doc.get("expiry_date")
            if expiry_date:
                # Ensure expiry_date is timezone-aware
                if expiry_date.tzinfo is None:
                    expiry_date = expiry_date.replace(tzinfo=timezone.utc)
                # If expired, fall through to the admin check below
                active = datetime.now(timezone.utc) < expiry_date
    except Exception as e:
        print(f"Error checking premium status for user {user_id}: {e}")
        return False

    if active:
        return True

    # (2) No active premium record: a database admin is premium too.
    from .user_management import is_admin
    try:
        return bool(await is_admin(user_id))
    except Exception as e:
        print(f"⚠️ Admin premium fallback failed for user {user_id}: {e}")
        return False


async def get_premium_user(user_id: int) -> Optional[Dict]:
    """
    Get premium user document
    
    Args:
        user_id: User ID
        
    Returns:
        Premium user document or None
    """
    try:
        return await premium_users_col.find_one({"user_id": user_id})
    except Exception:
        return None


async def add_premium_user(user_id: int, days: int, added_by: int, username: str = None) -> Tuple[bool, str]:
    """
    Add a user to premium or extend existing premium
    
    Args:
        user_id: User ID to add
        days: Number of days to add
        added_by: Admin user ID who added
        username: Optional username
        
    Returns:
        Tuple of (success: bool, message: str)
    """
    try:
        now = datetime.now(timezone.utc)
        
        # Check if user already has premium
        existing = await premium_users_col.find_one({"user_id": user_id})
        
        if existing:
            # Extend existing premium
            current_expiry = existing.get("expiry_date")
            
            # Ensure current_expiry is timezone-aware
            if current_expiry and current_expiry.tzinfo is None:
                current_expiry = current_expiry.replace(tzinfo=timezone.utc)
            
            # If expired, start from now, otherwise extend from current expiry
            if current_expiry and current_expiry > now:
                new_expiry = current_expiry + timedelta(days=days)
            else:
                new_expiry = now + timedelta(days=days)
            
            await premium_users_col.update_one(
                {"user_id": user_id},
                {
                    "$set": {
                        "expiry_date": new_expiry,
                        "last_updated": now,
                        "last_updated_by": added_by
                    }
                }
            )
            
            await log_action("premium_extended", by=added_by, target=user_id, extra={
                "days_added": days,
                "new_expiry": new_expiry.isoformat()
            })
            
            return True, f"Extended premium for user {user_id} by {days} days. New expiry: {new_expiry.strftime('%Y-%m-%d %H:%M UTC')}"
        else:
            # Add new premium user
            expiry_date = now + timedelta(days=days)

            premium_doc = {
                "user_id": user_id,
                "username": username,
                "added_date": now,
                "added_by": added_by,
                "expiry_date": expiry_date,
                "last_updated": now,
                "last_updated_by": added_by
            }

            await premium_users_col.insert_one(premium_doc)

            await log_action("premium_added", by=added_by, target=user_id, extra={
                "days": days,
                "expiry": expiry_date.isoformat()
            })

            return True, f"Added user {user_id} to premium for {days} days. Expiry: {expiry_date.strftime('%Y-%m-%d %H:%M UTC')}"

    except Exception as e:
        print(f"Error adding premium user {user_id}: {e}")
        return False, f"Error: {str(e)}"


async def edit_premium_user(user_id: int, days_delta: int, edited_by: int) -> Tuple[bool, str]:
    """
    Edit premium user by adding or removing days

    Args:
        user_id: User ID to edit
        days_delta: Number of days to add (positive) or remove (negative)
        edited_by: Admin user ID who edited

    Returns:
        Tuple of (success: bool, message: str)
    """
    try:
        premium_doc = await premium_users_col.find_one({"user_id": user_id})

        if not premium_doc:
            return False, f"User {user_id} is not a premium user"

        current_expiry = premium_doc.get("expiry_date")

        # Ensure current_expiry is timezone-aware
        if current_expiry.tzinfo is None:
            current_expiry = current_expiry.replace(tzinfo=timezone.utc)

        # Calculate new expiry
        new_expiry = current_expiry + timedelta(days=days_delta)
        now = datetime.now(timezone.utc)

        # Don't allow setting expiry in the past
        if new_expiry < now:
            new_expiry = now

        await premium_users_col.update_one(
            {"user_id": user_id},
            {
                "$set": {
                    "expiry_date": new_expiry,
                    "last_updated": now,
                    "last_updated_by": edited_by
                }
            }
        )

        await log_action("premium_edited", by=edited_by, target=user_id, extra={
            "days_delta": days_delta,
            "new_expiry": new_expiry.isoformat()
        })

        action = "added" if days_delta > 0 else "removed"
        return True, f"{action.capitalize()} {abs(days_delta)} days for user {user_id}. New expiry: {new_expiry.strftime('%Y-%m-%d %H:%M UTC')}"

    except Exception as e:
        print(f"Error editing premium user {user_id}: {e}")
        return False, f"Error: {str(e)}"


async def remove_premium_user(user_id: int, removed_by: int) -> Tuple[bool, str]:
    """
    Remove a user from premium

    Args:
        user_id: User ID to remove
        removed_by: Admin user ID who removed

    Returns:
        Tuple of (success: bool, message: str)
    """
    try:
        result = await premium_users_col.delete_one({"user_id": user_id})

        if result.deleted_count == 0:
            return False, f"User {user_id} is not a premium user"

        await log_action("premium_removed", by=removed_by, target=user_id)

        return True, f"Removed user {user_id} from premium"

    except Exception as e:
        print(f"Error removing premium user {user_id}: {e}")
        return False, f"Error: {str(e)}"


async def get_days_remaining(user_id: int) -> Optional[int]:
    """
    Get number of days remaining for premium user

    Args:
        user_id: User ID

    Returns:
        Number of days remaining or None if not premium
    """
    try:
        premium_doc = await premium_users_col.find_one({"user_id": user_id})

        if not premium_doc:
            return None

        expiry_date = premium_doc.get("expiry_date")
        if not expiry_date:
            return None

        # Ensure expiry_date is timezone-aware
        if expiry_date.tzinfo is None:
            expiry_date = expiry_date.replace(tzinfo=timezone.utc)

        now = datetime.now(timezone.utc)
        delta = expiry_date - now

        return max(0, delta.days)

    except Exception:
        return None


async def is_feature_premium_only(feature_name: str) -> bool:
    """
    Check if a feature is premium-only

    Args:
        feature_name: Name of the feature (e.g., "recent", "request", "get_all")

    Returns:
        True if feature is premium-only (enabled), False otherwise
    """
    try:
        feature_doc = await premium_features_col.find_one({"feature_name": feature_name})

        if not feature_doc:
            return False

        return feature_doc.get("enabled", False)

    except Exception:
        return False


async def toggle_feature(feature_name: str, toggled_by: int) -> Tuple[bool, str, bool]:
    """
    Toggle a premium feature on/off

    Args:
        feature_name: Name of the feature
        toggled_by: Admin user ID who toggled

    Returns:
        Tuple of (success: bool, message: str, new_state: bool)
    """
    try:
        feature_doc = await premium_features_col.find_one({"feature_name": feature_name})

        if not feature_doc:
            return False, f"Feature '{feature_name}' not found", False

        current_state = feature_doc.get("enabled", False)
        new_state = not current_state

        await premium_features_col.update_one(
            {"feature_name": feature_name},
            {"$set": {"enabled": new_state}}
        )

        await log_action("premium_feature_toggled", by=toggled_by, extra={
            "feature": feature_name,
            "new_state": new_state
        })

        state_text = "ON (Premium Only)" if new_state else "OFF (Available to All)"
        return True, f"Feature '{feature_name}' toggled {state_text}", new_state

    except Exception as e:
        print(f"Error toggling feature {feature_name}: {e}")
        return False, f"Error: {str(e)}", False


async def add_premium_feature(feature_name: str, description: str, added_by: int) -> Tuple[bool, str]:
    """
    Add a new premium feature

    Args:
        feature_name: Name of the feature
        description: Description of the feature
        added_by: Admin user ID who added

    Returns:
        Tuple of (success: bool, message: str)
    """
    try:
        # Check if feature already exists
        existing = await premium_features_col.find_one({"feature_name": feature_name})

        if existing:
            return False, f"Feature '{feature_name}' already exists"

        feature_doc = {
            "feature_name": feature_name,
            "description": description,
            "enabled": True,  # New features are enabled by default
            "added_date": datetime.now(timezone.utc),
            "added_by": added_by
        }

        await premium_features_col.insert_one(feature_doc)

        await log_action("premium_feature_added", by=added_by, extra={
            "feature": feature_name,
            "description": description
        })

        return True, f"Added new premium feature: {feature_name}"

    except Exception as e:
        print(f"Error adding premium feature {feature_name}: {e}")
        return False, f"Error: {str(e)}"


async def get_all_premium_features() -> List[Dict]:
    """
    Get all premium features

    Returns:
        List of premium feature documents
    """
    try:
        cursor = premium_features_col.find({})
        return await cursor.to_list(length=100)
    except Exception:
        return []


async def get_all_premium_users() -> List[Dict]:
    """
    Get all premium users

    Returns:
        List of premium user documents
    """
    try:
        cursor = premium_users_col.find({})
        return await cursor.to_list(length=1000)
    except Exception:
        return []


# ------------------------------------------------------------------ #
# Premium user list (admin /premium -> View Users)                    #
# ------------------------------------------------------------------ #
# Live view of premium_users_col: every page reads fresh docs, so expiry
# status is never stale. Sort is expiry-ascending (nearest deadline first).
# Search + pagination are encoded in callback data: rows carry an index
# prefix, and the query rides as an extra colon-separated part only when
# set, so "plist:next:2" and "plist:next:2:bob" parse unambiguously.

PREMIUM_LIST_PAGE_SIZE = 10
_PREMIUM_LIST_MAX_USERS = 1000
# NOTE: this cap counts UTF-8 BYTES, not chars. The query rides inside
# callback_data (Telegram hard-caps it at 64 bytes; "plist:next:999:" worst
# case is ~16 bytes, leaving 48 for the query).
_PREMIUM_LIST_MAX_QUERY = 24


def build_premium_menu():
    """The /premium main menu as ``(text, keyboard)``.

    Single source for cmd_premium, the ``premium:back`` callback and the
    user-list Back button, so the menu never drifts between them.
    """
    buttons = [
        [InlineKeyboardButton("Add Users", callback_data="premium:add_users")],
        [InlineKeyboardButton("Edit Users", callback_data="premium:edit_users")],
        [InlineKeyboardButton("Remove Users", callback_data="premium:remove_users")],
        [InlineKeyboardButton("View Users", callback_data="premium:list_users")],
        [InlineKeyboardButton("Manage Features", callback_data="premium:manage_features")]
    ]
    help_text = (
        "**Premium Management System**\n\n"
        "**Add Users:** Add users to premium with specified duration\n"
        "**Edit Users:** Modify premium duration for existing users\n"
        "**Remove Users:** Remove users from premium\n"
        "**View Users:** Browse, search and manage all premium users\n"
        "**Manage Features:** Control which features are premium-only\n\n"
        "Select an option below:"
    )
    return help_text, InlineKeyboardMarkup(buttons)


def _clean_list_query(query) -> Optional[str]:
    """Normalize a list filter: strip, drop colons (callback separator), cap UTF-8 bytes.

    The cap is on encoded bytes, not characters: the query rides inside
    callback_data, which Telegram caps at 64 bytes total.
    """
    if query is None:
        return None
    q = str(query).strip().replace(":", "")
    while q and len(q.encode("utf-8")) > _PREMIUM_LIST_MAX_QUERY:
        q = q[:-1]
    return q or None


def _list_query_token(query: Optional[str]) -> str:
    """Query encoded for callback data ('' = no filter)."""
    return f":{query}" if query else ""


def _premium_expiry(dt):
    """Timezone-aware expiry or None."""
    if not dt:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt


def _premium_list_status(doc: Dict, now: datetime) -> Tuple[str, int]:
    """``(STATUS, days)`` for one premium doc: ACTIVE / EXPIRING / EXPIRED.

    ``days`` is days left (active/expiring, floored) or days since lapse
    (expired, ceiled). EXPIRING = inside the largest expiry-reminder window.
    """
    expiry = _premium_expiry(doc.get("expiry_date"))
    if expiry is None:
        # Consistent with is_premium_user: no expiry_date means no active premium.
        return "EXPIRED", 0
    delta = expiry - now
    if delta.total_seconds() <= 0:
        past = -delta
        return "EXPIRED", max(1, int(past.days) + (1 if past.seconds else 0))
    days_left = delta.days
    warn_threshold = max(PREMIUM_EXPIRY_WARN_DAYS) if PREMIUM_EXPIRY_WARN_DAYS else 3
    if days_left <= warn_threshold:
        return "EXPIRING", days_left
    return "ACTIVE", days_left


async def build_premium_user_list(now: Optional[datetime] = None, page: int = 1,
                                  query: Optional[str] = None):
    """Build the admin premium-user list page.

    Returns ``(text, keyboard)``: a code-block list of 10 users sorted by
    nearest expiry, with Prev/Next (encoding the active filter), Search and
    Back buttons, plus per-row Edit/Remove actions keyed on user id.
    """
    now = now or datetime.now(timezone.utc)
    q = _clean_list_query(query)

    try:
        docs = await premium_users_col.find({}).to_list(length=_PREMIUM_LIST_MAX_USERS)
    except Exception as e:
        print(f"⚠️ premium user list query failed: {e}")
        docs = []

    rows = []
    for doc in docs:
        if not isinstance(doc, dict):
            continue
        uid = doc.get("user_id")
        if q:
            if q.isdigit():
                if str(uid) != q:
                    continue
            else:
                name = str(doc.get("username") or "")
                if q.lower() not in name.lower() and q != str(uid):
                    continue
        rows.append(doc)

    rows.sort(key=lambda d: _premium_expiry(d.get("expiry_date"))
              or datetime.max.replace(tzinfo=timezone.utc))

    total = len(rows)
    total_pages = max(1, (total + PREMIUM_LIST_PAGE_SIZE - 1) // PREMIUM_LIST_PAGE_SIZE)
    page = max(1, min(int(page or 1), total_pages))
    start_idx = (page - 1) * PREMIUM_LIST_PAGE_SIZE
    page_rows = rows[start_idx:start_idx + PREMIUM_LIST_PAGE_SIZE]

    if not total:
        if q:
            text = f'```\nNo premium users match "{q}"\n```'
            buttons = [[InlineKeyboardButton("Clear Filter",
                                             callback_data="plist:clear")]]
        else:
            text = "```\nNo premium users found.\n```"
            buttons = []
        buttons.append([InlineKeyboardButton("← Back", callback_data="premium:back")])
        return text, InlineKeyboardMarkup(buttons)

    active = expired = expiring = 0
    for doc in rows:
        status, _ = _premium_list_status(doc, now)
        if status == "EXPIRED":
            expired += 1
        else:
            active += 1
            if status == "EXPIRING":
                expiring += 1

    today = _day_key(now)

    # Batch enrichment: ONE query per side collection for the whole page.
    # A per-row find_one here would be 2N round-trips on every page turn.
    page_uids = [d.get("user_id") for d in page_rows]
    usage = {}
    try:
        ucursor = users_col.find(
            {"user_id": {"$in": page_uids}},
            {"user_id": 1, "download_day": 1, "downloads_today": 1, "watchlist": 1})
        for udoc in await ucursor.to_list(length=len(page_uids)):
            if isinstance(udoc, dict) and udoc.get("user_id") is not None:
                usage[udoc.get("user_id")] = udoc
    except Exception:
        usage = {}
    sources = {}
    try:
        pcursor = premium_payments_col.find({"user_id": {"$in": page_uids}})
        for pay in await pcursor.to_list(length=None):
            if isinstance(pay, dict) and pay.get("user_id") is not None:
                sources.setdefault(pay.get("user_id"), pay)
    except Exception:
        sources = {}

    list_text = "```\n"
    list_text += f"Premium Users - Page {page}/{total_pages}\n"
    list_text += (f"Total: {total} | Active: {active} | "
                  f"Expired: {expired} | Expiring: {expiring}\n")
    if q:
        list_text += f'Filter: "{q}"\n'
    list_text += "=" * 44 + "\n\n"

    buttons = []
    action_row = []
    for idx, doc in enumerate(page_rows, start=start_idx + 1):
        uid = doc.get("user_id")
        username = doc.get("username") or uid
        status, days = _premium_list_status(doc, now)
        if status == "EXPIRED":
            state = f"EXPIRED ({days}d ago)"
        else:
            state = f"{status} {days}d left"

        expiry = _premium_expiry(doc.get("expiry_date"))
        added = _premium_expiry(doc.get("added_date"))

        list_text += f"#{idx} {username} (ID: {uid}) {state}\n"
        list_text += (f"   End: {expiry.strftime('%Y-%m-%d %H:%M UTC') if expiry else 'N/A'}"
                      f" | Start: {added.strftime('%Y-%m-%d') if added else 'N/A'}"
                      f" | By: {doc.get('added_by', 'N/A')}\n")
        last_updated = _premium_expiry(doc.get("last_updated"))
        if last_updated:
            list_text += (f"   Upd: {last_updated.strftime('%Y-%m-%d')}"
                          f" by {doc.get('last_updated_by', 'N/A')}\n")

        # Usage today + watchlist + how premium was obtained, from the
        # batched reads above; missing rows degrade to "-".
        dl = wl = "-"
        udoc = usage.get(uid)
        if udoc:
            if udoc.get("download_day") == today:
                dl = udoc.get("downloads_today", 0)
            wl = len(udoc.get("watchlist") or [])
        pay = sources.get(uid)
        if pay:
            source = f"paid {pay.get('stars', '?')}XTR {pay.get('plan_key', '')}".strip()
        else:
            source = "grant"
        list_text += f"   DL: {dl} | WL: {wl} | {source}\n\n"

        action_row.append(InlineKeyboardButton(f"[{idx}] Edit",
                                               callback_data=f"plist:edit:{uid}"))
        action_row.append(InlineKeyboardButton(f"[{idx}] Remove",
                                               callback_data=f"plist:remove:{uid}"))
        if len(action_row) == 4:
            buttons.append(action_row)
            action_row = []
    if action_row:
        buttons.append(action_row)

    nav_row = []
    token = _list_query_token(q)
    if page > 1:
        nav_row.append(InlineKeyboardButton("← Prev",
                                            callback_data=f"plist:prev:{page - 1}{token}"))
    nav_row.append(InlineKeyboardButton(f"Page {page}/{total_pages}",
                                        callback_data="plist:noop"))
    if page < total_pages:
        nav_row.append(InlineKeyboardButton("Next →",
                                            callback_data=f"plist:next:{page + 1}{token}"))
    buttons.append(nav_row)

    tools_row = [InlineKeyboardButton("Search User", callback_data="plist:search")]
    if q:
        tools_row.append(InlineKeyboardButton("Clear Filter",
                                              callback_data="plist:clear"))
    buttons.append(tools_row)

    # Existing /premium actions stay one tap away, like the row-level
    # Edit/Remove buttons above (they reuse the premium: callbacks).
    buttons.append([
        InlineKeyboardButton("Add Users", callback_data="premium:add_users"),
        InlineKeyboardButton("Edit Users", callback_data="premium:edit_users"),
    ])
    buttons.append([
        InlineKeyboardButton("Remove Users", callback_data="premium:remove_users"),
        InlineKeyboardButton("Features", callback_data="premium:manage_features"),
    ])

    buttons.append([InlineKeyboardButton("← Menu", callback_data="premium:back")])

    list_text += "```"
    return list_text, InlineKeyboardMarkup(buttons)


async def cleanup_expired_premium():
    """
    Clean up expired premium users (optional maintenance task)
    This can be called periodically to remove expired premium entries
    """
    try:
        now = datetime.now(timezone.utc)
        result = await premium_users_col.delete_many({
            "expiry_date": {"$lt": now}
        })

        if result.deleted_count > 0:
            print(f"🧹 Cleaned up {result.deleted_count} expired premium users")
            await log_action("premium_cleanup", extra={
                "deleted_count": result.deleted_count
            })

    except Exception as e:
        print(f"Error cleaning up expired premium users: {e}")


# ------------------------------------------------------------------ #
# Daily download quota (tier-based gates)                             #
# ------------------------------------------------------------------ #
# Free users get FREE_DOWNLOAD_DAILY_LIMIT downloads/day; premium users
# get PREMIUM_DOWNLOAD_DAILY_LIMIT (0 = unlimited). Counters live on the
# user doc (download_day / downloads_today) so there is no extra collection.

def _day_key(now: datetime) -> str:
    """UTC day key used to roll the per-day download counter."""
    return now.strftime("%Y-%m-%d")


async def check_download_quota(user_id: int) -> Tuple[bool, Optional[int], int, Optional[str]]:
    """Check whether a user may download right now.

    Returns ``(allowed, remaining, limit, message)`` where ``limit`` 0 means
    unlimited and ``remaining`` is None for unlimited. The premium lookup only
    runs once the free allowance is exhausted, so the common path is a single
    cheap read. Any DB error fails OPEN (allow) so a hiccup never blocks users.
    """
    now = datetime.now(timezone.utc)
    today = _day_key(now)
    free_limit = FREE_DOWNLOAD_DAILY_LIMIT

    try:
        doc = await users_col.find_one({"user_id": user_id})
    except Exception:
        return True, None, free_limit, None

    count = 0
    if isinstance(doc, dict) and doc.get("download_day") == today:
        try:
            count = int(doc.get("downloads_today") or 0)
        except (TypeError, ValueError):
            count = 0

    # Fast path: free tier still has room (or free is unlimited).
    if free_limit <= 0 or count < free_limit:
        return True, (None if free_limit <= 0 else free_limit - count), \
            max(free_limit, 0), None

    # At the free cap - premium may raise (or lift) the limit.
    try:
        premium = await is_premium_user(user_id)
    except Exception:
        premium = False
    limit = PREMIUM_DOWNLOAD_DAILY_LIMIT if premium else free_limit

    if limit <= 0:
        return True, None, 0, None
    if count < limit:
        return True, limit - count, limit, None

    reset_at = (now + timedelta(days=1)).replace(
        hour=0, minute=0, second=0, microsecond=0)
    message = (
        f"🚫 **Daily download limit reached**\n\n"
        f"You've used {count}/{limit} downloads today.\n"
        f"Limit resets at {reset_at.strftime('%H:%M UTC')}.\n\n"
        f"⭐ Premium lifts this limit - use /buy_premium."
    )
    return False, 0, limit, message


async def record_download(user_id: int) -> int:
    """Increment the caller's daily download counter (resets on a new day).

    Returns the new count. Best-effort: failures are swallowed so a stats
    hiccup never breaks a download.
    """
    now = datetime.now(timezone.utc)
    today = _day_key(now)
    try:
        doc = await users_col.find_one({"user_id": user_id})
    except Exception:
        doc = None
    if isinstance(doc, dict) and doc.get("download_day") == today:
        try:
            new_count = int(doc.get("downloads_today") or 0) + 1
        except (TypeError, ValueError):
            new_count = 1
    else:
        new_count = 1
    try:
        await users_col.update_one(
            {"user_id": user_id},
            {"$set": {"download_day": today, "downloads_today": new_count}},
            upsert=True,
        )
    except Exception as e:
        print(f"⚠️ record_download failed for {user_id}: {e}")
    return new_count


async def get_download_quota_status(user_id: int) -> Dict:
    """Human-facing quota snapshot for /my_stat + /premium info."""
    now = datetime.now(timezone.utc)
    today = _day_key(now)
    premium = await is_premium_user(user_id)
    limit = PREMIUM_DOWNLOAD_DAILY_LIMIT if premium else FREE_DOWNLOAD_DAILY_LIMIT
    used = 0
    try:
        doc = await users_col.find_one({"user_id": user_id})
        if isinstance(doc, dict) and doc.get("download_day") == today:
            used = int(doc.get("downloads_today") or 0)
    except Exception:
        pass
    return {"premium": premium, "limit": limit, "used": used,
            "remaining": None if limit <= 0 else max(0, limit - used),
            "retention_minutes": (PREMIUM_FILE_DELETION_MINUTES if premium
                                  else FILE_DELETION_MINUTES),
            "bulk_retention_minutes": (PREMIUM_BULK_FILE_DELETION_MINUTES if premium
                                       else BULK_FILE_DELETION_MINUTES)}


async def get_retention_minutes(user_id: int, bulk: bool = False,
                                premium: Optional[bool] = None) -> int:
    """Auto-delete retention (minutes) for a user's tier.

    Pass ``premium`` to reuse an existing premium check (avoids a second DB
    read); otherwise it is resolved here. Always at least 1 minute.
    """
    if premium is None:
        try:
            premium = await is_premium_user(user_id)
        except Exception:
            premium = False
    if bulk:
        minutes = PREMIUM_BULK_FILE_DELETION_MINUTES if premium else BULK_FILE_DELETION_MINUTES
    else:
        minutes = PREMIUM_FILE_DELETION_MINUTES if premium else FILE_DELETION_MINUTES
    return max(1, int(minutes))


def retention_warn_minutes(retention_minutes: int) -> int:
    """Warning lead time for a given retention (never more than half of it)."""
    retention_minutes = max(1, int(retention_minutes or 1))
    warn = max(1, int(FILE_DELETION_WARN_MINUTES))
    return max(1, min(warn, retention_minutes // 2 or 1))


# ------------------------------------------------------------------ #
# Premium expiry reminders (DM 3d / 1d before)                        #
# ------------------------------------------------------------------ #

async def _send_expiry_warning(user_id: int, days_left: int, expiry: datetime) -> bool:
    """DM a premium user that their subscription is about to lapse."""
    from .config import client
    if client is None or user_id is None:
        return False
    try:
        await client.send_message(
            user_id,
            f"⏳ **Premium expiring soon**\n\n"
            f"Your premium access expires in {days_left} day(s) "
            f"(on {expiry.strftime('%Y-%m-%d')}).\n\n"
            f"Renew anytime with /buy_premium to avoid losing premium features.",
        )
        return True
    except Exception as e:
        print(f"⚠️ premium expiry DM failed for {user_id}: {e}")
        return False


async def warn_expiring_premium(warn_days=None, now: datetime = None) -> int:
    """DM users whose premium lapses within a threshold (once per threshold).

    Thresholds are applied SMALLEST-first: a user inside several windows gets
    only the tightest applicable reminder, and every larger threshold is then
    marked as warned so a later pass cannot emit a back-dated "3 days left"
    message to someone with hours remaining. Returns the number of DMs sent.
    """
    thresholds = sorted(warn_days or PREMIUM_EXPIRY_WARN_DAYS)
    now = now or datetime.now(timezone.utc)
    try:
        docs = await premium_users_col.find({}).to_list(length=2000)
    except Exception as e:
        print(f"⚠️ warn_expiring_premium query failed: {e}")
        return 0

    sent = 0
    for doc in docs:
        if not isinstance(doc, dict):
            continue
        expiry = doc.get("expiry_date")
        if not expiry:
            continue
        if expiry.tzinfo is None:
            expiry = expiry.replace(tzinfo=timezone.utc)
        delta = expiry - now
        if delta.total_seconds() <= 0:
            continue  # already expired - no reminder
        days_left = delta.days
        for idx, threshold in enumerate(thresholds):
            flag = f"warned_{threshold}d"
            if days_left <= threshold and not doc.get(flag):
                if await _send_expiry_warning(doc.get("user_id"), days_left, expiry):
                    sent += 1
                updates = {flag: True}
                # Larger thresholds no longer apply (user is already closer
                # to expiry): mark them so they never fire later.
                for larger in thresholds[idx + 1:]:
                    updates[f"warned_{larger}d"] = True
                try:
                    await premium_users_col.update_one(
                        {"user_id": doc.get("user_id")}, {"$set": updates})
                except Exception as e:
                    print(f"⚠️ expiry flag update failed: {e}")
                break
    return sent


async def start_premium_expiry_monitor(interval_minutes: int = 60):
    """Background task: DM premium users before their access lapses.

    Runs warn_expiring_premium every `interval_minutes` minutes. Started from
    features/bot.py alongside the other background monitors.
    """
    while True:
        try:
            await warn_expiring_premium()
        except Exception as e:
            print(f"⚠️ Premium expiry monitor error: {e}")
        await asyncio.sleep(interval_minutes * 60)


