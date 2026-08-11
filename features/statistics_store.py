"""
Shared Runtime Statistics Store

Central home for in-memory runtime statistics that are produced by background
tasks / services and consumed by the statistics dashboard.

Why this module exists:
- Previously prune_stats lived inside features/indexing.py, forcing consumers
  (features/statistics.py) to import the whole indexing module (and its heavy
  dependencies: pyrogram, database connections, etc.) just to read a dict.
- By keeping the dicts here - a module with zero imports - producers can
  populate them and consumers can read them without import-time coupling or
  circular-import risk, and tests have a single place to reset state.
"""

# Runtime statistics for the orphan prune monitor (channel-deletion cleanup).
# Populated by features/indexing.py.prune_orphaned_index_entries() and shown
# on the /stat dashboard, /quickstat and CSV exports via statistics.py.
prune_stats = {
    'runs': 0,                     # completed prune runs
    'total_deleted': 0,            # entries removed across all runs
    'total_skipped_access': 0,     # entries kept across all runs (access lost)
    'last_run': None,              # ISO timestamp of the most recent run
    'last_duration': 0,            # seconds the last run took
    'last_verified': 0,            # entries verified in the last run
    'last_deleted': 0,             # entries deleted in the last run
    'last_skipped_access': 0,      # entries skipped in the last run
    'last_paused': False,          # whether the last run paused on FloodWait
    'last_error': None,            # error message of the last failed run
}

# Runtime indexing counters, populated by features/indexing.py (index_message,
# process_message_queue, on_message) and shown via /indexing_stats, /stat and
# the CSV export (commands.py, statistics.py).
indexing_stats = {
    'total_attempts': 0,
    'successful_inserts': 0,
    'duplicate_errors': 0,
    'other_errors': 0,
    'concurrent_peak': 0,
}
