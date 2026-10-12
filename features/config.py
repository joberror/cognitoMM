"""
Configuration and Initialization Module

This module contains all configuration variables, environment settings,
and initialization code for the Movie Bot application.
"""

import os
import sys
from datetime import datetime, timezone
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

print(f"🐍 Python {sys.version}")
print("🎬 MovieBot - Bot Session")

# Bot start time for uptime tracking
BOT_START_TIME = datetime.now(timezone.utc)

# -------------------------
# VERSION
# -------------------------
# Canonical bot version (single source of truth). Bump with
# `make bump` (minor) / `make bump-patch` / `make bump-major`, or
# `scripts/bump_version.py --set X.Y.Z`. The pre-commit hook fails commits
# that add a new feature without bumping this constant. The webapp `/`
# endpoint exposes it (overridable via the BOT_VERSION env var).
BOT_VERSION = "1.18.2"

# -------------------------
# CONFIG / ENV
# -------------------------
API_ID = int(os.getenv("API_ID", "0"))
API_HASH = os.getenv("API_HASH", "")
BOT_TOKEN = os.getenv("BOT_TOKEN", "")             # Bot token (required for bot session)
BOT_ID = int(os.getenv("BOT_ID", "0"))             # Bot ID (optional, will be auto-detected)
MONGO_URI = os.getenv("MONGO_URI", "")
MONGO_DB = os.getenv("MONGO_DB", "moviebot")
ADMINS = [int(x) for x in os.getenv("ADMINS", "").split(",") if x.strip()]
LOG_CHANNEL = os.getenv("LOG_CHANNEL")             # optional - e.g. -1001234567890
FUZZY_THRESHOLD = int(os.getenv("FUZZY_THRESHOLD", "68"))
# Scheduled /update_db background rescan (incremental per channel)
DB_RESCAN_ENABLED = os.getenv("DB_RESCAN_ENABLED", "true").lower() in ("1", "true", "yes")
DB_RESCAN_INTERVAL_MINUTES = int(os.getenv("DB_RESCAN_INTERVAL_MINUTES", "360"))
AUTO_INDEX_DEFAULT = os.getenv("AUTO_INDEXING", "True").lower() in ("1", "true", "yes")
TMDB_API = os.getenv("TMDB_API", "")               # TMDb API key for request feature
START_MESSAGE = os.getenv("START_MESSAGE", os.getenv("START_MESSAGEE", "Welcome to the bot! Use buttons below to navigate."))
SUPPORT_LINK = os.getenv("SUPPORT_LINK", "https://t.me/")
# Public Telegraph help guides (published/updated by scripts/publish_telegraph.py).
# HELP_GUIDE_URL shows on every /help page; ADMIN_GUIDE_URL adds an admin-only
# "Admin Guide" button on the admin help section.
HELP_GUIDE_URL = os.getenv("HELP_GUIDE_URL", "").strip()
ADMIN_GUIDE_URL = os.getenv("ADMIN_GUIDE_URL", "").strip()

# -------------------------
# Premium monetization (Telegram Stars)
# -------------------------
# Stars purchases use currency "XTR" (no external payment provider needed).
PREMIUM_STARS_ENABLED = os.getenv("PREMIUM_STARS_ENABLED", "true").lower() in ("1", "true", "yes")
PREMIUM_STARS_CURRENCY = "XTR"


def _parse_premium_plans(raw: str) -> dict:
    """Parse "key:days:stars,key:days:stars" into {key: {key, days, stars}}."""
    plans = {}
    for part in (raw or "").split(","):
        bits = part.strip().split(":")
        if len(bits) != 3:
            continue
        key, days, stars = (b.strip() for b in bits)
        if not key or key in plans:
            continue
        try:
            days_i, stars_i = int(days), int(stars)
        except ValueError:
            continue
        if days_i <= 0 or stars_i <= 0:
            continue
        plans[key] = {"key": key, "days": days_i, "stars": stars_i}
    return plans


PREMIUM_PLANS = _parse_premium_plans(
    os.getenv("PREMIUM_PLANS", "1m:30:50,3m:90:120,6m:180:200,12m:365:350"))
# Days-before-expiry at which a DM reminder is sent (largest first applied).
PREMIUM_EXPIRY_WARN_DAYS = [
    int(x) for x in os.getenv("PREMIUM_EXPIRY_WARN_DAYS", "3,1").split(",")
    if x.strip().lstrip("-").isdigit() and int(x) > 0
] or [3, 1]
# Daily download quota by tier (0 = unlimited).
FREE_DOWNLOAD_DAILY_LIMIT = int(os.getenv("FREE_DOWNLOAD_DAILY_LIMIT", "10"))
PREMIUM_DOWNLOAD_DAILY_LIMIT = int(os.getenv("PREMIUM_DOWNLOAD_DAILY_LIMIT", "0"))

