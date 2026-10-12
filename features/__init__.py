"""
Features Package

This package contains modular components for the Movie Bot application.
Each module handles a specific aspect of the bot's functionality.

Modules:
- config: Configuration and initialization settings
- statistics_store: Shared runtime statistics (indexing_stats, prune_stats)
- database: Database connection and helper functions
- utils: Utility functions for file management and helpers
- metadata_parser: Robust metadata parsing for movies and series
"""

from .config import (
    API_ID, API_HASH, BOT_TOKEN, BOT_ID, MONGO_URI, MONGO_DB,
    ADMINS, LOG_CHANNEL, FUZZY_THRESHOLD, AUTO_INDEX_DEFAULT,
    bulk_downloads, file_deletions, file_deletions_lock, INDEX_EXTENSIONS,
    message_queue, queue_processor_task, active_indexing_threads,
    user_input_events, TempData, temp_data, BOT_VERSION,
    client
)

from .statistics_store import indexing_stats, prune_stats

from .logger import logger

from .database import (
    mongo, db, movies_col, users_col, channels_col,
    settings_col, logs_col, requests_col, user_request_limits_col,
    premium_users_col, premium_features_col,
    ensure_indexes
)

from .utils import (
    wait_for_user_input, set_user_input, cleanup_expired_bulk_downloads,
    format_file_size, get_readable_time,
    group_recent_content, format_movie_group, format_series_group,
    format_recent_output, resolve_chat_ref
)

# File-deletion subsystem is canonical in file_deletion.py (was previously
# duplicated in utils.py); imported here from its single canonical home.
from .file_deletion import (
    cleanup_expired_file_deletions, track_file_for_deletion,
    check_files_for_deletion, save_file_deletions_to_disk,
    load_file_deletions_from_disk, start_deletion_monitor,
    periodic_save_file_deletions
)

# Access control is canonical in user_management.py (was previously
# duplicated in utils.py); imported here from its single canonical home.
from .user_management import (
    get_user_doc, is_admin, is_banned, has_accepted_terms, log_action,
    load_terms_and_privacy, check_banned, check_terms_acceptance,
    should_process_command, require_not_banned, should_process_command_for_user
)

from .metadata_parser import (
    parse_metadata, BRACKET_TAG_RE
)

from .request_management import (
    check_rate_limits, update_user_limits, check_duplicate_request,
    validate_imdb_link, get_queue_position, MAX_PENDING_REQUESTS_PER_USER,
    MAX_REQUESTS_PER_DAY_PER_USER, MAX_GLOBAL_REQUESTS_PER_DAY
)

from .tmdb_integration import (
    search_tmdb, format_tmdb_result
)

from .premium_management import (
    initialize_premium_features, is_premium_user, get_premium_user,
    add_premium_user, edit_premium_user, remove_premium_user,
    get_days_remaining, is_feature_premium_only, toggle_feature,
    add_premium_feature, get_all_premium_features, get_all_premium_users,
    cleanup_expired_premium
)

__all__ = [
    # Config module + shared stats store exports
    'API_ID', 'API_HASH', 'BOT_TOKEN', 'BOT_ID', 'MONGO_URI', 'MONGO_DB',
    'ADMINS', 'LOG_CHANNEL', 'FUZZY_THRESHOLD', 'AUTO_INDEX_DEFAULT',
    'bulk_downloads', 'file_deletions', 'file_deletions_lock', 'INDEX_EXTENSIONS',
    'message_queue', 'queue_processor_task', 'active_indexing_threads',
    'indexing_stats', 'prune_stats', 'user_input_events', 'TempData', 'temp_data',
    'client', 'BOT_VERSION', 'get_readable_time',
    
    # Database module exports
    'mongo', 'db', 'movies_col', 'users_col', 'channels_col',
    'settings_col', 'logs_col', 'requests_col', 'user_request_limits_col',
    'premium_users_col', 'premium_features_col',
    'ensure_indexes',
    
    # Utils module exports
    'wait_for_user_input', 'set_user_input', 'cleanup_expired_bulk_downloads',
    'cleanup_expired_file_deletions', 'track_file_for_deletion',
    'check_files_for_deletion', 'save_file_deletions_to_disk',
    'load_file_deletions_from_disk', 'start_deletion_monitor',
    'periodic_save_file_deletions', 'format_file_size', 'load_terms_and_privacy',
    'check_banned', 'check_terms_acceptance', 'should_process_command',
    'require_not_banned', 'should_process_command_for_user',
    'get_user_doc', 'is_admin', 'is_banned', 'has_accepted_terms', 'log_action',
    'group_recent_content', 'format_movie_group', 'format_series_group',
    'format_recent_output', 'resolve_chat_ref',
    
    # Metadata parser module exports
    'parse_metadata', 'BRACKET_TAG_RE',

    # Request management module exports
    'check_rate_limits', 'update_user_limits', 'check_duplicate_request',
    'validate_imdb_link', 'get_queue_position', 'MAX_PENDING_REQUESTS_PER_USER',
    'MAX_REQUESTS_PER_DAY_PER_USER', 'MAX_GLOBAL_REQUESTS_PER_DAY',

    # TMDb integration module exports
    'search_tmdb', 'format_tmdb_result',

    # Premium management module exports
    'initialize_premium_features', 'is_premium_user', 'get_premium_user',
    'add_premium_user', 'edit_premium_user', 'remove_premium_user',
    'get_days_remaining', 'is_feature_premium_only', 'toggle_feature',
    'add_premium_feature', 'get_all_premium_features', 'get_all_premium_users',
    'cleanup_expired_premium'
]

# Version lives in config.py (single source of truth); re-exported here so
# `from features import __version__` stays accurate.
__version__ = BOT_VERSION
