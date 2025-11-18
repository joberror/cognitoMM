"""
Real-Time Channel Message Deletion Handling

Hydrogram currently (similar to Pyrogram) may not expose a high-level DeletedMessagesHandler.
To ensure we react to deletions, we register a RawUpdateHandler and heuristically inspect
the low-level update object for attributes that look like deletion updates.

Goal:
- When a channel message is deleted, immediately remove the corresponding indexed
  document(s) from movies_col (those created by auto-indexing or manual indexing).
- Preserve periodic orphan prune as a safety fallback (existing monitor in indexing.py).
- Provide diagnostic logging and audit actions.

Heuristic Strategy:
1. Raw update is inspected for potential channel/chat identifier attributes:
   channel_id, chat_id.
2. Potential container(s) of deleted message ids: message_ids, messages, ids.
3. If we find a channel_id and at least one message id, we attempt deletion of each
   matching DB entry: {"channel_id": channel_id, "message_id": mid}.
4. We log summary and send an audit log entry via log_action.
5. All exceptions are caught and logged without interrupting other handlers.

Notes / Limitations:
- **CRITICAL**: Telegram Bot API does NOT send deletion updates for channel posts to bots.
  This is a Telegram API limitation, not a library issue. Bots only receive deletion updates
  for messages in groups/supergroups where the bot is a member, NOT for channel posts.
- For channels, the ONLY reliable way to detect deletions is periodic verification by
  attempting to fetch messages (done by prune_orphaned_index_entries in indexing.py).
- This handler will catch deletions in groups/supergroups but will remain idle for channels.
- The periodic orphan monitor (every 30 minutes) is the PRIMARY deletion detection mechanism.

Diagnostic Tags:
- [REALTIME-DELETE] for visibility in runtime console.
- [REALTIME-DELETE-DEBUG] for detailed update inspection (enable for troubleshooting).
"""

from typing import Any, Iterable

from .database import movies_col, channels_col
from .user_management import log_action

# Enable debug mode to see all raw updates (WARNING: Very verbose!)
DEBUG_RAW_UPDATES = False


async def _extract_channel_id(update: Any) -> int | None:
    """Attempt to extract a channel/chat identifier from raw update object."""
    for attr in ("channel_id", "chat_id", "peer", "chat"):
        if hasattr(update, attr):
            val = getattr(update, attr)
            # peer/chat objects may have an id attribute
            if isinstance(val, int):
                return val
            if hasattr(val, "id"):
                try:
                    return int(getattr(val, "id"))
                except Exception:
                    pass
    return None


def _extract_message_ids(update: Any) -> list[int]:
    """
    Attempt to extract list of message ids from raw update.
    Accept multiple possible attribute names used across different TL schemas.
    """
    candidates: list[int] = []
    for attr in ("message_ids", "messages", "ids", "msg_ids"):
        if hasattr(update, attr):
            raw = getattr(update, attr)
            if isinstance(raw, (list, tuple, set)):
                for item in raw:
                    if isinstance(item, int):
                        candidates.append(item)
                    else:
                        # Some schemas may wrap message objects; try to extract .id
                        if hasattr(item, "id"):
                            try:
                                candidates.append(int(getattr(item, "id")))
                            except Exception:
                                pass
    # Deduplicate while preserving order
    unique: list[int] = []
    seen = set()
    for mid in candidates:
        if mid not in seen:
            unique.append(mid)
            seen.add(mid)
    return unique


async def handle_raw_update(client, update, users, chats):
    """
    Raw update handler for real-time deletion detection.

    Signature mirrors Hydrogram RawUpdateHandler expectations:
        (client, update, users, chats)

    We only act if heuristic detects deletion: presence of channel/chat id plus
    a list of message ids. All other updates are ignored.
    """
    try:
        # Debug mode: Log all raw updates to understand what we're receiving
        if DEBUG_RAW_UPDATES:
            update_type = type(update).__name__
            update_attrs = dir(update)
            print(f"[REALTIME-DELETE-DEBUG] Update type: {update_type}")
            print(f"[REALTIME-DELETE-DEBUG] Update attributes: {update_attrs}")
            if hasattr(update, '__dict__'):
                print(f"[REALTIME-DELETE-DEBUG] Update dict: {update.__dict__}")

        channel_id = await _extract_channel_id(update)
        message_ids = _extract_message_ids(update)

        # Debug: Log extraction results
        if DEBUG_RAW_UPDATES and (channel_id or message_ids):
            print(f"[REALTIME-DELETE-DEBUG] Extracted channel_id: {channel_id}, message_ids: {message_ids}")

        if not channel_id or not message_ids:
            return  # Not a deletion-like update

        # Verify channel is registered & enabled
        chdoc = await channels_col.find_one({"channel_id": channel_id})
        if not chdoc or not chdoc.get("enabled", True):
            return

        # Perform deletions
        deleted_count = 0
        for mid in message_ids:
            result = await movies_col.delete_one({"channel_id": channel_id, "message_id": mid})
            if getattr(result, "deleted_count", 0) > 0:
                deleted_count += 1

        # Only log if something was actually removed to reduce noise
        if deleted_count > 0:
            print(f"[REALTIME-DELETE] Channel {channel_id}: removed {deleted_count}/{len(message_ids)} indexed entries for deleted messages {message_ids}")
            await log_action(
                "realtime_channel_message_delete",
                extra={
                    "channel_id": channel_id,
                    "message_ids": message_ids,
                    "deleted_index_entries": deleted_count
                }
            )

    except Exception as e:
        # Defensive catch: never raise out of raw update handler
        print(f"[REALTIME-DELETE] Handler error: {e}")
        try:
            await log_action("realtime_delete_error", extra={"error": str(e)})
        except Exception:
            # If logging itself fails, ignore silently
            pass
