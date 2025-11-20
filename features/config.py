"""
Configuration and Initialization Module

This module contains all configuration variables, environment settings,
and initialization code for the Movie Bot application.
"""

import os
import sys
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

print(f"🐍 Python {sys.version}")
print("🎬 MovieBot - Bot Session")

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
AUTO_INDEX_DEFAULT = os.getenv("AUTO_INDEXING", "True").lower() in ("1", "true", "yes")
TMDB_API = os.getenv("TMDB_API", "")               # TMDb API key for request feature

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
indexing_stats = {
    'total_attempts': 0,
    'successful_inserts': 0,
    'duplicate_errors': 0,
    'other_errors': 0,
    'concurrent_peak': 0
}

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

# Add missing variables for indexing functionality
class temp_data:
    CANCEL = False

def get_readable_time(seconds):
    """Convert seconds to readable time format"""
    if seconds < 60:
        return f"{int(seconds)}s"
    elif seconds < 3600:
        minutes = int(seconds // 60)
        secs = int(seconds % 60)
        return f"{minutes}m {secs}s"
    else:
        hours = int(seconds // 3600)
        minutes = int((seconds % 3600) // 60)
        return f"{hours}h {minutes}m"
