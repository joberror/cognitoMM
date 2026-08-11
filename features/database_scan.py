"""
Database Scan Module

Contains the standalone message-range reconciliation scan used by the
/update_db command. It was extracted from features/commands.py so the scan
logic can be unit-tested in isolation without the interactive command flow
(see tests/test_scan_message_range.py).
"""

from datetime import datetime, timezone

from pyrogram.errors import FloodWait

from .database import movies_col
from .indexing import ACCESS_ERRORS, index_message


async def scan_message_range(
    client,
    channel_id,
    start_id,
    end_id,
    movies_col_ref=None,
    index_message_ref=None,
    progress_cb=None,
):
    """
    Scan message ids ``start_id``..``end_id`` on a channel and reconcile the
    movies database with the channel's current state (the /update_db scan
    loop, extracted from cmd_update_db so it can be unit-tested in isolation
    - see tests/test_scan_message_range.py).

    For each message id in the range:
    - empty stub / generic fetch error with an indexed entry -> entry removed
      (orphaned: the file was deleted from the channel)
    - known channel access error (ChannelPrivate, banned/removed, ...) -> entry
      KEPT: the bot lost access to the channel itself, which is not proof the
      message was deleted (see ACCESS_ERRORS). A single run therefore cannot
      wipe a channel's whole index.
    - FloodWait -> scan pauses (paused=True); nothing further is deleted and
      the caller can re-run to finish.
    - media message not yet indexed -> index_message() is called.

    ``movies_col_ref`` / ``index_message_ref`` allow injecting fakes for
    tests; they default to the module-level movies_col / index_message.
    ``progress_cb`` is an optional async callable invoked roughly every 10
    messages or 3 seconds with a state dict (scanned, total_range,
    progress_pct, eta_str, bar, orphan/new/already/skipped/error counters) so
    the caller can render progress.

    Returns:
        dict: {scanned, orphans_removed, new_indexed, already_indexed,
               skipped_no_media, errors, paused}
    """
    movies_col_ref = movies_col_ref or movies_col
    index_message_ref = index_message_ref or index_message

    scanned = 0
    orphans_removed = 0
    new_indexed = 0
    errors = 0
    skipped_no_media = 0
    already_indexed = 0
    paused = False
    total_range = end_id - start_id + 1

    # Step 4a: Get all indexed entries for this channel in the range
    existing_entries = await movies_col_ref.find(
        {"channel_id": channel_id, "message_id": {"$gte": start_id, "$lte": end_id}},
        {"message_id": 1, "_id": 1, "title": 1}
    ).to_list(length=None)

    existing_map = {doc["message_id"]: doc for doc in existing_entries}
    existing_ids = set(existing_map.keys())

    print(f"[UPDATE_DB] Found {len(existing_ids)} indexed entries in the specified range")

    # Step 4b: Iterate through messages in the range
    last_update = 0
    scan_start_time = datetime.now(timezone.utc).timestamp()

    for msg_id in range(start_id, end_id + 1):
        scanned += 1

        # Update progress every 10 messages or at least every 3 seconds
        current_time = datetime.now(timezone.utc).timestamp()
        if scanned % 10 == 0 or (current_time - last_update) >= 3:
            last_update = current_time
            progress_pct = (scanned / total_range) * 100

            # Calculate ETA
            elapsed = current_time - scan_start_time
            if scanned > 0 and elapsed > 0:
                rate = scanned / elapsed  # messages per second
                remaining = total_range - scanned
                eta_seconds = remaining / rate if rate > 0 else 0
                if eta_seconds < 60:
                    eta_str = f"{int(eta_seconds)}s"
                elif eta_seconds < 3600:
                    eta_str = f"{int(eta_seconds // 60)}m {int(eta_seconds % 60)}s"
                else:
                    eta_str = f"{int(eta_seconds // 3600)}h {int((eta_seconds % 3600) // 60)}m"
            else:
                eta_str = "calculating..."

            # Progress bar (20 chars wide)
            filled = int(progress_pct / 5)  # 20 segments = 100/5
            bar = "█" * filled + "░" * (20 - filled)

            if progress_cb is not None:
                try:
                    await progress_cb({
                        "scanned": scanned,
                        "total_range": total_range,
                        "progress_pct": progress_pct,
                        "eta_str": eta_str,
                        "bar": bar,
                        "orphans_removed": orphans_removed,
                        "new_indexed": new_indexed,
                        "already_indexed": already_indexed,
                        "skipped_no_media": skipped_no_media,
                        "errors": errors,
                    })
                except Exception:
                    pass  # Ignore progress-render errors (rate limit, etc.)

            # Terminal progress log every 50 messages
            if scanned % 50 == 0:
                print(f"[UPDATE_DB] Progress: {scanned}/{total_range} ({progress_pct:.1f}%) | "
                      f"Orphans: {orphans_removed} | New: {new_indexed} | ETA: {eta_str}")

        try:
            # Fetch the message from channel
            msg = await client.get_messages(channel_id, msg_id)

            if not msg or getattr(msg, "empty", False):
                # Message doesn't exist - check if we have it indexed
                if msg_id in existing_ids:
                    # Remove orphaned entry
                    doc = existing_map[msg_id]
                    await movies_col_ref.delete_one({"_id": doc["_id"]})
                    orphans_removed += 1
                    print(f"[UPDATE_DB] 🗑️ Removed orphan: {doc.get('title', 'Unknown')} (msg_id: {msg_id})")
                continue

            # Message exists - check if it has video content
            has_video = getattr(msg, "video", None) is not None
            has_doc = getattr(msg, "document", None) is not None and \
                     (getattr(getattr(msg, "document", None), "mime_type", "") or "").startswith("video")

            if not (has_video or has_doc):
                skipped_no_media += 1
                # If this non-media message is indexed, remove it (shouldn't happen but safety check)
                if msg_id in existing_ids:
                    doc = existing_map[msg_id]
                    await movies_col_ref.delete_one({"_id": doc["_id"]})
                    orphans_removed += 1
                    print(f"[UPDATE_DB] 🗑️ Removed non-media entry: {doc.get('title', 'Unknown')} (msg_id: {msg_id})")
                continue

            # Check if already indexed
            if msg_id in existing_ids:
                already_indexed += 1
                continue

            # Index this new file
            try:
                await index_message_ref(msg)
                new_indexed += 1

                # Get filename for logging
                if has_video and msg.video:
                    filename = getattr(msg.video, "file_name", None) or "Video"
                elif has_doc and msg.document:
                    filename = getattr(msg.document, "file_name", None) or "Document"
                else:
                    filename = "Unknown"

                print(f"[UPDATE_DB] ➕ Indexed new file: {filename} (msg_id: {msg_id})")

            except Exception as idx_err:
                # Check if it's a duplicate error (already indexed by race condition)
                if "duplicate key" in str(idx_err).lower():
                    already_indexed += 1
                else:
                    errors += 1
                    print(f"[UPDATE_DB] ⚠️ Error indexing msg {msg_id}: {idx_err}")

        except FloodWait as e:
            # Rate limited - not proof of deletion; pause the scan
            # and keep entries (mirrors prune_orphaned_index_entries).
            print(f"[UPDATE_DB] ⚠️ FloodWait {e.value}s - pausing scan (rate limiting is not proof of deletion)")
            paused = True
            break
        except ACCESS_ERRORS as e:
            # Bot lost access to the channel itself (ChannelPrivate,
            # banned/removed, etc.) - NOT proof the message was
            # deleted. Skip so a single /update_db run cannot wipe a
            # channel's whole index; entries stay for a later run.
            if msg_id in existing_ids:
                print(f"[UPDATE_DB] ⚠️ {type(e).__name__} on msg {msg_id} - channel access lost, keeping indexed entry")
            else:
                print(f"[UPDATE_DB] ⚠️ {type(e).__name__} on msg {msg_id} - channel access lost")
        except Exception as e:
            # Error fetching message - might be deleted or inaccessible
            if msg_id in existing_ids:
                doc = existing_map[msg_id]
                try:
                    await movies_col_ref.delete_one({"_id": doc["_id"]})
                    orphans_removed += 1
                    print(f"[UPDATE_DB] 🗑️ Removed inaccessible entry: {doc.get('title', 'Unknown')} (msg_id: {msg_id})")
                except Exception as del_err:
                    errors += 1
                    print(f"[UPDATE_DB] ⚠️ Error removing orphan {msg_id}: {del_err}")
            else:
                # Log the error but continue
                if "MESSAGE_ID_INVALID" not in str(e):
                    print(f"[UPDATE_DB] ⚠️ Error accessing msg {msg_id}: {e}")

    return {
        "scanned": scanned,
        "orphans_removed": orphans_removed,
        "new_indexed": new_indexed,
        "already_indexed": already_indexed,
        "skipped_no_media": skipped_no_media,
        "errors": errors,
        "paused": paused,
    }
