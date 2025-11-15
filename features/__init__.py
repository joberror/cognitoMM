"""
Features Package

This package contains modular components for the Movie Bot application.
Each module handles a specific aspect of the bot's functionality.

Modules:
- config: Configuration and initialization settings
- database: Database connection and helper functions
- utils: Utility functions for file management and helpers
- metadata_parser: Robust metadata parsing for movies and series
"""

from .config import (
    API_ID, API_HASH, BOT_TOKEN, BOT_ID, MONGO_URI, MONGO_DB,
    ADMINS, LOG_CHANNEL, FUZZY_THRESHOLD, AUTO_INDEX_DEFAULT,
    bulk_downloads, file_deletions, file_deletions_lock, INDEX_EXTENSIONS,
    message_queue, queue_processor_task, active_indexing_threads,
    indexing_stats, user_input_events, TempData, temp_data,
    client, get_readable_time
)

from .database import (
    mongo, db, movies_col, users_col, channels_col,
    settings_col, logs_col, ensure_indexes, get_user_doc,
    is_admin, is_banned, has_accepted_terms, log_action
)

from .utils import (
    wait_for_user_input, set_user_input, cleanup_expired_bulk_downloads,
    cleanup_expired_file_deletions, track_file_for_deletion,
    check_files_for_deletion, save_file_deletions_to_disk,
    load_file_deletions_from_disk, start_deletion_monitor,
    periodic_save_file_deletions, format_file_size, load_terms_and_privacy,
    check_banned, check_terms_acceptance, should_process_command,
    require_not_banned, should_process_command_for_user,
    group_recent_content, format_movie_group, format_series_group,
    format_recent_output, resolve_chat_ref
)

from .metadata_parser import (
    parse_metadata, BRACKET_TAG_RE
)

__all__ = [
    # Config module exports
    'API_ID', 'API_HASH', 'BOT_TOKEN', 'BOT_ID', 'MONGO_URI', 'MONGO_DB',
    'ADMINS', 'LOG_CHANNEL', 'FUZZY_THRESHOLD', 'AUTO_INDEX_DEFAULT',
    'bulk_downloads', 'file_deletions', 'file_deletions_lock', 'INDEX_EXTENSIONS',
    'message_queue', 'queue_processor_task', 'active_indexing_threads',
    'indexing_stats', 'user_input_events', 'TempData', 'temp_data',
    'client', 'get_readable_time',
    
    # Database module exports
    'mongo', 'db', 'movies_col', 'users_col', 'channels_col',
    'settings_col', 'logs_col', 'ensure_indexes', 'get_user_doc',
    'is_admin', 'is_banned', 'has_accepted_terms', 'log_action',
    
    # Utils module exports
    'wait_for_user_input', 'set_user_input', 'cleanup_expired_bulk_downloads',
    'cleanup_expired_file_deletions', 'track_file_for_deletion',
    'check_files_for_deletion', 'save_file_deletions_to_disk',
    'load_file_deletions_from_disk', 'start_deletion_monitor',
    'periodic_save_file_deletions', 'format_file_size', 'load_terms_and_privacy',
    'check_banned', 'check_terms_acceptance', 'should_process_command',
    'require_not_banned', 'should_process_command_for_user',
    'group_recent_content', 'format_movie_group', 'format_series_group',
    'format_recent_output', 'resolve_chat_ref',
    
    # Metadata parser module exports
    'parse_metadata', 'BRACKET_TAG_RE'
]

__version__ = '1.0.0'