# -------------------------
# Watchlist
# -------------------------
# How many titles a user can track at once, by tier. /watch refuses additions
# past the cap; admins bypass the cap (same rule as the /request rate limits).
WATCHLIST_FREE_LIMIT = int(os.getenv("WATCHLIST_FREE_LIMIT", "5"))
WATCHLIST_PREMIUM_LIMIT = int(os.getenv("WATCHLIST_PREMIUM_LIMIT", "20"))
# Per-(user, title) floodgate for watchlist DMs. A series batch (S01E01..E10)
# or a multi-file drop indexes in one burst and every file would otherwise DM
# the watcher; only the FIRST copy inside the window notifies, the rest are
# suppressed. Keyed per title, so two different titles uploaded together each
# get their own single message.
WATCHLIST_NOTIFY_COOLDOWN_SECONDS = float(
    os.getenv("WATCHLIST_NOTIFY_COOLDOWN_SECONDS", "300"))  # default 5 min
# Floor between two manual UPDATE presses on /watchlist (status re-fetch from
# TMDb/IMDb costs one API call per entry, so taps are rate-limited).
WATCHLIST_REFRESH_COOLDOWN_SECONDS = int(
    os.getenv("WATCHLIST_REFRESH_COOLDOWN_SECONDS", "60"))
# How many TMDb candidates the /watch disambiguation picker shows.
WATCHLIST_PICK_LIMIT = int(os.getenv("WATCHLIST_PICK_LIMIT", "5"))
# A movie is reported "In Cinemas" while it has no wide-theatrical release yet
# and its earliest premiere/limited release is within this many days.
WATCHLIST_IN_CINEMAS_DAYS = int(os.getenv("WATCHLIST_IN_CINEMAS_DAYS", "21"))

# Auto-deletion retention (minutes) by tier - how long a delivered file stays
# before the auto-delete monitor removes it.
FILE_DELETION_MINUTES = int(os.getenv("FILE_DELETION_MINUTES", "5"))
PREMIUM_FILE_DELETION_MINUTES = int(os.getenv("PREMIUM_FILE_DELETION_MINUTES", "30"))
# Bulk deliveries (Get All / season packs) keep files longer than single ones.
BULK_FILE_DELETION_MINUTES = int(os.getenv("BULK_FILE_DELETION_MINUTES", "15"))
PREMIUM_BULK_FILE_DELETION_MINUTES = int(
    os.getenv("PREMIUM_BULK_FILE_DELETION_MINUTES", "60"))
# Lead time (minutes before deletion) for the "will be deleted" warning DM.
# Scaled down automatically when retention is shorter than this.
FILE_DELETION_WARN_MINUTES = int(os.getenv("FILE_DELETION_WARN_MINUTES", "2"))

# Broadcast Configuration
BROADCAST_RATE_LIMIT = int(os.getenv("BROADCAST_RATE_LIMIT", "25"))  # messages per second
BROADCAST_PROGRESS_INTERVAL = int(os.getenv("BROADCAST_PROGRESS_INTERVAL", "100"))  # users
BROADCAST_TEST_MODE = os.getenv("BROADCAST_TEST_MODE", "False").lower() in ("1", "true", "yes")
BROADCAST_TEST_USERS = [int(x) for x in os.getenv("BROADCAST_TEST_USERS", "").split(",") if x.strip()]

# -------------------------
# Global Variables
# -------------------------

# Temporary storage for bulk downloads (to avoid callback data size limits)
bulk_downloads = {}

# Global dictionary to track files scheduled for deletion
file_deletions = {}

# Lock for thread-safe access to file_deletions
import asyncio
file_deletions_lock = asyncio.Lock()

# Lock for thread-safe access to indexing operations
indexing_lock = asyncio.Lock()

# Global variables for indexing
INDEX_EXTENSIONS = ['.mkv', '.mp4', '.avi', '.mov', '.wmv', '.flv', '.webm', '.m4v', '.3gp', '.ts', '.m2ts']

# SOLUTION: Message queue for sequential processing
from collections import deque

# Global message queue for sequential processing
message_queue = deque(maxlen=100)
queue_processor_task = None

# DIAGNOSTIC: Track concurrent indexing operations
active_indexing_threads = set()

# User input waiting system (replacement for client.listen)
user_input_events = {}

class TempData:
    """Temporary data storage for bot operations"""
    CANCEL = False
    INDEXING_CHAT = None
    INDEXING_USER = None

temp_data = TempData()

# Client will be initialized within async context
client = None
