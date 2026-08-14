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
BOT_VERSION = "1.6.0"

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
import time

# Global message queue for sequential processing
message_queue = deque(maxlen=100)
queue_processor_task = None

# DIAGNOSTIC: Track concurrent indexing operations
import threading
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
