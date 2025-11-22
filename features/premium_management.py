"""
Premium Management Module

This module handles premium user management and feature access control.
It includes functions for checking premium status, managing premium users,
and controlling premium features.
"""

from datetime import datetime, timezone, timedelta
from typing import Optional, Dict, List, Tuple
from .database import premium_users_col, premium_features_col, log_action


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
    Check if user has active premium status
    
    Args:
        user_id: User ID to check
        
    Returns:
        True if user has active premium, False otherwise
    """
    try:
        premium_doc = await premium_users_col.find_one({"user_id": user_id})
        
        if not premium_doc:
            return False
        
        # Check if premium has expired
        expiry_date = premium_doc.get("expiry_date")
        if not expiry_date:
            return False
        
        # Ensure expiry_date is timezone-aware
        if expiry_date.tzinfo is None:
            expiry_date = expiry_date.replace(tzinfo=timezone.utc)
        
        now = datetime.now(timezone.utc)
        
        # If expired, return False
        if now >= expiry_date:
            return False
        
        return True
    except Exception as e:
        print(f"Error checking premium status for user {user_id}: {e}")
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


