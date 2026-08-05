"""
Database Connection and Setup Module

This module handles MongoDB connection setup, database collections,
and database index creation for the Movie Bot application.
"""

from typing import Optional

from motor.motor_asyncio import AsyncIOMotorClient
from .config import MONGO_URI, MONGO_DB

# -------------------------
# DB (motor async)
# -------------------------
# Import safety: config.py defaults MONGO_URI to "" and CI/tests import this
# module without a MONGO_URI env var or .env file. Passing "" straight into
# AsyncIOMotorClient raises
#   pymongo.errors.ConfigurationError: Empty host (or extra comma in host list)
# at IMPORT time, which crashed every test module at collection (16 collection
# errors in CI's `make test`). We therefore resolve an empty URI to a localhost
# stand-in so the module always imports, and record the miss so
# ensure_indexes() can fail fast with a clear message at bot startup instead of
# silently probing localhost.

MONGO_URI_WAS_EMPTY = not MONGO_URI


def resolve_mongo_uri(uri: Optional[str]) -> str:
    """Return `uri`, or a localhost stand-in when it is empty/None/blank.

    The real connection string is required to RUN the bot; this fallback only
    exists so ``features.database`` stays importable (tests/CI) without a
    configured database.
    """
    return (uri or "").strip() or "mongodb://localhost:27017"


if MONGO_URI_WAS_EMPTY:
    print("⚠️ MONGO_URI is not set — imported with a localhost stand-in for "
          "test compatibility. The bot will refuse to start until MONGO_URI "
          "is configured.")

# Configure MongoDB client with longer timeouts for better connectivity
mongo = AsyncIOMotorClient(
    resolve_mongo_uri(MONGO_URI),
    connectTimeoutMS=60000,  # 60 seconds
    serverSelectionTimeoutMS=60000,  # 60 seconds
    socketTimeoutMS=60000,  # 60 seconds
    maxPoolSize=10,
    retryWrites=True
)
db = mongo[MONGO_DB]
movies_col = db["movies"]
users_col = db["users"]
channels_col = db["channels"]
settings_col = db["settings"]
logs_col = db["logs"]
requests_col = db["requests"]
user_request_limits_col = db["user_request_limits"]
premium_users_col = db["premium_users"]
premium_features_col = db["premium_features"]
broadcasts_col = db["broadcasts"]

async def ensure_indexes():
    """Create database indexes with error handling"""
    if MONGO_URI_WAS_EMPTY:
        raise RuntimeError(
            "MONGO_URI is not set: refusing to start without a database. "
            "Set MONGO_URI (e.g. mongodb+srv://...) and restart."
        )
    try:
        print("🔧 Creating database indexes...")
        
        # Test connection first
        await mongo.admin.command('ping')
        print("✅ MongoDB connection successful")
        
        # Create indexes with error handling
        indexes_to_create = [
            (movies_col, [("title", 1)], "title index"),
            (movies_col, [("year", 1)], "year index"),
            (movies_col, [("quality", 1)], "quality index"),
            (movies_col, [("type", 1)], "type index"),
            (movies_col, [("channel_id", 1), ("message_id", 1)], "channel_message index"),
            (users_col, [("user_id", 1)], "user_id index"),
            (channels_col, [("channel_id", 1)], "channel_id index"),
            (requests_col, [("user_id", 1)], "request user_id index"),
            (requests_col, [("status", 1)], "request status index"),
            (requests_col, [("request_date", 1)], "request date index"),
            (user_request_limits_col, [("user_id", 1)], "limits user_id index"),
            (premium_users_col, [("user_id", 1)], "premium user_id index"),
            (premium_features_col, [("feature_name", 1)], "premium feature_name index"),
            (broadcasts_col, [("broadcast_id", 1)], "broadcast_id index"),
            (broadcasts_col, [("admin_id", 1)], "broadcast admin_id index"),
            (broadcasts_col, [("started_at", -1)], "broadcast started_at index"),
            (broadcasts_col, [("status", 1)], "broadcast status index"),
        ]
        
        for collection, index_spec, description in indexes_to_create:
            try:
                if description in ["user_id index", "channel_id index", "limits user_id index", "premium user_id index", "premium feature_name index", "broadcast_id index"]:
                    await collection.create_index(index_spec, unique=True)
                else:
                    await collection.create_index(index_spec)
                print(f"✅ Created {description}")
            except Exception as e:
                print(f"⚠️ Failed to create {description}: {e}")
                
    except Exception as e:
        print(f"❌ Database connection failed: {e}")
        print("⚠️ Continuing without database indexes - some features may be slower")
        raise e

# -------------------------
# Helpers: roles, logs (canonical home: user_management.py)
# -------------------------
# The role/log helpers (get_user_doc, is_admin, is_banned, has_accepted_terms,
# log_action) are canonical in user_management.py. They were previously
# duplicated here with a diverging log_action implementation (direct logger
# route vs user_management's direct send_message). Consolidated into
# user_management.py; re-exported lazily below via PEP 562 __getattr__ so
# `from .database import log_action` keeps working WITHOUT a top-level import
# (which would create a circular import: user_management imports this module's
# collections at module level).

_USER_MANAGEMENT_HELPERS = ("get_user_doc", "is_admin", "is_banned",
                            "has_accepted_terms", "log_action")


def __getattr__(name):
    """Lazy backward-compat re-export of the user-management helpers."""
    if name in _USER_MANAGEMENT_HELPERS:
        from . import user_management
        return getattr(user_management, name)
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
